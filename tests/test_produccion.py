"""Pruebas de la versión de producción: robots.txt, TLS heredado, acceso, copias, estado, panel y CLI.

Ejecutar desde la carpeta del proyecto (no hay red: las peticiones se simulan):
    python -m unittest discover -s tests -v
Cada prueba usa su propia carpeta temporal de datos.
"""
import base64
import contextlib
import datetime as dt
import io
import logging
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("CONVENIOS_DATOS", tempfile.mkdtemp(prefix="convenios_produccion_"))

from convenios import __main__ as cli_main  # noqa: E402
from convenios import __version__  # noqa: E402
from convenios import acceso, config, copias, db, documentos, operacion, regcon, registro, robots, sync, util  # noqa: E402
from convenios import web  # noqa: E402

ROBOTS_BOE = "User-agent: *\nDisallow: /diario_boe/xml.php\nDisallow: /privado/\n"
CLAVE = "clave-muy-larga-2026"


class _Resp:
    """Respuesta HTTP simulada."""

    def __init__(self, status=200, texto="", contenido=b"", ctype=""):
        self.status_code = status
        self.text = texto
        self.content = contenido
        self.headers = {"content-type": ctype}

    def iter_content(self, chunk_size=1):
        yield self.content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def close(self):
        pass


def _reiniciar_registro():
    raiz = logging.getLogger("convenios")
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
        h.close()
    if hasattr(raiz, "_configurado"):
        del raiz._configurado


def _datos_temporales(testcase):
    """Redirige todas las rutas de datos a una carpeta temporal para esta prueba."""
    tmp = Path(tempfile.mkdtemp(prefix="convenios_prod_"))
    testcase.addCleanup(shutil.rmtree, tmp, True)
    rutas = {
        "DATOS": tmp, "BASE_DATOS": tmp / "convenios.db", "REGISTRO": tmp / "sincronizacion.log",
        "EXPORTACIONES": tmp / "exportaciones", "REGISTROS": tmp / "registros", "COPIAS": tmp / "copias",
        "ACCESO": tmp / "acceso.json", "BLOQUEO": tmp / "sincronizacion.lock",
    }
    for nombre, valor in rutas.items():
        p = mock.patch.object(config, nombre, valor)
        p.start()
        testcase.addCleanup(p.stop)
    _reiniciar_registro()
    testcase.addCleanup(_reiniciar_registro)
    testcase.addCleanup(_soltar_bloqueo)
    return tmp


def _soltar_bloqueo():
    if sync._bloqueo_sync is not None:
        sync._bloqueo_sync.close()
        sync._bloqueo_sync = None


def _pdf_de_prueba(texto):
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), texto)
    datos = doc.tobytes()
    doc.close()
    return datos


class PruebasRobots(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(robots, "_COMPROBADOR", robots._Comprobador())
        p.start()
        self.addCleanup(p.stop)
        self.respuestas, self.llamadas = {}, []

        def falso_get(url, **kwargs):
            self.llamadas.append(url)
            r = self.respuestas.get(url)
            if isinstance(r, Exception):
                raise r
            return r or _Resp(404)

        p = mock.patch.object(robots.requests, "get", side_effect=falso_get)
        p.start()
        self.addCleanup(p.stop)

    def test_prohibida_la_ruta_xml_del_boe_y_permitido_el_pdf(self):
        self.respuestas["https://www.boe.es/robots.txt"] = _Resp(200, ROBOTS_BOE)
        with self.assertRaises(robots.Bloqueada):
            robots.comprobar("https://www.boe.es/diario_boe/xml.php?id=BOE-A-2026-1")
        robots.comprobar("https://www.boe.es/boe/dias/2026/10/08/pdfs/BOE-A-2026-1.pdf")

    def test_sin_robots_no_hay_restricciones(self):
        robots.comprobar("https://ejemplo.es/doc.pdf")  # 404: sin restricciones

    def test_robots_no_disponible_se_recuerda_y_no_se_vuelve_a_pedir_enseguida(self):
        self.respuestas["https://ejemplo.es/robots.txt"] = _Resp(500)
        for _ in range(2):
            with self.assertRaises(robots.NoDisponible):
                robots.comprobar("https://ejemplo.es/doc.pdf")
        self.assertEqual(self.llamadas.count("https://ejemplo.es/robots.txt"), 1)

    def test_error_de_red_es_no_disponible(self):
        self.respuestas["https://ejemplo.es/robots.txt"] = requests.ConnectionError("sin red")
        with self.assertRaises(robots.NoDisponible):
            robots.comprobar("https://ejemplo.es/doc.pdf")

    def test_servidor_tls_heredado_lee_robots_con_sesion_especial(self):
        self.respuestas["https://bop.dipucr.es/robots.txt"] = requests.exceptions.SSLError("certificado")
        sesion = mock.Mock()
        sesion.get.return_value = _Resp(200, "User-agent: *\nDisallow: /anuncios/\n")
        with mock.patch.object(robots, "sesion_heredada", return_value=sesion):
            with self.assertRaises(robots.Bloqueada):
                robots.comprobar("https://bop.dipucr.es/anuncios/1.pdf")

    def test_ssl_fallido_en_otro_servidor_no_salta_la_verificacion(self):
        self.respuestas["https://ejemplo.es/robots.txt"] = requests.exceptions.SSLError("certificado")
        with self.assertRaises(robots.NoDisponible):
            robots.comprobar("https://ejemplo.es/doc.pdf")

    def test_modo_ignorar_no_pide_robots_txt(self):
        with mock.patch.object(config, "ROBOTS", "ignorar"):
            robots.comprobar("https://www.boe.es/diario_boe/xml.php?id=X")
        self.assertEqual(self.llamadas, [])


class PruebasDocumentosProduccion(unittest.TestCase):
    def test_boe_se_lee_de_su_pdf_en_modo_respetar(self):
        url = "https://www.boe.es/boe/dias/2026/10/08/pdfs/BOE-A-2026-20971.pdf"
        pdf = _pdf_de_prueba("Convenio colectivo de prueba. Articulo 1. Ambito.")
        with mock.patch.object(robots, "comprobar"), \
                mock.patch.object(documentos, "descargar", return_value=(pdf, "application/pdf", False)):
            out = documentos.procesar(url)
        self.assertEqual(out["via"], "boe-pdf")
        self.assertIn("Convenio colectivo de prueba", out["texto"])

    def test_boe_en_modo_ignorar_usa_el_xml(self):
        url = "https://www.boe.es/boe/dias/2026/10/08/pdfs/BOE-A-2026-20971.pdf"
        with mock.patch.object(config, "ROBOTS", "ignorar"), \
                mock.patch.object(documentos.boe, "documento_xml", return_value=("cuerpo", [])) as xml:
            out = documentos.procesar(url)
        xml.assert_called_once_with("BOE-A-2026-20971")
        self.assertEqual(out["via"], "boe-xml")

    def test_documento_prohibido_no_se_descarga(self):
        with mock.patch.object(robots, "comprobar", side_effect=robots.Bloqueada("x")), \
                mock.patch.object(documentos, "descargar") as descargar:
            with self.assertRaises(robots.Bloqueada):
                documentos.procesar("https://ejemplo.es/a.pdf")
        descargar.assert_not_called()

    def test_error_ssl_fuera_de_la_lista_no_se_salta(self):
        with mock.patch.object(documentos, "pedir", side_effect=requests.exceptions.SSLError("cert")), \
                mock.patch.object(documentos, "sesion_heredada") as sesion:
            with self.assertRaises(requests.exceptions.SSLError):
                documentos.descargar("https://ejemplo.es/a.pdf")
        sesion.assert_not_called()

    def test_error_ssl_en_servidor_de_la_lista_usa_sesion_heredada(self):
        llamadas = [requests.exceptions.SSLError("cert"), _Resp(200, contenido=b"%PDF-1.4 x", ctype="application/pdf")]

        def falso_pedir(sesion, metodo, url, **kwargs):
            r = llamadas.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with mock.patch.object(documentos, "pedir", side_effect=falso_pedir), \
                mock.patch.object(documentos, "sesion_heredada", return_value=object()):
            datos, _, legado = documentos.descargar("https://bop.dipucr.es/a.pdf")
        self.assertTrue(legado)
        self.assertEqual(datos, b"%PDF-1.4 x")

    def test_caracteres_de_control_fuera_y_saltos_conservados(self):
        self.assertEqual(util.quitar_control("uno\tdos\nN\x0c\x01x"), "uno\tdos\nN\x0cx")
        self.assertEqual(util.limpio("a\x00b\x07c \x0c d"), "abc d")
        self.assertEqual(util.quitar_control("a\x85b\x9fc"), "abc")  # C1 (categoría Cc)


class PruebasEstadosDeDocumento(unittest.TestCase):
    def setUp(self):
        _datos_temporales(self)
        self.con = db.conectar()
        self.addCleanup(self.con.close)

    def test_bloqueada_se_guarda_y_pendiente_no(self):
        def falso_procesar(url):
            if "bloq" in url:
                raise robots.Bloqueada(url)
            if "pend" in url:
                raise robots.NoDisponible("a.es")
            return {"texto": "x" * 300, "paginas": 1, "tablas": [], "via": "pdf"}

        urls = ["https://a.es/bloq.pdf", "https://a.es/pend.pdf", "https://a.es/ok.pdf"]
        with mock.patch.object(documentos, "procesar", side_effect=falso_procesar):
            resultados = {u: sync._documento_seguro(u) for u in urls}
        estados = {u: sync._guardar_documento(self.con, u, out, err) for u, (_, out, err) in resultados.items()}
        self.assertEqual(estados, {urls[0]: "bloqueada", urls[1]: "pendiente", urls[2]: "ok"})
        guardados = {r[0]: r[1] for r in self.con.execute("SELECT url, estado FROM documentos")}
        self.assertEqual(guardados[urls[0]], "bloqueada")
        self.assertNotIn(urls[1], guardados)  # pendiente: la siguiente sincronización lo reintentará

    def test_un_semaforo_por_servidor(self):
        self.assertIs(sync._semaforo("a.example"), sync._semaforo("a.example"))
        self.assertIsNot(sync._semaforo("a.example"), sync._semaforo("b.example"))


class PruebasAcceso(unittest.TestCase):
    def setUp(self):
        _datos_temporales(self)

    def test_clave_corta_o_usuario_con_dos_puntos_no_se_aceptan(self):
        with self.assertRaises(ValueError):
            acceso.guardar("ana", "corta")
        with self.assertRaises(ValueError):
            acceso.guardar("a:b", CLAVE)

    def test_solo_se_guarda_el_hash_y_se_verifica(self):
        acceso.guardar("ana", CLAVE)
        self.assertNotIn(CLAVE, config.ACCESO.read_text(encoding="utf-8"))
        self.assertTrue(acceso.verificar("ana", CLAVE))
        self.assertFalse(acceso.verificar("ana", "otra-clave-larga-2026"))
        self.assertFalse(acceso.verificar("luis", CLAVE))
        acceso.eliminar()
        self.assertTrue(acceso.verificar("cualquiera", "cualquiera"))  # sin usuario, el panel no pide acceso


class PruebasCopias(unittest.TestCase):
    def setUp(self):
        _datos_temporales(self)
        db.conectar().close()

    def test_copia_comprobada_y_retencion(self):
        for i in range(1, 4):
            carpeta = config.COPIAS / f"2020-01-0{i}_000000"
            carpeta.mkdir(parents=True)
            (carpeta / "convenios.db").write_bytes(b"x")
        nueva = copias.hacer(conservar=3)
        self.assertTrue((nueva / "convenios.db").exists())
        self.assertEqual(copias.listar()[0], nueva)
        self.assertEqual(len(copias.listar()), 3)
        self.assertFalse((config.COPIAS / "2020-01-01_000000").exists())

    def test_sin_base_de_datos_no_hay_copia(self):
        config.BASE_DATOS.unlink()
        with self.assertRaises(FileNotFoundError):
            copias.hacer()


class PruebasRegistroYEstado(unittest.TestCase):
    def setUp(self):
        self.tmp = _datos_temporales(self)

    def test_registro_escribe_en_el_fichero_del_proceso(self):
        registro.configurar("prueba")
        logging.getLogger("convenios.prueba").warning("mensaje de prueba")
        for h in logging.getLogger("convenios").handlers:
            h.flush()
        self.assertIn("mensaje de prueba", (self.tmp / "registros" / "prueba.log").read_text(encoding="utf-8"))

    def test_sin_base_de_datos_el_estado_es_error(self):
        info = operacion.diagnostico()
        self.assertEqual(info["estado"], operacion.ERROR)
        self.assertEqual(info["base_datos"], "no_existe")

    def test_sin_sincronizacion_correcta_es_atencion(self):
        db.conectar().close()
        self.assertEqual(operacion.diagnostico()["estado"], operacion.ATENCION)

    def test_sincronizacion_reciente_es_ok_y_antigua_es_atencion(self):
        con = db.conectar()
        ahora = dt.datetime.now()
        con.execute("INSERT INTO ejecuciones (inicio, fin, desde, hasta, resumen) VALUES (?,?,?,?,?)",
                    ("x", ahora.isoformat(timespec="seconds"), "2026-10-08", "2026-10-09", '{"ok": true}'))
        con.commit()
        self.assertEqual(operacion.diagnostico()["estado"], operacion.OK)
        con.execute("UPDATE ejecuciones SET fin = ?", ((ahora - dt.timedelta(hours=100)).isoformat(timespec="seconds"),))
        con.commit()
        info = operacion.diagnostico()
        self.assertEqual(info["estado"], operacion.ATENCION)
        self.assertGreater(info["horas_desde_ultima_sincronizacion"], 99)
        con.close()

    def test_depurar_robots_borra_solo_lo_prohibido_tras_copia(self):
        con = db.conectar()
        prohibido = "https://www.boe.es/boe/dias/2026/10/08/pdfs/BOE-A-2026-1.pdf"
        permitido = "https://ejemplo.es/permitido.pdf"
        for url, via in ((prohibido, "boe-xml"), (permitido, "pdf")):
            con.execute("INSERT INTO documentos (url, fuente, estado, via, caracteres, texto, procesado) "
                        "VALUES (?,?,?,?,?,?,?)", (url, "x", "ok", via, 0, b"", "x"))
        con.execute("INSERT INTO tablas (url, pagina, orden, contexto, salarial, puntuacion, filas) "
                    "VALUES (?,?,?,?,?,?,?)", (prohibido, 1, 1, "", 0, 0.0, "[]"))
        con.commit()
        con.close()

        def falso(url):
            if "xml.php" in url:
                raise robots.Bloqueada(url)

        with mock.patch.object(robots, "comprobar", side_effect=falso):
            sin_cambios = operacion.depurar_robots(aplicar=False)
            self.assertEqual(len(sin_cambios["lista"]), 1)
            self.assertIsNone(sin_cambios["copia"])
            resultado = operacion.depurar_robots(aplicar=True)
        self.assertIsNotNone(resultado["copia"])
        con = db.conectar()
        self.assertEqual([r[0] for r in con.execute("SELECT url FROM documentos")], [permitido])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM tablas").fetchone()[0], 0)
        con.close()


class PruebasRegcon(unittest.TestCase):
    FICHA = """<html><body>
      <div>EMSER 2002 S.L.U. (POLLENÇA) -</div>
      <div>07002582012006</div>
      <button>Copiar Código</button><button>Exportar Acuerdo</button>
      <div>PUBLICADO</div><div>Información</div>
      <p>Convenio publicado con fecha: 01/02/2026</p>
      <a href="chrome-extension://efaidnbmnnnibpcajpcglclefindmkaj/https://bop.dipuleon.es/x.pdf">Ver</a>
    </body></html>"""

    def test_enlace_envuelto_en_visor_se_desenvuelve(self):
        self.assertEqual(regcon._desenvolver_url(
            "chrome-extension://efaidnbmnnnibpcajpcglclefindmkaj/https://bop.dipuleon.es/x.pdf"),
            "https://bop.dipuleon.es/x.pdf")
        self.assertEqual(regcon._desenvolver_url("https://www.boe.es/a.pdf"), "https://www.boe.es/a.pdf")

    def test_enlace_con_https_delante_del_visor(self):
        self.assertEqual(regcon._desenvolver_url(
            "https://chrome-extension://efaidnbmnnnibpcajpcglclefindmkaj/https://www.dipucuenca.es/a.pdf?t=1"),
            "https://www.dipucuenca.es/a.pdf?t=1")

    def test_ficha_usa_la_url_real(self):
        ficha = regcon.parse_ficha(self.FICHA)
        self.assertEqual(ficha["url_publicacion"], "https://bop.dipuleon.es/x.pdf")
        self.assertEqual(ficha["fecha_publicacion"], "2026-02-01")


class PruebasPanelProduccion(unittest.TestCase):
    def setUp(self):
        _datos_temporales(self)
        db.conectar().close()
        self.cli = web.crear_app(permitir_iframe=False, hosts_permitidos=()).test_client()

    def test_host_no_permitido_se_rechaza(self):
        self.assertEqual(self.cli.get("/", base_url="http://evil.example").status_code, 400)
        self.assertEqual(self.cli.get("/", base_url="http://127.0.0.1:8000").status_code, 200)
        self.assertEqual(self.cli.get("/", base_url="http://localhost").status_code, 200)

    def test_host_permitido_por_configuracion(self):
        cli = web.crear_app(hosts_permitidos=("convenios.ejemplo.es", "*.ejemplo.es")).test_client()
        self.assertEqual(cli.get("/", base_url="http://panel.ejemplo.es").status_code, 200)
        self.assertEqual(cli.get("/", base_url="http://convenios.ejemplo.es").status_code, 200)
        self.assertEqual(cli.get("/", base_url="http://ejemplo.es").status_code, 400)
        self.assertEqual(cli.get("/", base_url="http://otro.org").status_code, 400)

    def test_funcion_de_nombres(self):
        self.assertTrue(web.host_permitido("[::1]:8000", ()))
        self.assertTrue(web.host_permitido("localhost:8000", ()))
        self.assertFalse(web.host_permitido("evil.example:80", ()))
        self.assertTrue(web.host_permitido("x.e2b.app", ("*.e2b.app",)))
        self.assertFalse(web.host_permitido("e2b.app", ("*.e2b.app",)))

    def test_cabeceras_de_seguridad(self):
        r = self.cli.get("/")
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'none'", r.headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])

    def test_con_iframe_permitido_no_se_envia_x_frame_options(self):
        r = web.crear_app(permitir_iframe=True, hosts_permitidos=()).test_client().get("/")
        self.assertNotIn("X-Frame-Options", r.headers)
        self.assertIn("frame-ancestors *", r.headers["Content-Security-Policy"])

    def test_post_exige_origin_del_mismo_panel(self):
        datos = {"termino": "metal"}
        self.assertEqual(self.cli.post("/seguimiento/nuevo", data=datos).status_code, 403)
        self.assertEqual(self.cli.post("/seguimiento/nuevo", data=datos,
                                       headers={"Origin": "http://evil.example"}).status_code, 403)
        self.assertEqual(self.cli.post("/seguimiento/nuevo", data=datos,
                                       headers={"Origin": "null"}).status_code, 403)
        self.assertEqual(self.cli.post("/seguimiento/nuevo", data=datos,
                                       headers={"Origin": "http://localhost"}).status_code, 302)

    def test_autenticacion_con_usuario_y_contrasena(self):
        acceso.guardar("ana", CLAVE)
        r = self.cli.get("/")
        self.assertEqual(r.status_code, 401)
        self.assertIn("Basic", r.headers["WWW-Authenticate"])
        buena = {"Authorization": "Basic " + base64.b64encode(f"ana:{CLAVE}".encode()).decode()}
        mala = {"Authorization": "Basic " + base64.b64encode(b"ana:mala-clave-larga").decode()}
        self.assertEqual(self.cli.get("/", headers=buena).status_code, 200)
        self.assertEqual(self.cli.get("/", headers=mala).status_code, 401)
        self.assertEqual(self.cli.get("/salud").status_code, 200)  # la monitorización no necesita usuario

    def test_salud_devuelve_json(self):
        datos = self.cli.get("/salud").get_json()
        self.assertIn(datos["estado"], ("ok", "atencion", "error"))
        self.assertIn("umbral_horas", datos)

    def test_errores_no_muestran_detalles_internos(self):
        r = self.cli.get("/no-existe")
        self.assertEqual(r.status_code, 404)
        self.assertIn("Error 404", r.get_data(as_text=True))
        with mock.patch.object(operacion, "diagnostico", side_effect=RuntimeError("secreto-interno")), \
                self.assertLogs("convenios.web", level="ERROR") as registrado:
            r = self.cli.get("/salud")
        self.assertIn("secreto-interno", "\n".join(registrado.output))  # el detalle queda en el registro
        self.assertEqual(r.status_code, 500)
        texto = r.get_data(as_text=True)
        self.assertIn("Error 500", texto)
        self.assertNotIn("secreto-interno", texto)

    def test_avisos_de_celdas_vacias_y_bloqueadas(self):
        self.assertNotEqual(web._aviso_vacias([["a", "", ""], ["x", "", ""]]), "")
        self.assertEqual(web._aviso_vacias([["a", "b"], ["1", "2"]]), "")
        self.assertIn("bloqueada", web._badge_documento(
            {"url_publicacion": "x", "doc_estado": "bloqueada", "doc_error": None}))


class PruebasLineaDeComandos(unittest.TestCase):
    def setUp(self):
        _datos_temporales(self)

    def test_estado_comprobar_devuelve_el_codigo_de_salida(self):
        for estado, codigo in (("ok", 0), ("atencion", 2), ("error", 1)):
            info = {"estado": estado, "mensajes": [], "ultima_sincronizacion_correcta": None,
                    "horas_desde_ultima_sincronizacion": None, "umbral_horas": 72, "base_datos": "ok"}
            with mock.patch.object(operacion, "diagnostico", return_value=info), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli_main.main(["estado", "--comprobar"]), codigo)

    def test_web_produccion_sin_usuario_se_niega(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli_main.main(["web", "--produccion"]), 1)

    def test_sync_con_otra_sincronizacion_en_marcha_sale_con_codigo_3(self):
        sync._bloquear_sincronizacion()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caso:
                cli_main.main(["sync", "--desde", "2026-01-05", "--hasta", "2026-01-05",
                               "--sin-boe", "--sin-documentos"])
        self.assertEqual(caso.exception.code, 3)

    def test_copia_desde_la_linea_de_comandos(self):
        db.conectar().close()
        with contextlib.redirect_stdout(io.StringIO()) as salida:
            self.assertEqual(cli_main.main(["copia", "--conservar", "2"]), 0)
        self.assertIn("Copia creada en", salida.getvalue())
        self.assertEqual(len(copias.listar()), 1)

    def test_version(self):
        with contextlib.redirect_stdout(io.StringIO()) as salida, self.assertRaises(SystemExit):
            cli_main.main(["--version"])
        # Se compara con __version__: la prueba no hay que tocarla en cada versión nueva.
        self.assertEqual(salida.getvalue().strip(), f"convenios {__version__}")



SUMARIO_JSON = {"data": {"sumario": {"diario": {"seccion": [
    {"codigo": "1", "departamento": {"nombre": "Otro", "epigrafe": {"nombre": "Otros", "item": {
        "identificador": "BOE-A-2026-9", "titulo": "Ley de prueba", "url_html": {"texto": "https://x/9.html"}}}}},
    {"codigo": "3", "departamento": {"nombre": "Ministerio de Trabajo", "epigrafe": {
        "nombre": "Convenios colectivos de trabajo", "item": [
            {"identificador": "BOE-A-2026-1", "titulo": "Resolución por la que se registra el convenio colectivo X",
             "url_html": {"texto": "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-1"},
             "url_pdf": {"texto": "https://www.boe.es/boe/dias/2026/10/09/pdfs/BOE-A-2026-1.pdf"},
             "url_xml": {"texto": "https://www.boe.es/diario_boe/xml.php?id=BOE-A-2026-1"}}]}}}]}}}}

XML_BOE = (b"<documento><analisis><texto>No debe usarse</texto></analisis><texto>"
           b"<p>Articulo 1. Ambito.</p>"
           b"<table><tr><td>Nivel</td><td>Salario base</td></tr><tr><td>Grupo 1</td><td>1.234,56</td></tr></table>"
           b"<p>Fin.</p></texto></documento>")


class PruebasBoe(unittest.TestCase):
    def test_sumario_separa_los_convenios(self):
        from convenios import boe
        respuesta = mock.Mock(status_code=200)
        respuesta.json.return_value = SUMARIO_JSON
        with mock.patch.object(boe, "pedir", return_value=respuesta):
            items = boe.sumario(dt.date(2026, 10, 9))
        self.assertEqual(len(items), 2)
        convenios_ = [i for i in items if boe.es_convenio(i)]
        self.assertEqual([i["identificador"] for i in convenios_], ["BOE-A-2026-1"])
        self.assertEqual(convenios_[0]["url_pdf"], "https://www.boe.es/boe/dias/2026/10/09/pdfs/BOE-A-2026-1.pdf")

    def test_dia_sin_boe_devuelve_lista_vacia(self):
        from convenios import boe
        with mock.patch.object(boe, "pedir", return_value=mock.Mock(status_code=404)):
            self.assertEqual(boe.sumario(dt.date(2026, 10, 11)), [])

    def test_texto_del_xml_ignora_el_analisis(self):
        from convenios import boe
        with mock.patch.object(boe, "pedir", return_value=_Resp(200, contenido=XML_BOE)):
            texto, tablas = boe.documento_xml("BOE-A-2026-1")
        self.assertNotIn("No debe usarse", texto)
        self.assertIn("Articulo 1. Ambito.", texto)
        self.assertEqual(len(tablas), 1)
        self.assertEqual(tablas[0]["filas"][1], ["Grupo 1", "1.234,56"])
        self.assertEqual(tablas[0]["contexto"], "Articulo 1. Ambito.")


class PruebasReparto(unittest.TestCase):
    def setUp(self):
        _datos_temporales(self)
        self.con = db.conectar()
        self.addCleanup(self.con.close)

    def test_las_urls_alternan_servidores(self):
        urls = ["https://a.es/1", "https://a.es/2", "https://b.es/1"]
        self.assertEqual(sync._intercalar_por_servidor(urls), ["https://a.es/1", "https://b.es/1", "https://a.es/2"])

    def test_resumen_de_publicaciones_por_estado(self):
        urls = ["https://a.es/ok.pdf", "https://a.es/bloq.pdf", "https://b.es/err.pdf"]

        def falso(url):
            if "bloq" in url:
                raise robots.Bloqueada(url)
            if "err" in url:
                raise ValueError("HTTP 403")
            return {"texto": "x" * 300, "paginas": 1, "tablas": [], "via": "pdf"}

        with mock.patch.object(sync, "_urls_pendientes", return_value=urls), \
                mock.patch.object(documentos, "procesar", side_effect=falso):
            resumen = sync.sincronizar_documentos(self.con, hilos=2)
        self.assertEqual((resumen["total"], resumen["ok"], resumen["bloqueada"], resumen["error"]), (3, 1, 1, 1))
        estados = {r[0]: r[1] for r in self.con.execute("SELECT url, estado FROM documentos")}
        self.assertEqual(estados["https://b.es/err.pdf"], "error")
        self.assertEqual(estados["https://a.es/bloq.pdf"], "bloqueada")

if __name__ == "__main__":
    unittest.main()
