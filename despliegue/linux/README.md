# Despliegue en Linux (systemd)

Carpeta reservada para los ficheros de despliegue. Ahora mismo solo contiene
este marcador: están pendientes de subir (ver PRODUCCION.md, sección 3).

Ficheros que deberían estar aquí:

- `convenios-web.service`
- `convenios-sync.service` y `convenios-sync.timer`
- `convenios-copia.service` y `convenios-copia.timer`
- `convenios.env.ejemplo`
- `Caddyfile.ejemplo`

Los ficheros asumen código en `/opt/convenios` y datos en `/var/lib/convenios`.
Pasaron `systemd-analyze verify` en la versión 1.1.0 (ver AUDITORIA.md,
sección 10).
