"""Estado operativo y mantenimiento: ruta /salud del panel, «estado --comprobar» y «depurar-robots».

Salvo las acciones pedidas explícitamente (depurar_robots con aplicar=True), no modifica nada.
"""
import datetime as dt
import json
import sqlite3

from . import config, copias, db, documentos, robots
from .sync import recalcular_convenios

OK, ATENCION, ERROR = "ok", "atencion", "error"


def _solo_lectura():
    return sqlite3.connect(config.BASE_DATOS.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)


def _ultima_correcta(con):
    for fin, resumen in con.execute("SELECT fin, resumen FROM ejecuciones WHERE fin IS NOT NULL ORDER BY id DESC"):
        try:
            if json.loads(resumen or "{}").get("ok"):
                return dt.datetime.fromisoformat(fin)
        except (TypeError, ValueError):
            continue
    return None


def diagnostico():
    """Estado de la instalación: «ok», «atencion» o «error». Los mensajes no revelan rutas internas."""
    info = {"estado": OK, "base_datos": "ok", "ultima_sincronizacion_correcta": None,
            "horas_desde_ultima_sincronizacion": None, "umbral_horas": config.ALERTA_HORAS, "mensajes": []}
    if not config.BASE_DATOS.exists():
        info.update(estado=ERROR, base_datos="no_existe")
        info["mensajes"].append("No existe la base de datos. Ejecuta 'sync' para crearla.")
        return info
    try:
        con = _solo_lectura()
        try:
            # quick_check cubre la estructura de las páginas y es mucho más rápido que integrity_check.
            integridad = con.execute("PRAGMA quick_check").fetchone()[0]
            ultima = _ultima_correcta(con)
        finally:
            con.close()
    except sqlite3.Error:
        info.update(estado=ERROR, base_datos="no_legible")
        info["mensajes"].append("La base de datos no se puede leer. Revisa el registro y la última copia.")
        return info
    if integridad != "ok":
        info.update(estado=ERROR, base_datos="danada")
        info["mensajes"].append("La base de datos no supera la comprobación de integridad. Restaura una copia.")
        return info
    if ultima is None:
        info["estado"] = ATENCION
        info["mensajes"].append("Todavía no hay una sincronización correcta.")
    else:
        horas = (dt.datetime.now() - ultima).total_seconds() / 3600
        info["ultima_sincronizacion_correcta"] = ultima.isoformat(timespec="seconds")
        info["horas_desde_ultima_sincronizacion"] = round(horas, 1)
        if horas > config.ALERTA_HORAS:
            info["estado"] = ATENCION
            info["mensajes"].append(f"La última sincronización correcta fue hace {round(horas)} horas.")
    return info


def bloqueadas_por_robots(con):
    """Textos guardados que proceden de una dirección que robots.txt prohíbe.
    Devuelve (lista de (url guardada, dirección pedida), número de direcciones sin dictamen)."""
    lista, sin_dictamen = [], 0
    for url, via in con.execute("SELECT url, via FROM documentos WHERE estado = 'ok'").fetchall():
        pedida = url
        m = documentos.PDF_BOE.search(url)
        if m and via == "boe-xml":  # el texto del BOE se pidió a su XML, no a su PDF
            pedida = config.BOE_XML.format(id=m.group(1))
        try:
            robots.comprobar(pedida)
        except robots.Bloqueada:
            lista.append((url, pedida))
        except robots.NoDisponible:
            sin_dictamen += 1
    return lista, sin_dictamen


def depurar_robots(aplicar=False):
    """Lista los textos que robots.txt prohíbe. Con aplicar=True, antes hace una copia de seguridad,
    los borra y recalcula los convenios. Tras borrarlos, la siguiente sincronización los registra como
    «bloqueada» y no vuelve a pedirlos. Devuelve un diccionario con lista, sin_dictamen y copia."""
    con = db.conectar()
    try:
        lista, sin_dictamen = bloqueadas_por_robots(con)
        copia = None
        if aplicar and lista:
            copia = copias.hacer()
            for url, _ in lista:
                con.execute("DELETE FROM tablas WHERE url = ?", (url,))
                con.execute("DELETE FROM documentos WHERE url = ?", (url,))
            con.commit()
            recalcular_convenios(con)
        return {"lista": lista, "sin_dictamen": sin_dictamen, "copia": copia}
    finally:
        con.close()
