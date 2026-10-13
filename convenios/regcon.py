"""Cliente del buscador público de REGCON (Registro de convenios colectivos).

REGCON no ofrece API. Este módulo reproduce lo que hace su propio formulario:
  1. búsqueda de trámites de convenios por rango de fechas (POST),
  2. paginación de resultados (GET ?pagina=N),
  3. ficha de cada expediente (POST con el botón «Ver», que solo necesita el identificador).

Cuando una búsqueda tiene más de una página, REGCON no reparte las filas de forma fiable
(los trámites con la misma fecha pueden repetirse o desaparecer). Por eso `listar()` comprueba
que las filas sean únicas y, si no lo son, parte la búsqueda por otro criterio.
"""
import hashlib
import math
import re
import time
import html as htmllib

import requests
from lxml import html as LH

from . import config
from .util import fecha_es, limpio, pedir, texto_de

# Criterios por los que se puede partir una búsqueda (en orden de preferencia).
DIMENSIONES = (
    "idAmbFuncionalConsPublica",    # ámbito funcional (6 valores): parte mejor los días con muchos trámites
    "idEstadoVigencia",             # estado de vigencia
    "idTipoTramiteConsPublica",     # tipo de trámite
    "autoridadLaboral",             # autoridad laboral (ámbito territorial): muchos valores, último recurso
)


def _doc(texto):
    """Árbol HTML desde texto. Se quita una posible declaración XML, que lxml no admite en str."""
    return LH.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", texto))


class Regcon:
    def __init__(self, pausa=config.REGCON_PAUSA):
        self.pausa = pausa
        self.sesion = requests.Session()
        self.sesion.headers.update({
            "User-Agent": config.USER_AGENT,
            "Referer": config.REGCON_BUSCADOR,
            "Accept-Language": "es-ES,es;q=0.9",
        })
        self.ocultos = None
        self.opciones = {}

    # --- transporte -------------------------------------------------------
    def _esperar(self):
        if self.pausa:
            time.sleep(self.pausa)

    @staticmethod
    def _texto(r):
        if "charset" not in r.headers.get("content-type", "").lower():
            r.encoding = "utf-8"
        return r.text

    def _get(self, params=None):
        self._esperar()
        r = pedir(self.sesion, "GET", config.REGCON_BUSCADOR, params=params)
        r.raise_for_status()
        return self._texto(r)

    def _post(self, datos):
        self._esperar()
        r = pedir(self.sesion, "POST", config.REGCON_BUSCADOR, data=datos)
        r.raise_for_status()
        return self._texto(r)

    # --- operaciones ------------------------------------------------------
    def abrir(self):
        """Carga el formulario: cookies de sesión, campos ocultos y listas de opciones."""
        texto = self._get()
        ocultos = []
        for attrs in re.findall(r"<input([^>]*)>", texto, re.I):
            nombre = re.search(r'name="([^"]+)"', attrs)
            tipo = re.search(r'type="([^"]+)"', attrs)
            valor = re.search(r'value="([^"]*)"', attrs)
            if nombre and tipo and tipo.group(1).lower() == "hidden":
                ocultos.append((nombre.group(1), valor.group(1) if valor else ""))
        if not ocultos:
            raise RuntimeError("El formulario de REGCON no tiene los campos esperados")
        opciones = {}
        for campo in DIMENSIONES:
            m = re.search(r'<select[^>]*name="%s"[^>]*>(.*?)</select>' % campo, texto, re.S | re.I)
            valores = re.findall(r'<option[^>]*value="([^"]*)"', m.group(1), re.I) if m else []
            opciones[campo] = [v for v in valores if v]
        if not opciones["idTipoTramiteConsPublica"] or not opciones["autoridadLaboral"]:
            raise RuntimeError("No se han encontrado las opciones del formulario de REGCON")
        self.ocultos = ocultos
        self.opciones = opciones
        return self

    def valores(self, campo):
        if self.ocultos is None:
            self.abrir()
        return self.opciones[campo]

    def buscar(self, desde, hasta, fijos=None):
        """Búsqueda de trámites de convenios entre dos fechas (ambas incluidas).

        `fijos` limita algún criterio a un valor concreto, p. ej. {"idTipoTramiteConsPublica": "3"}.
        Devuelve (total informado por REGCON, filas de la primera página)."""
        if self.ocultos is None:
            self.abrir()
        fijos = fijos or {}
        datos = list(self.ocultos) + [
            ("codigoConvenio", ""), ("denominacion", ""), ("tipoBusquedaDenominacion", "AND"), ("nif", ""),
            ("fhIncripcionPublicacionDesde", desde.strftime("%d/%m/%Y")),
            ("fhIncripcionPublicacionHasta", hasta.strftime("%d/%m/%Y")),
            ("idNaturalezaConsPublica", "1"),  # 1 = CONVENIO COLECTIVO
        ]
        for campo in DIMENSIONES:
            if campo in fijos:
                datos.append((campo, fijos[campo]))
            elif campo != "autoridadLaboral":  # sin restricción, la autoridad no se envía
                datos += [(campo, v) for v in self.opciones[campo]]
        texto = self._post(datos)
        return total_informado(texto), parse_listado(texto)

    def pagina(self, n):
        """Filas de la página n (desde 1) de la última búsqueda de esta sesión."""
        return parse_listado(self._get(params={"pagina": n}))

    def ficha(self, id_expediente):
        """Ficha de un expediente (dict) o None si la respuesta no es una ficha."""
        if self.ocultos is None:
            self.abrir()
        return parse_ficha(self._post(list(self.ocultos) + [(f"_verExpediente{id_expediente}", "")]))


# --- búsqueda completa -------------------------------------------------------
# Límite de niveles de partición (cada nivel añade un criterio fijo).
MAX_NIVEL = 3


def _unicas(filas):
    vistos, salida = set(), []
    for f in filas:
        if f["id_expediente"] not in vistos:
            vistos.add(f["id_expediente"])
            salida.append(f)
    return salida


def listar(cli, desde, hasta, fijos=None, nivel=0):
    """Todos los trámites entre dos fechas, sin duplicados. Devuelve (total informado, filas, completo).

    REGCON cuenta filas duplicadas en su total y, cuando una búsqueda ocupa más de una página,
    la paginación puede repetir filas y dejar otras fuera. Por eso:
      - una búsqueda que cabe en una página (<= 15 filas) se lee tal cual, sin paginar;
      - una búsqueda mayor se parte por un criterio (ámbito funcional, estado, tipo de trámite
        o autoridad laboral) hasta que cada parte quepa en una página;
      - se devuelven las filas únicas por identificador.
    `completo` es False si no se ha podido llegar a particiones de una página."""
    fijos = fijos or {}
    total, p1 = cli.buscar(desde, hasta, fijos)
    if total is None:
        raise RuntimeError("REGCON no informa del número de resultados")
    if total == 0:
        return 0, [], True
    if total <= config.REGCON_TAM_PAGINA:
        return total, _unicas(p1), len(p1) == total
    if nivel < MAX_NIVEL:
        for campo in DIMENSIONES:
            if campo in fijos or (campo == "autoridadLaboral" and nivel > 0):
                continue  # la autoridad laboral tiene muchos valores: solo se usa en el primer nivel
            resultados = [listar(cli, desde, hasta, {**fijos, campo: v}, nivel + 1)
                          for v in cli.valores(campo)]
            if all(ok for _, _, ok in resultados):
                filas = _unicas([f for _, fs, _ in resultados for f in fs])
                return total, filas, True
    # Sin partición válida: se pagina (queda marcado como incompleto). REGCON guarda una sola búsqueda
    # por sesión: tras probar particiones hay que repetir ESTA búsqueda, si no las páginas serían de otra.
    _, p1 = cli.buscar(desde, hasta, fijos)
    filas = list(p1)
    for p in range(2, math.ceil(total / config.REGCON_TAM_PAGINA) + 1):
        filas += cli.pagina(p)
    return total, _unicas(filas), False


# --- análisis de las respuestas ----------------------------------------------
def total_informado(texto):
    t = htmllib.unescape(texto)
    m = re.search(r"Resultados\s*\d+\s*-\s*\d+\s+de\s+(\d+)", t)
    if m:
        return int(m.group(1))
    if re.search(r"No se han? encontrado|ning[uú]n (acuerdo|resultado)|no hay resultados", t, re.I):
        return 0
    return None


def clave_sin_ficha(fila):
    """Clave estable (negativa, para no chocar con los ids de REGCON) de una fila sin botón de ficha."""
    base = "|".join(str(fila.get(k) or "") for k in
                    ("codigo", "tipo_tramite", "ambito", "fecha_registro", "vigencia_desde",
                     "vigencia_hasta", "denominacion"))
    return -(int(hashlib.sha1(base.encode("utf-8")).hexdigest()[:12], 16) + 1)


def parse_listado(texto):
    """Filas de la tabla de resultados: una por trámite.

    Algunas filas (p. ej. «PRONUNCIAMIENTO DEL TRIBUNAL») no tienen botón de ficha:
    se conservan con `sin_ficha=True` y una clave derivada de sus datos."""
    doc = _doc(texto)
    filas = []
    for tr in doc.iter("tr"):
        celdas = [c for c in tr if c.tag == "td"]
        if len(celdas) < 7:
            continue
        codigo = limpio(celdas[0].text_content())
        if not re.fullmatch(r"\d{14}", codigo):
            continue
        m = re.search(r"_verExpediente(\d+)", " ".join(tr.xpath(".//button/@name")))
        fila = {
            "id_expediente": int(m.group(1)) if m else None,
            "codigo": codigo,
            "denominacion": texto_de(celdas[1]),
            "tipo_tramite": texto_de(celdas[2]),
            "ambito": texto_de(celdas[3]),
            "fecha_registro": fecha_es(texto_de(celdas[4])),
            "vigencia_desde": fecha_es(texto_de(celdas[5])),
            "vigencia_hasta": fecha_es(texto_de(celdas[6])),
            "sin_ficha": m is None,
        }
        if fila["id_expediente"] is None:
            fila["id_expediente"] = clave_sin_ficha(fila)
        filas.append(fila)
    return filas


def _desenvolver_url(href):
    """Quita el visor de PDF que a veces envuelve el enlace de la publicación:
    chrome-extension://<id>/https://… → https://…  (esa URL nunca se podía descargar)."""
    m = re.search(r"chrome-extension://[a-z]+/(https?://.+)$", href)
    return m.group(1) if m else href


def parse_ficha(texto):
    """Datos de la ficha de un expediente, o None si la respuesta no es una ficha."""
    doc = _doc(texto)
    for el in doc.xpath("//script|//style"):
        el.drop_tree()
    lineas = [l for l in (limpio(t) for t in doc.itertext()) if l]
    unido = " ".join(lineas)
    if "EXPEDIENTE" not in unido.upper() and "Resultados" in unido:
        return None  # nos han devuelto el listado y no la ficha
    idx = next((i for i, l in enumerate(lineas) if re.fullmatch(r"\d{14}", l)), None)
    if idx is None:
        return None
    denominacion = lineas[idx - 1].rstrip(" -").strip() if idx > 0 else ""
    # Tras el código vienen los botones («Copiar…», «Exportar…») y, en mayúsculas, los estados
    # (publicación y denuncia). El primer texto que no está en mayúsculas («Información») marca
    # el final. Sin esta regla se colaba el número de expediente («EXPEDIENTE 82/01/0013/2026»).
    estado = []
    for l in lineas[idx + 1: idx + 12]:
        if l.upper().startswith(("COPIAR", "EXPORTAR")):
            continue
        if not l.isupper() or len(estado) >= 3:
            break
        estado.append(l)
    m = re.search(r"EXPEDIENTE\s+([\d/]+)", unido)
    n_exp = m.group(1) if m else None
    m = re.search(r"publicado con fecha:?\s*(\d{2}/\d{2}/\d{4})", unido, re.I)
    fecha_pub = fecha_es(m.group(1)) if m else None
    url = None
    if fecha_pub:
        for a in doc.iter("a"):
            href = _desenvolver_url((a.get("href") or "").strip())
            if href.startswith("http") and "mites.gob.es" not in href:
                url = href
                break
    return {
        "codigo": lineas[idx],
        "denominacion": denominacion,
        "estado": " | ".join(estado),
        "n_expediente": n_exp,
        "fecha_publicacion": fecha_pub,
        "url_publicacion": url,
    }
