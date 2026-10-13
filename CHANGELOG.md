# Cambios

## 1.1.1 — 2026-10-13

Correcciones tras la revisión del código de la versión 1.1.0.

### Corregido

- **Redirecciones y robots.txt**: las redirecciones ya no se siguen sin comprobarlas. Cada salto (hasta 5) se comprueba con `robots.txt`; antes, una dirección permitida que redirigía a una ruta prohibida se descargaba igualmente.
- **Días que no se completan**: un día con error o con listado incompleto de REGCON se guarda en `dias_pendientes` y se vuelve a consultar en cada sincronización. Tras 5 intentos fallidos se abandona, con aviso en el registro. Antes, un día así dejaba la sincronización como «atención» y hacía crecer la ventana hasta 365 días en cada ejecución.
- **Fallos del BOE**: un día del sumario del BOE que falla impide marcar la sincronización como correcta y se reintenta. Antes se perdía sin aviso.
- **Búsqueda**: los caracteres `%` y `_` se buscan como texto (antes actuaban como comodines).
- **XML del BOE**: el analizador no resuelve entidades externas ni accede a la red (solo se usa con `CONVENIOS_ROBOTS=ignorar`).
- **Panel**: sin `--produccion`, `web` ya no atiende a otras direcciones distintas de `127.0.0.1`.
- **Documentación**: se corrigen los README de `despliegue/` que decían que los ficheros estaban pendientes de subir.

### Pruebas

- 80 pruebas (eran 67), en `tests/test_correcciones.py` y en `tests/test_convenios.py`. Cobertura medida: 74 %.

## 1.1.0 — 2026-10-09

Versión preparada para producción. Guía de despliegue en [PRODUCCION.md](PRODUCCION.md).

### Añadido

- **Panel de producción**: `web --produccion` usa waitress y exige usuario y contraseña (`usuario`). Sin usuario, el modo de producción no arranca salvo que se indique `--sin-autenticacion`.
- **Protección del panel**: lista de nombres de host (`CONVENIOS_HOSTS_PERMITIDOS`), control de la cabecera `Origin` en los formularios (frente a CSRF), cabeceras de seguridad y páginas de error sin detalles internos.
- **Estado de salud**: ruta `/salud` (JSON; 503 solo si el estado es `error`) y `estado --comprobar` (código de salida 0, 2 o 1).
- **Copias de seguridad**: `copia` usa la API de copia de SQLite, comprueba la integridad y conserva las últimas `CONVENIOS_COPIAS_CONSERVAR`.
- **Robots.txt**: se respeta por defecto (`CONVENIOS_ROBOTS=respetar`). Nuevos estados de publicación: `bloqueada` (prohibida) y pendiente (no se pudo leer `robots.txt`; se reintenta). Comando `depurar-robots` para listar y, con `--aplicar`, borrar los textos prohibidos (con copia previa).
- **Registros técnicos** con rotación en `datos/registros/`.
- **Códigos de salida de `sync`**: 0 correcto, 2 con avisos o errores, 3 si ya hay otra sincronización, 130 si se interrumpe.
- **Aviso de tablas con muchas celdas vacías** (más de la mitad) en la ficha del convenio.
- **Comandos** `usuario`, `copia`, `depurar-robots` y `--version`.
- **Despliegue**: servicios y temporizadores de systemd (`despliegue/linux/`), script de tareas para Windows (`despliegue/windows/`, no ejecutado en Windows; con ajustes de batería, comprobación de dependencias y `-CopiasAConservar`), ejemplo de Caddy, flujo de integración continua (`.github/workflows/ci.yml`) y `requirements-lock.txt`.
- **Pruebas**: 67 pruebas (eran 20), con cobertura del 63 % (era del 46 %). Nuevos módulos de prueba: `tests/test_produccion.py`.

### Cambiado

- **BOE**: los textos se leen del PDF del BOE, que está permitido, en lugar de su XML, que `robots.txt` prohíbe. Con `CONVENIOS_ROBOTS=ignorar` se usa de nuevo el XML.
- **TLS heredado**: la verificación del certificado solo se omite para los servidores de `CONVENIOS_TLS_HEREDADO` (por defecto, `portaldogc.gencat.cat` y `bop.dipucr.es`). Antes se aplicaba a cualquier servidor que fallara la verificación.
- **Ritmo de peticiones**: pausa de 0,5 s entre consultas a REGCON (antes, 0,2 s) y como máximo 2 peticiones simultáneas a cada servidor de publicaciones.
- **Dependencias**: se añaden `protego` (robots.txt) y `waitress` (servidor de producción).
- **Configuración** por variables de entorno (ver README, sección «Configuración»).
- **Extracción de texto**: se eliminan los caracteres de control de la categoría Cc (salvo tabulador, salto de línea, retorno de carro y salto de página), también en celdas y contextos de las tablas.
- **Documentación**: README reescrito; se documentan las opciones que faltaban (`--carpeta`, `--puerto`, `--host`) y se elimina la mención al entorno virtual dentro del texto de los comandos.

### Corregido

- **Enlaces con el visor de Chrome** (`https://chrome-extension://…/https://…`): se extrae la URL real de la publicación. En la reparación de datos se releyeron 15 fichas: se recuperó el texto de 1 convenio; las 14 publicaciones restantes son de la Diputación de Cuenca, que responde 403 a las descargas automáticas.
- **Páginas de PDF que fallan al buscar tablas**: se cuentan y se registran (antes se descartaban sin rastro).
- **Bloqueo de sincronización**: una segunda ejecución sale con código 3 y no toca la base de datos.
- **Formularios del seguimiento**: rechazan peticiones de otros orígenes (403).

### Datos

Reparación puntual de la base de datos existente, con copia previa:

- 15 trámites con enlace de visor: fichas releídas; sus documentos con error se eliminaron y se volvieron a procesar.
- 276 textos y 40 tablas con caracteres de control: limpiados.
- Resultado: 2.870 convenios (+1 por la sincronización de hoy), 568 con tablas salariales.

### Pendiente

- Decisión sobre los 848 textos guardados de direcciones que `robots.txt` prohíbe (`depurar-robots --aplicar`).
- Decisión sobre el fallback TLS (lista actual de dos servidores).
- Mejora del detector de tablas salariales (medir con una muestra etiquetada).
- Licencia del proyecto.

## 1.0.0

Primera versión: búsqueda de convenios en REGCON y BOE, fichas, textos, tablas salariales, panel web local con seguimiento y exportación a CSV, y sincronización por días con reintentos.
