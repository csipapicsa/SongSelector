<#
.SYNOPSIS
    Replaces the outdated MSVC runtime DLLs that the PyQt5-Qt5 wheel ships (14.26, 2020)
    with the newer ones installed in Windows (C:\Windows\System32).
.DESCRIPTION
    Why: onnxruntime needs a current MSVC runtime. If PyQt5's old msvcp140.dll is loaded first
    in a process, onnxruntime crashes with an access violation (0xC0000005). This affects
    PyInstaller's build step (it imports Qt first), and the frozen exe would bundle the old DLL.
    Microsoft keeps v14 runtimes backward compatible, so Qt runs fine on the newer DLLs.

    Run automatically by setup.ps1; build.ps1 refuses to build until this has been applied.
    Reinstalling PyQt5-Qt5 restores the original files.
    Needs the "Microsoft Visual C++ Redistributable 2015-2022 (x64)":
    https://aka.ms/vs/17/release/vc_redist.x64.exe
.PARAMETER Check
    Only report; exit code 1 if PyQt5 still ships an older runtime than Windows.
#>
param([switch]$Check)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$qtBin = Join-Path $root '.venv\Lib\site-packages\PyQt5\Qt5\bin'
$system = Join-Path $env:SystemRoot 'System32'
$names = 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll'

if (-not (Test-Path -LiteralPath $qtBin)) { throw "PyQt5 not found in .venv ($qtBin). Run .\scripts\setup.ps1 first." }
$outdated = @()
foreach ($name in $names) {
    $qtFile = Join-Path $qtBin $name
    $systemFile = Join-Path $system $name
    if (-not (Test-Path -LiteralPath $qtFile)) { continue }
    if (-not (Test-Path -LiteralPath $systemFile)) {
        throw "$systemFile is missing. Install https://aka.ms/vs/17/release/vc_redist.x64.exe and run again."
    }
    $qtVersion = [version](Get-Item -LiteralPath $qtFile).VersionInfo.FileVersionRaw
    $systemVersion = [version](Get-Item -LiteralPath $systemFile).VersionInfo.FileVersionRaw
    if ($qtVersion -lt $systemVersion) { $outdated += [pscustomobject]@{ Name = $name; Qt = $qtVersion; System = $systemVersion } }
}

if (-not $outdated) {
    Write-Host 'PyQt5 MSVC runtime is up to date.'
    exit 0
}
if ($Check) {
    $outdated | ForEach-Object { Write-Host "Outdated: $($_.Name) $($_.Qt) < $($_.System)" }
    Write-Host 'Run .\scripts\update_qt_msvc_runtime.ps1 to update it.'
    exit 1
}
foreach ($file in $outdated) {
    Copy-Item -LiteralPath (Join-Path $system $file.Name) -Destination (Join-Path $qtBin $file.Name) -Force
    Write-Host "Updated $($file.Name): $($file.Qt) -> $($file.System)"
}
