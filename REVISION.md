# Revisión exhaustiva del programa de convenios

Fecha de la revisión: 9 de octubre de 2026.
Alcance: código (`convenios/`), pruebas (`tests/`), base de datos (`datos/convenios.db`), exportaciones, panel web, README y paquete para el PC.

## 1. Resumen

- Se revisaron los 11 módulos, la base de datos completa, las exportaciones, el panel y la documentación.
- Se encontraron **3 defectos de alta gravedad** que afectaban a los datos (texto mal codificado, fichas con estado contaminado y páginas de bloqueo guardadas como si fueran el convenio). Están corregidos y los datos afectados se han repetido.
- Se corrigieron además **5 defectos de gravedad media** y **5 de gravedad baja**.
- Quedan **4 decisiones** que cambian el comportamiento del programa y se dejan para el usuario (sección 4).
- Quedan **limitaciones externas** que no son defectos del código (sección 5).
- Tras las correcciones: 20 pruebas automáticas correctas, integridad de la base de datos correcta y sincronizaciones de comprobación terminadas sin errores de código (la última, con el código final).

## 2. Hallazgos corregidos

| # | Gravedad | Dónde | Problema | Efecto medido | Corrección |
|---|---|---|---|---|---|
| 1 | Alta | `regcon.parse_ficha` | El estado recogía todas las líneas en mayúsculas, también «EXPEDIENTE 82/01/0013/2026» y «TRAMITADO». | 75 trámites y 56 convenios con estado contaminado. | El estado se toma solo de las líneas en mayúsculas que siguen a los botones y se detiene en la primera línea en minúsculas. Se repitieron las 75 fichas. **Quedan 0.** |
| 2 | Alta | `documentos.procesar_html` | lxml adivinaba mal la codificación de bytes y convertía «ó» en «Ã³». | 151 documentos HTML con texto ilegible. | Decodificación propia: UTF-8 estricto, después el charset de la cabecera o de la etiqueta meta, y por último cp1252. Se repitieron los 151. **Quedan 0.** |
| 3 | Alta | `documentos.procesar_html` | Las páginas de bloqueo anti-bot (captcha de Radware) se guardaban como texto válido. | 38 documentos del BORM guardados como «ok» con el texto de la página de bloqueo (afectaban a unos 35 convenios). | Detección de captcha o bloqueo en páginas HTML cortas, que pasan a error «página de bloqueo». Tras repetir la descarga, 37 de esos documentos quedan con error y 1 se descarga como PDF real. |
| 4 | Media | `__main__.exportar` | La exportación de tablas salariales cruzaba con trámites y repetía filas cuando un convenio tenía varios trámites con la misma publicación. | 123 filas repetidas (0,5 %). | La consulta agrupa por convenio y publicación, y el orden pasa a ser `pagina, orden`. |
| 5 | Media | `sync.sincronizar` | Un día con listado incompleto (aviso) contaba como ejecución correcta, así que el día no se volvía a revisar cuando la ventana avanzaba. | No ocurrió en la carga real (0 avisos). | Un aviso impide marcar la ejecución como correcta. La ventana por defecto nunca pasa de 365 días, así que un día que no se completa no hace crecer las consultas sin límite. |
| 6 | Media | `regcon.listar` | Al no poder repartir un día, la paginación de respaldo pedía las páginas con la búsqueda equivocada: REGCON guarda una sola búsqueda por sesión. | No se activó en la carga real (0 avisos). Detectado con una prueba. | Se repite la búsqueda del nivel antes de paginar. |
| 7 | Media | `sync` | Dos sincronizaciones a la vez (la programada y una manual) podían solaparse. | Riesgo, no observado. | Bloqueo de archivo (`datos/sincronizacion.lock`). Se libera al terminar el proceso. Probado en Linux; **no probado en Windows**. |
| 8 | Media | `documentos.descargar` | La publicación se cargaba entera en memoria, sin límite de tamaño (2 GB de RAM en la sandbox). | No observado; 186 PDF tienen más de 40 páginas. | Lectura en trozos con límite de 100 MB (`DOC_MAX_BYTES`). Probado con una descarga real. |
| 9 | Baja | `util.celda_csv` | Un texto que empezara por `=`, `+`, `-` o `@` podía ejecutarse como fórmula al abrir el CSV en Excel. | Ninguna celda afectada hoy. | Se antepone una comilla simple en los textos de riesgo, en la CLI y en el panel. |
| 10 | Baja | `web.filtros` | Una fecha inválida (`?desde=2026-13-45`) devolvía cero resultados sin aviso. | — | Se valida la fecha y se muestra un aviso. |
| 11 | Baja | `web.documento`, `web.seguimiento` | Los textos truncados (300.000 caracteres) y las novedades (200) no avisaban. | — | Se muestra una nota con el número de elementos mostrados. |
| 12 | Baja | `sync.sincronizar` | La conexión a la base de datos no se cerraba al terminar. | — | Cierre explícito al final. |
| 13 | Baja | `__main__.estado` | El rótulo «con ficha completa» contaba también los trámites sin ficha (4.837 en lugar de 3.064). | — | Cuenta solo los trámites con ficha. |

Notas sobre la revisión:
- Una medición inicial de 3.718 filas repetidas en la exportación era **errónea**: el campo `orden` se reinicia en cada página de los PDF, así que no identifica una tabla. La duplicación real es la de la fila 4.
- Durante la revisión se creó por error un término de prueba en el seguimiento (80 caracteres «x»). Se borró; el seguimiento queda vacío.

Pruebas de robustez del panel (sin fallos 500):
- Página negativa, no numérica o fuera de rango; texto con comodines SQL; fecha inválida; intentos de inyección en el ámbito y en el código; texto con etiquetas HTML (se escapa correctamente); borrado con identificador no numérico o inexistente; alta de término vacío o de 500 caracteres.

## 3. Estado de los datos después de las correcciones

| Concepto | Cifra |
|---|---|
| Convenios | 2.869 (2.862 antes; las 7 nuevas vienen de los trámites de 8 y 9 de octubre) |
| Convenios con tablas salariales | 568 |
| Trámites | 4.837: 3.064 con ficha y 1.773 sin ficha |
| Publicaciones | 2.337: 1.819 con texto, 13 sin texto, 505 con error |
| Tablas | 5.029, de ellas 1.800 salariales |
| Disposiciones del BOE de convenios | 304 |
| Integridad de la base de datos | `integrity_check` = ok |

Comprobaciones posteriores a la reparación: 0 documentos con mojibake, 0 documentos de bloqueo marcados como válidos, 0 estados contaminados, 0 fichas pendientes o con error, y exportaciones coherentes con la base de datos (2.869 filas de convenios; tablas sin filas repetidas ni celdas con fórmulas).

## 4. Decisiones pendientes del usuario

Estas cuatro cuestiones cambian lo que muestra el programa. No se han modificado.

1. **Enlaces compartidos entre convenios.** 27 enlaces sirven a 144 convenios. Los más frecuentes son páginas de índice de boletines (bopsantacruzdetenerife.es: 44 convenios; boplaspalmas.net: 35; app.dipalme.org: 20), que no llevan al texto del convenio. Las tablas de un enlace compartido se asignan a todos los convenios que lo usan (afecta a 6 tablas salariales).
   - Opciones: (a) mantener el comportamiento actual con la advertencia del README; (b) no asignar automáticamente las tablas de enlaces compartidos; (c) buscar el enlace concreto de cada convenio (trabajo caso por caso).
   - Recomendación: (b).
2. **Significado de «URL de la última publicación».** 589 convenios apuntan a un trámite que no es un convenio (por ejemplo, una modificación o una comisión paritaria).
   - Opciones: (a) mantener «última publicación de cualquier trámite», con otro nombre en el panel; (b) usar «último texto del convenio» (solo trámites de tipo convenio colectivo).
   - Recomendación: (b), con (a) como respaldo cuando no exista un texto del convenio.
3. **Tablas del BOE en la vista de texto.** En el texto de 40 de cada 60 disposiciones del BOE muestreadas aparece el marcador «[tabla]». Hay 187 documentos del BOE con tablas salariales, de los que 133 están enlazados a un convenio.
   - Opciones: (a) mostrar las tablas en línea en la vista del documento; (b) dejarlo como está y documentarlo (ya está en el README).
   - Recomendación: (a), si se quiere revisar importes sin salir del panel.
4. **Búsqueda de tablas en PDF largos.** Solo se revisan las primeras 40 páginas candidatas por PDF (las que mencionan salarios y tienen al menos 5 importes). 186 PDF tienen más de 40 páginas. Subir el límite aumenta el tiempo de sincronización.
   - Opciones: (a) mantener 40; (b) subirlo a 80 y guardar el número de páginas candidatas para medir el alcance.

## 5. Limitaciones externas (no son defectos del código)

- **Servidores inaccesibles desde la sandbox**, con tiempo de espera, respuestas 403 o errores de conexión: bon.navarra.es (79), bop.dpz.es (67), miprincipado.asturias.es (65), bopmalaga (48, respuestas 403) y boc.cantabria.es (44, tiempo de espera). *Corrección tras la auditoría: boc.cantabria.es no da errores SSL; ver AUDITORIA.md, I1.* Pueden funcionar desde el PC del usuario; no se ha verificado.
- **BORM (Murcia)**: sus enlaces `services/anuncio/.../pdf` devuelven el bloqueo anti-bot. En cambio, `ofvirtual/documento?obj=anu&id=…` devolvió el PDF en una prueba. No se ha investigado más; el programa lo marca como error y el enlace sigue abriéndose en el navegador.
- **Páginas que necesitan JavaScript**: app.dipalme.org (20 convenios sin texto) y las rutas con `#` del BORM.
- **Altas tardías**: en el día 22/12/2025, REGCON devuelve hoy 38 trámites únicos, y 4 de ellos no estaban en la base de datos. No se ha identificado la causa. En una muestra de 6 días al azar (99 trámites), ninguno faltaba. Recomendación: repetir cada mes una sincronización de los últimos 60 días, por ejemplo `python -m convenios sync --desde <fecha de hace 60 días>`.
- **Revisiones salariales**: 1.773 trámites no tienen ficha ni enlace a la publicación.
- **Nombres truncados**: 51 convenios aparecen con «[..]» porque solo tienen el nombre del listado.
- **Fechas de vigencia anómalas**: 2 trámites tienen la fecha final anterior a la inicial (dato de REGCON).

## 6. Verificación realizada

- **Análisis estático**: pyflakes sin avisos; `py_compile` correcto en todos los módulos.
- **Compatibilidad con Python 3.10**: el análisis sintáctico con la gramática de 3.10 es correcto, y `vermin` no detecta nada posterior a 3.7 (confirmado en la auditoría). La sandbox solo tiene Python 3.13, así que **no se ha ejecutado con 3.10**.
- **Pruebas automáticas**: `python -m unittest discover -s tests -v`, 20 pruebas correctas. Cubren el estado de la ficha, la decodificación HTML, el captcha, el límite de descarga, el reparto del listado de REGCON, la exportación sin duplicados, las fórmulas en CSV, el aviso en la sincronización, el bloqueo y las rutas del panel. Usan una carpeta temporal y no tocan los datos.
- **Sincronización de extremo a extremo**: `sync --desde 2026-10-08 --hasta 2026-10-09` terminó con `ok: true`: 84 fichas correctas, 198 publicaciones (158 con texto, 40 con error: 37 por el bloqueo del BORM y 3 por tiempo de espera). Después, un reintento de esos 3 recuperó los 3.
- **Listado en vivo** del día 22/12/2025, con la versión corregida de `listar()`: listado completo, 38 trámites únicos (ver «altas tardías» en la sección 5).
- **Muestra manual de tablas salariales**: de 8 tablas elegidas al azar con semilla fija, 7 eran tablas salariales claras y 1 era un complemento salarial ambiguo. Es una muestra pequeña, no una validación del clasificador. *Corrección tras la auditoría: la muestra midió la precisión, pero no la exhaustividad. Las tablas salariales sin marcar son un riesgo alto; ver AUDITORIA.md, A2.*
- **Exportaciones**: `convenios.csv` con 2.869 filas, igual que la base de datos; `tablas_salariales.csv` con 25.195 filas y sin repeticiones.

## 7. Lo que no se ha podido verificar

- **Windows (PowerShell)**: la instalación, el bloqueo de sincronización (`msvcrt.locking`) y la programación con el Programador de tareas no se han probado en Windows.
- **macOS**: no probado.
- **Python 3.10 a 3.12**: no probado (ver sección 6).
- **Mi BOE**: no se implementa el inicio de sesión, por decisión del usuario; el seguimiento propio sí está disponible en el panel.

## 8. Archivos modificados en esta revisión

- `convenios/regcon.py`: estado de la ficha; paginación de respaldo de `listar()`.
- `convenios/documentos.py`: decodificación HTML; detección de captcha; descarga con límite de tamaño.
- `convenios/sync.py`: aviso en `ok`; ventana acotada a 365 días; bloqueo de sincronización; cierre de la conexión.
- `convenios/__main__.py`: exportación de tablas sin repeticiones y con orden por página; neutralización de fórmulas.
- `convenios/web.py`: aviso de fecha inválida; notas de truncado; neutralización de fórmulas en la exportación.
- `convenios/util.py`: función `celda_csv`.
- `convenios/config.py`: `DOC_MAX_BYTES`.
- `tests/test_convenios.py`: pruebas nuevas.
- `README.md`: limitaciones nuevas, bloqueo de sincronizaciones, sección de pruebas y estructura.
- `REVISION.md`: este informe.

Antes de las correcciones se guardó una copia de la base de datos fuera del proyecto (`/tmp/convenios_antes_revision.db`); no forma parte del paquete.
