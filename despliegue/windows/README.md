# Despliegue en Windows (Programador de tareas)

Carpeta reservada para el script de tareas programadas. Ahora mismo solo
contiene este marcador: está pendiente de subir (ver PRODUCCION.md, sección 4).

Ficheros que deberían estar aquí:

- `programar-tareas.ps1` — crea las tareas de actualización (07:30) y copia de
  seguridad (08:00). Admite `-HoraSincronizacion`, `-HoraCopia` y
  `-CopiasAConservar`. No se ha ejecutado en Windows: se comprobó con
  PowerShell 7 en Linux (ver README).
