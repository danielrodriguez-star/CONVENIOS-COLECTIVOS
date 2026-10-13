"""Panel web local (Flask): búsqueda, ficha de cada convenio, tablas salariales, textos y estado."""
import csv
import datetime as dt
import html
import io
import json
import logging
import math
import sqlite3
import zlib
from urllib.parse import quote, urlencode, urlsplit

from flask import Flask, Response, abort, g, redirect, request
from werkzeug.exceptions import HTTPException

from . import __version__, acceso, config, db, operacion
from .util import celda_csv, sin_acentos

log = logging.getLogger("convenios.web")

# El seguimiento se guarda aparte: así el panel nunca compite con la carga por la base principal.
SQL_SEGUIMIENTO = """
CREATE TABLE IF NOT EXISTS seguimiento (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    termino   TEXT NOT NULL UNIQUE,
    creado    TEXT NOT NULL,
    revisado  TEXT NOT NULL                  -- momento de la última visita: desde aquí se buscan novedades
);
"""


def _bd_seguimiento():
    con = sqlite3.connect(str(config.DATOS / "seguimiento.db"), timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(SQL_SEGUIMIENTO)
    return con

TAM = 50

CSS = """
:root{--azul:#1d4f91;--gris:#5b6470;--linea:#dfe3ea;--fondo:#f6f8fb;--verde:#1f7a4d;--ambar:#9a5b00;--rojo:#b42318}
*{box-sizing:border-box}
body{margin:0;font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#1d2330;background:var(--fondo)}
header{background:var(--azul);color:#fff;padding:12px 20px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
header a{color:#fff;text-decoration:none;opacity:.9}header a:hover{opacity:1;text-decoration:underline}
header strong{font-size:17px;margin-right:auto}
main{max-width:1200px;margin:20px auto;padding:0 16px 40px}
h1{font-size:22px;margin:4px 0 6px}
h2{font-size:17px;margin:24px 0 8px}
.card{background:#fff;border:1px solid var(--linea);border-radius:10px;padding:14px 16px;margin-bottom:14px}
form.filtros{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}
form.filtros label{display:flex;flex-direction:column;font-size:12px;color:var(--gris);gap:4px}
input,select{padding:7px 9px;border:1px solid #c8cfda;border-radius:7px;font:inherit;min-width:160px;background:#fff}
button{background:var(--azul);color:#fff;border:0;border-radius:7px;padding:9px 16px;font:inherit;cursor:pointer}
button.sec{background:var(--gris)}
table{border-collapse:collapse;width:100%;background:#fff}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--linea);vertical-align:top;font-size:14px}
th{background:#eef2f8}
.tab-wrap{overflow:auto;max-height:640px;border:1px solid var(--linea);border-radius:8px;margin-bottom:8px}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;background:#eef2f8;color:#334;margin:1px 2px 1px 0}
.ok{background:#e6f5ec;color:var(--verde)}.warn{background:#fff4e0;color:var(--ambar)}.err{background:#fde8e6;color:var(--rojo)}
.muted{color:var(--gris);font-size:13px}
.num{text-align:right;white-space:nowrap}
.pag{margin:14px 0}.pag a{margin-right:12px}
pre{white-space:pre-wrap;background:#fff;border:1px solid var(--linea);padding:12px;border-radius:8px;max-height:72vh;overflow:auto;font-size:13px}
a{color:var(--azul)}
footer{max-width:1200px;margin:0 auto 24px;padding:0 16px;font-size:13px;color:var(--gris)}
"""

COLUMNAS_CSV = ["codigo", "denominacion", "ambito", "n_tramites", "ultimo_tipo_tramite", "ultima_fecha_registro",
                "vigencia_hasta", "estado", "url_ultima_publicacion", "tiene_tablas_salariales"]


def esc(x):
    return html.escape("" if x is None else str(x), quote=True)


def badge(texto, clase=""):
    return f'<span class="badge {clase}">{esc(texto)}</span>' if texto else ""


def tabla_html(filas, maximo=80):
    if not filas:
        return '<p class="muted">Sin filas.</p>'
    partes = ['<div class="tab-wrap"><table>']
    for i, fila in enumerate(filas[:maximo]):
        etiqueta = "th" if i == 0 else "td"
        partes.append("<tr>" + "".join(f"<{etiqueta}>{esc(c)}</{etiqueta}>" for c in fila) + "</tr>")
    partes.append("</table></div>")
    if len(filas) > maximo:
        partes.append(f'<p class="muted">Se muestran {maximo} de {len(filas)} filas.</p>')
    return "".join(partes)


def _aviso_vacias(filas):
    """Aviso cuando más de la mitad de las celdas están vacías: suele indicar una tabla mal extraída."""
    celdas = [c for fila in filas for c in fila]
    if celdas and sum(1 for c in celdas if not (c or "").strip()) > len(celdas) / 2:
        return badge("Muchas celdas vacías: compruébala con el documento original", "warn")
    return ""


PIE = (f"<footer>Convenios colectivos v{__version__}. Datos de REGCON (Ministerio de Trabajo y Economía Social) "
       "y del BOE. Información orientativa: contrasta siempre con el documento oficial.</footer>")


def pagina(titulo, cuerpo):
    nav = ("<header><strong>Convenios colectivos</strong>"
           '<a href="/">Buscar</a><a href="/seguimiento">Seguimiento</a><a href="/boe">BOE</a><a href="/estado">Estado</a>'
           '<a href="/exportar/convenios.csv">Descargar CSV</a></header>')
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{esc(titulo)} · Convenios</title><style>{CSS}</style></head>"
            f"<body>{nav}<main>{cuerpo}</main>{PIE}</body></html>")


def _filtros(args):
    try:
        p = max(1, int(args.get("p", "1") or 1))
    except ValueError:
        p = 1
    desde, aviso = args.get("desde", "").strip(), ""
    if desde:
        try:
            dt.date.fromisoformat(desde)
        except ValueError:
            aviso = f"La fecha «{desde}» no es válida (formato AAAA-MM-DD). No se aplica el filtro de fecha."
            desde = ""
    return {"q": args.get("q", "").strip(), "ambito": args.get("ambito", "").strip(),
            "desde": desde, "salariales": args.get("salariales") == "1", "p": p, "aviso": aviso}


def _where(f):
    cond, params = ["1=1"], []
    for palabra in sin_acentos(f["q"]).split():
        cond.append("busqueda LIKE ?")
        params.append(f"%{palabra}%")
    if f["ambito"]:
        cond.append("ambito = ?")
        params.append(f["ambito"])
    if f["desde"]:
        cond.append("ultima_fecha_registro >= ?")
        params.append(f["desde"])
    if f["salariales"]:
        cond.append("tiene_tablas_salariales = 1")
    return " AND ".join(cond), params


def _formulario(f, ambitos):
    opciones = ['<option value="">Todos</option>']
    for a in ambitos:
        sel = " selected" if a == f["ambito"] else ""
        opciones.append(f'<option value="{esc(a)}"{sel}>{esc(a)}</option>')
    chk = " checked" if f["salariales"] else ""
    return ('<form class="filtros" method="get">'
            f'<label>Nombre o código<input name="q" value="{esc(f["q"])}" placeholder="p. ej. metal, comercio, Madrid"></label>'
            f'<label>Ámbito (autoridad laboral)<select name="ambito">{"".join(opciones)}</select></label>'
            f'<label>Último trámite desde<input type="date" name="desde" value="{esc(f["desde"])}"></label>'
            f'<label><span><input type="checkbox" name="salariales" value="1"{chk}> Solo con tablas salariales</span></label>'
            '<button type="submit">Buscar</button></form>')


def _fila_convenio(r):
    sal = badge("Tablas salariales", "ok") if r["tiene_tablas_salariales"] else ""
    return ("<tr>"
            f'<td><a href="/convenio/{esc(r["codigo"])}">{esc(r["denominacion"] or r["codigo"])}</a>'
            f'<div class="muted">{esc(r["codigo"])}</div></td>'
            f'<td>{esc(r["ambito"])}</td>'
            f'<td>{esc(r["ultimo_tipo_tramite"])}</td>'
            f'<td>{esc(r["ultima_fecha_registro"])}</td>'
            f'<td>{esc(r["vigencia_hasta"])}</td>'
            f'<td>{esc(r["estado"])}</td>'
            f'<td class="num">{r["n_tramites"]}</td>'
            f"<td>{sal}</td></tr>")


def _badge_documento(t):
    if not t["url_publicacion"]:
        return '<span class="muted">sin publicación</span>'
    estado = t["doc_estado"]
    if estado == "ok":
        return badge("texto", "ok")
    if estado == "sin_texto":
        return badge("sin texto (¿escaneado?)", "warn")
    if estado == "error":
        return f'<span class="badge err" title="{esc(t["doc_error"])}">error</span>'
    if estado == "bloqueada":
        return badge("bloqueada por robots.txt", "err")
    return badge("pendiente", "warn")


def _cond_texto(termino, columna="busqueda"):
    """Condición SQL: todas las palabras del término (sin acentos) aparecen en la columna."""
    cond, params = [], []
    for palabra in sin_acentos(termino).split():
        cond.append(f"{columna} LIKE ?")
        params.append(f"%{palabra}%")
    return (" AND ".join(cond) or "1=1"), params


_LOCALES = ("localhost", "127.0.0.1", "::1")


def _solo_nombre(host):
    """«localhost:8000» → «localhost»; «[::1]:8000» → «::1»."""
    host = (host or "").strip().lower()
    if host.startswith("["):
        return host[1:host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def host_permitido(host, permitidos):
    """Protege frente a «DNS rebinding»: solo se atiende a este equipo y a los nombres configurados."""
    nombre = _solo_nombre(host)
    if nombre in _LOCALES:
        return True
    for p in permitidos:
        if p.startswith("*.") and nombre.endswith(p[1:]) and nombre != p[2:]:
            return True
        if nombre == p:
            return True
    return False


def crear_app(hosts_permitidos=None, permitir_iframe=None):
    """Aplicación Flask del panel.

    hosts_permitidos: nombres aceptados además de localhost (por defecto, CONVENIOS_HOSTS_PERMITIDOS).
    permitir_iframe: si es True, el panel puede mostrarse dentro de otra página (vista previa).
    """
    app = Flask(__name__)
    permitidos = tuple(hosts_permitidos if hosts_permitidos is not None else config.HOSTS_PERMITIDOS)
    iframe = config.PERMITIR_IFRAME if permitir_iframe is None else permitir_iframe
    ancestros = "*" if iframe else "'none'"

    @app.before_request
    def _control_de_peticion():
        if not host_permitido(request.host, permitidos):
            abort(400, description="Este nombre de host no está permitido. Si accedes desde otra dirección, "
                                   "añádela a CONVENIOS_HOSTS_PERMITIDOS (ver PRODUCCION.md).")
        if acceso.configurado() and request.path != "/salud":
            auth = request.authorization
            if auth is None or not acceso.verificar(auth.username, auth.password):
                r = Response("Se necesita el usuario y la contraseña del panel.", 401)
                r.headers["WWW-Authenticate"] = 'Basic realm="Convenios", charset="UTF-8"'
                return r
        if request.method == "POST":
            # Frente a CSRF: el navegador debe indicar que la petición viene de este mismo panel.
            if urlsplit(request.headers.get("Origin", "")).netloc.lower() != request.host.lower():
                abort(403, description="La petición no viene de este panel (cabecera Origin ausente o distinta).")

    @app.after_request
    def _cabeceras(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            f"form-action 'self'; base-uri 'none'; frame-ancestors {ancestros}")
        if not iframe:
            resp.headers["X-Frame-Options"] = "DENY"
        return resp

    @app.errorhandler(Exception)
    def _error(e):
        if isinstance(e, HTTPException):
            codigo, mensaje = e.code or 500, e.description or e.name
            cuerpo = f"<h1>Error {codigo}</h1><p>{esc(mensaje)}</p><p><a href='/'>← Volver al inicio</a></p>"
            return pagina(f"Error {codigo}", cuerpo), codigo
        log.exception("Error interno en %s", request.path)
        return pagina("Error 500", "<h1>Error 500</h1><p>Ha ocurrido un error interno. "
                      "El detalle está en el registro del programa.</p>"), 500

    def bd():
        if "bd" not in g:
            g.bd = db.conectar()
        return g.bd

    @app.teardown_appcontext
    def cerrar_bd(_):
        b = g.pop("bd", None)
        if b is not None:
            b.close()

    def seg():
        if "seg" not in g:
            g.seg = _bd_seguimiento()
        return g.seg

    @app.teardown_appcontext
    def cerrar_seg(_):
        s = g.pop("seg", None)
        if s is not None:
            s.close()

    @app.route("/")
    def inicio():
        f = _filtros(request.args)
        c = bd()
        where, params = _where(f)
        total = c.execute(f"SELECT COUNT(*) FROM convenios WHERE {where}", params).fetchone()[0]
        n_pag = max(1, math.ceil(total / TAM))
        pag = min(f["p"], n_pag)
        filas = c.execute(
            f"SELECT * FROM convenios WHERE {where} ORDER BY ultima_fecha_registro DESC, codigo LIMIT ? OFFSET ?",
            params + [TAM, (pag - 1) * TAM]).fetchall()
        ambitos = [r[0] for r in c.execute(
            "SELECT DISTINCT ambito FROM convenios WHERE ambito IS NOT NULL ORDER BY ambito")]
        ult = c.execute("SELECT fin FROM ejecuciones WHERE fin IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        ult_txt = ult[0] if ult else "todavía no se ha sincronizado"

        def url_pag(n):
            args = request.args.to_dict()
            args["p"] = str(n)
            return "/?" + urlencode(args)

        enlaces = ""
        if n_pag > 1:
            partes = []
            if pag > 1:
                partes.append(f'<a href="{url_pag(pag - 1)}">« Anterior</a>')
            partes.append(f'<span class="muted">Página {pag} de {n_pag}</span>')
            if pag < n_pag:
                partes.append(f'<a href="{url_pag(pag + 1)}">Siguiente »</a>')
            enlaces = '<p class="pag">' + " ".join(partes) + "</p>"

        aviso = f'<p style="color:#b00020">⚠ {esc(f["aviso"])}</p>' if f["aviso"] else ""
        cuerpo = (
            "<h1>Convenios colectivos</h1>"
            f'<p class="muted">{total} convenios encontrados · última sincronización: {esc(ult_txt)}</p>{aviso}'
            f'<div class="card">{_formulario(f, ambitos)}</div>'
            '<div class="tab-wrap"><table><tr><th>Convenio</th><th>Ámbito</th><th>Último trámite</th>'
            '<th>Fecha</th><th>Vigencia hasta</th><th>Estado</th><th class="num">Trámites</th><th></th></tr>'
            + "".join(_fila_convenio(r) for r in filas) + "</table></div>" + enlaces)
        return pagina("Buscar", cuerpo)

    @app.route("/convenio/<codigo>")
    def convenio(codigo):
        c = bd()
        cab = c.execute("SELECT * FROM convenios WHERE codigo = ?", (codigo,)).fetchone()
        if cab is None:
            abort(404)
        tramites = c.execute(
            """SELECT t.*, d.estado AS doc_estado, d.error AS doc_error,
                      (SELECT COUNT(*) FROM tablas b WHERE b.url = t.url_publicacion AND b.salarial = 1) AS n_sal
               FROM tramites t LEFT JOIN documentos d ON d.url = t.url_publicacion
               WHERE t.codigo = ? ORDER BY t.fecha_registro DESC, t.id_expediente DESC""", (codigo,)).fetchall()
        tablas = c.execute(
            """SELECT b.*, (SELECT MAX(x.fecha_registro) FROM tramites x
                            WHERE x.url_publicacion = b.url AND x.codigo = ?) AS fecha
               FROM tablas b
               WHERE b.url IN (SELECT url_publicacion FROM tramites WHERE codigo = ? AND url_publicacion IS NOT NULL)
               ORDER BY b.salarial DESC, fecha DESC, b.url, b.orden""", (codigo, codigo)).fetchall()
        salariales = [t for t in tablas if t["salarial"]]
        otras = [t for t in tablas if not t["salarial"]]

        def bloque(t):
            filas = json.loads(t["filas"])
            enlace_texto = f'/documento?url={quote(t["url"], safe="")}'
            return ('<div class="card">'
                    f'<div class="muted">Fecha del trámite: {esc(t["fecha"] or "—")} · página {esc(t["pagina"] or "—")} · '
                    f'<a href="{esc(enlace_texto)}">ver texto</a> · '
                    f'<a href="{esc(t["url"])}" target="_blank" rel="noopener">documento original</a></div>'
                    f'<p class="muted">{esc(t["contexto"] or "")}</p>{_aviso_vacias(filas)}{tabla_html(filas)}</div>')

        if salariales:
            bloque_sal = "".join(bloque(t) for t in salariales)
        else:
            bloque_sal = ('<p class="muted">No se han detectado tablas salariales en las publicaciones procesadas. '
                          'Puede ser que el convenio no las tenga en el texto, que el documento sea una imagen '
                          'escaneada o que la tabla tenga un formato que no se reconoce.</p>')
        bloque_otras = ""
        if otras:
            bloque_otras = (f"<details><summary>Otras tablas detectadas ({len(otras)})</summary>"
                            + "".join(bloque(t) for t in otras[:20]) + "</details>")

        filas_t = ""
        for t in tramites:
            pub = (f'<a href="{esc(t["url_publicacion"])}" target="_blank" rel="noopener">abrir</a>'
                   if t["url_publicacion"] else '<span class="muted">—</span>')
            filas_t += ("<tr>"
                        f'<td>{esc(t["fecha_registro"])}</td><td>{esc(t["tipo_tramite"])}</td>'
                        f'<td>{esc(t["n_expediente"] or "")}</td><td>{esc(t["estado"] or "")}</td>'
                        f"<td>{pub}</td><td>{_badge_documento(t)}</td>"
                        f'<td class="num">{t["n_sal"] or ""}</td></tr>')

        cuerpo = (
            f'<h1>{esc(cab["denominacion"] or cab["codigo"])}</h1>'
            f'<p class="muted">Código {esc(cab["codigo"])} · Ámbito: {esc(cab["ambito"])} · '
            f'Estado: {esc(cab["estado"] or "—")} · Vigencia hasta: {esc(cab["vigencia_hasta"] or "—")} · '
            f'Trámites: {cab["n_tramites"]}</p>'
            "<h2>Tablas salariales</h2>"
            '<p class="muted">Extraídas automáticamente de las publicaciones oficiales. Compruébalas con el '
            "documento original antes de usar las cifras.</p>"
            f"{bloque_sal}{bloque_otras}"
            "<h2>Trámites en REGCON</h2>"
            '<div class="tab-wrap"><table><tr><th>Fecha</th><th>Trámite</th><th>Expediente</th><th>Estado</th>'
            "<th>Publicación</th><th>Texto</th><th class=\"num\">Tablas salariales</th></tr>"
            f"{filas_t}</table></div>"
            '<p><a href="/">← Volver a la búsqueda</a></p>')
        return pagina(cab["denominacion"] or codigo, cuerpo)

    @app.route("/documento")
    def documento():
        url = request.args.get("url", "")
        r = bd().execute("SELECT * FROM documentos WHERE url = ?", (url,)).fetchone()
        if r is None:
            abort(404)
        texto = zlib.decompress(r["texto"]).decode("utf-8") if r["texto"] else ""
        recorte = ""
        if len(texto) > 300000:
            recorte = (f"<p class='muted'>Se muestran los primeros 300.000 de {len(texto):,} caracteres "
                       "(el texto completo está en la base de datos).</p>").replace(",", ".")
        cuerpo = (f"<h1>Texto de la publicación</h1>"
                  f"<p class='muted'>{esc(r['caracteres'] or 0)} caracteres · vía {esc(r['via'] or '—')} · "
                  f"<a href='{esc(url)}' target='_blank' rel='noopener'>abrir el original</a></p>"
                  f"{recorte}<pre>{esc(texto[:300000])}</pre>")
        return pagina("Texto de la publicación", cuerpo)

    @app.route("/boe")
    def boe_lista():
        filas = bd().execute(
            "SELECT * FROM boe_disposiciones ORDER BY fecha DESC, identificador DESC LIMIT 300").fetchall()
        cuerpo_filas = ""
        for r in filas:
            enlace = r["url_html"] or r["url_pdf"] or ""
            cuerpo_filas += (f'<tr><td>{esc(r["fecha"])}</td>'
                             f'<td><a href="{esc(enlace)}" target="_blank" rel="noopener">{esc(r["titulo"])}</a></td>'
                             f'<td>{esc(r["identificador"])}</td></tr>')
        cuerpo = ("<h1>Convenios publicados en el BOE</h1>"
                  '<p class="muted">Sección III, «Convenios colectivos de trabajo». Últimas 300.</p>'
                  '<div class="tab-wrap"><table><tr><th>Fecha</th><th>Disposición</th><th>Identificador</th></tr>'
                  f"{cuerpo_filas}</table></div>")
        return pagina("BOE", cuerpo)

    @app.route("/seguimiento")
    def seguimiento():
        c = bd()
        s = seg()
        terminos = s.execute("SELECT * FROM seguimiento ORDER BY termino COLLATE NOCASE").fetchall()
        bloques = []
        for t in terminos:
            cond, params = _cond_texto(t["termino"], "c.busqueda")
            n_conv = c.execute(f"SELECT COUNT(*) FROM convenios c WHERE {cond}", params).fetchone()[0]
            nov = c.execute(
                f"""SELECT t.primera_vista, t.fecha_registro, t.tipo_tramite, t.ambito, t.codigo,
                           c.denominacion AS convenio
                    FROM tramites t JOIN convenios c ON c.codigo = t.codigo
                    WHERE t.primera_vista >= ? AND {cond}
                    ORDER BY t.primera_vista DESC, t.fecha_registro DESC LIMIT 201""",
                [t["revisado"]] + params).fetchall()
            recorte = ""
            if len(nov) > 200:
                nov = nov[:200]
                recorte = '<p class="muted">Se muestran las 200 novedades más recientes.</p>'
            if nov:
                filas = "".join(
                    "<tr>"
                    f"<td>{esc(r['primera_vista'][:16].replace('T', ' '))}</td>"
                    f"<td>{esc(r['fecha_registro'])}</td>"
                    f"<td><a href=\"/convenio/{esc(r['codigo'])}\">{esc(r['convenio'] or r['codigo'])}</a></td>"
                    f"<td>{esc(r['tipo_tramite'])}</td><td>{esc(r['ambito'])}</td>"
                    "</tr>" for r in nov)
                tabla = ('<div class="tab-wrap"><table><tr><th>Detectado</th><th>Registro</th><th>Convenio</th>'
                         f'<th>Trámite</th><th>Ámbito</th></tr>{filas}</table></div>')
            else:
                tabla = '<p class="muted">Sin novedades desde tu última visita.</p>'
            enlace = "/?" + urlencode({"q": t["termino"]})
            bloques.append(
                '<div class="card">'
                f'<h2>«{esc(t["termino"])}»</h2>'
                f'<p class="muted">{n_conv} convenios coinciden · {len(nov)} trámites nuevos desde tu última visita · '
                f'<a href="{esc(enlace)}">ver todos</a></p>'
                f"{recorte}{tabla}"
                '<form method="post" action="/seguimiento/borrar" style="margin-top:8px">'
                f'<input type="hidden" name="id" value="{t["id"]}">'
                '<button class="sec" type="submit">Dejar de seguir</button></form>'
                "</div>")
        # Se marca la visita después de calcular las novedades.
        s.execute("UPDATE seguimiento SET revisado = ?", (db.ahora(),))
        s.commit()
        alta = ('<div class="card"><form class="filtros" method="post" action="/seguimiento/nuevo">'
                '<label>Término a seguir<input name="termino" maxlength="80" required '
                'placeholder="p. ej. Madrid, hostelería, 9910…"></label>'
                '<button type="submit">Añadir</button></form></div>')
        intro = ('<p class="muted">Trámites nuevos de REGCON que coinciden con lo que sigues. '
                 'Cada vez que abres esta página, la lista empieza desde tu visita anterior.</p>')
        lista = "".join(bloques) if bloques else '<p class="muted">Todavía no sigues ningún término.</p>'
        return pagina("Seguimiento", "<h1>Seguimiento</h1>" + intro + alta + lista)

    @app.route("/seguimiento/nuevo", methods=["POST"])
    def seguimiento_nuevo():
        termino = " ".join(request.form.get("termino", "").split())[:80]
        if termino:
            s = seg()
            ahora = db.ahora()
            s.execute("INSERT OR IGNORE INTO seguimiento (termino, creado, revisado) VALUES (?, ?, ?)",
                      (termino, ahora, ahora))
            s.commit()
        return redirect("/seguimiento")

    @app.route("/seguimiento/borrar", methods=["POST"])
    def seguimiento_borrar():
        try:
            id_termino = int(request.form.get("id", ""))
        except ValueError:
            abort(400)
        s = seg()
        s.execute("DELETE FROM seguimiento WHERE id = ?", (id_termino,))
        s.commit()
        return redirect("/seguimiento")

    @app.route("/estado")
    def estado():
        c = bd()

        def n(sql):
            return c.execute(sql).fetchone()[0]

        cifras = [
            ("Convenios", n("SELECT COUNT(*) FROM convenios")),
            ("Convenios con tablas salariales", n("SELECT COUNT(*) FROM convenios WHERE tiene_tablas_salariales = 1")),
            ("Trámites de REGCON", n("SELECT COUNT(*) FROM tramites")),
            ("Trámites pendientes de ficha", n("SELECT COUNT(*) FROM tramites WHERE detalle_ok = 0")),
            ("Publicaciones con texto", n("SELECT COUNT(*) FROM documentos WHERE estado = 'ok'")),
            ("Publicaciones sin texto", n("SELECT COUNT(*) FROM documentos WHERE estado = 'sin_texto'")),
            ("Publicaciones con error", n("SELECT COUNT(*) FROM documentos WHERE estado = 'error'")),
            ("Publicaciones bloqueadas por robots.txt", n("SELECT COUNT(*) FROM documentos WHERE estado = 'bloqueada'")),
            ("Estado de la instalación", operacion.diagnostico()["estado"]),
        ]
        filas_c = "".join(f"<tr><td>{esc(k)}</td><td class='num'>{v}</td></tr>" for k, v in cifras)
        ejec = c.execute("SELECT * FROM ejecuciones ORDER BY id DESC LIMIT 10").fetchall()
        filas_e = "".join(
            f"<tr><td>{esc(e['inicio'])}</td><td>{esc(e['fin'] or 'en curso')}</td>"
            f"<td>{esc(e['desde'])} → {esc(e['hasta'])}</td>"
            f"<td class='muted'>{esc((e['resumen'] or '')[:300])}</td></tr>" for e in ejec)
        errores = c.execute("SELECT url, error FROM documentos WHERE estado = 'error' "
                            "ORDER BY procesado DESC LIMIT 50").fetchall()
        filas_err = "".join(f"<tr><td class='muted'>{esc(e['url'])}</td><td>{esc(e['error'])}</td></tr>"
                            for e in errores)
        cuerpo = (f"<h1>Estado de la base de datos</h1>"
                  f'<div class="tab-wrap"><table>{filas_c}</table></div>'
                  "<h2>Últimas ejecuciones</h2>"
                  '<div class="tab-wrap"><table><tr><th>Inicio</th><th>Fin</th><th>Periodo</th><th>Resumen</th></tr>'
                  f"{filas_e}</table></div>"
                  "<h2>Publicaciones con error (50 últimas)</h2>"
                  '<div class="tab-wrap"><table><tr><th>Enlace</th><th>Error</th></tr>'
                  f"{filas_err}</table></div>")
        return pagina("Estado", cuerpo)

    @app.route("/salud")
    def salud():
        """Estado para monitorización. No revela datos de los convenios."""
        info = operacion.diagnostico()
        codigo = 503 if info["estado"] == operacion.ERROR else 200
        return Response(json.dumps(info, ensure_ascii=False, indent=2), status=codigo,
                        mimetype="application/json; charset=utf-8")

    @app.route("/api/convenios")
    def api_convenios():
        f = _filtros(request.args)
        where, params = _where(f)
        cols = ", ".join(COLUMNAS_CSV)
        filas = bd().execute(
            f"SELECT {cols} FROM convenios WHERE {where} ORDER BY ultima_fecha_registro DESC LIMIT 500",
            params).fetchall()
        return Response(json.dumps([dict(r) for r in filas], ensure_ascii=False, indent=2),
                        mimetype="application/json; charset=utf-8")

    @app.route("/exportar/convenios.csv")
    def exportar_csv():
        filas = bd().execute("SELECT * FROM convenios ORDER BY ultima_fecha_registro DESC").fetchall()
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(COLUMNAS_CSV)
        for r in filas:
            w.writerow([celda_csv(r[k]) for k in COLUMNAS_CSV])
        return Response(buf.getvalue().encode("utf-8-sig"), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=convenios.csv"})

    return app
