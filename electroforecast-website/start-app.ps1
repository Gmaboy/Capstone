$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $venvPython)) {
  python -m venv (Join-Path $projectRoot '.venv')
}

& $venvPython -m pip install -r (Join-Path $projectRoot 'requirements.txt')
& $venvPython (Join-Path $projectRoot 'app.py')

