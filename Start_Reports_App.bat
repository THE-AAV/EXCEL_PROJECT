@echo off
REM Double-click this file to open the Business Reports app in your browser.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo First run: setting up, this takes a few minutes...
    python -m venv .venv || (echo Please install Python 3.10+ from https://www.python.org/downloads/ ^(tick "Add to PATH"^) & pause & exit /b 1)
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (pause & exit /b 1)
)
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless false --browser.gatherUsageStats false
pause
