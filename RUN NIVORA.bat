@echo off
setlocal
title NIVORA
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating the Python environment once, this takes a minute...
  py -3.12 -m venv .venv 2>nul || python -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Python 3.12 was not found. Install it from python.org and run this file again.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
)

if not exist "data\nivora.db" (
  echo First run: creating the demo shop...
  ".venv\Scripts\python.exe" -m scripts.seed_demo
)

start "" http://localhost:8000/login
echo.
echo   NIVORA is running at http://localhost:8000
echo   Sign in: demo@nivora.my / nivora-demo-2026
echo   Shop:    http://localhost:8000/shop?b=dapur-aminah
echo.
echo   Keep this window open. Press Ctrl+C to stop.
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
