"""Prueba dinámica de escape HTML en el panel web.

Crea una base de datos temporal con cargas maliciosas en los campos que vienen de webs externas,
pide cada página del panel y comprueba que ninguna etiqueta llega sin escapar.
No usa ni modifica datos/convenios.db.

Uso (desde la carpeta del proyecto):
    python auditoria/prueba_seguridad_panel.py
Código de salida 1 si alguna página HTML devuelve una etiqueta sin escapar.
"""
import json
import os
import sys
import tempfile
import zlib

import comun  # ajusta sys.path antes de importar convenios

assert comun.RAIZ.is_dir()
os.environ["CONVENIOS_DATOS"] = tempfile.mkdtemp(prefix="auditoria_xss_")

from convenios import db  # noqa: E402
from convenios.web import crear_app  # noqa: E402

CARGA = "<img src=x onerror=alert(1)><script>alert(2)</script>"
ETIQUETAS_PELIGROSAS = ("<img src=x", "<script>alert")


def preparar_base():
    con = db.conectar()
    con.execute("""INSERT INTO convenios (codigo, denominacion, ambito, n_tramites, ultimo_tipo_tramite,
                   ultima_fecha_registro, vigencia_hasta, estado, url_ultima_publicacion, tiene_tablas_salariales, busqueda)
                   VALUES ('C9', ?, ?, 1, ?, '2026-01-01', NULL, ?, 'https://ejemplo.org/b.pdf', 1, 'x')""",
                (CARGA, CARGA, CARGA, CARGA))
    con.execute("""INSERT INTO tramites (id_expediente, codigo, denominacion, tipo_tramite, ambito, fecha_registro,
                   n_expediente, estado, url_publicacion, detalle_ok, sin_ficha, primera_vista, ultima_vista)
                   VALUES (1, 'C9', ?, ?, ?, '2026-01-01', ?, ?, 'https://ejemplo.org/b.pdf', 1, 0, '2026-01-01', '2026-01-01')""",
                (CARGA, CARGA, CARGA, CARGA, CARGA))
    con.execute("""INSERT INTO documentos (url, fuente, estado, error, via, caracteres, texto, procesado)
                   VALUES ('https://ejemplo.org/b.pdf', 'ejemplo.org', 'ok', ?, 'pdf', 10, ?, '2026-01-01')""",
                (CARGA, zlib.compress(CARGA.encode(), 9)))
    filas = [[CARGA, "1.234,56"], [CARGA, "2.000,00"], ["Salario base", "1.000,00"]]
    con.execute("""INSERT INTO tablas (url, pagina, orden, contexto, salarial, puntuacion, filas)
                   VALUES ('https://ejemplo.org/b.pdf', 1, 1, ?, 1, 2.0, ?)""", (CARGA, json.dumps(filas)))
    con.execute("INSERT INTO ejecuciones (inicio, fin, desde, hasta, resumen) VALUES (?, ?, ?, ?, ?)",
                (CARGA, CARGA, CARGA, CARGA, json.dumps({"x": CARGA})))
    con.execute("""INSERT INTO boe_disposiciones (identificador, fecha, departamento, epigrafe, titulo, url_html,
                   url_pdf, url_xml, vista) VALUES ('BOE-X', '2026-01-01', ?, ?, ?, 'https://ejemplo.org/x', NULL, NULL, '2026-01-01')""",
                (CARGA, CARGA, CARGA))
    con.commit()
    con.close()


def main():
    preparar_base()
    cli = crear_app().test_client()
    cli.post("/seguimiento/nuevo", data={"termino": CARGA})
    rutas = ["/?q=" + CARGA, "/?ambito=" + CARGA, "/?desde=" + CARGA, "/convenio/C9",
             "/documento?url=https://ejemplo.org/b.pdf", "/estado", "/boe", "/seguimiento",
             "/api/convenios", "/exportar/convenios.csv"]
    fallos = 0
    for ruta in rutas:
        r = cli.get(ruta)
        texto = r.get_data(as_text=True)
        es_html = "html" in r.mimetype
        sin_escapar = [e for e in ETIQUETAS_PELIGROSAS if e in texto]
        if es_html and sin_escapar:
            fallos += 1
            estado = f"SIN ESCAPAR {sin_escapar}"
        else:
            estado = "escapado" if es_html else f"no es HTML ({r.mimetype})"
        print(f"{r.status_code}  {estado:<40} {ruta[:60]}")
    print("páginas HTML con etiquetas sin escapar:", fallos)
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
