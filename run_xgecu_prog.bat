:: Xgecu Prog runtime launcher wrapper - delegates to run_xgecu_prog.ps1.
:: Version: 2.1.0
@echo off
chcp 65001 >nul
title Xgecu Prog

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_xgecu_prog.ps1" %*
