"""Pruebas de las correcciones posteriores a la versión 1.1.0.

- Días pendientes: un día que falla o queda incompleto se reintenta y, tras MAX_INTENTOS_DIA, se abandona.
- Un fallo del BOE impide marcar la sincronización como correcta (y se reintenta).
- robots.txt se comprueba en cada salto de redirección (con un servidor local real).
- Los comodines % y _ de la búsqueda se tratan como texto.
- El XML del BOE no resuelve entidades externas.
- Sin --produccion, el panel no atiende a otros equipos.

Ejecutar desde la carpeta del proyecto:
    python -m unittest discover -s tests -v
"""
import contextlib
import datetime as dt
import http.server
import io
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from test_produccion import _Resp, _datos_temporales, _soltar_bloqueo  # noqa: E402

from convenios import __main__ as cli_main  # noqa: E402
from convenios import boe, db, documentos, robots, sync, web  # noqa: E402


def _listar_falso(completo=True, error=None, llamadas=None):
    """Sustituto de regcon.listar: sin filas, con el resultado indicado."""
    def falso(cli, desde, hasta, fijos=None, nivel=0):
        if llamadas is not None:
            llamadas.append(desde)
        if error:
            raise RuntimeError(error)
        return 0, [], completo
    return falso


class _SincronizacionBase(unittest.TestCase):
    def setUp(self):
        _datos_temporales(self)
        db.conectar().close()  # crea la base y su esquema en la carpeta temporal

    def correr(self, desde, hasta, boe_on=False):
        _soltar_bloqueo()  # cada ejecución es un proceso distinto: suelta el bloqueo de la anterior
        with contextlib.redirect_stdout(io.StringIO()):
            with mock.patch.object(sync, "Regcon"):
                return sync.sincronizar(desde=desde, hasta=hasta, boe_on=boe_on, documentos_on=False)

    def pendientes(self, fuente):
        con = db.conectar()
        try:
            return [(r[0], r[1]) for r in con.execute(
                "SELECT dia, intentos FROM dias_pendientes WHERE fuente = ? ORDER BY dia", (fuente,))]
        finally:
            con.close()


class PruebasDiasPendientes(_SincronizacionBase):
    DIA = dt.date(2026, 1, 5)
    OTRO_DIA = dt.date(2026, 1, 20)

    def test_listado_incompleto_se_reintenta_en_la_siguiente_ejecucion(self):
        with mock.patch.object(sync, "listar", side_effect=_listar_falso(completo=False)):
            res = self.correr(self.DIA, self.DIA)
        self.assertFalse(res["ok"])
        self.assertEqual(self.pendientes("regcon"), [(self.DIA.isoformat(), 1)])

        # La siguiente ejecución cubre otro día: el pendiente se consulta igualmente, fuera de la ventana.
        consultados = []
        with mock.patch.object(sync, "listar", side_effect=_listar_falso(completo=True, llamadas=consultados)):
            res = self.correr(self.OTRO_DIA, self.OTRO_DIA)
        self.assertIn(self.DIA, consultados)
        self.assertTrue(res["ok"])
        self.assertEqual(self.pendientes("regcon"), [])

    def test_dia_se_abandona_tras_agotar_los_intentos(self):
        with mock.patch.object(sync, "listar", side_effect=_listar_falso(completo=False)):
            for intento in range(1, sync.MAX_INTENTOS_DIA):
                res = self.correr(self.DIA, self.DIA)
                self.assertFalse(res["ok"], f"intento {intento}")
                self.assertEqual(self.pendientes("regcon"), [(self.DIA.isoformat(), intento)])
            res = self.correr(self.DIA, self.DIA)  # último intento: se abandona y la ejecución es correcta
        self.assertTrue(res["ok"])
        self.assertEqual(self.pendientes("regcon"), [])
        self.assertEqual(res["regcon_listado"]["abandonados"], [self.DIA.isoformat()])

    def test_la_ventana_avanza_aunque_haya_dias_pendientes(self):
        # Antes, un día pendiente bloqueaba la ventana: cada ejecución volvía a consultar desde aquel día.
        hoy = dt.date.today()
        dia = hoy - dt.timedelta(days=60)
        with mock.patch.object(sync, "listar", side_effect=_listar_falso(completo=False)):
            self.correr(dia, dia)
        self.assertEqual(self.pendientes("regcon"), [(dia.isoformat(), 1)])
        consultados = []
        with mock.patch.object(sync, "listar", side_effect=_listar_falso(llamadas=consultados)):
            res = self.correr(None, hoy)  # sin fechas: ventana por defecto
        self.assertEqual(res["desde"], (dia - dt.timedelta(days=7)).isoformat())
        self.assertIn(dia, consultados)  # el día pendiente se vuelve a consultar
        self.assertTrue(res["ok"])
        self.assertEqual(self.pendientes("regcon"), [])

    def test_error_de_regcon_queda_pendiente(self):
        with mock.patch.object(sync, "listar", side_effect=_listar_falso(error="HTTP 503")):
            res = self.correr(self.DIA, self.DIA)
        self.assertFalse(res["ok"])
        self.assertEqual(self.pendientes("regcon"), [(self.DIA.isoformat(), 1)])

    def test_fallo_del_boe_impide_marcar_correcta_y_se_reintenta(self):
        # Antes, un día del BOE caído no afectaba a «ok» y la ventana avanzaba sin volver a pedirlo.
        with mock.patch.object(sync, "listar", side_effect=_listar_falso()), \
                mock.patch.object(boe, "sumario", side_effect=ConnectionError("sin red")):
            res = self.correr(self.DIA, self.DIA, boe_on=True)
        self.assertFalse(res["ok"])
        self.assertEqual(self.pendientes("boe"), [(self.DIA.isoformat(), 1)])

        pedidos = []

        def sumario_ok(dia):
            pedidos.append(dia)
            return []
        with mock.patch.object(sync, "listar", side_effect=_listar_falso()), \
                mock.patch.object(boe, "sumario", side_effect=sumario_ok):
            res = self.correr(self.OTRO_DIA, self.OTRO_DIA, boe_on=True)
        self.assertIn(self.DIA, pedidos)
        self.assertTrue(res["ok"])
        self.assertEqual(self.pendientes("boe"), [])


class _Servidor:
    """Servidor HTTP local de pruebas. `rutas`: ruta → (código, cabeceras, cuerpo)."""

    def __init__(self, testcase, rutas):
        self.visitas = []
        visitas, rutas_ = self.visitas, rutas

        class Manejador(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                visitas.append(self.path)
                codigo, cabeceras, cuerpo = rutas_.get(self.path, (404, {}, b""))
                self.send_response(codigo)
                for k, v in cabeceras.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

        self.servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        testcase.addCleanup(self.servidor.shutdown)
        testcase.addCleanup(self.servidor.server_close)
        self.base = f"http://127.0.0.1:{self.servidor.server_port}"


class PruebasRedireccionesRobots(unittest.TestCase):
    HTML = ("<html><body><h1>Convenio colectivo de prueba</h1>"
            + "<p>Texto del convenio colectivo, articulo uno. </p>" * 30 + "</body></html>").encode("utf-8")
    ROBOTS = b"User-agent: *\nDisallow: /privado/\n"

    def setUp(self):
        p = mock.patch.object(robots, "_COMPROBADOR", robots._Comprobador())
        p.start()
        self.addCleanup(p.stop)
        # Las peticiones al servidor local no deben pasar por ningún proxy del entorno.
        p = mock.patch.dict(os.environ, {"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
        p.start()
        self.addCleanup(p.stop)

    def _servidor(self, **extra):
        rutas = {
            "/robots.txt": (200, {"Content-Type": "text/plain"}, self.ROBOTS),
            "/ok.html": (200, {"Content-Type": "text/html; charset=utf-8"}, self.HTML),
            "/privado/convenio.html": (200, {"Content-Type": "text/html; charset=utf-8"}, self.HTML),
        }
        rutas.update(extra)
        return _Servidor(self, rutas)

    def test_redireccion_a_ruta_prohibida_no_se_descarga(self):
        srv = self._servidor(**{"/publicado.html": (302, {"Location": "/privado/convenio.html"}, b"")})
        with self.assertRaises(robots.Bloqueada):
            documentos.descargar(srv.base + "/publicado.html")
        self.assertNotIn("/privado/convenio.html", srv.visitas)  # la ruta prohibida nunca se pide
        self.assertIn("/robots.txt", srv.visitas)  # el salto se comprobó con robots.txt

    def test_redireccion_a_ruta_permitida_se_sigue(self):
        srv = self._servidor(**{"/publicado.html": (301, {"Location": "/ok.html"}, b"")})
        datos, ctype, legado = documentos.descargar(srv.base + "/publicado.html")
        self.assertIn(b"Convenio colectivo de prueba", datos)
        self.assertIn("text/html", ctype)
        self.assertFalse(legado)

    def test_redireccion_en_bucle_es_error(self):
        srv = self._servidor(**{"/a.html": (302, {"Location": "/a.html"}, b"")})
        with self.assertRaises(ValueError):
            documentos.descargar(srv.base + "/a.html")

    def test_redireccion_a_protocolo_no_permitido_es_error(self):
        srv = self._servidor(**{"/a.html": (302, {"Location": "file:///etc/passwd"}, b"")})
        with self.assertRaises(ValueError):
            documentos.descargar(srv.base + "/a.html")


class PruebasXmlBoe(unittest.TestCase):
    def test_entidad_externa_no_lee_ficheros_locales(self):
        tmp = tempfile.mkdtemp(prefix="convenios_xxe_")
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        secreto = Path(tmp) / "secreto.txt"
        secreto.write_text("SECRETO-XML-123", encoding="utf-8")
        xml = (f'<?xml version="1.0"?>\n<!DOCTYPE documento [<!ENTITY ext SYSTEM "{secreto.as_uri()}">]>\n'
               '<documento><texto><p>Inicio &ext; fin</p></texto></documento>').encode("utf-8")
        with mock.patch.object(boe, "pedir", return_value=_Resp(200, contenido=xml)):
            texto, _ = boe.documento_xml("BOE-A-2026-1")
        self.assertNotIn("SECRETO-XML-123", texto)


class PruebasBusquedaComodines(_SincronizacionBase):
    def test_los_comodines_se_buscan_como_texto(self):
        con = db.conectar()
        con.execute("INSERT INTO convenios (codigo, denominacion, busqueda) VALUES ('1', 'Metal', 'metal')")
        con.execute("INSERT INTO convenios (codigo, denominacion, busqueda) "
                    "VALUES ('2', 'Metal 100%', 'metal 100% convenio')")
        con.execute("INSERT INTO convenios (codigo, denominacion, busqueda) VALUES ('3', 'a_b', 'a_b')")
        con.commit()

        def contar(q):
            where, params = web._where(web._filtros({"q": q}))
            return con.execute(f"SELECT COUNT(*) FROM convenios WHERE {where}", params).fetchone()[0]

        self.assertEqual(contar("metal"), 2)
        self.assertEqual(contar("%"), 1)   # solo el que contiene un % literal
        self.assertEqual(contar("_"), 1)   # solo el que contiene un _ literal
        self.assertEqual(contar("x%"), 0)
        con.close()


class PruebasAccesoDesdeLaRed(_SincronizacionBase):
    def test_sin_produccion_no_se_atiende_a_otros_equipos(self):
        with mock.patch("flask.Flask.run", side_effect=AssertionError("no debe arrancar")), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli_main.main(["web", "--host", "0.0.0.0"]), 1)

    def test_sin_produccion_en_local_arranca_el_panel(self):
        with mock.patch("flask.Flask.run") as arrancar:
            self.assertEqual(cli_main.main(["web"]), 0)
        arrancar.assert_called_once()


if __name__ == "__main__":
    unittest.main()
