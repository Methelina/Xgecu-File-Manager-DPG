:: Xgecu Prog Runtime Launcher by Soror L.'.L.'.
:: Version: 3.0.0
:: Updated: 2026-11-19
::
:: Full functional equivalent of run_xgecu_prog.ps1 (no PowerShell).
:: Patchnote v3.0.0 (Soror L.'.L.'.):
::   [+] Standalone cmd implementation: env check with auto-install
::       (delegates to the install bat menu), stale-process kill by
::       project-local python.exe path or 'Xgecu' window title, console
::       auto-close 15 s after exit with keep-open option, -Legacy
::       switch for the Kivy gui.py during the DearPyGui migration.
:: Patchnote v2.1.0 (Soror L.'.L.'.):
::   [+] Was a thin wrapper over run_xgecu_prog.ps1.
@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Xgecu Prog Launcher
set "ROOT=%~dp0"
set "ENVDIR=%ROOT%xgecu_env"
set "PYTHON=%ENVDIR%\Scripts\python.exe"
set "CACHE=%ROOT%.cache"
set "TMPD=%CACHE%\tmp"
if not exist "%TMPD%" mkdir "%TMPD%" >nul 2>&1
set "UV_CACHE_DIR=%CACHE%\uv"
set "PIP_CACHE_DIR=%CACHE%\pip"
set "TMP=%TMPD%"
set "TEMP=%TMPD%"
set "PYTHONUNBUFFERED=1"
:: ============================================================
:: Environment check (auto-install when missing)
:: ============================================================
if exist "%PYTHON%" goto env_ok
echo [INFO] Launcher: Environment not found: %ENVDIR%
echo [INFO] Launcher: Delegating to install_xgecu_prog.bat...
call "%ROOT%install_xgecu_prog.bat"
if not exist "%PYTHON%" (
    echo [ERROR] Launcher: Installation failed. See logs\install.log
    pause
    exit /b 1
)
:: install bat runs its own menu loop; if it returns with an env present
:: the user may have started the app from there already.
:env_ok
for /f "usebackq delims=" %%V in (`"%PYTHON%" --version 2^>nul`) do set "PYVER=%%V"
echo [INFO] Launcher: Python: %PYVER%
:: ============================================================
:: Stale processes
:: ============================================================
:: Orphaned instances keep T48 USB handles open; a new window would fail
:: to claim the programmer. Match by project-local python.exe path or by
:: a window title containing 'Xgecu'.
set "KILLED=0"
for /f "tokens=2 delims=," %%P in ('wmic process where "name='python.exe'" get ProcessId^,ExecutablePath /format:csv 2^>nul ^| find /i "xgecu_env"') do (
    echo [RUNNER] [INFO] Killing stale process: PID=%%P ^(project env^)
    taskkill /F /PID %%P >nul 2>&1
    set "KILLED=1"
)
taskkill /F /FI "WINDOWTITLE eq Xgecu*" /IM python.exe >nul 2>&1
if "%KILLED%"=="1" (
    timeout /t 1 /nobreak >nul
) else (
    echo [RUNNER] [INFO] No stale processes found.
)
:: ============================================================
:: Run
:: ============================================================
pushd "%ROOT%"
if "%~1"=="-Legacy" goto run_legacy
echo [INFO] Launcher: Starting Xgecu Prog (DearPyGui)...
"%PYTHON%" -X utf8 "src\gui_dpg.py"
set "EXITCODE=%ERRORLEVEL%"
goto app_done
:run_legacy
echo [INFO] Launcher: Starting legacy Kivy GUI (gui.py)...
"%PYTHON%" -X utf8 "src\gui.py"
set "EXITCODE=%ERRORLEVEL%"
:app_done
popd
echo [RUNNER] App exited with code %EXITCODE%.
choice /C CN /T 15 /D C /N /M "Console closes in 15 s. [C]=close now, [N]=keep open"
if errorlevel 2 pause
endlocal
exit /b %EXITCODE%
