<#
.SYNOPSIS
  Crea en el Programador de tareas la actualización diaria y la copia de seguridad de convenios.

.DESCRIPTION
  No necesita permisos de administrador: las tareas se ejecutan con tu usuario.
  Requiere haber creado antes el entorno virtual .venv dentro de la carpeta del proyecto (ver README.md).
  Si una tarea ya existe, se sustituye.
  Las tareas se ejecutan con tu sesión iniciada. Si la hora programada pasa con el equipo apagado,
  se ejecutan en cuanto inicies sesión. También se ejecutan con batería.

  AVISO: no se ha ejecutado en Windows. La sintaxis y la lógica se comprobaron con PowerShell 7 en Linux,
  simulando los cmdlets del Programador de tareas. Revisa las tareas en el Programador de tareas y
  ejecuta una a mano antes de confiar en ellas.

.PARAMETER Carpeta
  Carpeta del proyecto (la que contiene README.md).

.PARAMETER HoraSincronizacion
  Hora de la actualización diaria. Por defecto, 07:30.

.PARAMETER HoraCopia
  Hora de la copia de seguridad diaria. Por defecto, 08:00.

.PARAMETER CopiasAConservar
  Número de copias de seguridad que se conservan (1 a 365). Por defecto, 14.
  Cada copia ocupa unos 50 MB.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File despliegue\windows\programar-tareas.ps1 -Carpeta "C:\convenios"
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Carpeta,
    [string]$HoraSincronizacion = "07:30",
    [string]$HoraCopia = "08:00",
    [ValidateRange(1, 365)]
    [int]$CopiasAConservar = 14
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Carpeta -PathType Container)) {
    throw "No existe la carpeta '$Carpeta'. Indica la carpeta del proyecto (la que contiene README.md)."
}
$Carpeta = (Resolve-Path -LiteralPath $Carpeta).Path
$python = Join-Path $Carpeta ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "No se encuentra $python. Crea primero el entorno virtual (ver README.md)."
}

# Si falta alguna dependencia, las tareas fallarían cada día. Mejor avisar ahora.
& $python -c "import requests, lxml, pymupdf, flask, protego, waitress"
if ($LASTEXITCODE -ne 0) {
    throw "Faltan dependencias en .venv. Instálalas con: $python -m pip install -r requirements.txt"
}

function Registrar-Tarea {
    param([string]$Nombre, [string]$Argumentos, [string]$Hora)
    $accion = New-ScheduledTaskAction -Execute $python -Argument $Argumentos -WorkingDirectory $Carpeta
    $disparador = New-ScheduledTaskTrigger -Daily -At $Hora
    # Por defecto, Windows no arranca la tarea con batería, la para si el equipo pasa a batería
    # y no recupera las ejecuciones perdidas. Se cambia aquí para que funcione también en portátiles.
    $ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 6) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $Nombre -Action $accion -Trigger $disparador -Settings $ajustes `
        -Description "Convenios colectivos de España" -Force | Out-Null
    Write-Host "Tarea creada: $Nombre (cada día a las $Hora)"
}

Registrar-Tarea -Nombre "Convenios - actualizacion diaria" -Argumentos "-m convenios sync" -Hora $HoraSincronizacion
Registrar-Tarea -Nombre "Convenios - copia de seguridad" -Argumentos "-m convenios copia --conservar $CopiasAConservar" -Hora $HoraCopia
Write-Host "Listo. Para probar una tarea: Start-ScheduledTask -TaskName 'Convenios - actualizacion diaria'"
