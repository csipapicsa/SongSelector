<#
.SYNOPSIS
    Creates .venv with Python 3.11 and installs the pinned dev dependencies.
.EXAMPLE
    .\scripts\setup.ps1
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root '.venv'

if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe'))) {
    py -3.11 -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the venv. Is Python 3.11 installed (py -3.11)?' }
}
$python = Join-Path $venv 'Scripts\python.exe'
& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $root 'requirements-dev.txt')
# Editable install so `python -m traktor_key_calculator` works from anywhere.
& $python -m pip install --no-deps -e $root
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
# PyQt5 ships a 2020 MSVC runtime that makes onnxruntime crash; see the script for details.
& (Join-Path $PSScriptRoot 'update_qt_msvc_runtime.ps1')
Write-Host 'Environment ready. Activate with: .\.venv\Scripts\Activate.ps1'
