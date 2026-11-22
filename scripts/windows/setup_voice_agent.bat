@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem One-time setup for the Mumbai Bank voice agent demo.
rem Double-click this file. It clones the repo into a "voice-agent" folder next to it,
rem creates a Python environment and installs the requirements. Safe to run again.

cd /d "%~dp0"
set "REPO_URL=https://github.com/RohanKhollamkar/voice-agent.git"
set "BRANCH=main"
set "REPO_DIR=%~dp0voice-agent"

echo.
echo === 1/5  Checking Git ===
where git >nul 2>nul
if errorlevel 1 (
  echo Git is not installed. Install it from https://git-scm.com/download/win
  echo then run this file again.
  goto :fail
)
git --version

echo.
echo === 2/5  Finding Python 3.11, 3.12 or 3.13 ===
set "PY="
for %%C in ("py -3.12" "py -3.11" "py -3.13" "python") do (
  if not defined PY (
    %%~C -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY=%%~C"
  )
)
if not defined PY (
  echo No suitable Python found. Install Python 3.12 from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" in the installer, then run this file again.
  goto :fail
)
echo Using: %PY%
%PY% --version

echo.
echo === 3/5  Getting the code ===
if exist "%REPO_DIR%\.git" (
  echo Repo already here, updating it.
  git -C "%REPO_DIR%" fetch origin
  git -C "%REPO_DIR%" checkout "%BRANCH%"
  git -C "%REPO_DIR%" pull --ff-only
) else (
  git clone --branch "%BRANCH%" "%REPO_URL%" "%REPO_DIR%"
)
if errorlevel 1 goto :fail

cd /d "%REPO_DIR%"

echo.
echo === 4/5  Creating the Python environment and installing requirements ===
echo This can take a few minutes the first time.
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
  if errorlevel 1 goto :fail
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Installing the requirements failed. Copy the error above and send it to Claude.
  goto :fail
)

echo.
echo === 5/5  Settings file ===
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Created .env from .env.example. Notepad will open it now:
  echo fill in SARVAM_API_KEY, NVIDIA_API_KEY and WEBHOOK_URL, then save and close.
  start "" notepad ".env"
) else (
  echo .env already exists, left unchanged.
)

echo.
echo Setup finished. To start the demo, double-click start_demo.bat.
echo.
pause
exit /b 0

:fail
echo.
echo Setup stopped. Fix the problem above and run this file again.
pause
exit /b 1
