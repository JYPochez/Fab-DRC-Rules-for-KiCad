@echo off
rem Runs install_windows.ps1 even when PowerShell scripts are blocked.
rem   install_windows.bat              install for KiCad 10.0
rem   install_windows.bat -Version 9.0
rem   install_windows.bat -Uninstall
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1" %*
pause
