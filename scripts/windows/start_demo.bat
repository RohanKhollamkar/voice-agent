@echo off
rem Starts the demo console and opens it in the browser.
rem Keep this window open during the call; close it (or press Ctrl+C) to stop the demo.
cd /d "%~dp0voice-agent"
if not exist ".venv\Scripts\python.exe" (
  echo The demo is not set up yet. Double-click setup_voice_agent.bat first.
  pause
  exit /b 1
)
echo Starting the demo at http://localhost:7860/demo
".venv\Scripts\python.exe" -m voice.demo --open
pause
