@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" noise_cancel.py --input "Microphone (Realtek" --output "CABLE Input"
pause
