"""Acceso al BOE: sumario diario (API de datos abiertos) y texto XML de cada disposición."""
import re

from lxml import etree

from . import config
from .util import limpio, pedir, texto_de


def _lista(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _url(x):
    return x.get("texto") if isinstance(x, dict) else x


def sumario(fecha):
    """Disposiciones del sumario del BOE de un día. Lista vacía si ese día no hay BOE."""
    url = config.BOE_SUMARIO.format(fecha=fecha.strftime("%Y%m%d"))
    r = pedir(None, "GET", url, headers={"Accept": "application/json"})
    if r.status_code == 404:
        return []
    r.raise_for_status()
    datos = r.json()["data"]["sumario"]
    items = []
    for diario in _lista(datos.get("diario")):
        for seccion in _lista(diario.get("seccion")):
            for dep in _lista(seccion.get("departamento")):
                for epi in _lista(dep.get("epigrafe")):
                    for it in _lista(epi.get("item")):
                        items.append({
                            "identificador": it.get("identificador"),
                            "titulo": limpio(it.get("titulo")),
                            "seccion": str(seccion.get("codigo", "")),
                            "departamento": limpio(dep.get("nombre")),
                            "epigrafe": limpio(epi.get("nombre")),
                            "url_html": _url(it.get("url_html")),
                            "url_pdf": _url(it.get("url_pdf")),
                            "url_xml": _url(it.get("url_xml")),
                            "fecha": fecha.isoformat(),
                        })
    return items


def es_convenio(item):
    """Sección III con epígrafe de convenios, o título que menciona un convenio colectivo."""
    if item.get("seccion") != "3":
        return False
    if (item.get("epigrafe") or "").lower().startswith("convenios colectivos"):
        return True
    return bool(re.search(r"convenio colectivo", item.get("titulo") or "", re.I))


def documento_xml(identificador):
    """(texto, tablas) de una disposición del BOE, leídos de su XML oficial."""
    r = pedir(None, "GET", config.BOE_XML.format(id=identificador))
    r.raise_for_status()
    # Sin resolver entidades externas ni acceder a la red: el XML no puede leer ficheros locales.
    raiz = etree.fromstring(r.content, etree.XMLParser(resolve_entities=False, no_network=True))
    # El cuerpo es el hijo directo <texto> de <documento>; hay otros <texto> dentro de <analisis>.
    cuerpo = raiz.find("texto")
    if cuerpo is None:
        cuerpo = raiz
    partes, tablas = [], []
    ultimo = {"parrafo": ""}

    def recorrer(nodo):
        etiqueta = nodo.tag if isinstance(nodo.tag, str) else ""
        if etiqueta == "table":
            filas = []
            for tr in nodo.iter("tr"):
                celdas = [texto_de(c) for c in tr if isinstance(c.tag, str) and c.tag in ("td", "th")]
                if any(celdas):
                    filas.append(celdas)
            if len(filas) >= 2:
                tablas.append({"pagina": None, "orden": len(tablas) + 1,
                               "contexto": ultimo["parrafo"][-220:], "filas": filas})
                partes.append("[tabla]")
            return
        if etiqueta == "p":
            t = texto_de(nodo)
            if t:
                partes.append(t)
                ultimo["parrafo"] = t
            return
        for hijo in nodo:
            recorrer(hijo)

    recorrer(cuerpo)
    return "\n".join(partes), tablas
