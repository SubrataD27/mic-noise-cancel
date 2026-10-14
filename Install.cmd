@echo off
cd /d "%~dp0"
echo Creating Python environment in .venv ...
python -m venv .venv || (echo Python not found. Install Python 3.10+ from python.org and tick "Add to PATH". & pause & exit /b 1)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo.
echo Done. Your audio devices:
".venv\Scripts\python.exe" noise_cancel.py --list
pause
