<#
.SYNOPSIS
    Xgecu Prog launcher.
    Version: 2.1.0
    Updated: 2026-11-18

.DESCRIPTION
    Checks xgecu_env (delegates to install_xgecu_prog.ps1 when missing),
    kills stale processes from a previous run, sets environment variables
    and starts gui_dpg.py. -Legacy starts the Kivy gui.py instead.
#>

param(
    [switch]$Legacy
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "Xgecu Prog Launcher"

Write-Host @"

  ===========================================
    Xgecu Prog Launcher
    Version: 2.1.0
  ===========================================

"@

$ROOT = $PSScriptRoot
$ENVDIR = Join-Path $ROOT "xgecu_env"
$PYTHON = Join-Path $ENVDIR "Scripts\python.exe"
$LOGS = Join-Path $ROOT "logs"

$CacheDir = Join-Path $ROOT ".cache"
$TmpDir = Join-Path $CacheDir "tmp"
if (-not (Test-Path $TmpDir)) { New-Item -ItemType Directory -Force -Path $TmpDir | Out-Null }
$env:UV_CACHE_DIR = Join-Path $CacheDir "uv"
$env:PIP_CACHE_DIR = Join-Path $CacheDir "pip"
$env:TMP = $TmpDir
$env:TEMP = $TmpDir

$env:PYTHONUNBUFFERED = "1"

# ==========================================================
# Environment check (auto-install when missing)
# ==========================================================
if (-not (Test-Path $PYTHON)) {
    Write-Host "[INFO] Launcher: Environment not found: $ENVDIR" -ForegroundColor Yellow
    Write-Host "[INFO] Launcher: Delegating to install_xgecu_prog.ps1..." -ForegroundColor Cyan
    & (Join-Path $ROOT "install_xgecu_prog.ps1")
    if (-not (Test-Path $PYTHON)) {
        Write-Host "[ERROR] Launcher: Installation failed. See logs\install.log" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}
$ver = (& $PYTHON --version 2>$null) -replace "`r|`n", ""
Write-Host "[INFO] Launcher: Python: $ver"

# ==========================================================
# Zombie processes
# ==========================================================
# Orphaned instances keep T48 USB handles open; a new window would fail
# to claim the programmer. Match by project-local python.exe path or by
# a window title containing 'Xgecu'. Own ancestors are never touched.
$projectPython = $PYTHON.ToLowerInvariant()
$zombiePids = @{}

$ancestorPids = @{}
$cursor = $PID
for ($i = 0; $i -lt 16 -and $cursor; $i++) {
    if ($ancestorPids.ContainsKey([uint32]$cursor)) { break }
    $ancestorPids[[uint32]$cursor] = $true
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $cursor" -ErrorAction SilentlyContinue
    if (-not $proc) { break }
    $cursor = $proc.ParentProcessId
}

foreach ($p in @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue)) {
    if ($ancestorPids.ContainsKey([uint32]$p.ProcessId)) { continue }
    if ($p.ExecutablePath -and $p.ExecutablePath.ToLowerInvariant() -eq $projectPython) {
        $zombiePids[[uint32]$p.ProcessId] = "exe=$($p.ExecutablePath)"
    }
}
foreach ($gp in @(Get-Process -Name python -ErrorAction SilentlyContinue)) {
    if ($ancestorPids.ContainsKey([uint32]$gp.Id)) { continue }
    if ($gp.MainWindowTitle -match 'Xgecu') {
        $zombiePids[[uint32]$gp.Id] = "title='$($gp.MainWindowTitle)'"
    }
}

if ($zombiePids.Count -gt 0) {
    foreach ($entry in $zombiePids.GetEnumerator()) {
        Write-Host "[RUNNER] [INFO] Killing stale process: PID=$($entry.Key) $($entry.Value)"
        Stop-Process -Id $entry.Key -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 500
} else {
    Write-Host "[RUNNER] [INFO] No stale processes found."
}

# ==========================================================
# Run
# ==========================================================
Set-Location $ROOT
if ($Legacy) {
    Write-Host "[INFO] Launcher: Starting legacy Kivy GUI (gui.py)..." -ForegroundColor Yellow
    & $PYTHON "-X" "utf8" "gui.py"
} else {
    Write-Host "[INFO] Launcher: Starting Xgecu Prog (DearPyGui)..." -ForegroundColor Cyan
    & $PYTHON "-X" "utf8" "gui_dpg.py"
}
$exitCode = $LASTEXITCODE

# ==========================================================
# Auto-close console (any key cancels)
# ==========================================================
Write-Host "[RUNNER] App exited with code $exitCode. Console closes in 15 s - press any key to keep it open..."
$autoCloseCancelled = $false
for ($i = 15; $i -ge 1; $i--) {
    try {
        if ([Console]::KeyAvailable) {
            [void][Console]::ReadKey($true)
            $autoCloseCancelled = $true
            break
        }
    } catch {
        break
    }
    Write-Host ("`rClosing in {0,2} s...  " -f $i) -NoNewline
    Start-Sleep -Seconds 1
}
if ($autoCloseCancelled) {
    Write-Host ""
    Write-Host "[RUNNER] Auto-close cancelled - console stays open."
    Read-Host "Press Enter to exit"
}
exit $exitCode
