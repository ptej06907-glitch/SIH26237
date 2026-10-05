$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Python environment missing. See README installation steps.' }
$env:PYTHONPATH = Join-Path $ProjectRoot 'services\api'
Set-Location -LiteralPath $ProjectRoot
& $Python -m uvicorn provenance.app:app --host 127.0.0.1 --port 8000
