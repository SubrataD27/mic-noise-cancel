@echo off
cd /d "%~dp0"
echo Speak into your inline earphone microphone to hear the cleaned audio.
echo Press Enter to compare raw and cleaned audio. Type q then Enter to stop.
".venv\Scripts\python.exe" -c "import noise_cancel as n; s=n.Settings.load(); s.input_device='Microphone (Realtek'; s.output_device='Headphones (Realtek'; n.run_live(s, False)"
pause
