"""Compara las URL que descarga el programa con el robots.txt de cada servidor.

Uso (desde la carpeta del proyecto):
    python auditoria/comprobar_robots.py

Necesita la biblioteca 'protego' (pip install protego), que entiende los comodines de robots.txt.
Solo descarga los robots.txt; no descarga ningún documento.
"""
import collections
import concurrent.futures as cf
import sqlite3
import urllib.parse

import requests
from protego import Protego

from comun import UA_PROGRAMA, base_datos, url_real


def robots_de(netloc):
    """Devuelve (servidor, reglas) con reglas None si no hay robots.txt (permitido) o 'error' si no se pudo leer."""
    for esquema in ("https", "http"):
        try:
            r = requests.get(f"{esquema}://{netloc}/robots.txt", timeout=10, headers={"User-Agent": UA_PROGRAMA})
        except requests.RequestException:
            continue
        if r.status_code == 200:
            return netloc, Protego.parse(r.text)
        if 400 <= r.status_code < 500:
            return netloc, None  # RFC 9309: un 4xx significa que no hay restricciones
        return netloc, "error"
    return netloc, "error"


def main():
    con = sqlite3.connect(base_datos())
    pedidas = {url_real(u) for (u,) in con.execute("SELECT url FROM documentos")}
    por_servidor = collections.defaultdict(list)
    for u in pedidas:
        por_servidor[urllib.parse.urlsplit(u).netloc].append(u)
    with cf.ThreadPoolExecutor(12) as pool:
        reglas = dict(pool.map(robots_de, list(por_servidor)))

    resultado = collections.Counter()
    prohibidas_por_servidor = collections.Counter()
    for servidor, urls in por_servidor.items():
        rp = reglas.get(servidor)
        for u in urls:
            if rp is None:
                resultado["sin robots.txt (permitido)"] += 1
            elif isinstance(rp, str):
                resultado["robots.txt no disponible (sin dictamen)"] += 1
            elif rp.can_fetch(u, "*"):
                resultado["permitida"] += 1
            else:
                resultado["PROHIBIDA para agentes genéricos"] += 1
                prohibidas_por_servidor[servidor] += 1

    print(f"URL que pide el programa: {len(pedidas)} en {len(por_servidor)} servidores")
    for etiqueta, n in resultado.most_common():
        print(f"   {n:5d}  {etiqueta}")
    print("Servidores con URL prohibidas:")
    for servidor, n in prohibidas_por_servidor.most_common(12):
        print(f"   {n:4d}  {servidor}  (de {len(por_servidor[servidor])})")
    if any(s.endswith("boe.es") for s in prohibidas_por_servidor):
        print("Nota: la regla del BOE es 'Disallow: /diario_boe/xml.php?' para el agente '*'. "
              "Su PDF (/boe/dias/.../pdfs/...) sí está permitido.")


if __name__ == "__main__":
    main()
