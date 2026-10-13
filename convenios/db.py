"""Base de datos SQLite: esquema y conexión."""
import datetime as dt
import sqlite3

from . import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS tramites (
    id_expediente     INTEGER PRIMARY KEY,   -- identificador interno de REGCON
    codigo            TEXT NOT NULL,         -- código REGCON del convenio (14 dígitos)
    denominacion      TEXT,
    tipo_tramite      TEXT,                  -- p. ej. CONVENIO COLECTIVO (TEXTO NUEVO)
    ambito            TEXT,                  -- autoridad laboral: Estatal, provincia o comunidad
    fecha_registro    TEXT,                  -- AAAA-MM-DD
    vigencia_desde    TEXT,
    vigencia_hasta    TEXT,
    n_expediente      TEXT,
    estado            TEXT,                  -- de la ficha: PUBLICADO | NO DENUNCIADO ...
    fecha_publicacion TEXT,
    url_publicacion   TEXT,                  -- enlace al BOE, BOP o boletín autonómico
    detalle_ok        INTEGER NOT NULL DEFAULT 0,
    detalle_error     TEXT,
    sin_ficha         INTEGER NOT NULL DEFAULT 0,  -- 1 = la fila del listado no tiene ficha (p. ej. sentencias)
    primera_vista     TEXT,
    ultima_vista      TEXT
);
CREATE INDEX IF NOT EXISTS ix_tramites_codigo ON tramites(codigo);
CREATE INDEX IF NOT EXISTS ix_tramites_fecha ON tramites(fecha_registro);
CREATE INDEX IF NOT EXISTS ix_tramites_pendientes ON tramites(detalle_ok);
CREATE INDEX IF NOT EXISTS ix_tramites_url ON tramites(url_publicacion);

CREATE TABLE IF NOT EXISTS convenios (
    codigo                  TEXT PRIMARY KEY,
    denominacion            TEXT,
    ambito                  TEXT,
    n_tramites              INTEGER,
    ultimo_tipo_tramite     TEXT,
    ultima_fecha_registro   TEXT,
    vigencia_hasta          TEXT,
    estado                  TEXT,
    url_ultima_publicacion  TEXT,
    tiene_tablas_salariales INTEGER NOT NULL DEFAULT 0,
    busqueda                TEXT             -- texto normalizado para buscar
);

CREATE TABLE IF NOT EXISTS documentos (
    url        TEXT PRIMARY KEY,
    fuente     TEXT,
    estado     TEXT NOT NULL,                -- ok | sin_texto | error | bloqueada (robots.txt)
    error      TEXT,
    via        TEXT,                         -- pdf | boe-pdf | html | boe-xml (+tls-heredado)
    paginas    INTEGER,
    caracteres INTEGER,
    texto      BLOB,                         -- texto comprimido con zlib
    procesado  TEXT
);

CREATE TABLE IF NOT EXISTS tablas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    url        TEXT NOT NULL,
    pagina     INTEGER,
    orden      INTEGER,
    contexto   TEXT,                         -- texto que precede a la tabla
    salarial   INTEGER NOT NULL DEFAULT 0,   -- 1 = probablemente una tabla salarial
    puntuacion REAL,
    filas      TEXT NOT NULL                 -- JSON: lista de filas, cada una lista de celdas
);
CREATE INDEX IF NOT EXISTS ix_tablas_url ON tablas(url);

CREATE TABLE IF NOT EXISTS boe_disposiciones (
    identificador TEXT PRIMARY KEY,          -- p. ej. BOE-A-2026-20971
    fecha         TEXT,
    departamento  TEXT,
    epigrafe      TEXT,
    titulo        TEXT,
    url_html      TEXT,
    url_pdf       TEXT,
    url_xml       TEXT,
    vista         TEXT
);

CREATE TABLE IF NOT EXISTS ejecuciones (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio  TEXT,
    fin     TEXT,
    desde   TEXT,
    hasta   TEXT,
    resumen TEXT                             -- JSON
);
"""


def _migrar(con):
    """Añade columnas nuevas a bases de datos creadas con una versión anterior."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(tramites)")}
    if "sin_ficha" not in cols:
        con.execute("ALTER TABLE tramites ADD COLUMN sin_ficha INTEGER NOT NULL DEFAULT 0")


def conectar(ruta=None):
    ruta = ruta or config.BASE_DATOS
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(ruta), timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(ESQUEMA)
    _migrar(con)
    return con


def ahora():
    return dt.datetime.now().isoformat(timespec="seconds")
