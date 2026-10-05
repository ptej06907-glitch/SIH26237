$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$WebRoot = Join-Path $ProjectRoot 'apps\web'
if (-not (Test-Path -LiteralPath (Join-Path $WebRoot 'node_modules'))) { throw 'Web dependencies missing. See README installation steps.' }
Set-Location -LiteralPath $WebRoot
$env:NEXT_PUBLIC_API_URL = 'http://127.0.0.1:8000'
$env:NEXT_TELEMETRY_DISABLED = '1'
npm run start
