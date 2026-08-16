@echo off
setlocal
cd /d "%~dp0\\..\\.."
if not exist "env\\Scripts\\python.exe" (
  echo Project virtual environment not found. Install root requirements first.
  exit /b 1
)
"env\\Scripts\\python.exe" -m etl_business.shop_data_extractor.cli inspect
exit /b %errorlevel%
