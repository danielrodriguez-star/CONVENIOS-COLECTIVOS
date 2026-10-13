"""Utilidades compartidas: limpieza de texto, fechas y peticiones HTTP con reintentos."""
import re
import ssl
import time
import unicodedata

import requests
from requests.adapters import HTTPAdapter
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning
from urllib3.util.ssl_ import create_urllib3_context

_ESPACIOS = re.compile(r"\s+")
# Caracteres de control Unicode (categoría Cc) salvo tabulador, salto de línea, retorno de carro y
# salto de página. Llegan de PDF con fuentes mal codificadas y ensucian los textos guardados.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f-\x9f]")


def quitar_control(texto):
    """Quita los caracteres de control, sin tocar los espacios ni los saltos de línea."""
    return _CONTROL.sub("", texto or "")


def limpio(texto):
    """Quita caracteres de control, colapsa espacios (incluido el no separable) y recorta."""
    if texto is None:
        return ""
    return _ESPACIOS.sub(" ", _CONTROL.sub("", str(texto))).strip()


def texto_de(elemento):
    """Texto de un nodo lxml sin pegar las palabras separadas por <br>."""
    return limpio(" ".join(elemento.itertext()))


def fecha_es(texto):
    """'08/10/2026' -> '2026-10-08' (None si no hay fecha)."""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", texto or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def sin_acentos(texto):
    """Minúsculas y sin tildes, para buscar y comparar."""
    nfd = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower()


class _TlsHeredado(HTTPAdapter):
    """Para servidores que solo negocian cifrados antiguos. No verifica el certificado."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context(ciphers="ALL:@SECLEVEL=0")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def sesion_heredada():
    """Sesión para los servidores de CONVENIOS_TLS_HEREDADO. Ver PRODUCCION.md."""
    disable_warnings(InsecureRequestWarning)
    sesion = requests.Session()
    sesion.mount("https://", _TlsHeredado())
    return sesion


def pedir(sesion, metodo, url, intentos=3, **kwargs):
    """Petición HTTP con reintentos ante fallos de red, 429 y errores 5xx.

    `sesion` puede ser una requests.Session o None (en ese caso se usa requests).
    """
    cliente = sesion if sesion is not None else requests
    kwargs.setdefault("timeout", 90)
    ultimo = None
    for intento in range(1, intentos + 1):
        try:
            r = cliente.request(metodo, url, **kwargs)
            if r.status_code not in (429, 500, 502, 503, 504):
                return r
            ultimo = requests.HTTPError(f"HTTP {r.status_code} en {url}")
        except requests.exceptions.SSLError:
            raise  # un fallo TLS no es transitorio: quien llama decide qué hacer
        except requests.RequestException as e:
            ultimo = e
        if intento < intentos:
            time.sleep(3 * intento)
    raise ultimo


def celda_csv(valor):
    """Neutraliza los textos que Excel interpretaría como fórmula (empiezan por = + - @ o tabulador)."""
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valor
    return valor
