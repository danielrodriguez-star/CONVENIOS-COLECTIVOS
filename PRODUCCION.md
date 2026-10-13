# Puesta en producción

Esta guía explica cómo dejar el programa funcionando de forma continua, con el panel accesible a varias personas por HTTPS, actualización diaria automática, copias de seguridad y vigilancia del estado.

Para uso personal en un solo equipo, el [README](README.md) basta.

## 1. Qué incluye la versión de producción

- **Panel con servidor de producción** (waitress) y con usuario y contraseña (`web --produccion`).
- **Protección del panel**: nombres de host permitidos, control de origen en los formularios, cabeceras de seguridad y páginas de error sin detalles internos.
- **Actualización diaria** con códigos de salida que permiten alertas (0, 2, 3 y 130; ver README).
- **Copias de seguridad** comprobadas con retención configurable (`copia`).
- **Estado para monitorización**: `estado --comprobar` (código de salida) y `GET /salud` (JSON).
- **Registros técnicos** con rotación en `datos/registros/`.
- **Respeto de `robots.txt`** por defecto.

No incluye: escalado a varios servidores (la base de datos es SQLite, con un único escritor), límite de intentos de acceso ni HTTPS propio (eso lo pone un proxy inverso), ni gestión de varios usuarios con permisos distintos.

## 2. Antes de empezar

- [ ] Un equipo (Linux o Windows) con Python 3.10 o superior y acceso a Internet.
- [ ] Un nombre público para el panel (p. ej., `convenios.ejemplo.es`) apuntando a ese equipo.
- [ ] Un proxy inverso con HTTPS (Caddy, nginx o IIS). Este documento incluye un ejemplo con Caddy.
- [ ] Decidir la política de `robots.txt` y el fallback TLS (sección 6). Por defecto: respetar y limitar el fallback a dos servidores.
- [ ] Espacio: la base de datos ocupa unos 50 MB con 12 meses de datos; cada copia, otros tantos. Reserva al menos 2 GB.

## 3. Instalación en Linux (systemd)

Los ficheros de `despliegue/linux/` asumen esta distribución:

- Código en `/opt/convenios` (de solo lectura para el servicio).
- Datos en `/var/lib/convenios` (los crea systemd con `StateDirectory`).
- Configuración en `/etc/convenios/convenios.env`.
- Usuario del sistema `convenios`, sin shell de inicio de sesión.

Comandos (ejecutar como administrador en la carpeta del proyecto):

```bash
sudo useradd --system --home-dir /var/lib/convenios --shell /usr/sbin/nologin convenios
sudo install -d -o convenios -g convenios -m 750 /var/lib/convenios
sudo mkdir -p /opt/convenios /etc/convenios
sudo cp -r README.md PRODUCCION.md requirements.txt requirements-lock.txt convenios auditoria despliegue /opt/convenios/
cd /opt/convenios
sudo python3 -m venv .venv
sudo .venv/bin/python -m pip install -r requirements-lock.txt
sudo cp despliegue/linux/convenios.env.ejemplo /etc/convenios/convenios.env
sudo cp despliegue/linux/convenios-*.service despliegue/linux/convenios-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

Edita `/etc/convenios/convenios.env` y pon tu nombre público en `CONVENIOS_HOSTS_PERMITIDOS`.

No copies la carpeta `datos` al servidor: la base de producción vive en `/var/lib/convenios`. Si quieres conservar los datos que ya tienes, para el servicio y copia `datos/convenios.db` y `datos/seguimiento.db` a `/var/lib/convenios/` (con el mismo nombre) antes de arrancar el panel. Si la base viene de otra instalación con cambios sin fusionar, ejecuta antes `python -m convenios estado` para que SQLite fusione los datos pendientes.

**Crear el usuario del panel** (la contraseña se pide por teclado y no queda en el historial):

```bash
cd /opt/convenios
sudo -u convenios env CONVENIOS_DATOS=/var/lib/convenios /opt/convenios/.venv/bin/python -m convenios usuario
```

**Carga inicial de 12 meses** (tarda horas; conviene lanzarla dentro de `tmux` o `screen`):

```bash
cd /opt/convenios
sudo -u convenios env CONVENIOS_DATOS=/var/lib/convenios /opt/convenios/.venv/bin/python -m convenios sync --desde 2025-10-08
```

**Activar el panel y las tareas diarias:**

```bash
sudo systemctl enable --now convenios-web.service
sudo systemctl enable --now convenios-sync.timer convenios-copia.timer
systemctl list-timers | grep convenios
```

Ver el registro de la actualización: `journalctl -u convenios-sync.service -n 100`.

**Proxy HTTPS (ejemplo con Caddy)**: `despliegue/linux/Caddyfile.ejemplo` redirige `convenios.ejemplo.es` a `127.0.0.1:8000` y obtiene el certificado automáticamente. Caddy reenvía el nombre de host original, que debe estar en `CONVENIOS_HOSTS_PERMITIDOS`.

## 4. Instalación en Windows

En Windows, el panel y las tareas se ejecutan con el mismo Python del entorno virtual. Los pasos del README sirven para crear el entorno. Después:

1. **Configuración**: define las variables que necesites con `setx` (sección 5). Abre una terminal nueva para que se apliquen.
2. **Usuario del panel**: `python -m convenios usuario` (con el entorno activado).
3. **Tareas diarias**: ejecuta `despliegue\windows\programar-tareas.ps1` con `-Carpeta`. Ese script **no se ha ejecutado en Windows** (solo se comprobó con PowerShell 7 en Linux, con los cmdlets del Programador simulados): revisa las tareas creadas y ejecuta una a mano antes de confiar en ellas.
4. **Panel**: `python -m convenios web --produccion --host 127.0.0.1 --puerto 8000` detrás de un proxy HTTPS (IIS con ARR o Caddy). Para que arranque solo al iniciar sesión, crea una tarea con el desencadenador «Al iniciar sesión». Como servicio de Windows necesitas una herramienta externa (p. ej., NSSM); no se ha probado.

## 5. Configuración

Todas las opciones son variables de entorno. Sin ninguna definida, el programa usa los valores por defecto.

| Variable | Por defecto | Efecto |
|---|---|---|
| `CONVENIOS_DATOS` | `datos` dentro de la carpeta del proyecto | Carpeta de datos (en Linux, `/var/lib/convenios`) |
| `CONVENIOS_ROBOTS` | `respetar` | `respetar` o `ignorar`. Con `ignorar` se usa el XML del BOE y no se consulta `robots.txt`: no recomendado |
| `CONVENIOS_TLS_HEREDADO` | `portaldogc.gencat.cat,bop.dipucr.es` | Servidores para los que se acepta un certificado sin verificar, solo si fallan con la verificación normal |
| `CONVENIOS_HOSTS_PERMITIDOS` | (vacío) | Nombres de host aceptados además de `localhost`, `127.0.0.1` y `::1`. Admite comodines (`*.ejemplo.es`) |
| `CONVENIOS_COPIAS_CONSERVAR` | `14` | Copias que se conservan al crear una nueva |
| `CONVENIOS_ALERTA_HORAS` | `72` | Horas sin sincronización correcta antes de que `/salud` y `estado --comprobar` avisen |
| `CONVENIOS_PERMITIR_IFRAME` | `no` | `si` permite mostrar el panel dentro de otra página. Solo para vistas previas |

## 6. Decisiones de política

**robots.txt (`CONVENIOS_ROBOTS=respetar`).** Antes de pedir una publicación, el programa lee el `robots.txt` del servidor (con caché de 24 h y reintento a los 10 min si no se puede leer). Si la regla prohíbe la dirección, la publicación queda como «bloqueada por robots.txt». Si el `robots.txt` no se puede leer, la publicación queda pendiente y se reintenta en la siguiente sincronización.

Textos ya guardados antes de esta versión: `python -m convenios depurar-robots` los lista. Con los datos de la versión 1.1.0 había 848 textos de direcciones prohibidas (304 del XML del BOE y 544 de otros 17 servidores); además, 156 textos no se pudieron comprobar porque el `robots.txt` de su servidor no respondió en ese momento. Si se borran todos los textos prohibidos, 663 convenios de 1.530 que tienen texto se quedarían sin él. Si además el BOE se vuelve a descargar de su PDF (permitido), la cifra baja a 461. Por eso el borrado no se hace solo: `depurar-robots --aplicar` hace antes una copia y luego recalcula los convenios.

**TLS heredado (`CONVENIOS_TLS_HEREDADO`).** Para los servidores de la lista, y solo para ellos, si la verificación del certificado falla, se vuelve a pedir sin verificarlo. El documento queda marcado con `+tls-heredado`. Para quitar el fallback, deja la variable vacía: `CONVENIOS_TLS_HEREDADO=` en el fichero de configuración.

## 7. Operación diaria

| Qué | Cómo | Cuándo |
|---|---|---|
| Actualizar | `convenios-sync.timer` (`python -m convenios sync`) | Cada día a las 07:30 |
| Copia de seguridad | `convenios-copia.timer` (`python -m convenios copia`) | Cada día a las 08:00 |
| Comprobar el estado | `python -m convenios estado --comprobar` | Cuando quieras, o desde un monitor |
| Vigilar desde fuera | `GET https://convenios.ejemplo.es/salud` | Cada pocos minutos |

**Códigos de salida de `estado --comprobar`**: 0 correcto; 2 atención (p. ej., más de `CONVENIOS_ALERTA_HORAS` sin una sincronización correcta, o ninguna todavía); 1 error (base de datos ausente, ilegible o dañada).

**Respuesta de `/salud`**: JSON con `estado` (`ok`, `atencion` o `error`), `ultima_sincronizacion_correcta`, `horas_desde_ultima_sincronizacion`, `umbral_horas` y `mensajes`. Devuelve 503 solo si el estado es `error`, así que puede usarse directamente con un monitor HTTP. No muestra datos de los convenios.

**Alertas de actualización (systemd)**: si `convenios-sync.service` termina con código 2 o 3, queda como fallido. Puedes avisar con `OnFailure=` o revisando `systemctl --failed`.

**Registros**: `datos/registros/sincronizacion.log` y `datos/registros/panel.log`, con rotación de 5 MB y 5 copias. `datos/sincronizacion.log` contiene el resumen de cada ejecución.

**Copias**: se conservan las últimas `CONVENIOS_COPIAS_CONSERVAR` en `datos/copias/AAAA-MM-DD_HHMMSS/`. Cada una se comprueba con `PRAGMA integrity_check` antes de darla por buena. Copia también la carpeta `datos/copias` a otro equipo: una copia que vive en el mismo disco no protege frente a un fallo del disco.

## 8. Restaurar una copia

```bash
sudo systemctl stop convenios-web.service convenios-sync.timer convenios-copia.timer
sudo -u convenios rm -f /var/lib/convenios/convenios.db-wal /var/lib/convenios/convenios.db-shm
sudo -u convenios cp /var/lib/convenios/copias/AAAA-MM-DD_HHMMSS/convenios.db /var/lib/convenios/convenios.db
sudo systemctl start convenios-web.service convenios-sync.timer convenios-copia.timer
cd /opt/convenios && sudo -u convenios env CONVENIOS_DATOS=/var/lib/convenios /opt/convenios/.venv/bin/python -m convenios estado --comprobar
```

Sustituye `AAAA-MM-DD_HHMMSS` por la carpeta elegida. Si se restauró `seguimiento.db`, cópialo igual desde esa carpeta.

## 9. Actualizar a una versión nueva

1. Haz una copia: `python -m convenios copia`.
2. Para el panel: `sudo systemctl stop convenios-web.service`.
3. Sustituye el código en `/opt/convenios` conservando `.venv`, y actualiza las dependencias con `requirements-lock.txt`.
4. Ejecuta las pruebas: `python -m unittest discover -s tests`.
5. Vuelve a arrancar: `sudo systemctl start convenios-web.service`.
6. Comprueba `estado --comprobar` y `/salud`.

Las versiones que cambian la base de datos se migran solas al arrancar (`db.py`). Antes de actualizar, la copia de seguridad es imprescindible.

## 10. Seguridad

Lo que el programa hace:

- Atiende solo a los nombres de host configurados (frente a «DNS rebinding»).
- Acepta formularios solo desde el propio panel (cabecera `Origin`; frente a CSRF).
- Envía `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` y `Cache-Control: no-store`.
- Escapa todo el contenido que llega de fuentes externas (la prueba `auditoria/prueba_seguridad_panel.py` lo comprueba).
- Guarda la contraseña del panel como hash (scrypt, mediante Werkzeug) en `datos/acceso.json`, con permisos 600 en Linux.
- No muestra trazas de error ni rutas internas: el detalle va al registro.

Lo que debes hacer tú:

- Usar HTTPS (el proxy). Sin HTTPS, la contraseña viaja en claro.
- Usar una contraseña de al menos 12 caracteres (el programa lo exige) y no reutilizarla.
- No exponer el puerto 8000 directamente a Internet: solo el proxy debe llegar a él.
- Limitar los intentos de acceso en el proxy si el panel es público (el programa no lo hace).
- Mantener el sistema y Python al día, y revisar `pip-audit -r requirements-lock.txt` de vez en cuando.

## 11. Lista de verificación final

- [ ] `python -m unittest discover -s tests` termina sin errores.
- [ ] Hay un usuario del panel (`datos/acceso.json` existe) y la contraseña tiene 12 caracteres o más.
- [ ] `curl -s https://convenios.ejemplo.es/salud` devuelve `"estado": "ok"` (tras la primera sincronización).
- [ ] Las tareas diarias están activas (`systemctl list-timers` o Programador de tareas).
- [ ] Hay al menos una copia en `datos/copias/` y se ha comprobado su integridad.
- [ ] `CONVENIOS_HOSTS_PERMITIDOS` contiene solo el nombre público (sin comodines innecesarios).
- [ ] Las decisiones de la sección 6 están tomadas y documentadas.
- [ ] Existe una licencia, si el programa se va a compartir (ver README, «Licencia»).

## 12. Límites conocidos

- SQLite admite un único proceso escritor. La sincronización y el panel pueden convivir (el panel lee la base y guarda el seguimiento en otra), pero no hay réplicas ni alta disponibilidad.
- Las fuentes oficiales pueden cambiar sin aviso. REGCON no tiene API pública; si cambia su formulario, hay que adaptar `convenios/regcon.py`.
- La detección de tablas salariales es heurística (ver AUDITORIA.md, A2).
- Los servidores de boletines pueden bloquear o limitar las descargas (p. ej., la Diputación de Cuenca responde 403). El programa lo registra y no insiste.
- Las ficheros de despliegue de Windows y la configuración de Caddy no se han probado en un servidor real en este entorno (ver el README y la sección 4).
