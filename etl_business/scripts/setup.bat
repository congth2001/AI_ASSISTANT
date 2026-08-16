@echo off
setlocal
cd /d "%~dp0\\..\\.."
py -3.11 -m venv env
call env\\Scripts\\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Setup complete. Edit config\\local.yml, then run etl_business\\scripts\\run_inspect.bat
