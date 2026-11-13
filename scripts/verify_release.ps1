<#
.SYNOPSIS
    Verifies a built exe in two stages:
      1. Packaged self-check: runs the exe headless with SONGSELECTOR_VERIFY_BUILD=1, which
         executes songselector.selfcheck inside the frozen app.
      2. Native smoke test: starts the exe normally, waits for its real window,
         checks it responds, closes it and expects exit code 0.
    Both stages use a throwaway data directory under %TEMP%\songselector-verify\,
    so your real settings and imported tracks are never touched (and the exe unpacks there,
    not on the project's disk).
.PARAMETER Exe
    Path to the exe. Defaults to the newest dist\SongSelector-*.exe.
.PARAMETER Model
    Optional path to cnn14.onnx. When given (or SONGSELECTOR_VERIFY_MODEL is set), the
    self-check also runs a real embedding analysis inside the exe.
.EXAMPLE
    .\scripts\verify_release.ps1
#>
param([string]$Exe, [string]$Model = $env:SONGSELECTOR_VERIFY_MODEL)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Exe) {
    $found = Get-ChildItem -LiteralPath (Join-Path $root 'dist') -Filter 'SongSelector-*.exe' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $found) { throw 'No exe in dist\. Run .\scripts\build.ps1 first.' }
    $Exe = $found.FullName
}
$Exe = (Resolve-Path -LiteralPath $Exe).Path
# Long form of the temp folder: $env:TEMP can be an 8.3 short path (C:\Users\GERGOG~1\...),
# which the app's path comparisons do not treat as the same folder.
$tempRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Temp'
$runDir = Join-Path $tempRoot ('songselector-verify\' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $runDir | Out-Null
Write-Host "Verifying $Exe"
Write-Host "Results in $runDir"

# ---- Stage 1: packaged self-check -------------------------------------------
$packagedDir = Join-Path $runDir 'packaged'
New-Item -ItemType Directory -Path $packagedDir | Out-Null
$packagedResult = Join-Path $runDir 'packaged-results.json'
$savedEnv = @{}
foreach ($name in 'TEMP','TMP','PATH','PYTHONPATH','PYTHONHOME','QT_QPA_PLATFORM','SONGSELECTOR_APP_DATA_DIR','SONGSELECTOR_VERIFY_BUILD','SONGSELECTOR_VERIFY_RESULT','SONGSELECTOR_VERIFY_MODEL','SONGSELECTOR_EMBEDDING_MODEL') {
    $savedEnv[$name] = [Environment]::GetEnvironmentVariable($name)
}
try {
    $env:TEMP = $packagedDir
    $env:TMP = $packagedDir
    # Minimal PATH/PYTHON* so the exe cannot accidentally use a local Python install.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:PYTHONPATH = ''
    $env:PYTHONHOME = ''
    $env:QT_QPA_PLATFORM = 'offscreen'
    $env:SONGSELECTOR_APP_DATA_DIR = $packagedDir
    $env:SONGSELECTOR_VERIFY_BUILD = '1'
    $env:SONGSELECTOR_VERIFY_RESULT = $packagedResult
    $env:SONGSELECTOR_VERIFY_MODEL = $Model
    # No default model: the app windows must not start analysing the bundled library.
    $env:SONGSELECTOR_EMBEDDING_MODEL = 'none'
    $process = Start-Process -FilePath $Exe -WorkingDirectory $packagedDir -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(300000)) { $process.Kill(); throw 'Packaged self-check timed out.' }
    if (Test-Path -LiteralPath $packagedResult) { Get-Content -LiteralPath $packagedResult }
    if ($process.ExitCode -ne 0) { throw 'Packaged self-check failed.' }
    if (-not (Get-Content -LiteralPath $packagedResult -Raw | ConvertFrom-Json).ok) { throw 'Packaged self-check reported failure.' }

    # ---- Stage 2: native window smoke test ----------------------------------
    $nativeDir = Join-Path $runDir 'native'
    New-Item -ItemType Directory -Path $nativeDir | Out-Null
    $env:TEMP = $nativeDir
    $env:TMP = $nativeDir
    $env:SONGSELECTOR_APP_DATA_DIR = $nativeDir
    $env:QT_QPA_PLATFORM = ''
    $env:SONGSELECTOR_VERIFY_BUILD = ''
    $env:SONGSELECTOR_VERIFY_RESULT = ''
    $env:SONGSELECTOR_VERIFY_MODEL = ''

    Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class SongSelectorNativeWindow {
    public delegate bool EnumProc(IntPtr hwnd, IntPtr parameter);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc callback, IntPtr parameter);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int count);
    [DllImport("user32.dll")] static extern IntPtr SendMessageTimeout(IntPtr hwnd, uint message, IntPtr wparam, IntPtr lparam, uint flags, uint timeout, out IntPtr result);
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr hwnd, uint message, IntPtr wparam, IntPtr lparam);
    public static IntPtr Find(int[] processIds) {
        var allowed = new HashSet<int>(processIds);
        IntPtr found = IntPtr.Zero;
        EnumWindows((hwnd, parameter) => {
            uint id; GetWindowThreadProcessId(hwnd, out id);
            if (!allowed.Contains((int)id)) return true;
            var title = new StringBuilder(512); GetWindowText(hwnd, title, title.Capacity);
            if (!title.ToString().StartsWith("SongSelector")) return true;
            found = hwnd; return false;
        }, IntPtr.Zero);
        return found;
    }
    public static bool Responsive(IntPtr hwnd) {
        IntPtr result;
        return SendMessageTimeout(hwnd, 0, IntPtr.Zero, IntPtr.Zero, 2, 2000, out result) != IntPtr.Zero;
    }
    public static void Close(IntPtr hwnd) { PostMessage(hwnd, 0x10, IntPtr.Zero, IntPtr.Zero); }
}
"@
    $process = Start-Process -FilePath $Exe -WorkingDirectory $nativeDir -WindowStyle Hidden -PassThru
    # The one-file bootloader starts a child process that owns the window.
    $ownedIds = @($process.Id)
    try {
        $deadline = [DateTime]::UtcNow.AddSeconds(60)  # a one-file exe unpacks first; slow on a busy disk
        $window = [IntPtr]::Zero
        do {
            $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($process.Id)" | ForEach-Object { [int]$_.ProcessId })
            $ownedIds = @($process.Id) + $children
            $window = [SongSelectorNativeWindow]::Find([int[]]$ownedIds)
            if ($window -ne [IntPtr]::Zero) { break }
            if ($process.HasExited) { throw 'App exited before opening its window.' }
            Start-Sleep -Milliseconds 200
        } while ([DateTime]::UtcNow -lt $deadline)
        if ($window -eq [IntPtr]::Zero) { throw 'App window was not found.' }
        Start-Sleep -Seconds 2
        if (-not [SongSelectorNativeWindow]::Responsive($window)) { throw 'App window is not responding.' }
        [SongSelectorNativeWindow]::Close($window)
        if (-not $process.WaitForExit(10000)) { throw 'App did not close cleanly.' }
        if ($process.ExitCode -ne 0) { throw "App exited with code $($process.ExitCode)." }
        $settings = Get-Content -LiteralPath (Join-Path $nativeDir 'SongSelector_settings.json') -Raw | ConvertFrom-Json
        if ($settings.'Rating display version' -ne 1) { throw 'Settings were not saved on close.' }
        $nativeResult = [ordered]@{
            ok = $true; executable = $Exe; window_found = $true; responsive = $true
            closed_cleanly = $true; exit_code = $process.ExitCode; settings_saved = $true
        }
        $nativeResult | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runDir 'native-results.json') -Encoding UTF8
        $nativeResult | ConvertTo-Json
    } finally {
        foreach ($id in $ownedIds) {
            if (Get-Process -Id $id -ErrorAction SilentlyContinue) { Stop-Process -Id $id -ErrorAction SilentlyContinue }
        }
    }
} finally {
    foreach ($name in $savedEnv.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnv[$name]) }
}
Write-Host ''
Write-Host 'Release verification passed.'
