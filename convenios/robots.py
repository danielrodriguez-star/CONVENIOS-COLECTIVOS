"""Comprobación de robots.txt antes de pedir cada publicación (estándar RFC 9309).

- Sin robots.txt, o con un 4xx, no hay restricciones.
- Si la regla del agente prohíbe la dirección, no se pide (Bloqueada).
- Si robots.txt no se puede leer ahora (error de red o 5xx), no se pide nada de ese servidor:
  la publicación queda pendiente (NoDisponible) y se reintenta en la siguiente sincronización.
"""
import logging
import threading
import time
from urllib.parse import urlsplit

import requests
from protego import Protego

from . import config
from .util import sesion_heredada

log = logging.getLogger("convenios.robots")

TTL_CORRECTO = 24 * 3600  # segundos que se recuerda un robots.txt leído
TTL_ERROR = 600           # segundos antes de volver a intentar un robots.txt no disponible


class Bloqueada(Exception):
    """robots.txt prohíbe pedir esta dirección."""


class NoDisponible(Exception):
    """robots.txt no se puede leer en este momento."""


class _Comprobador:
    def __init__(self):
        self._cache = {}
        self._candados = {}
        self._cerrojo = threading.Lock()

    def _candado(self, clave):
        with self._cerrojo:
            return self._candados.setdefault(clave, threading.Lock())

    @staticmethod
    def _descargar(url, host):
        cabeceras = {"User-Agent": config.USER_AGENT}
        try:
            return requests.get(url, timeout=10, headers=cabeceras)
        except requests.exceptions.SSLError:
            if host not in config.TLS_HEREDADO:
                raise
            return sesion_heredada().get(url, timeout=10, headers=cabeceras, verify=False)

    def _leer(self, esquema, netloc):
        """(reglas, segundos a recordarlas). Reglas: Protego, None (sin restricciones) o «error»."""
        url = f"{esquema}://{netloc}/robots.txt"
        host = (urlsplit(f"//{netloc}").hostname or "").lower()
        try:
            r = self._descargar(url, host)
        except requests.RequestException as e:
            log.info("robots.txt de %s no disponible (%s)", netloc, type(e).__name__)
            return "error", TTL_ERROR
        if r.status_code == 200:
            try:
                return Protego.parse(r.text), TTL_CORRECTO
            except Exception:  # noqa: BLE001  robots.txt que no se puede interpretar
                log.warning("robots.txt de %s no se puede interpretar", netloc)
                return "error", TTL_ERROR
        if 400 <= r.status_code < 500:
            return None, TTL_CORRECTO
        log.info("robots.txt de %s responde %s", netloc, r.status_code)
        return "error", TTL_ERROR

    def reglas(self, esquema, netloc):
        clave = (esquema, netloc)
        # Un candado por servidor: aunque lleguen varias peticiones a la vez, robots.txt se descarga una sola vez.
        with self._candado(clave):
            entrada = self._cache.get(clave)
            if entrada and entrada[0] > time.monotonic():
                return entrada[1]
            valor, ttl = self._leer(esquema, netloc)
            self._cache[clave] = (time.monotonic() + ttl, valor)
            return valor

    def comprobar(self, url):
        p = urlsplit(url)
        reglas = self.reglas(p.scheme or "https", p.netloc)
        if reglas is None:
            return
        if isinstance(reglas, str):
            raise NoDisponible(p.netloc)
        if not reglas.can_fetch(url, config.TOKEN_AGENTE):
            raise Bloqueada(url)


_COMPROBADOR = _Comprobador()


def comprobar(url):
    """No devuelve nada si la dirección se puede pedir. Si no, lanza Bloqueada o NoDisponible.
    Con CONVENIOS_ROBOTS=ignorar no hace ninguna petición."""
    if config.ROBOTS == "ignorar":
        return
    _COMPROBADOR.comprobar(url)
