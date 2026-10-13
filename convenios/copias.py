"""Copias de seguridad fechadas de la base de datos.

Usan la API de copia de SQLite, así que se pueden hacer con el programa o el panel en marcha.
Cada copia se comprueba con PRAGMA integrity_check antes de darla por buena.
"""
import datetime as dt
import re
import shutil
import sqlite3

from . import config

_FORMATO = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}$")


def _copiar(origen, destino):
    fuente = sqlite3.connect(origen, timeout=30)
    try:
        copia = sqlite3.connect(destino)
        try:
            fuente.backup(copia)
        finally:
            copia.close()
    finally:
        fuente.close()
    con = sqlite3.connect(destino)
    try:
        resultado = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    if resultado != "ok":
        raise RuntimeError(f"la copia {destino.name} no supera la comprobación de integridad")


def listar():
    """Carpetas de copia, de la más reciente a la más antigua."""
    if not config.COPIAS.exists():
        return []
    return sorted((p for p in config.COPIAS.iterdir() if p.is_dir() and _FORMATO.match(p.name)), reverse=True)


def hacer(conservar=None):
    """Crea una copia de convenios.db (y de seguimiento.db si existe) y elimina las más antiguas.
    Devuelve la carpeta creada."""
    if not config.BASE_DATOS.exists():
        raise FileNotFoundError("No hay base de datos que copiar. Ejecuta 'sync' primero.")
    conservar = config.COPIAS_CONSERVAR if conservar is None else conservar
    if conservar < 1:
        raise ValueError("Hay que conservar al menos una copia.")
    carpeta = config.COPIAS / dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    carpeta.mkdir(parents=True, exist_ok=False)
    try:
        for nombre in ("convenios.db", "seguimiento.db"):
            if (config.DATOS / nombre).exists():
                _copiar(config.DATOS / nombre, carpeta / nombre)
    except Exception:
        shutil.rmtree(carpeta, ignore_errors=True)  # no dejar copias a medias
        raise
    for antigua in listar()[conservar:]:
        shutil.rmtree(antigua)
    return carpeta
