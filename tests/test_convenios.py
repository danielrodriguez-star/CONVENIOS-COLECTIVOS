"""Pruebas del programa (biblioteca estándar, sin dependencias extra).

Ejecutar desde la carpeta del proyecto:
    python -m unittest discover -s tests -v
Usan una carpeta temporal de datos: no tocan convenios.db ni seguimiento.db.
"""
import csv
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
_TMP = tempfile.mkdtemp(prefix="convenios_pruebas_")
os.environ["CONVENIOS_DATOS"] = _TMP  # debe fijarse antes de importar el paquete

from convenios import __main__ as cli_main  # noqa: E402
from convenios import db, documentos, regcon, sync  # noqa: E402
from convenios.util import celda_csv  # noqa: E402


def _nueva_bd(nombre):
    ruta = Path(_TMP) / nombre
    if ruta.exists():
        ruta.unlink()
    return db.conectar(ruta)


class PruebasFicha(unittest.TestCase):
    """La ficha de REGCON: tras el código van los botones, luego los estados en mayúsculas."""

    HTML = """<html><body>
      <div>EMSER 2002 S.L.U. (POLLENÇA) -</div>
      <div>07002582012006</div>
      <button>Copiar Código</button><button>Copiar Denominación</button><button>Exportar Acuerdo</button>
      <div>PUBLICADO</div><div>DENUNCIADO</div>
      <div>Información</div><div>Acuerdo</div>
      <div>Expedientes</div>
      <div>EXPEDIENTE 07/01/0117/2025</div><div>TRAMITADO</div><div>ACUERDO PARCIAL</div>
      <div>publicado con fecha: 14/10/2025</div>
      <a href="https://www.caib.es/eboibfront/ca/2025/12172/707028/">BOIB</a>
      <div>Hoja 1</div>
    </body></html>"""

    def test_estado_no_incluye_expediente_ni_tramitacion(self):
        ficha = regcon.parse_ficha(self.HTML)
        self.assertEqual(ficha["estado"], "PUBLICADO | DENUNCIADO")
        self.assertEqual(ficha["n_expediente"], "07/01/0117/2025")
        self.assertEqual(ficha["codigo"], "07002582012006")
        self.assertEqual(ficha["fecha_publicacion"], "2025-10-14")

    def test_estado_de_dos_partes_con_texto_no_denunciado(self):
        html = self.HTML.replace("<div>DENUNCIADO</div>", "<div>NO DENUNCIADO</div>")
        self.assertIn("NO DENUNCIADO", html)
        self.assertEqual(regcon.parse_ficha(html)["estado"], "PUBLICADO | NO DENUNCIADO")


class PruebasDocumentos(unittest.TestCase):
    TEXTO = "Ordenación del trabajo: ¡Ó! € «comillas» ñ"

    def test_utf8_sin_cabecera_ni_meta(self):
        datos = f"<html><body><p>{self.TEXTO}</p></body></html>".encode("utf-8")
        self.assertIn(self.TEXTO, documentos.procesar_html(datos, "")["texto"])

    def test_cp1252_declarado_en_cabecera(self):
        datos = f"<html><body><p>{self.TEXTO}</p></body></html>".encode("cp1252", "replace")
        self.assertIn(self.TEXTO, documentos.procesar_html(datos, "text/html; charset=windows-1252")["texto"])

    def test_utf8_con_meta_mal_etiquetada(self):
        datos = (f'<html><head><meta charset="iso-8859-1"></head><body><p>{self.TEXTO}</p></body></html>'
                 .encode("utf-8"))
        texto = documentos.procesar_html(datos, "text/html")["texto"]
        self.assertIn(self.TEXTO, texto)
        self.assertNotIn("Ã", texto)

    def test_declaracion_xml_no_rompe_el_parseo(self):
        datos = ('<?xml version="1.0" encoding="UTF-8"?><html><body><p>' + self.TEXTO + "</p></body></html>"
                 ).encode("utf-8")
        self.assertIn(self.TEXTO, documentos.procesar_html(datos, "application/xhtml+xml")["texto"])

    def test_pagina_de_captcha_es_error(self):
        datos = (b"<html><head><title>Radware Captcha Page</title></head>"
                 b"<body><p>Please enable JS and disable any ad blocker</p></body></html>")
        with self.assertRaises(ValueError):
            documentos.procesar_html(datos, "text/html")

    def test_tabla_salarial_frente_a_tabla_de_texto(self):
        salarial = [["Categoría", "Salario base", "Plus"], ["Oficial", "1.234,56", "45,00"],
                    ["Peón", "1.100,00", "30,00"]]
        otra = [["Nombre", "Dirección"], ["Ana", "Calle Mayor 1"], ["Luis", "Plaza Sol 2"]]
        self.assertEqual(documentos.puntuar_tabla(salarial, "")[0], 1)
        self.assertEqual(documentos.puntuar_tabla(otra, "")[0], 0)


class PruebasDescarga(unittest.TestCase):
    class Respuesta:
        def __init__(self, trozos):
            self._trozos, self.cerrada = trozos, False

        def iter_content(self, chunk_size=1):
            return iter(self._trozos)

        def close(self):
            self.cerrada = True

    def test_lee_completo_si_no_supera_el_limite(self):
        self.assertEqual(documentos.leer_acotado(self.Respuesta([b"ab", b"cd"]), limite=10), b"abcd")

    def test_corta_si_supera_el_limite(self):
        r = self.Respuesta([b"a" * 6, b"b" * 6])
        with self.assertRaises(ValueError):
            documentos.leer_acotado(r, limite=10)
        self.assertTrue(r.cerrada)


class PruebasListado(unittest.TestCase):
    """listar() debe devolver todas las filas, sin duplicados, aunque REGCON pagine mal."""

    class FalsoRegcon:
        """Simula el buscador: total = filas que cumplen los criterios fijos; 15 filas por página."""

        def __init__(self, filas, opciones):
            self.filas, self.opciones, self.buscada = filas, opciones, filas

        def valores(self, campo):
            return self.opciones[campo]

        def buscar(self, desde, hasta, fijos=None):
            fijos = fijos or {}
            self.buscada = [f for f in self.filas if all(f[k] == v for k, v in fijos.items())]
            return len(self.buscada), self.buscada[:regcon.config.REGCON_TAM_PAGINA]

        def pagina(self, n):
            t = regcon.config.REGCON_TAM_PAGINA
            return self.buscada[(n - 1) * t:n * t]

    def _opciones(self):
        return {"idAmbFuncionalConsPublica": ["1", "2", "3"], "idEstadoVigencia": ["a", "b"],
                "idTipoTramiteConsPublica": ["x", "y"], "autoridadLaboral": ["m", "n", "o", "p", "q"]}

    def test_reparte_y_recupera_todas_las_filas(self):
        filas = [{"id_expediente": i, "idAmbFuncionalConsPublica": str(1 + i % 3), "idEstadoVigencia": "ab"[i % 2],
                  "idTipoTramiteConsPublica": "xy"[i % 2], "autoridadLaboral": "mnopq"[i % 5]}
                 for i in range(100)]
        total, unicas, completo = regcon.listar(self.FalsoRegcon(filas, self._opciones()),
                                                dt.date(2026, 1, 1), dt.date(2026, 1, 1))
        self.assertTrue(completo)
        self.assertEqual(sorted(f["id_expediente"] for f in unicas), list(range(100)))

    def test_si_no_se_puede_repartir_queda_marcado_incompleto(self):
        filas = [{"id_expediente": i, "idAmbFuncionalConsPublica": "1", "idEstadoVigencia": "a",
                  "idTipoTramiteConsPublica": "x", "autoridadLaboral": "m"} for i in range(40)]
        _, unicas, completo = regcon.listar(self.FalsoRegcon(filas, self._opciones()),
                                            dt.date(2026, 1, 1), dt.date(2026, 1, 1))
        self.assertFalse(completo)
        self.assertEqual(len(unicas), 40)


class PruebasExportacion(unittest.TestCase):
    def test_celda_csv_neutraliza_formulas(self):
        self.assertEqual(celda_csv("=SUMA(A1)"), "'=SUMA(A1)")
        self.assertEqual(celda_csv("-10"), "'-10")
        self.assertEqual(celda_csv("+34"), "'+34")
        self.assertEqual(celda_csv("@x"), "'@x")
        self.assertEqual(celda_csv("Texto normal"), "Texto normal")
        self.assertEqual(celda_csv(""), "")
        self.assertEqual(celda_csv(12), 12)
        self.assertIsNone(celda_csv(None))

    def test_tablas_no_se_duplican_con_varios_tramites_del_mismo_convenio(self):
        con = _nueva_bd("exportacion.db")
        url = "https://ejemplo.org/boletin.pdf"
        con.execute("""INSERT INTO convenios (codigo, denominacion, ambito, n_tramites, ultimo_tipo_tramite,
                       ultima_fecha_registro, estado, url_ultima_publicacion, tiene_tablas_salariales, busqueda)
                       VALUES ('C1', 'Convenio uno', 'Madrid', 2, 'CONVENIO COLECTIVO', '2026-05-01', 'PUBLICADO',
                       ?, 1, 'convenio uno c1 madrid')""", (url,))
        for i, fecha in enumerate(["2026-04-01", "2026-05-01"], 1):  # dos trámites con la misma publicación
            con.execute("""INSERT INTO tramites (id_expediente, codigo, denominacion, tipo_tramite, ambito,
                           fecha_registro, url_publicacion, detalle_ok, sin_ficha, primera_vista, ultima_vista)
                           VALUES (?, 'C1', 'Convenio uno', 'CONVENIO COLECTIVO', 'Madrid', ?, ?, 1, 0, 'x', 'x')""",
                        (i, fecha, url))
        con.execute("INSERT INTO documentos (url, fuente, estado, via, caracteres) VALUES (?, 'ejemplo.org', 'ok', 'pdf', 9)",
                    (url,))
        filas = [["Categoría", "Salario base"], ["Oficial", "1.234,56"], ["Peón", "1.100,00"]]
        con.execute("INSERT INTO tablas (url, pagina, orden, contexto, salarial, puntuacion, filas) VALUES (?,?,?,?,?,?,?)",
                    (url, 3, 1, "", 1, 2.0, __import__("json").dumps(filas, ensure_ascii=False)))
        con.commit()
        carpeta = Path(_TMP) / "export_tablas"
        cli_main.exportar(con, carpeta)
        con.close()
        with open(carpeta / "tablas_salariales.csv", encoding="utf-8-sig", newline="") as f:
            filas_csv = list(csv.reader(f, delimiter=";"))[1:]
        # La tabla tiene 3 filas (cabecera incluida). Con un JOIN por trámite serían 6.
        self.assertEqual(len(filas_csv), 3, "una fila por cada fila de la tabla, no por trámite")
        self.assertEqual({r[7] for r in filas_csv}, {"1", "2", "3"})


class PruebasSincronizacion(unittest.TestCase):
    def tearDown(self):
        if sync._bloqueo_sync is not None:
            sync._bloqueo_sync.close()
            sync._bloqueo_sync = None

    def test_listado_con_avisos_no_cuenta_como_correcto(self):
        _nueva_bd("sync_ok.db").close()
        dia = dt.date(2026, 1, 5)
        listado = {"filas": 0, "nuevos": 0, "errores": [], "avisos": [f"{dia}: listado incompleto"]}
        with mock.patch.object(sync, "sincronizar_listado", return_value=listado), \
                mock.patch.object(sync, "sincronizar_fichas", return_value=(0, 0)), \
                mock.patch.object(sync, "recalcular_convenios", return_value=0):
            res = sync.sincronizar(desde=dia, hasta=dia, boe_on=False, documentos_on=False)
        self.assertFalse(res["ok"])

    def test_no_se_puede_lanzar_dos_sincronizaciones(self):
        sync._bloquear_sincronizacion()
        with self.assertRaises(SystemExit) as caso:
            sync._bloquear_sincronizacion()
        self.assertEqual(caso.exception.code, 3)  # código 3: otra sincronización en marcha


class PruebasPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from convenios.web import crear_app
        _nueva_bd("panel.db").close()
        cls.cli = crear_app().test_client()

    def test_rutas_con_entradas_raras_no_fallan(self):
        for ruta in ["/?p=-5", "/?p=abc", "/?p=999999", "/?q=%25_%25", "/?ambito=%27%20OR%201%3D1--",
                     "/convenio/NO-EXISTE", "/documento", "/seguimiento", "/exportar/convenios.csv",
                     "/api/convenios?q=metal"]:
            self.assertIn(self.cli.get(ruta).status_code, (200, 404), ruta)

    def test_fecha_no_valida_muestra_aviso(self):
        texto = self.cli.get("/?desde=2026-13-45").get_data(as_text=True)
        self.assertIn("no es válida", texto)

    def test_exportacion_csv_con_cabecera(self):
        respuesta = self.cli.get("/exportar/convenios.csv")
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.get_data(as_text=True).lstrip("\ufeff").startswith("codigo;"))

    def test_borrar_con_id_no_numerico_es_peticion_incorrecta(self):
        # Con Origin de este panel (protección frente a CSRF) el id no numérico es una petición incorrecta.
        cabeceras = {"Origin": "http://localhost"}
        self.assertEqual(self.cli.post("/seguimiento/borrar", data={"id": "abc"}, headers=cabeceras).status_code, 400)


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
