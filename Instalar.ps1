param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& $Python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'No fue posible crear el entorno Python 3.11+.' }
& '.\.venv\Scripts\python.exe' -m pip install -e '.[test]'
if ($LASTEXITCODE -ne 0) { throw 'Falló la instalación de dependencias.' }
Write-Host 'Instalado. Abra Iniciar_DEM.cmd.'
