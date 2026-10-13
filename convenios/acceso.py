"""Acceso al panel: usuario y contraseña, guardados como hash en datos/acceso.json.

Si ese fichero no existe, el panel no pide contraseña y solo es accesible desde este equipo.
"""
import hmac
import json
import os

from werkzeug.security import check_password_hash, generate_password_hash

from . import config

MINIMO_CLAVE = 12


def configurado():
    return config.ACCESO.exists()


def guardar(usuario, clave):
    usuario = (usuario or "").strip()
    if not usuario or ":" in usuario:
        raise ValueError("El usuario no puede estar vacío ni contener «:».")
    if len(clave or "") < MINIMO_CLAVE:
        raise ValueError(f"La contraseña debe tener al menos {MINIMO_CLAVE} caracteres.")
    config.DATOS.mkdir(parents=True, exist_ok=True)
    temporal = config.ACCESO.with_suffix(".tmp")
    datos = {"usuario": usuario, "clave_hash": generate_password_hash(clave)}
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name != "nt":
        os.chmod(temporal, 0o600)  # solo el propietario puede leerlo
    os.replace(temporal, config.ACCESO)


def eliminar():
    if config.ACCESO.exists():
        config.ACCESO.unlink()


def verificar(usuario, clave):
    if not configurado():
        return True
    datos = json.loads(config.ACCESO.read_text(encoding="utf-8"))
    usuario_ok = hmac.compare_digest((usuario or "").encode("utf-8"), datos["usuario"].encode("utf-8"))
    clave_ok = check_password_hash(datos["clave_hash"], clave or "")
    return usuario_ok and clave_ok
