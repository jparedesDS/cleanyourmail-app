@echo off
setlocal
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11+ is required. Install it from https://www.python.org/downloads/
  pause
  exit /b 1
)
python app.py
if errorlevel 1 pause
