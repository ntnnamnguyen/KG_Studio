@echo off
setlocal
cd /d "%~dp0"

if exist "..\KG_Studio_MVP\.venv-win\Scripts\python.exe" (
    "..\KG_Studio_MVP\.venv-win\Scripts\python.exe" run_app.py %*
    exit /b %ERRORLEVEL%
)

if exist ".venv-win\Scripts\python.exe" (
    ".venv-win\Scripts\python.exe" run_app.py %*
    exit /b %ERRORLEVEL%
)

python run_app.py %*

