<#
.SYNOPSIS
    Xgecu Prog portable installer & launcher (uv-based).
    Version: 2.1.0
    Updated: 2026-11-18

.DESCRIPTION
    Portable, idempotent setup:
      - uv.exe is downloaded into the project root;
      - uv/pip/TMP caches are isolated inside .cache;
      - venv xgecu_env (Python 3.11) is created by uv, python.exe is
        also exposed as xgecu_env\python.exe (hardlink);
      - dependencies are installed from requirements.txt via uv pip.
    Menu: install, run, reinstall, exit.
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
function Install-XgecuProg {
    param([bool]$Reinstall = $false)

    if ($Reinstall) {
        Write-Status "Reinstall: removing existing environment..." "WARN"
        if (Test-Path $EnvName) { Remove-Item -Path $EnvName -Recurse -Force }
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
        & $PythonExePath "-X" "utf8" "gui.py"
    } else {
        & $PythonExePath "-X" "utf8" "gui_dpg.py"
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
