"""Línea de comandos: python -m convenios <orden> [opciones]."""
import argparse
import csv
import datetime as dt
import getpass
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__, acceso, config, copias, db, operacion, registro
from .util import celda_csv

# Códigos de salida (útiles en el Programador de tareas y en cron)
SALIDA_OK, SALIDA_ERROR, SALIDA_ATENCION, SALIDA_BLOQUEO, SALIDA_INTERRUMPIDO = 0, 1, 2, 3, 130


def _fecha(texto):
    try:
        return dt.date.fromisoformat(texto)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"fecha no válida: {texto} (formato AAAA-MM-DD)") from e


def _lista(texto):
    return tuple(v.strip().lower() for v in texto.split(",") if v.strip())


def contar(con, sql):
    return con.execute(sql).fetchone()[0]


def estado(con):
    sql_ok = "SELECT COUNT(*) FROM documentos WHERE estado = 'ok'"
    sql_sin = "SELECT COUNT(*) FROM documentos WHERE estado = 'sin_texto'"
    sql_err = "SELECT COUNT(*) FROM documentos WHERE estado = 'error'"
    sql_blq = "SELECT COUNT(*) FROM documentos WHERE estado = 'bloqueada'"
    print(f"Convenios: {contar(con, 'SELECT COUNT(*) FROM convenios')}")
    print("  con tablas salariales detectadas: "
          + str(contar(con, "SELECT COUNT(*) FROM convenios WHERE tiene_tablas_salariales = 1")))
    print(f"Trámites de REGCON: {contar(con, 'SELECT COUNT(*) FROM tramites')}"
          f" (con ficha: {contar(con, 'SELECT COUNT(*) FROM tramites WHERE sin_ficha = 0 AND detalle_ok = 1')})")
    print(f"Publicaciones: {contar(con, sql_ok)} con texto, {contar(con, sql_sin)} sin texto, "
          f"{contar(con, sql_err)} con error, {contar(con, sql_blq)} bloqueadas por robots.txt")
    print(f"Disposiciones de convenios en el BOE: {contar(con, 'SELECT COUNT(*) FROM boe_disposiciones')}")
    ult = con.execute("SELECT * FROM ejecuciones ORDER BY id DESC LIMIT 1").fetchone()
    if ult:
        print(f"Última ejecución: {ult['inicio']} (periodo {ult['desde']} → {ult['hasta']}, "
              f"terminada: {ult['fin'] or 'no'})")
    else:
        print("Todavía no se ha ejecutado ninguna sincronización.")


def comprobar_estado():
    info = operacion.diagnostico()
    etiquetas = {"ok": "correcto", "atencion": "atención", "error": "error"}
    print(f"Estado: {etiquetas[info['estado']]}")
    if info["ultima_sincronizacion_correcta"]:
        print(f"Última sincronización correcta: {info['ultima_sincronizacion_correcta']} "
              f"(hace {info['horas_desde_ultima_sincronizacion']} horas)")
    for mensaje in info["mensajes"]:
        print(f"  - {mensaje}")
    return {"ok": SALIDA_OK, "atencion": SALIDA_ATENCION, "error": SALIDA_ERROR}[info["estado"]]


def exportar(con, carpeta):
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    cols = ["codigo", "denominacion", "ambito", "n_tramites", "ultimo_tipo_tramite", "ultima_fecha_registro",
            "vigencia_hasta", "estado", "url_ultima_publicacion", "tiene_tablas_salariales"]
    ruta_c = carpeta / "convenios.csv"
    with open(ruta_c, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cols)
        for r in con.execute("SELECT * FROM convenios ORDER BY ultima_fecha_registro DESC"):
            w.writerow([celda_csv(r[c]) for c in cols])
    ruta_t = carpeta / "tablas_salariales.csv"
    # Una fila por convenio, publicación y tabla. (Unir con los trámites daba una copia por trámite.)
    sql = """SELECT p.codigo, cv.denominacion, cv.ambito, p.fecha, b.url, b.pagina, b.orden, b.filas
             FROM (SELECT codigo, url_publicacion AS url, MAX(fecha_registro) AS fecha
                   FROM tramites WHERE url_publicacion IS NOT NULL GROUP BY codigo, url_publicacion) p
             JOIN tablas b ON b.url = p.url
             JOIN convenios cv ON cv.codigo = p.codigo
             WHERE b.salarial = 1 ORDER BY p.codigo, p.fecha DESC, b.url, b.pagina, b.orden"""
    n = 0
    with open(ruta_t, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["codigo", "denominacion", "ambito", "fecha_registro", "url_publicacion",
                    "pagina", "tabla", "fila", "celdas"])
        for r in con.execute(sql):
            for i, fila in enumerate(json.loads(r["filas"]), 1):
                w.writerow([celda_csv(v) for v in (r["codigo"], r["denominacion"], r["ambito"], r["fecha"],
                                                  r["url"], r["pagina"], r["orden"], i,
                                                  " | ".join(c for c in fila if c))])
                n += 1
    print(f"Exportado: {ruta_c} y {ruta_t} ({n} filas de tablas salariales)")


def sincronizar_cli(args):
    from .sync import sincronizar
    registro.configurar("sincronizacion")
    try:
        resumen = sincronizar(desde=args.desde, hasta=args.hasta, boe_on=not args.sin_boe,
                              documentos_on=not args.sin_documentos, reintentar_errores=args.reintentar_errores)
    except KeyboardInterrupt:
        print("Interrumpido. Vuelve a ejecutar 'sync': lo ya guardado no se pierde.", file=sys.stderr)
        return SALIDA_INTERRUMPIDO
    return SALIDA_OK if resumen["ok"] else SALIDA_ATENCION


LOCALES = ("127.0.0.1", "localhost", "::1")


def servir(args):
    from .web import crear_app
    registro.configurar("panel")
    if not args.produccion and args.host not in LOCALES:
        # Sin --produccion no hay usuario y contraseña obligatorios: no se atiende a otros equipos.
        print(f"No se atiende a otros equipos ({args.host}) sin --produccion, que exige usuario y contraseña. "
              "Usa «web --produccion --host ...» (ver PRODUCCION.md).", file=sys.stderr)
        return SALIDA_ERROR
    app = crear_app(hosts_permitidos=args.hosts_permitidos)
    if not args.produccion:
        app.run(host=args.host, port=args.puerto, debug=False, threaded=True)
        return SALIDA_OK
    if not acceso.configurado() and not args.sin_autenticacion:
        print("Antes de publicar el panel crea su usuario con: python -m convenios usuario\n"
              "Si el acceso ya está protegido por otro medio, usa --sin-autenticacion.", file=sys.stderr)
        return SALIDA_ERROR
    if not acceso.configurado():
        print("AVISO: el panel no pide contraseña. Cualquiera que llegue a este equipo podrá verlo.",
              file=sys.stderr)
    from waitress import serve
    print(f"Panel de convenios en http://{args.host}:{args.puerto} (Ctrl+C para detenerlo)", flush=True)
    serve(app, host=args.host, port=args.puerto, threads=args.hilos, ident="convenios")
    return SALIDA_OK


def gestionar_usuario(eliminar):
    if eliminar:
        acceso.eliminar()
        print("Acceso eliminado: el panel ya no pide usuario ni contraseña.")
        return SALIDA_OK
    usuario = input("Usuario del panel: ").strip()
    clave = getpass.getpass(f"Contraseña (mínimo {acceso.MINIMO_CLAVE} caracteres; no se muestra): ")
    repetida = getpass.getpass("Repite la contraseña: ")
    if clave != repetida:
        print("Las contraseñas no coinciden. No se ha cambiado nada.", file=sys.stderr)
        return SALIDA_ERROR
    try:
        acceso.guardar(usuario, clave)
    except ValueError as e:
        print(e, file=sys.stderr)
        return SALIDA_ERROR
    print(f"Usuario «{usuario}» guardado. En {config.ACCESO.name} solo queda el hash de la contraseña.")
    return SALIDA_OK


def hacer_copia(conservar):
    try:
        carpeta = copias.hacer(conservar)
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError) as e:
        print(f"No se ha podido hacer la copia: {e}", file=sys.stderr)
        return SALIDA_ERROR
    print(f"Copia creada en {carpeta}")
    return SALIDA_OK


def depurar(aplicar):
    resultado = operacion.depurar_robots(aplicar=aplicar)
    lista = resultado["lista"]
    if not lista:
        print("No hay textos guardados de direcciones que robots.txt prohíba.")
    else:
        print(f"Textos guardados de direcciones que robots.txt prohíbe: {len(lista)}")
        for servidor, n in Counter(urlsplit(pedida).netloc for _, pedida in lista).most_common():
            print(f"  {servidor}: {n}")
        if aplicar:
            print(f"Eliminados. Copia previa: {resultado['copia']}. Los convenios afectados se han recalculado.")
        else:
            print("No se ha borrado nada. Para borrarlos (se hace una copia antes): "
                  "python -m convenios depurar-robots --aplicar")
    if resultado["sin_dictamen"]:
        print(f"Sin dictamen (robots.txt no disponible ahora; no se cuentan): {resultado['sin_dictamen']}")
    return SALIDA_OK


def main(argv=None):
    # En Windows la consola o una redirección a fichero pueden usar cp1252, que no admite símbolos como «→».
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="convenios",
                                description="Busca y actualiza los convenios colectivos de España (REGCON y BOE).")
    p.add_argument("--version", action="version", version=f"convenios {__version__}")
    orden = p.add_subparsers(dest="orden", required=True)

    s = orden.add_parser("sync", help="sincroniza; sin fechas, continúa desde la última ejecución correcta")
    s.add_argument("--desde", type=_fecha,
                   help="primer día a consultar (AAAA-MM-DD). Carga inicial, p. ej. 2025-10-08")
    s.add_argument("--hasta", type=_fecha, help="último día a consultar (por defecto, hoy)")
    s.add_argument("--sin-boe", action="store_true", help="no consultar el sumario del BOE")
    s.add_argument("--sin-documentos", action="store_true", help="no descargar ni leer las publicaciones")
    s.add_argument("--reintentar-errores", action="store_true",
                   help="volver a procesar las publicaciones con error")

    est = orden.add_parser("estado", help="muestra un resumen de la base de datos")
    est.add_argument("--comprobar", action="store_true",
                     help="solo el estado de salud; código de salida 0 correcto, 2 atención, 1 error")

    exp = orden.add_parser("exportar", help="exporta convenios y tablas salariales a CSV")
    exp.add_argument("--carpeta", type=Path, default=config.EXPORTACIONES)

    w = orden.add_parser("web", help="abre el panel web")
    w.add_argument("--host", default="127.0.0.1",
                   help="127.0.0.1 = solo este equipo (por defecto). Otra dirección (p. ej. 0.0.0.0, para la red) "
                        "solo con --produccion")
    w.add_argument("--puerto", type=int, default=8000)
    w.add_argument("--produccion", action="store_true",
                   help="servidor de producción (waitress) con las comprobaciones de seguridad")
    w.add_argument("--hilos", type=int, default=4, help="peticiones simultáneas con --produccion (por defecto 4)")
    w.add_argument("--sin-autenticacion", action="store_true",
                   help="con --produccion, permite no tener usuario (solo si el acceso ya está protegido)")
    w.add_argument("--hosts-permitidos", type=_lista, default=None,
                   help="nombres de host aceptados, separados por comas (p. ej. convenios.ejemplo.es,*.ejemplo.es)")

    u = orden.add_parser("usuario", help="crea o cambia el usuario y la contraseña del panel")
    u.add_argument("--eliminar", action="store_true", help="quita el acceso con contraseña")

    c = orden.add_parser("copia", help="crea una copia de seguridad de la base de datos")
    c.add_argument("--conservar", type=int, default=None,
                   help=f"copias que se conservan (por defecto {config.COPIAS_CONSERVAR})")

    d = orden.add_parser("depurar-robots", help="lista los textos que robots.txt prohíbe")
    d.add_argument("--aplicar", action="store_true", help="los borra (antes hace una copia)")

    args = p.parse_args(argv)

    if args.orden == "sync":
        return sincronizar_cli(args)  # antes de abrir la base: así el bloqueo no depende de ella
    if args.orden == "web":
        return servir(args)
    if args.orden == "usuario":
        return gestionar_usuario(args.eliminar)
    if args.orden == "copia":
        return hacer_copia(args.conservar)
    if args.orden == "depurar-robots":
        return depurar(args.aplicar)
    if args.orden == "estado" and args.comprobar:
        return comprobar_estado()
    con = db.conectar()
    try:
        if args.orden == "estado":
            estado(con)
        elif args.orden == "exportar":
            exportar(con, args.carpeta)
    finally:
        con.close()
    return SALIDA_OK


if __name__ == "__main__":
    sys.exit(main())
