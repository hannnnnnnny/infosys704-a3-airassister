$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$airAssistPythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $airAssistPythonPath) { throw 'Python 3.10 or newer is required. Run python server.py when Python is available.' }
& $airAssistPythonPath -B (Join-Path $PSScriptRoot 'server.py') --port 8789
exit $LASTEXITCODE
