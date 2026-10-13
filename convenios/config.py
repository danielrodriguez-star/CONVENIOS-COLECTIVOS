"""Configuración: rutas, direcciones oficiales, ritmo de las peticiones y ajustes de producción.

Los ajustes de producción se cambian con variables de entorno (ver PRODUCCION.md).
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATOS = Path(os.environ.get("CONVENIOS_DATOS", RAIZ / "datos"))
BASE_DATOS = DATOS / "convenios.db"
REGISTRO = DATOS / "sincronizacion.log"      # historial de sincronizaciones (texto)
EXPORTACIONES = DATOS / "exportaciones"
REGISTROS = DATOS / "registros"              # registros técnicos, con rotación por tamaño
COPIAS = DATOS / "copias"                    # copias de seguridad fechadas
ACCESO = DATOS / "acceso.json"               # usuario y hash de la contraseña del panel (si existe)
BLOQUEO = DATOS / "sincronizacion.lock"      # evita dos sincronizaciones a la vez

USER_AGENT = "Mozilla/5.0 (compatible; convenios-es/1.0; consulta de datos publicos)"
TOKEN_AGENTE = "convenios-es"                # nombre del agente para las reglas de robots.txt

# REGCON: buscador público del Registro de convenios colectivos (Ministerio de Trabajo)
REGCON_BUSCADOR = "https://expinterweb.mites.gob.es/regcon/pub/consultaPublicaEstatal"
# BOE: API de datos abiertos (sumario diario) y XML de cada disposición.
# El XML está prohibido por robots.txt: solo se usa con CONVENIOS_ROBOTS=ignorar.
BOE_SUMARIO = "https://www.boe.es/datosabiertos/api/boe/sumario/{fecha}"
BOE_XML = "https://www.boe.es/diario_boe/xml.php?id={id}"

REGCON_PAUSA = 0.5        # segundos entre peticiones de cada hilo (cortesía con el servidor)
REGCON_HILOS = 3          # sesiones simultáneas contra REGCON
REGCON_TAM_PAGINA = 15    # filas por página del listado de REGCON
DOC_HILOS = 8             # publicaciones procesadas en paralelo
DOC_POR_SERVIDOR = 2      # peticiones simultáneas máximas a un mismo servidor
DOC_MAX_PAG_TABLAS = 40   # páginas por PDF en las que se buscan tablas salariales
DOC_MAX_BYTES = 100 * 1024 * 1024  # tamaño máximo de una publicación descargada


def _lista(valor):
    return tuple(v.strip().lower() for v in valor.split(",") if v.strip())


# Robots.txt: «respetar» (por defecto) o «ignorar» (no recomendado: reproduce la versión 1.0).
ROBOTS = os.environ.get("CONVENIOS_ROBOTS", "respetar").strip().lower()
if ROBOTS not in ("respetar", "ignorar"):
    raise ValueError("CONVENIOS_ROBOTS debe ser «respetar» o «ignorar».")

# Servidores que solo aceptan cifrados antiguos. Solo para ellos se descarga sin verificar el certificado.
TLS_HEREDADO = frozenset(_lista(os.environ.get("CONVENIOS_TLS_HEREDADO", "portaldogc.gencat.cat,bop.dipucr.es")))

# Panel web y operación
HOSTS_PERMITIDOS = _lista(os.environ.get("CONVENIOS_HOSTS_PERMITIDOS", ""))  # p. ej. convenios.ejemplo.es,*.ejemplo.es
COPIAS_CONSERVAR = int(os.environ.get("CONVENIOS_COPIAS_CONSERVAR", "14"))
ALERTA_HORAS = int(os.environ.get("CONVENIOS_ALERTA_HORAS", "72"))
# «si» permite mostrar el panel dentro de otra página (la vista previa del entorno de pruebas lo necesita).
PERMITIR_IFRAME = os.environ.get("CONVENIOS_PERMITIR_IFRAME", "no").strip().lower() in ("si", "sí", "1", "true")
