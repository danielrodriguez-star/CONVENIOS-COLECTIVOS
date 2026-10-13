# Convenios colectivos de España: búsqueda y actualización

Programa que localiza y mantiene al día **todos los convenios colectivos de España** (estatales, autonómicos, provinciales y de empresa) a partir de fuentes oficiales, y los muestra en un panel web.

Por cada convenio guarda:

- **Ficha**: código REGCON, denominación, ámbito (autoridad laboral), estado, vigencia, expediente y todos sus trámites.
- **Texto** de la publicación oficial (BOE, boletín provincial o autonómico), comprimido en la base de datos.
- **Tablas salariales** detectadas automáticamente en la publicación.

Versión **1.1.2**. Novedades en [CHANGELOG.md](CHANGELOG.md). Para publicar el panel en un servidor con varios usuarios, ver [PRODUCCION.md](PRODUCCION.md).

La primera vez, empieza por [«Arranque paso a paso (primera vez)»](#arranque-paso-a-paso-primera-vez): **instalar el programa no lo arranca**.

## Fuentes

| Fuente | Qué aporta |
|---|---|
| **REGCON** (Registro de convenios colectivos, Ministerio de Trabajo y Economía Social) | Todos los trámites de convenios, con su ficha y el enlace a la publicación oficial |
| **BOE** (API de datos abiertos) | Convenios publicados cada día en la sección III, con su texto y sus tablas |
| **Boletines oficiales** (BOP, BOJA, DOGC, BOCYL…) | Texto y tablas de los convenios autonómicos y provinciales, a partir del enlace de REGCON |

## Requisitos

- Python 3.10 o superior (probado con Python 3.13).
- Conexión a Internet.

## Instalación

Abre una terminal **dentro de la carpeta del proyecto**, la que contiene `README.md` y `requirements.txt`. No entres en la carpeta interior `convenios` (es el código del programa).

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

- Si PowerShell bloquea la activación («la ejecución de scripts está deshabilitada en este sistema»), ejecuta una sola vez: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
- Si `python` no se reconoce, usa `py -3` en lugar de `python`.

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Para instalar exactamente las versiones con las que se ha probado el programa, cambia `requirements.txt` por `requirements-lock.txt` en el último comando.

A partir de aquí los comandos son iguales en Windows y en macOS/Linux. Ejecútalos siempre con el entorno virtual activado (la terminal muestra su nombre al principio de la línea).

**Aviso: instalar no es arrancar.** Al terminar la instalación solo tienes los archivos y las dependencias: el programa no se ha ejecutado ni una vez. No hay datos en la base de datos, y por eso el panel se ve vacío («0 convenios encontrados · última sincronización: todavía no se ha sincronizado»). No es un fallo ni una instalación incompleta: falta la carga inicial y el arranque, que son los pasos de la sección siguiente.

## Arranque paso a paso (primera vez)

Estos pasos se hacen **una sola vez**, y en este orden: cada uno necesita el anterior. Hasta que no llegues al 4, el panel no muestra ningún convenio.

**1. Abre la terminal con el entorno virtual activado.** Igual que en la instalación: la terminal, **dentro de la carpeta del proyecto** (la que contiene `README.md`), y con el entorno virtual activado (`.venv\Scripts\Activate.ps1` en Windows, `source .venv/bin/activate` en macOS o Linux).

**2. Comprueba que la instalación sirve.**

```
python -m convenios --version
```

Debe responder `convenios 1.1.2`. Si dice que no reconoce el módulo `convenios`, casi siempre es que el entorno virtual no está activado o que la terminal no está en la carpeta del proyecto.

**3. Carga los datos (solo la primera vez; tarda horas).**

```
python -m convenios sync --desde 2025-10-13 --hasta 2026-10-13
```

- Pon las fechas del periodo que quieras tener. Los 12 meses del ejemplo son lo recomendado; para ver el panel antes, empieza por tres meses.
- Necesita conexión a Internet y **ocupa la terminal mientras dura**: puedes minimizarla y seguir usando el equipo, pero no la cierres.
- Si se interrumpe, repite el mismo comando: lo ya guardado no se pierde y la carga continúa.
- Sale con código 0 si todo fue bien y con 2 si algún día quedó pendiente; los días pendientes se vuelven a consultar solos en la siguiente sincronización (ver «Códigos de salida»).
- Para una prueba rápida de minutos, sin descargar publicaciones: `python -m convenios sync --desde 2026-07-13 --hasta 2026-10-13 --sin-documentos --sin-boe` (solo REGCON, sin textos ni tablas). La carga completa sigue siendo necesaria después.

Al acabar, mira cuánto hay guardado:

```
python -m convenios estado
```

**4. Arranca el panel.**

```
python -m convenios web
```

- La terminal muestra `Running on http://127.0.0.1:8000` y **no devuelve el control**: mientras esa ventana siga abierta, el panel está en marcha.
- Abre <http://127.0.0.1:8000> en el navegador. **Deja la ventana de la terminal abierta**; si la cierras, el panel se detiene y esa dirección deja de responder.
- Para parar el panel, vuelve a esa terminal y pulsa Ctrl+C.
- Si el puerto 8000 ya está ocupado: `python -m convenios web --puerto 8001` y abre <http://127.0.0.1:8001>.
- El panel solo se ve desde este equipo. Verlo desde otros equipos o publicarlo en Internet está explicado en [PRODUCCION.md](PRODUCCION.md).

**5. Los días siguientes.**

| Situación | Qué hacer |
|---|---|
| Poner al día los datos | `python -m convenios sync` (sin fechas). Tarda minutos. Si unos días fallaron, se recuperan solos |
| Ver el panel | `python -m convenios web` otra vez, y dejar la terminal abierta. Después de reiniciar el equipo, hay que volver a arrancarlo |
| No tener que hacer nada a mano | Programar `sync` una vez al día: ver [«Actualización diaria»](#actualización-diaria) |
| Comprobar que todo va bien | `python -m convenios estado`, o la página «Estado» del panel |

## Uso

Lista completa de órdenes. Si es la primera vez, sigue antes [«Arranque paso a paso (primera vez)»](#arranque-paso-a-paso-primera-vez).

```
python -m convenios sync --desde 2025-10-13 --hasta 2026-10-13
python -m convenios sync
python -m convenios web
python -m convenios estado
python -m convenios exportar
python -m convenios copia
```

- `sync --desde … --hasta …`: carga inicial de 12 meses. Tarda horas, sobre todo por las publicaciones. Si se interrumpe, basta con repetirla: lo ya guardado no se pierde.
- `sync`: actualización desde la última ejecución completa, con 7 días de solape. Los días pendientes (ver `dias_pendientes`) se vuelven a consultar aparte.
- `web`: panel en http://127.0.0.1:8000. Se detiene con Ctrl+C.
- `estado`: resumen de la base de datos. Con `estado --comprobar` solo muestra si la instalación está bien (ver «Códigos de salida»).
- `exportar`: genera los CSV en `datos/exportaciones/`.
- `copia`: copia de seguridad fechada en `datos/copias/`.

Opciones de `sync`:

- `--sin-boe`: no consulta el sumario del BOE.
- `--sin-documentos`: solo actualiza REGCON (fichas y listados), sin descargar publicaciones.
- `--reintentar-errores`: vuelve a intentar las publicaciones que fallaron antes.

Para ver todas las opciones: `python -m convenios --help` y `python -m convenios web --help`.

## Panel web

- Por defecto solo es accesible desde este equipo (http://127.0.0.1:8000 o http://localhost:8000).
- Secciones: **Buscar** (por nombre, código o ámbito; solo convenios con tablas salariales), **ficha** de cada convenio (tablas salariales con su contexto y el enlace al original, otras tablas y todos sus trámites), **Texto** de cada publicación, **Seguimiento** (términos que sigues, con los trámites nuevos desde tu última visita), **BOE** (últimos convenios publicados), **Estado** (cifras, ejecuciones y errores) y **CSV**.
- `http://127.0.0.1:8000/salud` devuelve el estado de la instalación en formato JSON, para vigilarlo desde otra herramienta.
- Sin `--produccion`, el panel solo atiende a este equipo: otra dirección de `--host` (p. ej. `0.0.0.0`, para la red) se rechaza. Para verlo desde otros equipos, usa el modo de producción (`web --produccion --host 0.0.0.0`), que exige usuario y contraseña. Está descrito en [PRODUCCION.md](PRODUCCION.md).

## Actualización diaria

El programa no se ejecuta solo: hay que programar `sync` una vez al día. Si un día el equipo estuvo apagado, la siguiente sincronización recupera el periodo que falta.

**Windows (Programador de tareas, sin permisos de administrador):** crea una tarea diaria con:

- Programa: `C:\ruta\a\convenios\.venv\Scripts\python.exe`
- Argumentos: `-m convenios sync`
- Iniciar en: `C:\ruta\a\convenios`

Si creas la tarea a mano, en la pestaña «Condiciones» desmarca las opciones de batería, y en «Configuración» marca la opción de ejecutar lo antes posible cuando se pierde un inicio programado. Si no, en un portátil con batería la tarea no se ejecuta.

También puedes crear la actualización (07:30) y la copia de seguridad (08:00) con el script incluido. Admite `-HoraSincronizacion`, `-HoraCopia` y `-CopiasAConservar` (14 por defecto; cada copia ocupa unos 50 MB). El script no se ha ejecutado en Windows: se comprobó con PowerShell 7 en Linux, así que revisa las tareas después.

```powershell
powershell -ExecutionPolicy Bypass -File despliegue\windows\programar-tareas.ps1 -Carpeta "C:\ruta\a\convenios"
```

**macOS / Linux (cron):** para ejecutarlo todos los días a las 7:30 (`crontab -e`):

```
30 7 * * * cd /ruta/a/convenios && .venv/bin/python -m convenios sync >> datos/cron.log 2>&1
```

Si una sincronización ya está en marcha (la programada y otra lanzada a mano, por ejemplo), la segunda se detiene con un aviso y no modifica nada.

## Códigos de salida

| Código | Significado |
|---|---|
| 0 | Correcto |
| 2 | Terminó con días pendientes: un día con error o con listado incompleto de REGCON, o con error en el BOE. Cada día pendiente se vuelve a consultar en las ejecuciones siguientes; tras 5 intentos fallidos se abandona, queda registrado en `datos/sincronizacion.log` y se puede repetir con `sync --desde AAAA-MM-DD --hasta AAAA-MM-DD` |
| 3 | Ya hay otra sincronización en marcha. No se ha hecho nada |
| 130 | Interrumpida con Ctrl+C. Lo ya guardado se conserva |
| 1 | Error inesperado. Queda registrado en `datos/registros/` |

`estado --comprobar` usa otros códigos: 0 correcto, 2 atención (p. ej., hace más de 72 horas que no hay una sincronización correcta) y 1 error (base de datos ausente o dañada).

## Configuración

Las variables de entorno cambian el comportamiento. No hace falta definir ninguna para el uso normal.

| Variable | Por defecto | Para qué sirve |
|---|---|---|
| `CONVENIOS_DATOS` | `datos` dentro de la carpeta del proyecto | Carpeta de los datos |
| `CONVENIOS_ROBOTS` | `respetar` | `respetar`: no se piden direcciones que `robots.txt` prohíbe. `ignorar`: no recomendado |
| `CONVENIOS_TLS_HEREDADO` | `portaldogc.gencat.cat,bop.dipucr.es` | Servidores que solo aceptan cifrados antiguos; para ellos, y solo para ellos, se descarga sin verificar el certificado |
| `CONVENIOS_HOSTS_PERMITIDOS` | (vacío) | Nombres de host adicionales que acepta el panel. `localhost`, `127.0.0.1` y `::1` siempre se aceptan |
| `CONVENIOS_COPIAS_CONSERVAR` | `14` | Número de copias de seguridad que se conservan |
| `CONVENIOS_ALERTA_HORAS` | `72` | Horas sin sincronización correcta antes de que el estado pase a «atención» |
| `CONVENIOS_PERMITIR_IFRAME` | `no` | `si` permite mostrar el panel dentro de otra página (solo para vistas previas) |

Para cambiar una variable en Windows, por ejemplo: `setx CONVENIOS_DATOS "D:\convenios-datos"` (se aplica a las terminales y tareas que se abran después).

## Datos y ficheros

- `datos/convenios.db`: base de datos SQLite. Tablas principales:
  - `convenios`: un registro por convenio, con su resumen.
  - `tramites`: cada trámite de REGCON.
  - `documentos`: publicaciones oficiales (texto comprimido, estado y errores). Estados: `ok`, `sin_texto`, `error` y `bloqueada` (prohibida por `robots.txt`).
  - `tablas`: tablas extraídas de las publicaciones, con la marca de tabla salarial.
  - `boe_disposiciones`: convenios publicados en el BOE.
  - `dias_pendientes`: días de REGCON o del BOE que no se completaron, con sus intentos. Se vuelven a consultar hasta que van bien o se agotan los intentos.
  - `ejecuciones`: historial de sincronizaciones.
- `datos/seguimiento.db`: los términos que sigues en el panel. Está aparte para que el panel no compita con la sincronización.
- `datos/sincronizacion.log`: resumen de cada ejecución, en texto.
- `datos/registros/`: registros técnicos, uno por proceso (`sincronizacion.log` y `panel.log`), con rotación automática por tamaño.
- `datos/copias/`: copias de seguridad fechadas. Cada copia se comprueba antes de darla por buena.
- `datos/exportaciones/`: CSV generados con `exportar`.
- `datos/acceso.json`: usuario del panel y hash de su contraseña. Solo existe si creas un usuario (`python -m convenios usuario`).
- `datos/sincronizacion.lock`: marca de sincronización en curso. La gestiona el programa; no hace falta tocarla.

Para hacer copia a mano, basta con copiar la carpeta `datos` cuando no haya ninguna sincronización en marcha, o usar `python -m convenios copia`.

## Cómo funciona

1. **BOE**: consulta el sumario de cada día del periodo y guarda los convenios de la sección III.
2. **REGCON**: consulta los trámites de convenios día a día (por fecha de registro). REGCON cuenta filas duplicadas y pagina mal los resultados largos, así que cada día se parte por ámbito, estado, tipo de trámite o autoridad laboral hasta que cada consulta cabe en una página, y después se eliminan los duplicados.
3. **Fichas**: abre la ficha de cada trámite nuevo para obtener el estado, el expediente y el enlace a la publicación. Algunos trámites aparecen sin ficha (revisiones salariales, pronunciamientos judiciales, mediaciones, prórrogas): se guardan con los datos del listado, sin estado ni publicación.
4. **Robots.txt**: antes de pedir cada publicación, el programa lee el `robots.txt` de su servidor (ver la sección siguiente).
5. **Publicaciones**: descarga cada publicación permitida. Las del BOE se leen de su PDF; los boletines oficiales, en PDF o HTML.
6. **Tablas salariales**: se buscan tablas en páginas que mencionan salarios, retribuciones o tablas salariales y que contienen importes en formato español (1.234,56). Una tabla se marca como salarial si la mayoría de sus celdas son importes y su cabecera o el texto previo habla de salarios o retribuciones.
7. **Resumen por convenio**: se recalculan el estado, la vigencia y la presencia de tablas salariales a partir de sus trámites.

## robots.txt y TLS heredado

- **robots.txt.** El programa respeta las reglas de cada servidor para su agente. Si una regla prohíbe una dirección, no la pide y la marca como «bloqueada por robots.txt». Si el `robots.txt` no se puede leer en ese momento, la publicación queda pendiente y se reintenta en la siguiente sincronización. El BOE se lee de su PDF, que está permitido, y no de su XML, que está prohibido.
- **Textos ya guardados.** Antes de la versión 1.1.0 se guardaron textos de direcciones prohibidas. No se borran solos. `python -m convenios depurar-robots` los lista (con el número de textos por servidor). `python -m convenios depurar-robots --aplicar` los borra, pero antes hace una copia y recalcula los convenios. Borrarlos deja sin texto a algunos convenios; el detalle está en [PRODUCCION.md](PRODUCCION.md).
- **TLS heredado.** Algunos servidores solo aceptan cifrados antiguos. Para los servidores de `CONVENIOS_TLS_HEREDADO` (solo esos) el programa reintenta sin verificar el certificado, y el documento queda marcado como `tls-heredado`. El contenido sigue siendo público, pero en esos casos no hay garantía de autenticidad.

## Limitaciones

- **REGCON no tiene API.** El programa usa el mismo buscador que la web del registro. Si el Ministerio cambia el formulario, habrá que adaptar `convenios/regcon.py`.
- **Las tablas salariales se detectan con heurísticas.** Puede faltar alguna tabla o aparecer alguna que no sea salarial. Antes de usar una cifra, compárala con el documento original (el panel incluye el enlace). Un clasificador medido sobre una muestra pequeña tiene una sensibilidad incierta (ver AUDITORIA.md, hallazgo A2).
- **No hay OCR.** Los PDF escaneados aparecen como «sin texto».
- **Errores de descarga.** Algunos servidores bloquean las peticiones, no responden o devuelven errores (p. ej., la Diputación de Cuenca responde 403 a las descargas automáticas). Esas publicaciones quedan marcadas con error en la página «Estado». Se pueden reintentar con `--reintentar-errores`, aunque la mayoría de los errores son persistentes.
- **Páginas que necesitan JavaScript.** Algunos boletines cargan el texto con scripts y el programa no puede leerlo: esas publicaciones aparecen como «sin texto».
- **BORM (Murcia) bloquea las peticiones automáticas.** Sus publicaciones devuelven una página de comprobación anti-bot. El programa lo detecta y las marca con error «página de bloqueo». El enlace se puede abrir desde un navegador habitual.
- **Enlaces compartidos.** Algunos boletines provinciales dan un enlace a su página de índice, que usan muchos convenios a la vez. Las tablas de un enlace compartido se asignan a todos los convenios que lo usan, así que conviene revisar el original.
- **Tablas del BOE.** En el texto de una disposición del BOE, cada tabla aparece como «[tabla]». Sus importes se guardan como tablas, pero solo aparecen en la ficha del convenio cuando REGCON enlaza esa disposición.
- **Búsqueda de tablas en PDF largos.** En cada PDF se revisan, como máximo, las primeras 40 páginas que hablan de salarios. Un anexo salarial posterior puede no detectarse.
- **Revisiones salariales.** Son la mayoría de los trámites sin ficha. REGCON no ofrece enlace a su publicación, así que aparecen en el historial del convenio sin texto ni tablas propias.
- **Solo se guarda el texto.** Los PDF originales no se almacenan; el enlace lleva siempre al documento oficial.
- **Recuentos.** El total que muestra REGCON incluye filas repetidas, así que puede ser mayor que el número de trámites reales. El programa guarda solo los trámites únicos.
- **Mi BOE.** El programa no entra en tu cuenta de Mi BOE: el acceso requiere usuario, contraseña y reCAPTCHA. Los convenios del BOE se obtienen de la API de datos abiertos, que no necesita cuenta. Para seguir términos, usa la página «Seguimiento».
- **Cobertura.** La carga inicial se limita al periodo que indiques. Para completar un periodo más antiguo, basta con `sync` con `--desde` y `--hasta`.

## Seguridad del panel

- Solo atiende a los nombres de host de este equipo y a los que pongas en `CONVENIOS_HOSTS_PERMITIDOS` (protección frente a «DNS rebinding»).
- Los formularios solo se aceptan desde el propio panel (cabecera `Origin`; protección frente a CSRF).
- Cabeceras de seguridad en todas las respuestas: `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy` y `Cache-Control: no-store`.
- Las páginas de error no muestran detalles internos; el detalle queda en el registro.
- Con `web --produccion`, el panel exige usuario y contraseña (se guarda solo el hash).
- No hay límite de intentos de acceso ni HTTPS propio: para publicarlo en Internet, usa un proxy inverso con HTTPS (ver PRODUCCION.md).

## Pruebas

Para comprobar que todo funciona (no modifica tus datos: usa carpetas temporales y no hace peticiones a Internet):

```
python -m unittest discover -s tests -v
```

Hay 80 pruebas. Con cobertura: `python -m coverage run --source=convenios -m unittest discover -s tests` y después `python -m coverage report -m`.

## Licencia

El proyecto **todavía no tiene licencia**. Hasta que su autor elija una, no se concede permiso para reutilizar ni redistribuir el código.

## Fuentes y aviso legal

- REGCON: https://expinterweb.mites.gob.es/regcon/
- BOE, API de datos abiertos: https://www.boe.es/datosabiertos/
- Los datos son públicos y proceden de fuentes oficiales. Al reutilizarlos, cita la fuente y la fecha de consulta.
- Este programa no sustituye al texto oficial ni constituye asesoramiento jurídico.

## Estructura del proyecto

```
convenios/
├── README.md               # este documento
├── PRODUCCION.md           # puesta en producción, operación y seguridad
├── CHANGELOG.md            # cambios por versión
├── AUDITORIA.md            # auditoría de la versión 1.0.0 y estado de sus hallazgos
├── REVISION.md             # revisión de la versión 1.0.0
├── requirements.txt        # dependencias, con versiones mínimas
├── requirements-lock.txt   # versiones exactas con las que se ha probado
├── .github/workflows/ci.yml  # pruebas automáticas (GitHub Actions)
├── despliegue/
│   ├── linux/              # servicios y temporizadores de systemd, y ejemplo de configuración
│   └── windows/            # script para crear las tareas programadas (no ejecutado en Windows)
├── auditoria/              # comprobaciones de la auditoría (no modifican los datos)
├── convenios/
│   ├── __main__.py         # línea de comandos
│   ├── config.py           # rutas, direcciones, ritmo de las peticiones y ajustes de producción
│   ├── acceso.py           # usuario y contraseña del panel
│   ├── copias.py           # copias de seguridad comprobadas
│   ├── db.py               # esquema SQLite y migraciones
│   ├── documentos.py       # PDF, HTML y XML: texto y tablas salariales
│   ├── operacion.py        # estado de salud y depuración de textos prohibidos
│   ├── regcon.py           # buscador de REGCON, búsqueda completa por particiones y fichas
│   ├── registro.py         # registros técnicos con rotación
│   ├── robots.py           # comprobación de robots.txt
│   ├── boe.py              # sumario del BOE y XML de las disposiciones
│   ├── sync.py             # orquestación de la sincronización
│   ├── web.py              # panel web (Flask)
│   └── util.py             # utilidades HTTP, fechas y texto
├── tests/
│   ├── test_convenios.py   # pruebas de la base funcional
│   ├── test_produccion.py  # pruebas de robots, acceso, copias, estado, panel y CLI
│   └── test_correcciones.py  # días pendientes, redirecciones, búsqueda, XML del BOE y acceso desde la red
└── datos/                  # base de datos, registros, copias y exportaciones (se crea al ejecutar)
```
