$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$airAssistPythonCommand = Get-Command python -ErrorAction SilentlyContinue
$airAssistPythonPath = if ($airAssistPythonCommand -and $airAssistPythonCommand.Source -notlike '*WindowsApps*') { $airAssistPythonCommand.Source } else { $null }
if (-not $airAssistPythonPath) {
    $airAssistBundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $airAssistBundledPython) { $airAssistPythonPath = $airAssistBundledPython }
}
if (-not $airAssistPythonPath) { throw 'Python 3.10 or newer is required. Run python server.py when Python is available.' }
& $airAssistPythonPath -B (Join-Path $PSScriptRoot 'server.py') --port 8789
exit $LASTEXITCODE
