:: Xgecu Prog Installer & Portable Launcher by Soror L.'.L.'.
:: Version: 3.2.0
:: Updated: 2026-11-26
::
:: Full functional equivalent of install_xgecu_prog.ps1 (no PowerShell).
:: Patchnote v3.2.0 (Soror L.'.L.'.):
::   [+] WinFsp driver step (4c): downloads winfsp msi from the official
::       GitHub release and installs best-effort with a UAC prompt; declined
::       install only disables the Data Browser drive-letter mount.
::   [+] winfspy added to the critical import check.
::   [*] Fixed v3.1.0 latent bug: the :step_imports label was missing, so
::       any `goto step_imports` silently terminated the installer.
:: Patchnote v3.1.0 (Soror L.'.L.'.):
::   [-] Removed legacy Kivy GUI support (menu options removed).
::       DPG-only from this version forward.
:: Patchnote v3.0.0 (Soror L.'.L.'.):
::   [+] Standalone cmd implementation: menu, portable uv download (curl),
::       zip extraction via tar, venv creation, hardlink python.exe,
::       dependency install with retry, font and import checks,
::       logs\install.log - all in pure batch.
::   [+] Stale-process kill by project env path and 'Xgecu' window title
::       at install start; broken env quarantine by rename.
:: Patchnote v2.1.0 (Soror L.'.L.'.):
::   [+] Was a thin wrapper over install_xgecu_prog.ps1.
@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Xgecu Prog Installer
set "ROOT=%~dp0"
set "ENVDIR=%ROOT%xgecu_env"
set "PYTHON=%ENVDIR%\Scripts\python.exe"
set "UVEXE=%ROOT%uv.exe"
set "CACHE=%ROOT%.cache"
set "UVCACHE=%CACHE%\uv"
set "PIPCACHE=%CACHE%\pip"
set "TMPD=%CACHE%\tmp"
set "LOGDIR=%ROOT%logs"
set "LOGF=%LOGDIR%\install.log"
set "FONTS=%ROOT%assets\fonts"
set "REQ=%ROOT%requirements.txt"
set "UVVER=0.11.6"
set "UVURL=https://github.com/astral-sh/uv/releases/download/%UVVER%/uv-x86_64-pc-windows-msvc.zip"
if not exist "%CACHE%" mkdir "%CACHE%" >nul 2>&1
if not exist "%UVCACHE%" mkdir "%UVCACHE%" >nul 2>&1
if not exist "%PIPCACHE%" mkdir "%PIPCACHE%" >nul 2>&1
if not exist "%TMPD%" mkdir "%TMPD%" >nul 2>&1
set "UV_CACHE_DIR=%UVCACHE%"
set "PIP_CACHE_DIR=%PIPCACHE%"
set "TMP=%TMPD%"
set "TEMP=%TMPD%"
set "UV_PYTHON_INSTALL_DIR=%CACHE%\uv_python"
:: ============================================================
:: Main menu
:: ============================================================
:menu
cls
echo  ===========================================
echo.
echo   T48 eMMC Flasher - Xgecu Prog
echo   Portable Installer v3.2.0 (uv)
echo   Python 3.11 + DearPyGui 2.3
echo   ===========================================
echo.
call :is_installed
if "%INSTALLED%"=="1" (
    echo   1^) Start Xgecu Prog ^(DearPyGui^)
    echo   2^) Reinstall environment
    echo   3^) Exit
) else (
    echo   1^) Install Xgecu Prog ^(first-time setup^)
    echo   2^) Exit
)
echo.
set /p CHOICE=Your choice:
if not defined CHOICE goto do_exit
if "%INSTALLED%"=="1" goto menu_installed
if "%CHOICE%"=="1" goto do_install
if "%CHOICE%"=="2" goto do_exit
goto menu
:menu_installed
if "%CHOICE%"=="1" goto run_dpg
if "%CHOICE%"=="2" goto do_reinstall
if "%CHOICE%"=="3" goto do_exit
goto menu
:do_exit
echo [INFO] Exit.
endlocal
exit /b 0
:do_install
echo [INFO] Starting installation...
call :kill_stale
call :install 0
goto ask_return
:do_reinstall
echo [WARN] Reinstall: killing stale Xgecu Prog processes...
call :kill_stale
echo [WARN] Removing existing environment...
if exist "%ENVDIR%" rmdir /s /q "%ENVDIR%"
if exist "%ENVDIR%" call :quarantine_env
if exist "%ENVDIR%" (
    call :log ERROR "Environment files are in use ^(running Xgecu Prog, IDE or an open terminal in xgecu_env^)."
    call :log ERROR "Close them and run Reinstall again."
    goto ask_return
)
call :install 1
goto ask_return
:run_dpg
call :check_installed_or_exit
echo [INFO] Starting Xgecu Prog (DearPyGui)...
pushd "%ROOT%"
set "PYTHONUNBUFFERED=1"
"%PYTHON%" -X utf8 "src\gui_dpg.py"
set "EXITCODE=%ERRORLEVEL%"
popd
goto app_done
:app_done
echo [RUNNER] App exited with code %EXITCODE%.
choice /C CN /T 15 /D C /N /M "Console closes in 15 s. [C]=close now, [N]=keep open"
if errorlevel 2 pause
exit /b %EXITCODE%
:ask_return
echo.
echo Press any key to return to the menu...
pause >nul
goto menu
:: ============================================================
:: Functions
:: ============================================================
:kill_stale
set "KILLED=0"
for /f "tokens=2 delims=," %%P in ('wmic process where "name='python.exe'" get ProcessId^,ExecutablePath /format:csv 2^>nul ^| find /i "xgecu_env"') do (
    echo [RUNNER] [INFO] Killing stale process: PID=%%P ^(project env^)
    taskkill /F /PID %%P >nul 2>&1
    set "KILLED=1"
)
taskkill /F /FI "WINDOWTITLE eq Xgecu*" /IM python.exe >nul 2>&1
if "%KILLED%"=="1" timeout /t 1 /nobreak >nul
exit /b 0
:is_installed
set "INSTALLED=0"
if exist "%PYTHON%" set "INSTALLED=1"
exit /b 0
:check_installed_or_exit
call :is_installed
if "%INSTALLED%"=="1" exit /b 0
echo [ERROR] Environment is not installed. Run installation first.
pause
exit /b 1
:log
echo [%~1] %~2
if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>&1
for /f "tokens=1-2 delims=." %%a in ("%TIME%") do set "TSTAMP=%%a"
echo [%DATE% %TSTAMP%] [%~1] %~2>>"%LOGF%"
exit /b 0
:install
:: %1 = 1 when called from reinstall (env already removed)
if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>&1
:: ---- step 0: uv.exe ----
if exist "%UVEXE%" (
    call :log SUCCESS "uv already present."
    goto step_venv
)
call :log INFO "Downloading uv %UVVER%..."
set "UVZIP=%ROOT%uv.zip"
curl -L -f --retry 3 --retry-delay 5 -o "%UVZIP%" "%UVURL%"
if errorlevel 1 (
    call :log ERROR "Failed to download uv."
    goto install_fail
)
for %%F in ("%UVZIP%") do set "ZIPSIZE=%%~zF"
if %ZIPSIZE% LSS 1000 (
    call :log ERROR "Download corrupted (size %ZIPSIZE%)."
    goto install_fail
)
set "UVTMP=%CACHE%\uv_tmp"
if exist "%UVTMP%" rmdir /s /q "%UVTMP%"
mkdir "%UVTMP%" >nul 2>&1
tar -xf "%UVZIP%" -C "%UVTMP%"
if errorlevel 1 (
    call :log ERROR "Failed to extract uv archive."
    goto install_fail
)
copy /y "%UVTMP%\uv.exe" "%UVEXE%" >nul
copy /y "%UVTMP%\uvx.exe" "%ROOT%uvx.exe" >nul 2>&1
rmdir /s /q "%UVTMP%"
del /q "%UVZIP%" >nul 2>&1
call :log SUCCESS "uv %UVVER% ready."
goto step_venv
:install_fail
call :log ERROR "Installation aborted."
goto ask_return
:quarantine_env
:: loaded DLLs keep a broken env undeletable (e.g. a foreign process
:: loaded our pywin32 files); rename it aside and start fresh
set "QUAR=%ENVDIR%_broken_%RANDOM%"
ren "%ENVDIR%" "%QUAR%" >nul 2>&1
if not errorlevel 1 (
    call :log WARN "Undeletable broken environment quarantined as %QUAR%."
    call :log WARN "Delete that folder manually once no process uses it."
)
exit /b 0
:: ---- step 1: venv ----
:step_venv
if exist "%PYTHON%" (
    call :log SUCCESS "Environment already present."
    goto py_link_ok
)
if exist "%ENVDIR%" rmdir /s /q "%ENVDIR%"
if exist "%ENVDIR%" call :quarantine_env
if exist "%ENVDIR%" (
    call :log ERROR "Broken environment at %ENVDIR% cannot be removed - files in use."
    goto install_fail
)
call :log INFO "Creating virtual environment (xgecu_env, Python 3.11)..."
"%UVEXE%" venv "%ENVDIR%" --python 3.11
if errorlevel 1 (
    call :log ERROR "Failed to create the environment."
    goto install_fail
)
if exist "%ENVDIR%\python.exe" goto py_link_ok
mklink /H "%ENVDIR%\python.exe" "%PYTHON%" >nul 2>&1
if errorlevel 1 (
    copy /y "%PYTHON%" "%ENVDIR%\python.exe" >nul 2>&1
)
:py_link_ok
for /f "usebackq delims=" %%V in (`"%PYTHON%" --version 2^>nul`) do set "PYVER=%%V"
call :log INFO "Python in environment: %PYVER%"
echo %PYVER% | find "3.11." >nul
if errorlevel 1 call :log WARN "Expected Python 3.11, found: %PYVER%"
:: ---- step 2: project layout ----
if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul
if not exist "%ROOT%temp" mkdir "%ROOT%temp" >nul
if not exist "%FONTS%" mkdir "%FONTS%" >nul
:: ---- step 3: fonts ----
set "FONTS_MISSING="
for %%F in (ModeSevenBETAVHS.ttf ModeSevenBETAVHS20212.ttf VCR_OSD_Mono_RUS-VHS.ttf JetBrainsMonoNerdFont-Regular.ttf) do (
    if not exist "%FONTS%\%%F" set "FONTS_MISSING=!FONTS_MISSING! %%F"
)
setlocal EnableDelayedExpansion
if defined FONTS_MISSING (
    call :log WARN "Missing fonts:!FONTS_MISSING!"
    call :log WARN "DPG fallback will use consola.ttf / segoeui.ttf / arial.ttf"
) else (
    call :log SUCCESS "Full font set present."
)
endlocal
:: ---- step 4: dependencies ----
if not exist "%REQ%" (
    call :log WARN "requirements.txt not found in project root"
    goto step_imports
)
call :log INFO "Installing dependencies (uv pip install -r requirements.txt)..."
set "PIP_TRY=0"
:pip_retry
set /a PIP_TRY+=1
"%UVEXE%" pip install --python "%PYTHON%" -r "%REQ%"
if errorlevel 1 (
    if %PIP_TRY% LSS 3 (
        call :log WARN "Retry in 5 s... (attempt %PIP_TRY% of 3)"
        timeout /t 5 /nobreak >nul
        goto pip_retry
    )
    call :log WARN "Dependency install reported warnings (see logs\install.log)"
) else (
    call :log SUCCESS "Dependencies installed."
)
:: ---- step 4b: build dependencies ----
set "BUILDREQ=%ROOT%requirements-build.txt"
if not exist "%BUILDREQ%" goto step_imports
call :log INFO "Installing build dependencies (requirements-build.txt)..."
"%UVEXE%" pip install --python "%PYTHON%" -r "%BUILDREQ%"
if errorlevel 1 (
    call :log WARN "Build dependency install reported warnings (see logs\install.log)"
) else (
    call :log SUCCESS "Build dependencies installed."
)
:: ---- step 4c: WinFsp driver (drive-letter mount) ----
set "WINFSPDLL=C:\Program Files (x86)\WinFsp\bin\winfsp-x64.dll"
if exist "%WINFSPDLL%" (
    call :log SUCCESS "WinFsp driver already present."
    goto step_imports
)
set "WINFSPVER=2.2.26323"
set "WINFSPURL=https://github.com/winfsp/winfsp/releases/download/v2.2/winfsp-%WINFSPVER%.msi"
set "WINFSPMSI=%TMPD%\winfsp-%WINFSPVER%.msi"
call :log INFO "WinFsp not found; downloading %WINFSPVER% (UAC prompt possible)..."
curl -L -f --retry 3 --retry-delay 5 -o "%WINFSPMSI%" "%WINFSPURL%"
if errorlevel 1 (
    call :log WARN "Failed to download WinFsp; drive-letter mount will be unavailable."
    goto step_imports
)
for %%F in ("%WINFSPMSI%") do set "MSISIZE=%%~zF"
if %MSISIZE% LSS 100000 (
    call :log WARN "WinFsp download corrupted; drive-letter mount will be unavailable."
    goto step_imports
)
msiexec /i "%WINFSPMSI%" /qb
if exist "%WINFSPDLL%" (
    call :log SUCCESS "WinFsp %WINFSPVER% installed."
) else (
    call :log WARN "WinFsp install not confirmed (UAC declined?); drive-letter mount unavailable."
)
:: ---- step 5: critical imports ----
:step_imports
call :log INFO "Checking critical imports..."
set "ALL_OK=1"
for %%M in (dearpygui.dearpygui PIL winfspy) do (
    "%PYTHON%" -c "import %%M" >nul 2>&1
    if errorlevel 1 (
        call :log ERROR "%%M NOT FOUND"
        set "ALL_OK=0"
    ) else (
        call :log SUCCESS "    [+] %%M"
    )
)
if "%ALL_OK%"=="1" (
    call :log SUCCESS "All critical imports OK."
) else (
    call :log ERROR "Import error. See logs\install.log"
)
call :log SUCCESS "Installation complete!"
exit /b 0