<#
.SYNOPSIS
    Xgecu Prog Installer & Portable Launcher by Soror L.'.L.'.
    Version: 2.1.0
    Updated: 2026-11-19

.DESCRIPTION
    Patchnote v2.1.0 (Soror L.'.L.'.):
      [*] Rewritten from conda to portable uv: uv.exe downloaded into the
          project root, caches isolated in .cache.
      [+] Menu: install / run (DPG or legacy Kivy) / reinstall / exit.
      [+] Font set check in assets\fonts with fallback warning.
      [+] Critical import check (dearpygui, PIL, kivy) into logs\install.log.
      [+] Stale-process kill by xgecu_env python path and 'Xgecu' window
          title at install start; broken env quarantine by rename.
    Patchnote v2.0.0 (Soror L.'.L.'.):
      [+] Conda replaced by uv; xgecu_env via "uv venv --python 3.11"
          with python.exe hardlink for env\python.exe path compatibility.
      [+] uv release URL fixed to github.com/astral-sh/uv (releases.astral.sh
          mirror returned 404 HTML silently).
      [*] uv pip does not know --no-warn-script-location: dropped.
      [-] Conda dependency removed (Miniforge/Anaconda no longer required).
    Patchnote v1.0.0 (Soror L.'.L.'.):
      [+] Initial release: env conda env, requirements install, folder and
          font checks, T48 WinUSB driver note.
#>

$ScriptPath = $PSScriptRoot
if (-not $ScriptPath) { $ScriptPath = "." }
Set-Location $ScriptPath
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "Xgecu Prog Portable Launcher"

# ==========================================================
# PORTABILITY ISOLATION
# ==========================================================
$EnvName = "xgecu_env"
$CacheDir = Join-Path $ScriptPath ".cache"
$UvCacheDir = Join-Path $CacheDir "uv"
$PipCacheDir = Join-Path $CacheDir "pip"
$TmpDir = Join-Path $CacheDir "tmp"
@($CacheDir, $UvCacheDir, $PipCacheDir, $TmpDir) | ForEach-Object {
    if (-not (Test-Path $_)) { New-Item -ItemType Directory -Force -Path $_ | Out-Null }
}
$env:UV_CACHE_DIR = $UvCacheDir
$env:PIP_CACHE_DIR = $PipCacheDir
$env:TMP = $TmpDir
$env:TEMP = $TmpDir
$env:UV_PYTHON_INSTALL_DIR = Join-Path $CacheDir "uv_python"

# ==========================================================
# Helpers
# ==========================================================
function Write-Status {
    param([string]$Message, [string]$Type = "INFO")
    $color = switch ($Type) {
        "INFO"   { "Cyan" }
        "WARN"   { "Yellow" }
        "ERROR"  { "Red" }
        "SUCCESS"{ "Green" }
        default  { "White" }
    }
    Write-Host "[$Type] $Message" -ForegroundColor $color
    $logLine = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [$Type] $Message"
    $LogsPath = Join-Path $ScriptPath "logs"
    if (!(Test-Path $LogsPath)) { New-Item -ItemType Directory -Path $LogsPath -Force | Out-Null }
    Add-Content -Path (Join-Path $LogsPath "install.log") -Value $logLine -Encoding UTF8
}

function Test-Command {
    param([string]$Cmd)
    return $null -ne (Get-Command $Cmd -ErrorAction SilentlyContinue)
}

function Test-IsInstalled {
    return (Test-Path (Join-Path $ScriptPath $EnvName "Scripts\python.exe"))
}

function Invoke-WithRetry {
    param([scriptblock]$Script, [int]$MaxAttempts = 3, [int]$DelaySec = 5)
    $attempt = 0
    while ($attempt -lt $MaxAttempts) {
        try {
            & $Script
            if ($LASTEXITCODE -eq 0) { return $true }
        } catch {}
        $attempt++
        if ($attempt -ge $MaxAttempts) { return $false }
        Write-Status "Retry in $DelaySec s... (attempt $attempt of $MaxAttempts)" "WARN"
        Start-Sleep -Seconds $DelaySec
    }
    return $false
}

function Invoke-UvPipInstall {
    param([string]$Command)
    Write-Host "   > uv pip install $Command" -ForegroundColor DarkGray
    $process = Start-Process -FilePath $UvExePath -ArgumentList "pip install --python `"$PythonExePath`" $Command" -NoNewWindow -Wait -PassThru
    return $process.ExitCode
}

# ==========================================================
# Install
# ==========================================================
function Kill-StaleProcesses {
    # Orphaned Xgecu Prog instances hold T48 USB handles and env files.
    # Match by project-local xgecu_env python.exe path or by a window
    # title containing 'Xgecu'. Own ancestors are never touched.
    Write-Status "Killing stale Xgecu Prog processes..." "INFO"
    foreach ($p in @(Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction SilentlyContinue)) {
        if ($p.ExecutablePath -and $p.ExecutablePath.ToLower().StartsWith($ScriptPath.ToLower()) -and $p.ExecutablePath.ToLower().Contains("xgecu_env")) {
            Write-Status "Killing stale process: PID=$($p.ProcessId)"
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    Get-Process -Name python -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -match 'Xgecu' } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

function Install-XgecuProg {
    param([bool]$Reinstall = $false)

    Kill-StaleProcesses

    if ($Reinstall) {
        Write-Status "Reinstall: removing existing environment..." "WARN"
        if (Test-Path $EnvName) { Remove-Item -Path $EnvName -Recurse -Force }
        if (Test-Path $EnvName) {
            # loaded DLLs keep a broken env undeletable; quarantine by rename
            $quar = "$EnvName.broken.$(Get-Random)"
            try {
                Rename-Item -Path $EnvName -NewName $quar -ErrorAction Stop
                Write-Status "Undeletable broken environment quarantined as $quar." "WARN"
                Write-Status "Delete that folder manually once no process uses it." "WARN"
            } catch {
                Write-Status "Environment files are in use (running Xgecu Prog, IDE or an open terminal in xgecu_env)." "ERROR"
                Write-Status "Close them and run Reinstall again." "ERROR"
                return $false
            }
        }
    }

    # ---- 0. uv ----
    $UvVersion = "0.11.6"
    $UvZipUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip"
    $global:UvExePath = Join-Path $ScriptPath "uv.exe"
    if (-not (Test-Path $UvExePath)) {
        Write-Status "Downloading uv $UvVersion..." "INFO"
        $uvZip = Join-Path $ScriptPath "uv.zip"
        $dlOk = Invoke-WithRetry -Script {
            Invoke-WebRequest -Uri $UvZipUrl -OutFile $uvZip -UseBasicParsing -ErrorAction Stop
            if (-not (Test-Path $uvZip)) { throw "download failed" }
            if ((Get-Item $uvZip).Length -lt 1000) { throw "download corrupted" }
        } -MaxAttempts 3 -DelaySec 5
        if (-not $dlOk) {
            Write-Status "Failed to download uv." "ERROR"
            return $false
        }
        $uvTmp = Join-Path $CacheDir "uv_tmp"
        if (Test-Path $uvTmp) { Remove-Item -Recurse -Force $uvTmp }
        Expand-Archive -Path $uvZip -DestinationPath $uvTmp -Force
        $extractedDir = Get-ChildItem -Path $uvTmp -Directory | Select-Object -First 1
        if (-not $extractedDir) { $extractedDir = @{ FullName = $uvTmp } }
        Copy-Item (Join-Path $extractedDir.FullName "uv.exe") $UvExePath
        Copy-Item (Join-Path $extractedDir.FullName "uvx.exe") (Join-Path $ScriptPath "uvx.exe") -ErrorAction SilentlyContinue
        Remove-Item $uvTmp -Recurse -Force
        Remove-Item $uvZip -Force
        Write-Status "uv $UvVersion ready." "SUCCESS"
    } else {
        Write-Status "uv already present." "SUCCESS"
    }

    # ---- 1. venv ----
    $PythonVersion = "3.11"
    $EnvDirPath = Join-Path $ScriptPath $EnvName
    if (-not (Test-Path (Join-Path $EnvDirPath "Scripts\python.exe"))) {
        # leftover of a broken/aborted install - remove before uv venv,
        # which refuses to reuse an existing directory; quarantine on lock
        if (Test-Path $EnvDirPath) {
            Remove-Item -Path $EnvDirPath -Recurse -Force -ErrorAction SilentlyContinue
            if (Test-Path $EnvDirPath) {
                $quar = "$EnvDirPath.broken.$(Get-Random)"
                try {
                    Rename-Item -Path $EnvDirPath -NewName $quar -ErrorAction Stop
                    Write-Status "Undeletable broken environment quarantined as $quar." "WARN"
                } catch {
                    Write-Status "Broken environment at $EnvDirPath cannot be removed - files in use." "ERROR"
                    return $false
                }
            }
        }
        Write-Status "Creating virtual environment ($EnvName, Python $PythonVersion)..." "INFO"
        & $UvExePath venv $EnvDirPath --python $PythonVersion
        if ($LASTEXITCODE -ne 0) {
            Write-Status "Failed to create the environment." "ERROR"
            return $false
        }
    } else {
        Write-Status "Environment already present." "SUCCESS"
    }
    $pythonTarget = Join-Path $EnvDirPath "Scripts\python.exe"
    $pythonLink = Join-Path $EnvDirPath "python.exe"
    if (-not (Test-Path $pythonLink)) {
        try { New-Item -ItemType HardLink -Path $pythonLink -Target $pythonTarget -ErrorAction Stop | Out-Null } catch {
            Set-Content -Path $pythonLink -Value "@`"%~dp0Scripts\python.exe`" %*" -Encoding ASCII
        }
    }
    $global:PythonExePath = $pythonTarget
    $ver = (& $PythonExePath --version 2>$null) -replace "`r|`n", ""
    Write-Status "Python in environment: $ver" "INFO"
    if ($ver -notmatch "Python 3\.11\.") {
        Write-Status "Expected Python 3.11, found: $ver" "WARN"
    }

    # ---- 2. Project layout ----
    foreach ($d in @("logs", "temp", "assets\fonts")) {
        if (!(Test-Path (Join-Path $ScriptPath $d))) { New-Item -ItemType Directory -Force -Path (Join-Path $ScriptPath $d) | Out-Null }
    }

    # ---- 3. Fonts ----
    $Fonts = @("ModeSevenBETAVHS.ttf", "ModeSevenBETAVHS20212.ttf",
               "VCR_OSD_Mono_RUS-VHS.ttf", "JetBrainsMonoNerdFont-Regular.ttf")
    $FontsMissing = @($Fonts | Where-Object { -not (Test-Path (Join-Path $ScriptPath "assets\fonts\$_")) })
    if ($FontsMissing.Count -gt 0) {
        Write-Status "Missing fonts: $($FontsMissing -join ', ')" "WARN"
        Write-Status "DPG fallback will use consola.ttf / segoeui.ttf / arial.ttf" "WARN"
    } else {
        Write-Status "Full font set present." "SUCCESS"
    }

    # ---- 4. Dependencies ----
    $ReqFile = Join-Path $ScriptPath "requirements.txt"
    if (Test-Path $ReqFile) {
        Write-Status "Installing dependencies (uv pip install -r requirements.txt)..." "INFO"
        $pipOk = Invoke-WithRetry -Script {
            Invoke-UvPipInstall "-r `"$ReqFile`""
            if ($LASTEXITCODE -ne 0) { throw "uv pip install failed" }
        }
        if ($pipOk) { Write-Status "Dependencies installed." "SUCCESS" }
        else { Write-Status "Dependency install reported warnings (see logs\install.log)" "WARN" }
    } else {
        Write-Status "requirements.txt not found in project root" "WARN"
    }

    # ---- 5. Critical imports ----
    Write-Status "Checking critical imports..." "INFO"
    $Modules = @(
        "dearpygui.dearpygui",
        "PIL",
        "kivy"
    )
    $AllOK = $true
    foreach ($mod in $Modules) {
        & $PythonExePath -c "import $mod" 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Status "    [+] $mod" "SUCCESS"
        } else {
            if ($mod -eq "kivy") {
                Write-Status "    [?] kivy not installed (legacy gui.py will not run; DPG will)" "WARN"
            } else {
                Write-Status "    [!] $mod NOT FOUND" "ERROR"
                $AllOK = $false
            }
        }
    }
    if ($AllOK) { Write-Status "All critical imports OK." "SUCCESS" }
    else { Write-Status "Import error. See logs\install.log" "ERROR" }

    Write-Status "Installation complete!" "SUCCESS"
    return $true
}

# ==========================================================
# Run
# ==========================================================
function Start-XgecuProg {
    param([switch]$Legacy)

    if (-not (Test-IsInstalled)) {
        Write-Status "Environment is not installed. Run installation first." "ERROR"
        return $false
    }
    $PythonExePath = Join-Path $ScriptPath $EnvName "Scripts\python.exe"
    Write-Status "Starting Xgecu Prog ($(if ($Legacy) { 'legacy Kivy' } else { 'DearPyGui' }))..." "INFO"
    Set-Location $ScriptPath
    $env:PYTHONUNBUFFERED = "1"
    if ($Legacy) {
        & $PythonExePath "-X" "utf8" "src\gui.py"
    } else {
        & $PythonExePath "-X" "utf8" "src\gui_dpg.py"
    }
    return $true
}

# ==========================================================
# Menu
# ==========================================================
function Show-Menu {
    Clear-Host
    Write-Host " ===========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  T48 eMMC Flasher - Xgecu Prog" -ForegroundColor Yellow
    Write-Host "  Portable Launcher v2.1.0 (uv)" -ForegroundColor Green
    Write-Host "  Python 3.11 + DearPyGui 2.3" -ForegroundColor Cyan
    Write-Host "  ===========================================" -ForegroundColor Cyan
    Write-Host ""
    $installed = Test-IsInstalled
    if ($installed) {
        Write-Host "  1) Start Xgecu Prog (DearPyGui)" -ForegroundColor Yellow
        Write-Host "  2) Start legacy GUI (Kivy gui.py)" -ForegroundColor Yellow
        Write-Host "  3) Reinstall environment (remove and set up again)" -ForegroundColor Yellow
        Write-Host "  4) Exit" -ForegroundColor Gray
    } else {
        Write-Host "  1) Install Xgecu Prog (first-time setup)" -ForegroundColor Yellow
        Write-Host "  2) Exit" -ForegroundColor Gray
    }
    Write-Host ""
    $choice = Read-Host "Your choice"
    return $choice, $installed
}

# ==========================================================
# Main loop
# ==========================================================
do {
    $choice, $installed = Show-Menu
    switch ($choice) {
        "1" {
            if (-not $installed) {
                Write-Status "Starting installation..." "INFO"
                Install-XgecuProg -Reinstall $false | Out-Null
            } else {
                Start-XgecuProg
            }
        }
        "2" {
            if ($installed) {
                Write-Status "Starting reinstall..." "INFO"
                Install-XgecuProg -Reinstall $true | Out-Null
            } else {
                Write-Status "Exit." "INFO"
                exit 0
            }
        }
        "3" {
            if ($installed) {
                Start-XgecuProg -Legacy
            } else {
                Write-Status "Invalid choice." "WARN"
            }
        }
        "4" {
            Write-Status "Exit." "INFO"
            exit 0
        }
        default {
            Write-Status "Invalid choice." "WARN"
        }
    }
    if ($choice -ne "4") {
        Write-Host "`nPress any key to return to the menu..." -ForegroundColor Gray
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    }
} while ($true)
