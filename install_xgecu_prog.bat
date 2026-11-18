:: Xgecu Prog portable installer & launcher (uv) - delegates to install_xgecu_prog.ps1.
:: Version: 2.1.0
@echo off
chcp 65001 >nul
title Xgecu Prog Installer

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_xgecu_prog.ps1" %*
