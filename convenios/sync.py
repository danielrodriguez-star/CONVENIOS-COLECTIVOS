"""Sincronización: BOE → REGCON (listado y fichas) → publicaciones (texto y tablas) → resumen por convenio."""
import datetime as dt
import json
import os
import sys
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from . import boe, config, db, documentos, robots
from .regcon import Regcon, listar
from .util import sin_acentos


def log(mensaje):
    linea = f"[{dt.datetime.now():%H:%M:%S}] {mensaje}"
    print(linea, flush=True)
    try:
        config.DATOS.mkdir(parents=True, exist_ok=True)
        with open(config.REGISTRO, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except OSError:
        pass


def _por_bloques(elementos, tam):
    for i in range(0, len(elementos), tam):
        yield elementos[i:i + tam]


# --- 1. BOE ------------------------------------------------------------------
def sincronizar_boe(con, desde, hasta):
    dias = [desde + dt.timedelta(days=i) for i in range((hasta - desde).days + 1)]

    def trabajar(dia):
        try:
            return dia, boe.sumario(dia), None
        except Exception as e:  # noqa: BLE001
            return dia, [], f"{dia}: {type(e).__name__}: {e}"

    n, errores = 0, []
    with ThreadPoolExecutor(4) as pool:
        for dia, items, error in pool.map(trabajar, dias):
            if error:
                errores.append(error)
            for it in items:
                if not it.get("identificador") or not boe.es_convenio(it):
                    continue
                con.execute(
                    """INSERT INTO boe_disposiciones
                       (identificador, fecha, departamento, epigrafe, titulo, url_html, url_pdf, url_xml, vista)
                       VALUES (?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(identificador) DO UPDATE SET
                         fecha=excluded.fecha, departamento=excluded.departamento, epigrafe=excluded.epigrafe,
                         titulo=excluded.titulo, url_html=excluded.url_html, url_pdf=excluded.url_pdf,
                         url_xml=excluded.url_xml, vista=excluded.vista""",
                    (it["identificador"], it["fecha"], it["departamento"], it["epigrafe"], it["titulo"],
                     it["url_html"], it["url_pdf"], it["url_xml"], db.ahora()))
                n += 1
    con.commit()
    log(f"BOE: {n} disposiciones de convenios en {len(dias)} días ({len(errores)} errores)")
    return n, errores


# --- 2. REGCON: listado de trámites -------------------------------------------
_local = threading.local()


def _cliente_hilo():
    """Un cliente de REGCON (sesión propia) por hilo."""
    if getattr(_local, "cli", None) is None:
        _local.cli = Regcon()
    return _local.cli


def _listar_dia(dia):
    """Todos los trámites de un día. Si falla, se reintenta una vez con una sesión nueva."""
    error = ""
    for _ in range(2):
        try:
            total, filas, completo = listar(_cliente_hilo(), dia, dia)
            return dia, total, filas, completo, None
        except Exception as e:  # noqa: BLE001
            error = f"{type(e).__name__}: {e}"[:300]
            _local.cli = None
    return dia, None, [], False, f"{dia}: {error}"


def _guardar_filas(con, filas):
    nuevos = 0
    ahora = db.ahora()
    for f in filas:
        ya = con.execute("SELECT 1 FROM tramites WHERE id_expediente = ?", (f["id_expediente"],)).fetchone()
        sin_ficha = 1 if f.get("sin_ficha") else 0
        con.execute(
            """INSERT INTO tramites (id_expediente, codigo, denominacion, tipo_tramite, ambito, fecha_registro,
                                     vigencia_desde, vigencia_hasta, sin_ficha, detalle_ok, primera_vista, ultima_vista)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id_expediente) DO UPDATE SET
                 codigo=excluded.codigo,
                 denominacion=CASE WHEN tramites.detalle_ok=1 THEN tramites.denominacion ELSE excluded.denominacion END,
                 tipo_tramite=excluded.tipo_tramite, ambito=excluded.ambito,
                 fecha_registro=excluded.fecha_registro, vigencia_desde=excluded.vigencia_desde,
                 vigencia_hasta=excluded.vigencia_hasta, ultima_vista=excluded.ultima_vista""",
            (f["id_expediente"], f["codigo"], f["denominacion"], f["tipo_tramite"], f["ambito"],
             f["fecha_registro"], f["vigencia_desde"], f["vigencia_hasta"], sin_ficha, sin_ficha,
             ahora, ahora))
        if not ya:
            nuevos += 1
    return nuevos


def sincronizar_listado(con, desde, hasta, hilos=config.REGCON_HILOS):
    """Listado diario: cada día se consulta por separado (ver regcon.listar)."""
    dias = [desde + dt.timedelta(days=i) for i in range((hasta - desde).days + 1)]
    vistos = nuevos = 0
    errores, avisos = [], []
    with ThreadPoolExecutor(hilos) as pool:
        for n, (dia, total, filas, completo, error) in enumerate(pool.map(_listar_dia, dias), 1):
            if error:
                errores.append(error)
                log(f"ERROR en el listado de REGCON {error}")
                continue
            nuevos += _guardar_filas(con, filas)
            vistos += len(filas)
            if not completo:
                avisos.append(f"{dia}: listado incompleto ({len(filas)} trámites; REGCON informa de {total})")
            if filas:
                log(f"REGCON {dia}: {len(filas)} trámites")
            if n % 10 == 0:
                con.commit()
    con.commit()
    log(f"REGCON listado {desde}..{hasta}: {vistos} trámites únicos, {nuevos} nuevos, "
        f"{len(errores)} días con error, {len(avisos)} avisos")
    return {"filas": vistos, "nuevos": nuevos, "errores": errores, "avisos": avisos}


# --- 3. REGCON: fichas (estado, enlace a la publicación) ----------------------
def _lote_fichas(lote):
    cli = Regcon()
    res = []
    for id_exp, codigo in lote:
        try:
            ficha = cli.ficha(id_exp)
            if ficha is None or ficha["codigo"] != codigo:
                raise ValueError("la ficha no corresponde al convenio esperado")
            res.append((id_exp, ficha, None))
        except Exception as e:  # noqa: BLE001
            res.append((id_exp, None, f"{type(e).__name__}: {e}"[:300]))
            cli = Regcon()  # sesión nueva tras un fallo
    return res


def sincronizar_fichas(con, hilos=config.REGCON_HILOS, tam_lote=60):
    pendientes = [(r[0], r[1]) for r in con.execute(
        "SELECT id_expediente, codigo FROM tramites WHERE detalle_ok = 0 ORDER BY fecha_registro DESC")]
    ok = err = 0
    if not pendientes:
        log("Fichas: no hay trámites pendientes")
        return 0, 0
    with ThreadPoolExecutor(hilos) as pool:
        for res in pool.map(_lote_fichas, list(_por_bloques(pendientes, tam_lote))):
            for id_exp, ficha, error in res:
                if ficha:
                    con.execute(
                        """UPDATE tramites SET codigo=?, denominacion=COALESCE(NULLIF(?, ''), denominacion),
                           estado=?, n_expediente=?, fecha_publicacion=?, url_publicacion=?,
                           detalle_ok=1, detalle_error=NULL WHERE id_expediente=?""",
                        (ficha["codigo"], ficha["denominacion"], ficha["estado"] or None, ficha["n_expediente"],
                         ficha["fecha_publicacion"], ficha["url_publicacion"], id_exp))
                    ok += 1
                else:
                    con.execute("UPDATE tramites SET detalle_error=? WHERE id_expediente=?", (error, id_exp))
                    err += 1
            con.commit()
            log(f"Fichas: {ok} correctas, {err} con error (de {len(pendientes)} pendientes)")
    return ok, err


# --- 4. Publicaciones: texto y tablas ----------------------------------------
def _urls_pendientes(con):
    urls = set()
    for sql in (
        "SELECT DISTINCT url_publicacion FROM tramites WHERE url_publicacion IS NOT NULL",
        "SELECT DISTINCT url_pdf FROM boe_disposiciones WHERE url_pdf IS NOT NULL",
    ):
        urls.update(r[0] for r in con.execute(sql))
    ya = {r[0] for r in con.execute("SELECT url FROM documentos")}
    return sorted(urls - ya)


# Valores de «error» que no son errores reales: el documento no se guarda como fallido.
_PENDIENTE = "__pendiente__"   # robots.txt no se pudo leer: se reintenta en la siguiente sincronización
_BLOQUEADA = "__bloqueada__"   # robots.txt prohíbe la descarga: no se vuelve a pedir
_semaforos = {}
_cerrojo_semaforos = threading.Lock()


def _semaforo(servidor):
    """Como mucho DOC_POR_SERVIDOR peticiones simultáneas a un mismo servidor."""
    with _cerrojo_semaforos:
        if servidor not in _semaforos:
            _semaforos[servidor] = threading.BoundedSemaphore(config.DOC_POR_SERVIDOR)
        return _semaforos[servidor]


def _documento_seguro(url):
    with _semaforo(urlparse(url).netloc):
        try:
            return url, documentos.procesar(url), None
        except robots.Bloqueada:
            return url, None, _BLOQUEADA
        except robots.NoDisponible:
            return url, None, _PENDIENTE
        except Exception as e:  # noqa: BLE001  el error se guarda y se muestra en /estado
            return url, None, f"{type(e).__name__}: {e}"[:300]


def _guardar_documento(con, url, out, error):
    fuente = urlparse(url).netloc
    if error == _PENDIENTE:
        return "pendiente"  # no se guarda: la siguiente sincronización volverá a intentarlo
    if error == _BLOQUEADA:
        con.execute("INSERT OR REPLACE INTO documentos (url, fuente, estado, error, procesado) VALUES (?,?,?,?,?)",
                    (url, fuente, "bloqueada", "robots.txt prohíbe esta descarga", db.ahora()))
        return "bloqueada"
    if error:
        con.execute("INSERT OR REPLACE INTO documentos (url, fuente, estado, error, procesado) VALUES (?,?,?,?,?)",
                    (url, fuente, "error", error, db.ahora()))
        return "error"
    texto = out.get("texto") or ""
    estado = "ok" if len(texto.strip()) >= 200 else "sin_texto"
    con.execute("DELETE FROM tablas WHERE url = ?", (url,))
    con.execute(
        """INSERT OR REPLACE INTO documentos (url, fuente, estado, error, via, paginas, caracteres, texto, procesado)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (url, fuente, estado, None, out.get("via"), out.get("paginas"), len(texto),
         zlib.compress(texto.encode("utf-8"), 9), db.ahora()))
    for t in out.get("tablas", []):
        con.execute(
            "INSERT INTO tablas (url, pagina, orden, contexto, salarial, puntuacion, filas) VALUES (?,?,?,?,?,?,?)",
            (url, t.get("pagina"), t.get("orden"), t.get("contexto"), int(t.get("salarial", 0)),
             t.get("puntuacion"), json.dumps(t["filas"], ensure_ascii=False)))
    return estado


def _intercalar_por_servidor(urls):
    """Reordena las URLs para que las consecutivas sean de servidores distintos.
    Así los hilos no se quedan todos esperando al mismo servidor lento."""
    grupos = {}
    for u in urls:
        grupos.setdefault(urlparse(u).netloc, []).append(u)
    colas, salida = list(grupos.values()), []
    while colas:
        for cola in colas:
            salida.append(cola.pop(0))
        colas = [c for c in colas if c]
    return salida


def sincronizar_documentos(con, hilos=config.DOC_HILOS):
    urls = _intercalar_por_servidor(_urls_pendientes(con))
    cuenta = {"ok": 0, "sin_texto": 0, "error": 0, "bloqueada": 0, "pendiente": 0}
    hecho = 0
    with ThreadPoolExecutor(hilos) as pool:
        for bloque in _por_bloques(urls, 120):
            for url, out, error in pool.map(_documento_seguro, bloque):
                cuenta[_guardar_documento(con, url, out, error)] += 1
                hecho += 1
            con.commit()
            log(f"Publicaciones: {hecho}/{len(urls)} (con texto {cuenta['ok']}, sin texto {cuenta['sin_texto']}, "
                f"errores {cuenta['error']}, bloqueadas {cuenta['bloqueada']}, pendientes {cuenta['pendiente']})")
    return {"total": len(urls), **cuenta}


# --- 5. Resumen por convenio ---------------------------------------------------
def recalcular_convenios(con):
    con_salariales = {r[0] for r in con.execute(
        "SELECT DISTINCT t.codigo FROM tramites t JOIN tablas b ON b.url = t.url_publicacion WHERE b.salarial = 1")}
    agg = {}
    for r in con.execute("SELECT * FROM tramites ORDER BY codigo, fecha_registro DESC, id_expediente DESC"):
        a = agg.get(r["codigo"])
        if a is None:
            a = agg[r["codigo"]] = {"det": None, "lista": None, "ambito": r["ambito"], "tipo": r["tipo_tramite"],
                                    "fecha": r["fecha_registro"], "vig": None, "estado": None, "url": None, "n": 0}
        a["n"] += 1
        if r["detalle_ok"] and not r["sin_ficha"] and a["det"] is None and r["denominacion"]:
            a["det"] = r["denominacion"]
        if a["lista"] is None and r["denominacion"]:
            a["lista"] = r["denominacion"]
        if r["detalle_ok"] and a["estado"] is None and r["estado"]:
            a["estado"] = r["estado"]
        if a["url"] is None and r["url_publicacion"]:
            a["url"] = r["url_publicacion"]
        if r["vigencia_hasta"] and (a["vig"] is None or r["vigencia_hasta"] > a["vig"]):
            a["vig"] = r["vigencia_hasta"]
    con.execute("DELETE FROM convenios")
    for codigo, a in agg.items():
        den = a["det"] or a["lista"] or ""
        con.execute(
            """INSERT INTO convenios (codigo, denominacion, ambito, n_tramites, ultimo_tipo_tramite,
                 ultima_fecha_registro, vigencia_hasta, estado, url_ultima_publicacion, tiene_tablas_salariales, busqueda)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (codigo, den, a["ambito"], a["n"], a["tipo"], a["fecha"], a["vig"], a["estado"], a["url"],
             1 if codigo in con_salariales else 0, sin_acentos(f"{den} {codigo} {a['ambito'] or ''}")))
    con.commit()
    return len(agg)


# --- Orquestación -----------------------------------------------------------------
def ultima_ejecucion_ok(con):
    for r in con.execute("SELECT hasta, resumen FROM ejecuciones ORDER BY id DESC"):
        try:
            if json.loads(r["resumen"] or "{}").get("ok"):
                return dt.date.fromisoformat(r["hasta"])
        except (ValueError, TypeError):
            continue
    return None


_bloqueo_sync = None  # el descriptor debe seguir abierto mientras dure la sincronización


def _bloquear_sincronizacion():
    """Impide dos sincronizaciones a la vez (p. ej. la tarea programada y una manual).
    El bloqueo del sistema operativo se libera solo al terminar el proceso, aunque falle."""
    global _bloqueo_sync
    config.DATOS.mkdir(parents=True, exist_ok=True)
    f = open(config.DATOS / "sincronizacion.lock", "a+")
    try:
        if f.seek(0, 2) == 0:
            f.write("bloqueo\n")
            f.flush()
        f.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        print("Ya hay una sincronización en marcha. Espera a que termine antes de lanzar otra.", file=sys.stderr)
        raise SystemExit(3)
    _bloqueo_sync = f


def sincronizar(desde=None, hasta=None, boe_on=True, documentos_on=True, reintentar_errores=False):
    _bloquear_sincronizacion()
    con = db.conectar()
    hoy = dt.date.today()
    hasta = hasta or hoy
    if desde is None:
        ult = ultima_ejecucion_ok(con)
        # Ventana por defecto: desde la última ejecución correcta (con 7 días de margen), sin pasar de 365 días.
        desde = max((ult - dt.timedelta(days=7)) if ult else hoy - dt.timedelta(days=365),
                    hoy - dt.timedelta(days=365))
    if desde > hasta:
        raise SystemExit("La fecha inicial es posterior a la final.")
    eid = con.execute("INSERT INTO ejecuciones (inicio, desde, hasta) VALUES (?,?,?)",
                      (db.ahora(), desde.isoformat(), hasta.isoformat())).lastrowid
    con.commit()
    resumen = {"ok": False, "desde": desde.isoformat(), "hasta": hasta.isoformat()}
    log(f"=== Sincronización de {desde} a {hasta} ===")
    try:
        if boe_on:
            n, errs = sincronizar_boe(con, desde, hasta)
            resumen["boe"] = {"convenios": n, "errores": errs[:20]}
        listado = sincronizar_listado(con, desde, hasta)
        resumen["regcon_listado"] = {k: (v[:20] if isinstance(v, list) else v) for k, v in listado.items()}
        ok, err = sincronizar_fichas(con)
        resumen["regcon_fichas"] = {"ok": ok, "error": err}
        # Resumen intermedio: así el panel web ya muestra los convenios mientras se descargan las publicaciones.
        recalcular_convenios(con)
        if documentos_on:
            if reintentar_errores:
                con.execute("DELETE FROM documentos WHERE estado = 'error'")
                con.commit()
            resumen["documentos"] = sincronizar_documentos(con)
        resumen["convenios"] = recalcular_convenios(con)
        # Un día con avisos (listado incompleto) no cuenta como correcto: así la siguiente
        # ejecución vuelve a empezar antes de ese día y no lo pierde.
        resumen["ok"] = not listado["errores"] and not listado["avisos"]
    finally:
        con.execute("UPDATE ejecuciones SET fin = ?, resumen = ? WHERE id = ?",
                    (db.ahora(), json.dumps(resumen, ensure_ascii=False), eid))
        con.commit()
        con.close()
    log("=== Fin. " + json.dumps(resumen, ensure_ascii=False)[:800])
    return resumen
