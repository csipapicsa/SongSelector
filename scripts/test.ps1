<#
.SYNOPSIS
    Runs the automated test suite. Extra arguments are passed to pytest.
.EXAMPLE
    .\scripts\test.ps1
    .\scripts\test.ps1 -k color
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}
Push-Location $root
try {
    & $python -m pytest @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
