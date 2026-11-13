<#
.SYNOPSIS
    Publishes the model files as the GitHub release "models-v1", where the app downloads them from.
.DESCRIPTION
    Checks every file in -Folder against the size and SHA-256 the app expects (src/songselector/core/model_download.py),
    so the app can never download a file it would reject, then creates the release with the files, SHA256SUMS.txt,
    packaging/models/MODELS.md (sources, licences) and the licence texts. Needs the GitHub CLI (gh), signed in.
    Run once per model version; app releases (vX.Y.Z tags) do not touch it.
.PARAMETER Folder
    Folder with cnn14.onnx and the clap-* files (made by scripts/export_cnn14_onnx.py and scripts/export_clap_onnx.py).
.PARAMETER DryRun
    Only check the files; publish nothing.
.EXAMPLE
    .\scripts\publish_models.ps1 -Folder .appdata\models
#>
param([Parameter(Mandatory = $true)][string]$Folder, [string]$Tag = 'models-v1', [switch]$DryRun)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'

# The expected files, read from the app's own list.
$expected = & $python -c "import json; from songselector.core.model_download import FILES; print(json.dumps(FILES))" | ConvertFrom-Json
$assets = @()
$sums = @()
foreach ($property in $expected.PSObject.Properties) {
    $name = $property.Name
    $size, $hash = $property.Value
    $path = Join-Path $Folder $name
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing: $path" }
    $file = Get-Item -LiteralPath $path
    if ($file.Length -ne $size) { throw "$name has $($file.Length) bytes, the app expects $size" }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $hash) { throw "$name has SHA-256 $actual, the app expects $hash" }
    Write-Host "OK  $name"
    $assets += $file.FullName
    $sums += "$hash  $name"
}
$work = Join-Path $env:TEMP "songselector-$Tag"
New-Item -ItemType Directory -Force -Path $work | Out-Null
$sumsFile = Join-Path $work 'SHA256SUMS.txt'
Set-Content -LiteralPath $sumsFile -Value $sums -Encoding ascii
$notes = Join-Path $root 'packaging\models\MODELS.md'
$assets += $sumsFile, $notes, (Join-Path $root 'packaging\models\LICENSE-MS-PL.txt'), (Join-Path $root 'packaging\models\LICENSE-Apache-2.0.txt')

if ($DryRun) { Write-Host "Dry run: $($assets.Count) files ready, nothing published."; return }
# --latest=false: the repository's "latest release" stays the newest app version.
gh release create $Tag --title "Model files v1 (for SongSelector 1.1+)" --latest=false --notes-file $notes @assets
if ($LASTEXITCODE -ne 0) { throw "gh release create failed" }
Write-Host "Published $Tag with $($assets.Count) files."
