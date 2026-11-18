<#
.SYNOPSIS
    Build the DearPyGui frontend into bin\T48_eMMC_dpg_v<version>.exe.
    Version: 1.0.0
    Updated: 2026-11-19

.DESCRIPTION
    Requires xgecu_env with pyinstaller installed (install_xgecu_prog.ps1
    installs the runtime; add pyinstaller via
      uv pip install --python xgecu_env\Scripts\python.exe pyinstaller
    or run this script with -InstallBuildDeps).
#>

param(
    [switch]$InstallBuildDeps
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "Xgecu Prog Build"

$ROOT = $PSScriptRoot
$PYTHON = Join-Path $ROOT "xgecu_env\Scripts\python.exe"
$UvExe = Join-Path $ROOT "uv.exe"
$OutDir = Join-Path $ROOT "bin"
$Spec = Join-Path $ROOT "T48_eMMC_dpg.spec"

# isolation, same as install/run scripts
$CacheDir = Join-Path $ROOT ".cache"
$env:UV_CACHE_DIR = Join-Path $CacheDir "uv"
$env:PIP_CACHE_DIR = Join-Path $CacheDir "pip"
$TmpDir = Join-Path $CacheDir "tmp"
if (-not (Test-Path $TmpDir)) { New-Item -ItemType Directory -Force -Path $TmpDir | Out-Null }
$env:TMP = $TmpDir
$env:TEMP = $TmpDir

if (-not (Test-Path $PYTHON)) {
    Write-Host "[ERROR] xgecu_env not found. Run install_xgecu_prog.ps1 first." -ForegroundColor Red
    exit 1
}

if ($InstallBuildDeps) {
    if (-not (Test-Path $UvExe)) {
        Write-Host "[ERROR] uv.exe not found in project root." -ForegroundColor Red
        exit 1
    }
    Write-Host "[INFO] Installing PyInstaller..." -ForegroundColor Cyan
    & $UvExe pip install --python $PYTHON pyinstaller==6.22.3
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

& $PYTHON -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] PyInstaller is not installed in xgecu_env." -ForegroundColor Red
    Write-Host "        Run again with -InstallBuildDeps." -ForegroundColor Red
    exit 1
}

$version = (Get-Content (Join-Path $ROOT ".version.cfg") -Raw).Trim()
if (-not $version) { $version = "0.0.0" }
$exeName = "T48_eMMC_dpg_v$version.exe"
Write-Host "[INFO] Building $exeName (version $version)..." -ForegroundColor Cyan

Set-Location $ROOT
& $PYTHON -m PyInstaller --noconfirm --distpath (Join-Path $ROOT ".cache\pyinstaller") --workpath (Join-Path $ROOT ".cache\pyinstaller_work") $Spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] PyInstaller build failed." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Force -Path $OutDir | Out-Null }
$built = Join-Path (Join-Path $ROOT ".cache\pyinstaller") "T48_eMMC_dpg.exe"
if (-not (Test-Path $built)) {
    Write-Host "[ERROR] Built exe not found: $built" -ForegroundColor Red
    exit 1
}
$target = Join-Path $OutDir $exeName
Copy-Item $built $target -Force

$sizeMb = [math]::Round((Get-Item $target).Length / 1MB, 1)
Write-Host "[OK] Built: $target ($sizeMb MB)" -ForegroundColor Green
Write-Host "[i] Smoke check: launch it and confirm the window opens." -ForegroundColor Cyan
exit 0
