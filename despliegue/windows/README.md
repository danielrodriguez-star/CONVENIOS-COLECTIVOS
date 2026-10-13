# Despliegue en Windows (Programador de tareas)

Script de tareas programadas para Windows (ver PRODUCCION.md, sección 4).

Fichero de esta carpeta:

- `programar-tareas.ps1` — crea las tareas de actualización (07:30) y copia de
  seguridad (08:00). Admite `-HoraSincronizacion`, `-HoraCopia` y
  `-CopiasAConservar`. No se ha ejecutado en Windows: se comprobó con
  PowerShell 7 en Linux (ver README).
