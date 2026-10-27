<#
.SYNOPSIS
    Builds the one-file Windows exe into dist\TraktorKeyCalculator-<version>.exe.
.EXAMPLE
    .\scripts\build.ps1
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}

$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONHASHSEED = '0'
$env:PYINSTALLER_CONFIG_DIR = Join-Path $root 'build\pyinstaller-cache'

Push-Location $root
try {
    # PyInstaller logs to stderr; Windows PowerShell 5.1 would turn that into
    # terminating errors under 'Stop', so rely on the exit code instead.
    $ErrorActionPreference = 'Continue'
    & $python -B -m PyInstaller --noconfirm --clean `
        --distpath (Join-Path $root 'dist') `
        --workpath (Join-Path $root 'build') `
        (Join-Path $root 'packaging\TraktorKeyCalculator.spec')
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
    $ErrorActionPreference = 'Stop'
} finally {
    Pop-Location
}

$exe = Get-ChildItem -LiteralPath (Join-Path $root 'dist') -Filter 'TraktorKeyCalculator-*.exe' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$hash = (Get-FileHash -LiteralPath $exe.FullName -Algorithm SHA256).Hash.ToLower()
Write-Host ''
Write-Host "Built:  $($exe.FullName)"
Write-Host "Size:   $([math]::Round($exe.Length / 1MB, 1)) MB"
Write-Host "SHA256: $hash"
