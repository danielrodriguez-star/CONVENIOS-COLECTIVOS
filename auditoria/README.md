# Comprobaciones de la auditoría

Carpeta reservada para los scripts de la auditoría (ver AUDITORIA.md, sección
9). Ahora mismo solo contiene este marcador: están pendientes de subir.

Ficheros que deberían estar aquí:

- `comprobar_robots.py` — comprueba los `robots.txt` de los servidores a los
  que se piden documentos. Solo lee los `robots.txt`; no descarga documentos.
- `comprobar_tablas.py` — compara los importes de las tablas guardadas con el
  documento original. Solo lee la base de datos.
- `prueba_seguridad_panel.py` — comprueba el escape HTML del panel con cargas
  maliciosas. Usa una base temporal.

Ninguno modifica `datos/convenios.db`. Para repetirlos, una vez esté el código
en el repositorio:

```
pip install protego
python auditoria/comprobar_robots.py
python auditoria/prueba_seguridad_panel.py
python auditoria/comprobar_tablas.py
```
