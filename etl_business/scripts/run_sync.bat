@echo off
setlocal
cd /d "%~dp0\..\.."
if not exist "env\Scripts\python.exe" (
  echo Project virtual environment not found. Install root requirements first.
  exit /b 1
)
"env\Scripts\python.exe" run_business_etl.py
exit /b %errorlevel%
