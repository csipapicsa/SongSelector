<#
.SYNOPSIS
    Prints the CHANGELOG.md section of one version: the release notes of a GitHub Release.
    Fails if the section is missing or empty, so a release can't go out without a changelog entry.
.EXAMPLE
    .\scripts\release_notes.ps1 -Version 1.0.1
    .\scripts\release_notes.ps1 -Version 1.0.1 -Out notes.md
#>
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Out
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$lines = Get-Content -LiteralPath (Join-Path $root 'CHANGELOG.md') -Encoding UTF8

$header = '^## \[' + [regex]::Escape($Version) + '\]'
$start = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match $header) { $start = $i + 1; break }
}
if ($start -lt 0) { throw "CHANGELOG.md has no section '## [$Version]'." }

# The section ends at the next version heading (##) or top-level heading (#).
$section = New-Object System.Collections.Generic.List[string]
for ($i = $start; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^#{1,2} ') { break }
    $section.Add($lines[$i])
}
$text = ($section -join "`n").Trim()
if (-not $text) { throw "The CHANGELOG.md section '## [$Version]' is empty." }

if ($Out) {
    Set-Content -LiteralPath $Out -Value $text -Encoding UTF8
} else {
    $text
}
