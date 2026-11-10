@echo off
REM Windows: double-click this file
cd /d "%~dp0"
if not exist .venv ( py -3 -m venv .venv )
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
start "" http://localhost:8000
python app.py
