@echo off
REM Double-click to run the Business Reports web app on this computer for everyone in the office.
REM Free: no hosting service, no card. Keep this window open while people use the app.
cd /d "%~dp0"
title Business Reports - web app (keep this window open)
if not exist ".venv\Scripts\python.exe" (
    echo First run: setting up, this takes a few minutes...
    python -m venv .venv || (echo Please install Python 3.10+ from https://www.python.org/downloads/ ^(tick "Add Python to PATH"^) & pause & exit /b 1)
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
)
echo Checking required packages...
".venv\Scripts\python.exe" -m pip install -q -r requirements-server.txt || (echo Could not install the packages. Check the internet connection and try again. & pause & exit /b 1)
echo.
echo If Windows asks whether to allow Python on networks, tick "Private networks" and click Allow,
echo so the other computers in the office can reach the app.
".venv\Scripts\python.exe" -m server.office
pause
