# Auditoría del programa de convenios

Fecha: 9 de octubre de 2026.
Objeto: el programa tal como está tras la revisión de hoy (`convenios` 1.0.0), su base de datos (`datos/convenios.db`), el panel web y la documentación.
Las comprobaciones están en la carpeta `auditoria/` y se pueden repetir (sección 9).

## 1. Conclusión

El programa funciona y los datos son fiables en lo que se ha podido comprobar contra la fuente: 10 de 10 fichas coinciden exactamente con REGCON, y prácticamente todos los importes de las tablas aparecen en el documento original (100 % en HTML y 99,99 % en PDF). No hay inyección SQL ni XSS, las dependencias no tienen vulnerabilidades conocidas y la instalación limpia funciona.

Sin embargo, hay **dos riesgos altos** que requieren una decisión tuya:

1. **Incumplimiento de `robots.txt`.** El programa no consulta `robots.txt` y el 45 % de los documentos válidos proceden de direcciones que el servidor prohíbe a agentes automáticos. Incluye los 304 textos del BOE, que se obtienen de una ruta que el BOE prohíbe expresamente.
2. **El detector de tablas salariales pierde tablas.** Las que marca son fiables (19 de 20 revisadas), pero de las tablas no marcadas que tienen señales salariales, la mayoría parece salarial. Estimación: entre 148 y 284 tablas salariales sin marcar en el grupo analizado (intervalo del 95 %, muestra pequeña).

Además hay defectos corregibles sin decisión (enlaces mal formados que dejan 13 convenios sin texto, errores silenciados, concurrencia alta sobre un mismo servidor, cabeceras y protección CSRF del panel, cobertura de pruebas del 46 %).

**Veredicto:** apto para el uso personal descrito en el README. No recomiendo publicar ni redistribuir los datos hasta resolver el riesgo A1.

## 2. Alcance, método y límites

**Comprobado:**

- Integridad y coherencia de la base de datos (referencias, totales, fechas, duplicados, identificadores).
- Exactitud frente a la fuente: fichas de REGCON pedidas en vivo y tablas comparadas con el documento original.
- Seguridad: escape HTML del panel con cargas maliciosas en una base temporal, inyección SQL, cabeceras HTTP, aceptación de `Host` ajeno, CSRF, dependencias (`pip-audit`), usos peligrosos del código.
- Cumplimiento: `robots.txt` de los 68 servidores a los que se piden documentos, y TLS sin verificación.
- Operación: instalación en entorno limpio, arranque desde cero, dos sincronizaciones simultáneas de verdad, interrupción con Ctrl+C, tiempos del panel.
- Código: `pyflakes`, `vermin` (versión mínima de Python), `vulture` (código muerto), `coverage` (cobertura de pruebas), búsqueda de manejo de errores.
- Documentación frente al código: banderas de la CLI, requisitos, instrucciones de Windows.

**Límites:**

- La sandbox es Linux con Python 3.13. No se ha probado en Windows, en macOS ni en Python 3.10.
- Desde la sandbox no responden varios servidores autonómicos y provinciales (sección 4, I1). Desde tu PC el resultado podría ser distinto.
- Las estimaciones de exhaustividad de tablas se basan en muestras pequeñas (18 casos); se dan con intervalo de confianza.
- El análisis de `robots.txt` aplica el estándar RFC 9309 con la biblioteca `protego`. No es un dictamen jurídico: el `robots.txt` es una política técnica del servidor, y cómo se aplica la reutilización de información pública en tu caso requiere asesoramiento específico.

**Incidencias del propio proceso de auditoría** (para que conste):

- Una primera prueba de Ctrl+C no fue válida: los procesos lanzados en segundo plano heredan la señal SIGINT ignorada. Se repitió en primer plano y el resultado es el de la sección 5.
- Tres peticiones de prueba a enlaces internos de boletines (dipuleon, dipucuenca) se hicieron antes de consultar su `robots.txt`. Después se comprobó que las tres rutas estaban permitidas.
- Una prueba de CSRF creó un término en el seguimiento real; se borró y el seguimiento vuelve a estar vacío.
- Las cargas de prueba de sincronización se hicieron en una carpeta temporal (`/tmp/aud_fresh`), no en `datos/`.

## 3. Resumen de hallazgos

| ID | Gravedad | Área | Hallazgo | Estado |
|---|---|---|---|---|
| A1 | Alta | Cumplimiento | Se descargan documentos prohibidos por el `robots.txt`, incluido el BOE vía `xml.php` | Decisión tuya |
| A2 | Alta | Calidad | El detector de tablas salariales no marca un número relevante de tablas salariales | Medir y mejorar |
| M1 | Media | Datos | 15 enlaces con prefijo de visor de Chrome; 13 convenios se quedan sin texto por ello | Corregible |
| M2 | Media | Robustez | Las páginas con error al buscar tablas se descartan sin registro | Corregible |
| M3 | Media | Cortesía | Hasta 8 peticiones simultáneas al mismo servidor al final de una carga | Corregible |
| M4 | Media | Seguridad | Descarga sin verificar el certificado de 2 servidores (45 documentos) | Decisión tuya |
| M5 | Media | Seguridad panel | CSRF en el seguimiento, acepta cualquier `Host`, sin cabeceras de seguridad | Corregible |
| M6 | Media | Pruebas | Cobertura de las pruebas automáticas del 46 %; `sync.py` 30 %, `boe.py` 15 % | Corregible |
| M7 | Media | Calidad | 64 tablas con más del 70 % de celdas vacías (55 salariales) | Corregible |
| B1 | Baja | Texto | Caracteres de control en 19 documentos (más del 1 % de su texto) | Corregible |
| B2 | Baja | Cobertura | Altas tardías: 4 de 38 trámites de un día no estaban en la base de datos | Operativo |
| B3 | Baja | Documentación | Banderas no documentadas; Python 3.10 sin probar; `(.venv)` en el texto | Corregible |
| B4 | Baja | Reproducibilidad | Dependencias sin límite superior y sin archivo de versiones fijas | Opcional |
| B5 | Baja | Operación | Sin copia de seguridad automática y sin licencia | Decisión tuya |
| I1 | Info | Entorno | 347 errores por tiempo de espera, concentrados en cuatro servidores | Verificar desde tu PC |

## 4. Hallazgos en detalle

### A1. Descargas prohibidas por `robots.txt` (alta)

**Qué pasa.** El programa no lee `robots.txt` en ningún punto (ninguna referencia en el código). Pide cada publicación sin comprobar si el servidor la permite a agentes automáticos.

**Evidencia.** Con `auditoria/comprobar_robots.py`:

- Publicaciones pedidas: 2.337 (en 68 servidores). De ellas, 885 están prohibidas para agentes genéricos (`*`). Entre los documentos válidos (1.819), 820 proceden de direcciones prohibidas (45 %).
- BOE: el `robots.txt` contiene `Disallow: /diario_boe/xml.php?` para `*`. El programa obtiene el texto de los 304 convenios del BOE por esa ruta. Su PDF oficial (`/boe/dias/.../pdfs/...`) sí está permitido.
- Otros servidores con todas o casi todas sus direcciones prohibidas: bizkaia.eus (102 de 102; prohíbe `*lehendakaritza/Bao_bob/*`), caib.es (56 de 56; prohíbe `/eboibfront`), bop.dacoruna.gal (49 de 49), bopmalaga.es (48 de 48; `edicto.php`), dip-alicante.es (48 de 48), diphuelva.es (42 de 42), dogc.gencat.cat (28 de 28), larioja.org (25 de 25), bop.diputoledo.es (20 de 20).
- Para 479 direcciones no se pudo leer el `robots.txt` del servidor. No se han contado como prohibidas, así que la cifra real puede ser mayor.

**Impacto si se respeta la regla.** Los convenios con texto válido son 1.529. Si se respetara el `robots.txt`:

- 641 convenios (42 %) quedarían sin ninguna fuente permitida.
- 439 si el BOE se obtuviera por su PDF, que sí está permitido.

**Recomendación.**

1. Cambiar el BOE a su PDF, que está permitido. Requiere reprocesar 304 documentos y comparar la calidad de las tablas con una muestra (ya se ha verificado que los importes del XML aparecen en el PDF: 60 de 60 en tres documentos).
2. Incorporar la comprobación de `robots.txt` al programa, con caché por servidor. Las direcciones prohibidas se marcan como «bloqueadas por robots.txt» en lugar de pedirse.
3. Para los boletines que quieras seguir usando, pedir permiso o usar un canal oficial de datos.

### A2. El detector de tablas salariales pierde tablas (alta)

**Precisión (fiable).** De 20 tablas marcadas como salariales que he revisado a ojo, 19 lo son claramente. La vigésima es un complemento salarial ambiguo.

**Exhaustividad (insuficiente).** Revisé dos muestras de tablas no marcadas. La primera son 10 tablas con cabecera salarial e importes, un grupo de 302. De ellas, 8 parecen salariales reales («TABLA SALARIAL AÑO 2026», «Salario base (€)», «SALARIO AÑO», «Trienio»). Con 8 de 10, la estimación es del 80 % (IC 95 %: 49 %–94 %), es decir, entre 148 y 284 tablas salariales sin marcar en ese grupo. La segunda son 8 tablas con contexto salarial (110 en total), y 5 parecen salariales. Son cifras orientativas: los grupos no cubren todas las tablas no marcadas.

**Impacto.** 65 convenios sin marca salarial tienen una tabla con cabecera salarial e importes.

**Causas probables** (observadas, no todas verificadas en todos los casos):

- La detección de PyMuPDF por defecto encuentra solo tablas con líneas de cuadrícula. En el PDF de la muestra del BOCM, la detección por defecto encontró 5 tablas y la basada en texto, 13.
- Importes de tres decimales («5.309,047») que la expresión regular no reconoce.
- Tablas fragmentadas en dos o tres filas, que la regla no puntúa.
- La regla de «proporción numérica» penaliza las tablas con columnas de texto (nombres de puesto).

**Recomendación.** Antes de cambiar nada, etiquetar a mano una muestra de 100 a 200 tablas para medir la precisión y la exhaustividad. Después: una segunda pasada con detección por texto, reglas por cabecera, reconocimiento de tres decimales y unión de fragmentos.

### M1. Enlaces con prefijo de visor de Chrome (media)

**Qué pasa.** En 15 trámites, la URL de la publicación llega envuelta en el visor de PDF de Adobe: `https://chrome-extension://efaidnb…/https://bop.dipuleon.es/…`. El programa la guarda tal cual y la descarga falla siempre.

**Impacto.** Estos 15 trámites corresponden a 13 convenios que no tienen ningún otro texto válido, así que quedan sin texto por un error evitable.

**Verificación.** El enlace interno de dipuleon devuelve un PDF (HTTP 200). Los dos de dipucuenca devuelven 403 a nuestro agente, así que quizá no se recuperen todos.

**Recomendación.** Desenvolver la URL interna en `parse_ficha` y validar que el resultado sea `http` o `https`.

### M2. Errores silenciados al buscar tablas (media)

**Qué pasa.** En `documentos._tablas_pdf`, una excepción de `find_tables()` hace `continue` sin registro. La página se descarta y nadie se entera.

**Evidencia.** En el documento de prueba (BOCM-20260515-1.PDF) no hubo fallos. No se conoce el alcance en el conjunto de datos porque no se registra.

**Recomendación.** Contar las páginas omitidas por documento y guardar el número en la base de datos o en el registro.

### M3. Concurrencia alta sobre un mismo servidor (media)

**Qué pasa.** El programa usa 8 hilos para las publicaciones. El reparto por servidor intercala las URL, pero al final de una carga solo quedan las de un servidor grande y los 8 hilos van a ese servidor a la vez.

**Evidencia.** Simulando el orden real de descarga de 2.337 URL: en 181 ventanas de 8 peticiones consecutivas, las 8 van al mismo servidor; en el peor caso, a `www.boe.es`. Es una simulación aproximada, porque el tiempo real de cada petición varía.

**Recomendación.** Límite por servidor de 1 o 2 peticiones simultáneas y una pausa mínima entre ellas. Para REGCON (3 hilos, pausa de 0,2 s) conviene una pausa de 0,5 s o más.

### M4. Descarga sin verificar el certificado (media)

**Qué pasa.** Para servidores que solo aceptan cifrados antiguos, el programa desactiva la verificación del certificado (`verify=False`, `CERT_NONE`).

**Evidencia.** 45 documentos: `portaldogc.gencat.cat` (28) y `bop.dipucr.es` (17), marcados como `tls-heredado`.

**Impacto.** Un intermediario podría alterar el texto guardado sin que nadie lo note. El README lo advierte, pero no hay forma de comprobar esos textos.

**Recomendación.** Limitar el fallback a una lista de servidores conocidos, o eliminarlo si no es imprescindible. Si se mantiene, mostrar el aviso en el panel junto al documento.

### M5. Seguridad del panel (media, bajo en la práctica)

El panel es local, y los datos de REGCON y del BOE son públicos. Aun así:

- **CSRF confirmado.** Una petición POST desde otro origen (`Origin: https://evil.example`) a `/seguimiento/nuevo` fue aceptada (302) y creó un término. Un sitio malicioso podría añadir o borrar tus términos de seguimiento, que son tus preferencias.
- **Host ajeno aceptado.** Con `Host: evil.example` el panel responde 200. Esto permite ataques de *DNS rebinding* contra el panel que esté en marcha.
- **Sin cabeceras de seguridad.** No hay `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options` ni `Referrer-Policy`.
- **Versión expuesta.** La cabecera `Server` muestra `Werkzeug/3.1.9 Python/3.13.16`.

**Recomendación.** Validar `Origin` en los POST, comprobar `Host` contra `localhost` y `127.0.0.1`, añadir las cabeceras básicas y quitar la versión del servidor.

### M6. Cobertura de las pruebas automáticas (media)

**Evidencia** (`coverage`, 20 pruebas):

- Total: 46 %.
- `sync.py`: 30 %. Es el orquestador de la carga y el que recupera los errores.
- `boe.py`: 15 %. Parseo del sumario y del XML del BOE.
- `__main__.py`: 38 %.
- `web.py`: 57 %. `documentos.py`: 53 %. `regcon.py`: 50 %.

**Recomendación.** Pruebas de `boe.py` con XML de muestra guardado, de `sync.py` con dobles de prueba, y del parser de REGCON con HTML real guardado como fixture.

### M7. Tablas con celdas vacías (media)

64 tablas de 5.029 tienen más del 70 % de sus celdas vacías. De ellas, 5 son salariales. Entre las 1.800 salariales, 55 (un 3 %) superan el 50 % de celdas vacías. Suelen ser extracciones incompletas de PDF.

**Recomendación.** Marcar esas tablas en el panel como «extracción incompleta» y no contarlas como salariales si superan el 70 % de celdas vacías.

### B1. Caracteres de control en el texto (baja)

Hay 123.811 caracteres de control de 124 millones (0,099 % del texto). Solo 19 documentos superan el 1 % y 7 superan el 10 %. Son fuentes de PDF con codificación rota. El texto de esos documentos es poco legible.

**Recomendación.** Eliminar los caracteres de control y marcar el documento como «texto parcial».

### B2. Altas tardías (baja)

El 22 de diciembre de 2025, REGCON devuelve hoy 38 trámites para la búsqueda de ese día. Cuatro no estaban en la base de datos. No he identificado la causa. En una muestra aleatoria de 6 días (99 trámites) no faltó ninguno.

**Recomendación.** Repetir cada mes una sincronización de los últimos 60 días: `python -m convenios sync --desde <fecha de hace 60 días>`.

### B3. Documentación (baja)

- `--carpeta` (en `exportar`) y `--puerto` (en `web`) no aparecen en el README.
- El README exige Python 3.10 o superior. Es coherente con PyMuPDF (requiere 3.10 o superior en la versión instalada), pero no está probado en 3.10.
- La línea 46 del README menciona `(.venv)` en texto explicativo, no en un comando. No lo cuento como incumplimiento, pero conviene quitarlo para evitar confusiones.

### B4. Reproducibilidad (baja)

`requirements.txt` fija mínimos, sin máximos ni archivo de versiones bloqueadas. Una instalación limpia en un entorno nuevo funcionó y las pruebas pasaron, así que hoy no hay un problema real. Un `pip freeze` de referencia evitaría sorpresas futuras.

### B5. Copia de seguridad y licencia (baja)

No hay copia de seguridad automática de `datos/convenios.db`, que es la única copia de los datos recogidos (las fuentes pueden cambiar o desaparecer). El proyecto no tiene archivo de licencia. Es una decisión tuya.

### I1. Errores de servidores (informativo)

De los 505 errores de publicaciones:

| Causa | Casos |
|---|---|
| Tiempo de espera | 347 |
| HTTP 403 (prohibido) | 74 |
| Página de bloqueo (BORM, captcha) | 37 |
| HTTP 5xx | 21 |
| Enlace mal formado (M1) | 15 |
| Conexión cortada | 11 |

Los tiempos de espera se concentran en bon.navarra.es (79), bop.dpz.es (67), miprincipado.asturias.es (65) y boc.cantabria.es (44): 255 de los 347. Son errores de conexión desde esta sandbox. Desde tu PC podrían funcionar: conviene comprobarlo.

**Corrección a mi informe anterior:** boc.cantabria.es no da errores de TLS, sino de tiempo de espera. Lo corrijo en `REVISION.md`.

## 5. Verificado sin incidencias

- **Exactitud frente a la fuente.** 10 de 10 fichas coinciden con REGCON en código, denominación, estado, número de expediente, fecha de publicación y enlace.
- **Fidelidad de las tablas.** El 100 % de los importes de las tablas HTML (9.753) y el 99,99 % de los de PDF (42.166 de 42.171) aparecen en el documento original. En el BOE, 60 de 60 importes de tres disposiciones aparecen en su PDF oficial.
- **Integridad relacional.** 0 registros huérfanos, 0 incoherencias en los totales por convenio, en las marcas de tablas salariales y en las URL de última publicación. Los 22 grupos de posibles duplicados son expedientes distintos. Los 1.773 identificadores sintéticos son únicos.
- **Escape HTML.** Ninguna página HTML del panel devuelve etiquetas sin escapar. Se probaron ocho vistas con cargas maliciosas en todos los campos que vienen de webs externas. JSON y CSV no son HTML.
- **Inyección SQL.** Las consultas usan parámetros. Las únicas partes que se interpolan son condiciones fijas. Las pruebas con cargas de inyección no provocaron errores 500.
- **Dependencias.** `pip-audit` no encuentra vulnerabilidades conocidas en `requirements.txt`.
- **Instalación limpia.** En un entorno virtual nuevo, con `pip install -r requirements.txt`, las 20 pruebas pasan.
- **Arranque desde cero.** Una sincronización de un día en una carpeta de datos vacía termina bien: 16 trámites, 15 fichas, 12 publicaciones y `ok: true`.
- **Bloqueo entre procesos.** Con una sincronización en marcha, una segunda sale con código 1 y el mensaje «Ya hay una sincronización en marcha».
- **Ctrl+C.** Con la señal enviada en primer plano, el programa muestra «Interrumpido», la base de datos queda íntegra, la ejecución se registra como no correcta y la siguiente sincronización funciona.
- **Rendimiento del panel.** Entre 2 y 32 ms por página con 2.869 convenios.
- **Mi BOE.** No hay código de inicio de sesión, ni contraseñas, ni reCAPTCHA (búsqueda sin coincidencias).
- **Código.** Sin `except` desnudos. `pyflakes` sin avisos. `vulture` no encuentra código muerto real (sus avisos son las rutas de Flask, que se registran con decoradores). `vermin`: el código no requiere más de Python 3.7.
- **Instrucciones de Windows.** El bloque de PowerShell del README no contiene `source` ni prompts.

## 6. Correcciones a `REVISION.md`

1. **Sección 5:** boc.cantabria.es no tiene errores SSL, sino de tiempo de espera. bopmalaga.es (48 errores) responde 403 en rutas que su `robots.txt` prohíbe; no es «inaccesible».
2. **Sección 6:** «no se usan funciones de 3.11 o posteriores» queda confirmado con `vermin` (mínimo detectado: 3.7). La ejecución en 3.10 sigue sin probarse.
3. **Sección 6:** la muestra de tablas midió la precisión (fiable), pero no la exhaustividad. Eso es A2.
4. **No recogido en la revisión:** A1 (robots.txt), M1 (enlaces con prefijo), M3 (concurrencia), M5 (CSRF y cabeceras), M6 (cobertura real de las pruebas) y M7 (tablas vacías).

## 7. Decisiones que necesito de ti

1. **A1 (robots.txt).** ¿Respetamos `robots.txt` por defecto? Recomiendo sí, con dos pasos: pasar el BOE a su PDF y que el programa marque como bloqueadas las direcciones prohibidas. El efecto es menor cobertura (entre 439 y 641 convenios sin texto, según el BOE) hasta conseguir permisos o fuentes alternativas.
2. **M4 (TLS sin verificar).** ¿Mantenemos el fallback para los dos servidores, con aviso, o lo quitamos? Recomiendo limitarlo a una lista de servidores o quitarlo si los 45 documentos no son imprescindibles.
3. **A2 (tablas).** ¿Te parece bien etiquetar a mano una muestra de 100 a 200 tablas antes de cambiar el detector? Recomiendo hacerlo primero para medir y no cambiar a ciegas.
4. **B5 (copia de seguridad y licencia).** ¿Quieres una copia automática de la base de datos y una licencia para el proyecto?

## 8. Plan de acción propuesto

**Inmediato, sin decisiones previas:**

- M1: desenvolver los enlaces con prefijo de visor (13 convenios recuperables).
- M3: límite de peticiones por servidor y pausa para REGCON.
- M5: validación de `Origin` y `Host`, cabeceras de seguridad y quitar la versión del servidor.
- M2: registrar las páginas omitidas al buscar tablas.
- B3: documentar `--carpeta` y `--puerto`, quitar `(.venv)` del texto.

**Tras tus decisiones:**

- A1: BOE por PDF y comprobación de `robots.txt` en el programa (con caché).
- M4: limitar o quitar el fallback TLS.
- B5: copia automática y licencia, si las quieres.

**Medio plazo:**

- A2: muestra etiquetada, después la mejora del detector y medir de nuevo.
- M6: pruebas de `boe.py` y `sync.py`.
- M7 y B1: marcas de extracción incompleta y limpieza de caracteres de control.
- B4: archivo de versiones fijas.

## 9. Cómo repetir la auditoría

Desde la carpeta del proyecto (los comandos valen igual en PowerShell y en macOS/Linux):

```
pip install protego
python auditoria/comprobar_robots.py
python auditoria/prueba_seguridad_panel.py
python auditoria/comprobar_tablas.py
python -m unittest discover -s tests -v
```

`comprobar_robots.py` solo lee los `robots.txt`; no descarga documentos. `prueba_seguridad_panel.py` usa una base temporal. `comprobar_tablas.py` solo lee la base de datos. Ninguno modifica `datos/convenios.db`.


## 10. Estado de los hallazgos en la versión 1.1.0

Las secciones 1 a 9 describen la versión 1.0.0 tal como se auditó y no se han modificado. Esta sección recoge lo que se ha hecho después (2026-10-09). Cambios detallados en [CHANGELOG.md](CHANGELOG.md).

| ID | Estado | Qué se ha hecho | Qué queda |
|---|---|---|---|
| A1 | Parcial | Política por defecto `CONVENIOS_ROBOTS=respetar`. El BOE se lee de su PDF. Las direcciones prohibidas quedan como «bloqueada». Si `robots.txt` no se puede leer, la publicación queda pendiente. Comando `depurar-robots`. | Decidir si se borran los 848 textos ya guardados de direcciones prohibidas (304 del XML del BOE y 544 de otros 17 servidores). Con el BOE recuperado de su PDF, 461 de 1.530 convenios con texto perderían su texto; sin esa recuperación, 663. |
| A2 | Abierto | Sin cambios en el detector. | Etiquetar una muestra de 100 a 200 tablas para medir la sensibilidad con su intervalo de confianza. Solo después, cambiar el detector. |
| M1 | Corregido | Se extrae la URL real del visor de Chrome. Se releyeron 15 fichas y 1 convenio recuperó su texto. | Las otras 14 publicaciones (Diputación de Cuenca) responden 403 al programa (ver I1). |
| M2 | Corregido | Las páginas que no se pueden analizar al buscar tablas se cuentan y se registran. | — |
| M3 | Corregido | Como máximo 2 peticiones simultáneas por servidor, reparto intercalado entre servidores y pausa de 0,5 s en REGCON. | — |
| M4 | Parcial | La verificación del certificado solo se omite para los servidores de `CONVENIOS_TLS_HEREDADO` (por defecto, 2) y solo si falla la verificación normal. | Decidir si se mantiene el fallback o se elimina. |
| M5 | Corregido | Lista de nombres de host, control de `Origin` en los formularios, cabeceras de seguridad, sin versión del servidor en las cabeceras, usuario y contraseña en modo de producción. | Sin límite de intentos de acceso: se recomienda ponerlo en el proxy. |
| M6 | Corregido en lo esencial | 67 pruebas (eran 20). Cobertura total del 68 % (era del 46 %): `boe.py` 95 % (era 15 %), `sync.py` 52 % (era 30 %). | `regcon.py` tiene un 51 % de cobertura. Las llamadas a REGCON se prueban con respuestas simuladas, no contra el servidor. |
| M7 | Parcial | El panel avisa cuando más de la mitad de las celdas de una tabla están vacías. | La extracción de esas tablas no mejora todavía. |
| B1 | Corregido | Limpieza de caracteres de control en textos, celdas y contextos. Reparación de 276 textos y 40 tablas, con copia previa. | — |
| B2 | Operativo | Sin cambios de código. | Programar la sincronización diaria (carpeta `despliegue/`). |
| B3 | Corregido | README reescrito, con las opciones documentadas y sin el entorno virtual en el texto de los comandos. | — |
| B4 | Corregido | `requirements-lock.txt` con las versiones probadas, límites inferiores en `requirements.txt` y flujo de integración continua para Python 3.10 y 3.13. | El flujo no se ha ejecutado en GitHub desde este entorno, ni la prueba con Python 3.10. |
| B5 | Parcial | Copia por comando, con comprobación de integridad, y programada en `despliegue/`. | Licencia pendiente de elegir. |
| I1 | Abierto (externo) | Sin cambios de código. Los errores quedan registrados en la página «Estado». | Revisar desde tu equipo los servidores con error. La Diputación de Cuenca responde 403 a las descargas automáticas. |

**Verificación de la versión 1.1.0.** 67 pruebas pasan, también en un entorno limpio instalado desde `requirements.txt`. La prueba de escape HTML no encuentra etiquetas sin escapar. La fidelidad de las tablas no cambia (100 % de los importes en HTML y 99,99 % en PDF; `auditoria/comprobar_tablas.py`). Las unidades de systemd pasan `systemd-analyze verify`, con el intérprete de Python sustituido porque la ruta de producción no existe en el entorno de pruebas.
