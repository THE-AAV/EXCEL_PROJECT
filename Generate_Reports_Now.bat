@echo off
REM Double-click to build the Excel report pack from the newest file in the "input" folder.
REM The result is saved in the "output" folder. Can also be scheduled with Windows Task Scheduler.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
".venv\Scripts\python.exe" generate_reports.py %*
if "%1"=="" start "" "%~dp0output"
