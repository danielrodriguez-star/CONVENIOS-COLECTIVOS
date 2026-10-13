# Pruebas automáticas

Carpeta reservada para las pruebas del programa. Ahora mismo solo contiene este
marcador: el código real está pendiente de subir.

Ficheros que deberían estar aquí (ver README.md, sección «Pruebas»):

- `test_convenios.py` — pruebas de la base funcional.
- `test_produccion.py` — pruebas de robots, acceso, copias, estado, panel y CLI.

En total, 67 pruebas. Para ejecutarlas, una vez esté el código en el
repositorio:

```
python -m unittest discover -s tests -v
```
