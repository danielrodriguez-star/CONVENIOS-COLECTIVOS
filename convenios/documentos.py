"""Descarga y lectura de publicaciones oficiales: texto y tablas, con detección de tablas salariales."""
import logging
import re
from urllib.parse import urljoin, urlsplit

import requests
from lxml import html as LH

try:  # PyMuPDF >= 1.24 expone el módulo como «pymupdf»
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

from . import boe, config, robots
from .util import limpio, pedir, quitar_control, sesion_heredada, sin_acentos, texto_de

log = logging.getLogger("convenios.documentos")

# Publicaciones del BOE. Con CONVENIOS_ROBOTS=respetar (por defecto) se leen de su PDF, que sí está
# permitido. Con «ignorar» se leen de su XML, que el robots.txt del BOE prohíbe.
PDF_BOE = re.compile(r"/boe/dias/\d{4}/\d{2}/\d{2}/pdfs/(BOE-[A-Z]-\d{4}-\d+)\.pdf")
# Expresiones que suelen encabezar las tablas salariales (texto sin tildes).
KW_SALARIAL = re.compile(
    r"tablas? salariales?|tabla salarial|salario base|tablas? de (salarios|retribuciones)"
    r"|retribuciones (anuales|mensuales|brutas)|salarios? (mensuales|anuales|brutos)|sueldo base")
# Palabras de la cabecera o del texto previo que sugieren contenido salarial.
KW_CABECERA = re.compile(r"salari|retribuc|sueldo|percepcion")
# Importes en formato español: 1.234,56 · 1234,56 · 1.234 · 1234
IMPORTE = re.compile(r"^\d{1,3}(\.\d{3})*(,\d{1,2})?$|^\d+(,\d{1,2})?$")
IMPORTE_EN_TEXTO = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}\b")


def puntuar_tabla(filas, contexto=""):
    """Heurística: devuelve (salarial 0/1, puntuación). Conviene revisar siempre el original."""
    if len(filas) < 3:
        return 0, 0.0
    celdas = []
    for fila in filas[1:]:
        for c in fila[1:]:  # la primera columna suele ser el nombre de la categoría
            c = (c or "").replace("€", "").replace("EUR", "").replace("\xa0", " ").strip()
            if c:
                celdas.append(c)
    if not celdas:
        return 0, 0.0
    proporcion = sum(1 for c in celdas if IMPORTE.match(c.replace(" ", ""))) / len(celdas)
    cabecera = sin_acentos(" ".join(" ".join(f) for f in filas[:2]) + " " + (contexto or ""))
    kw = bool(KW_CABECERA.search(cabecera))
    salarial = 1 if (proporcion >= 0.5 and kw) else 0
    return salarial, round(proporcion * (2 if kw else 1), 3)


def _tablas_pdf(doc, paginas):
    """Tablas de las páginas indicadas. Devuelve (tablas, número de páginas que no se pudieron analizar)."""
    res, omitidas = [], 0
    for i in paginas:
        pagina = doc[i]
        try:
            encontradas = pagina.find_tables()
        except Exception:  # noqa: BLE001  página sin estructura de tabla legible: se cuenta y se sigue
            omitidas += 1
            continue
        for k, tb in enumerate(encontradas.tables, 1):
            filas = [[limpio(c) for c in fila] for fila in tb.extract()]
            if len(filas) < 2 or max(len(f) for f in filas) < 2:
                continue
            _, y0, _, _ = tb.bbox
            zona = fitz.Rect(0, max(0, y0 - 160), pagina.rect.width, max(0, y0))
            contexto = limpio(pagina.get_text("text", clip=zona))[-220:]
            salarial, puntuacion = puntuar_tabla(filas, contexto)
            res.append({"pagina": i + 1, "orden": k, "contexto": contexto, "filas": filas,
                        "salarial": salarial, "puntuacion": puntuacion})
    return res, omitidas


def procesar_pdf(datos):
    doc = fitz.open(stream=datos, filetype="pdf")
    paginas = [quitar_control(p.get_text("text")) for p in doc]
    # Solo se buscan tablas en páginas que hablan de salarios y tienen importes.
    candidatas = [i for i, t in enumerate(paginas)
                  if KW_SALARIAL.search(sin_acentos(t)) and len(IMPORTE_EN_TEXTO.findall(t)) >= 5]
    tablas, omitidas = _tablas_pdf(doc, candidatas[:config.DOC_MAX_PAG_TABLAS])
    doc.close()
    return {"texto": "\n\f".join(paginas), "paginas": len(paginas), "tablas": tablas, "via": "pdf",
            "paginas_omitidas": omitidas}


def _normalizar(texto):
    texto = quitar_control(texto)
    lineas = [re.sub(r"[ \t\r\f\v\xa0]+", " ", l).strip() for l in texto.splitlines()]
    salida, vacia = [], False
    for l in lineas:
        if l:
            salida.append(l)
            vacia = False
        elif not vacia:
            salida.append("")
            vacia = True
    return "\n".join(salida).strip()


_RE_CHARSET_CABECERA = re.compile(r"charset=\s*[\"']?([\w.:-]+)", re.I)
_RE_CHARSET_META = re.compile(rb"<meta[^>]+charset=[\"']?\s*([\w.:-]+)", re.I)
_RE_DECLARACION_XML = re.compile(r"^\s*<\?xml[^>]*\?>")
_RE_BLOQUEO = re.compile(r"captcha|radware|access denied|acceso denegado", re.I)


def decodificar_html(datos, charset=None):
    """Texto de unos bytes HTML. Se prueba UTF-8 (estricto), luego el charset de la cabecera HTTP
    o de la etiqueta meta, y por último cp1252. Así no aparece «Ã³» en lugar de «ó»: lxml, si recibe
    bytes, adivina la codificación y suele equivocarse con páginas UTF-8."""
    candidatos = ["utf-8-sig"]
    if charset:
        candidatos.append(charset)
    m = _RE_CHARSET_META.search(datos[:4096])
    if m:
        candidatos.append(m.group(1).decode("ascii", "ignore"))
    for enc in candidatos:
        try:
            return datos.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return datos.decode("cp1252", errors="replace")


def procesar_html(datos, ctype=""):
    m = _RE_CHARSET_CABECERA.search(ctype or "")
    texto = decodificar_html(datos, m.group(1) if m else None)
    doc = LH.fromstring(_RE_DECLARACION_XML.sub("", texto, count=1))  # lxml no admite declaración XML en str
    for el in doc.xpath("//script|//style|//noscript"):
        el.drop_tree()
    if len(doc.text_content()) < 3000 and _RE_BLOQUEO.search(doc.text_content()):
        # Algunos servidores devuelven un captcha (p. ej. Radware) en lugar de la publicación.
        raise ValueError("el servidor devolvió una página de bloqueo (captcha), no el documento")
    tablas = []
    for tb in doc.iter("table"):
        filas = []
        for tr in tb.iter("tr"):
            celdas = [texto_de(c) for c in tr if isinstance(c.tag, str) and c.tag in ("td", "th")]
            if any(celdas):
                filas.append(celdas)
        if len(filas) >= 2:
            salarial, puntuacion = puntuar_tabla(filas, "")
            tablas.append({"pagina": None, "orden": len(tablas) + 1, "contexto": "", "filas": filas,
                           "salarial": salarial, "puntuacion": puntuacion})
    return {"texto": _normalizar(doc.text_content()), "paginas": None, "tablas": tablas, "via": "html"}


def leer_acotado(r, limite=config.DOC_MAX_BYTES):
    """Contenido de una respuesta en trozos. Corta si supera `limite` (evita llenar la memoria)."""
    trozos, total = [], 0
    for trozo in r.iter_content(chunk_size=1 << 16):
        total += len(trozo)
        if total > limite:
            r.close()
            raise ValueError(f"documento demasiado grande (más de {limite // (1024 * 1024)} MB)")
        trozos.append(trozo)
    return b"".join(trozos)


REDIRECCIONES = (301, 302, 303, 307, 308)
MAX_REDIRECCIONES = 5


def _pedir_salto(url, cabeceras):
    """Una sola petición, sin seguir redirecciones. Devuelve (respuesta, si usó el TLS heredado)."""
    try:
        return pedir(None, "GET", url, headers=cabeceras, timeout=20, intentos=2, stream=True,
                     allow_redirects=False), False
    except requests.exceptions.SSLError:
        # Solo para los servidores de CONVENIOS_TLS_HEREDADO (ver PRODUCCION.md): se reintenta
        # una vez con cifrados antiguos y sin verificar el certificado.
        if urlsplit(url).hostname not in config.TLS_HEREDADO:
            raise
        return pedir(sesion_heredada(), "GET", url, headers=cabeceras, timeout=20, intentos=2,
                     verify=False, stream=True, allow_redirects=False), True


def descargar(url):
    """(contenido, content-type, legado). `legado` indica que se usó el TLS heredado.

    Las redirecciones no las sigue requests: cada salto se comprueba con robots.txt como si fuera
    una petición nueva. Si no, una dirección permitida podría llevar a una prohibida."""
    cabeceras = {"Accept": "application/pdf,text/html;q=0.9,*/*;q=0.5"}
    actual, legado = url, False
    for salto in range(MAX_REDIRECCIONES + 1):
        r, por_tls_heredado = _pedir_salto(actual, cabeceras)
        legado = legado or por_tls_heredado
        destino = r.headers.get("location")
        if r.status_code in REDIRECCIONES or (300 <= r.status_code < 400 and destino):
            r.close()
            if not destino:
                raise ValueError(f"redirección sin destino (HTTP {r.status_code})")
            if salto == MAX_REDIRECCIONES:
                raise ValueError(f"demasiadas redirecciones (más de {MAX_REDIRECCIONES})")
            siguiente = urljoin(actual, destino)
            if urlsplit(siguiente).scheme not in ("http", "https"):
                raise ValueError("redirección a un protocolo no permitido")
            robots.comprobar(siguiente)  # puede lanzar Bloqueada o NoDisponible
            actual = siguiente
            continue
        if 300 <= r.status_code < 400:
            r.close()
            raise ValueError(f"redirección sin destino (HTTP {r.status_code})")
        r.raise_for_status()
        return leer_acotado(r), r.headers.get("content-type", "").lower(), legado
    raise ValueError("demasiadas redirecciones")  # no se alcanza: el bucle siempre sale antes


def _procesar_boe_xml(identificador):
    texto, tablas = boe.documento_xml(identificador)
    for t in tablas:
        t["salarial"], t["puntuacion"] = puntuar_tabla(t["filas"], t["contexto"])
    return {"texto": texto, "paginas": None, "tablas": tablas, "via": "boe-xml"}


def procesar(url):
    """Devuelve {'texto', 'paginas', 'tablas', 'via'} para una publicación oficial.

    Lanza robots.Bloqueada si robots.txt prohíbe la descarga y robots.NoDisponible si no se puede
    consultar en este momento. Quien llama decide: «bloqueada» o «pendiente»."""
    m = PDF_BOE.search(url)
    if m and config.ROBOTS == "ignorar":
        return _procesar_boe_xml(m.group(1))
    robots.comprobar(url)
    datos, ctype, legado = descargar(url)
    if datos[:4] == b"%PDF" or "pdf" in ctype:
        out = procesar_pdf(datos)
    elif "html" in ctype or b"<html" in datos[:4000].lower():
        out = procesar_html(datos, ctype)
    else:
        raise ValueError(f"formato no soportado ({ctype or 'desconocido'})")
    if m and out["via"] == "pdf":
        out["via"] = "boe-pdf"
    if legado:
        out["via"] += "+tls-heredado"
    if out.get("paginas_omitidas"):
        log.warning("%s: %d páginas sin búsqueda de tablas (error de lectura)", url, out["paginas_omitidas"])
    return out
