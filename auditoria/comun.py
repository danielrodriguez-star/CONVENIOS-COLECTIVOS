"""Utilidades compartidas por las comprobaciones de la auditoría.

Las comprobaciones son de solo lectura sobre datos/convenios.db. No modifican la base de datos
ni descargan documentos prohibidos por el robots.txt del servidor.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# Mismo agente de usuario que usa el programa (ver convenios/config.py).
UA_PROGRAMA = "Mozilla/5.0 (compatible; convenios-es/1.0; consulta de datos publicos)"


def url_real(url):
    """URL que realmente pide el programa: los PDF del BOE se obtienen por su XML (xml.php)."""
    from convenios import config, documentos
    m = documentos.PDF_BOE.search(url)
    return config.BOE_XML.format(id=m.group(1)) if m else url


def base_datos():
    from convenios import config
    return config.BASE_DATOS
