"""Registros técnicos del programa, con rotación por tamaño. Cada proceso escribe su propio fichero."""
import logging
from logging.handlers import RotatingFileHandler

from . import config


def configurar(proceso):
    """Envía los registros de «convenios» a datos/registros/<proceso>.log. Solo se configura una vez."""
    raiz = logging.getLogger("convenios")
    if getattr(raiz, "_configurado", False):
        return raiz
    config.REGISTROS.mkdir(parents=True, exist_ok=True)
    controlador = RotatingFileHandler(config.REGISTROS / f"{proceso}.log", maxBytes=5 * 1024 * 1024,
                                      backupCount=5, encoding="utf-8")
    controlador.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    raiz.addHandler(controlador)
    raiz.setLevel(logging.INFO)
    raiz._configurado = True
    return raiz
