@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 tools\check_env.py
echo.
pause
