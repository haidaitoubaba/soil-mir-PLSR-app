$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host ""
Write-Host "Soil MIR PLSR launcher"
Write-Host "Platform: Windows"
Write-Host ""

function Test-PythonVersion {
    param(
        [string]$Executable,
        [string[]]$PrefixArgs = @()
    )

    & $Executable @PrefixArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
    return $LASTEXITCODE -eq 0
}

$PythonExecutable = $null
$PythonPrefixArgs = @()

if ($env:PYTHON_BIN) {
    $PythonExecutable = $env:PYTHON_BIN
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    if (Test-PythonVersion -Executable "py" -PrefixArgs @("-3")) {
        $PythonExecutable = "py"
        $PythonPrefixArgs = @("-3")
    }
}

if (-not $PythonExecutable -and (Get-Command python -ErrorAction SilentlyContinue)) {
    if (Test-PythonVersion -Executable "python") {
        $PythonExecutable = "python"
    }
}

if (-not $PythonExecutable) {
    Write-Host "Python 3.10 or newer was not found."
    Write-Host "Install a supported Python version, then run this launcher again."
    Read-Host "Press Enter to close"
    exit 1
}

& $PythonExecutable @PythonPrefixArgs "$Root\scripts\launch_app.py"
$ExitCode = $LASTEXITCODE

if ($ExitCode -ne 0) {
    Write-Host ""
    Write-Host "Soil MIR could not start. Exit code: $ExitCode"
    Write-Host "You can copy this window output when reporting the problem."
    Read-Host "Press Enter to close"
}

exit $ExitCode
