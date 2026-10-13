"""Fidelidad de las tablas salariales: ¿aparecen sus importes en el documento de origen?

Para tablas HTML y PDF compara cada importe con el texto guardado del documento.
Las tablas del BOE no se pueden comprobar así (su texto guardado sustituye las tablas por «[tabla]»);
para ellas hay que consultar el PDF oficial, que sí está permitido por robots.txt.

Uso (desde la carpeta del proyecto):
    python auditoria/comprobar_tablas.py
"""
import json
import re
import sqlite3
import zlib

from comun import base_datos

IMPORTE = re.compile(r"^\d{1,3}(\.\d{3})*,\d{2}$|^\d+,\d{2}$")


def sin_espacios(s):
    return re.sub(r"[\s\u00a0€]", "", s)


def main():
    con = sqlite3.connect(base_datos())
    textos = {}
    totales = {}
    peores = []
    filas_tablas = con.execute("""SELECT b.url, d.via, b.filas FROM tablas b JOIN documentos d ON d.url = b.url
                                  WHERE b.salarial = 1 AND d.estado = 'ok' AND d.via IN ('html', 'pdf')""").fetchall()
    for url, via, filas_json in filas_tablas:
        if url not in textos:
            bruto = con.execute("SELECT texto FROM documentos WHERE url = ?", (url,)).fetchone()[0]
            textos[url] = sin_espacios(zlib.decompress(bruto).decode("utf-8"))
        encontrados = total = 0
        for fila in json.loads(filas_json):
            for celda in fila:
                importe = sin_espacios((celda or "").replace("€", "")).strip()
                if IMPORTE.match(importe):
                    total += 1
                    encontrados += importe in textos[url]
        t, e = totales.get(via, (0, 0))
        totales[via] = (t + total, e + encontrados)
        if total >= 4 and encontrados / total < 0.5:
            peores.append((round(encontrados / total, 2), total, url))

    print("Importes de tablas salariales que aparecen en el texto del documento de origen:")
    for via, (total, enc) in sorted(totales.items()):
        print(f"   {via:<5} {enc:6d} de {total:6d}  ({100 * enc / max(total, 1):.2f} %)")
    print(f"Tablas con menos de la mitad de sus importes en el texto (de más de 4): {len(peores)}")
    for proporcion, total, url in sorted(peores)[:5]:
        print(f"   {proporcion}  ({total} importes)  {url[:90]}")


if __name__ == "__main__":
    main()
