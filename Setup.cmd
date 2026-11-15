@echo off
title Daily Brief - automated setup
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-all.ps1" %*
echo.
pause
