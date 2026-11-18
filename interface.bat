@echo off
rem Opens the court practice analyzer in the browser.
cd /d "%~dp0"
set "PY=python"
if exist "%USERPROFILE%\.venvs\sud-parser\Scripts\python.exe" set "PY=%USERPROFILE%\.venvs\sud-parser\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" -m streamlit run sud_parser\practice\app.py --server.address localhost --server.port 8501
pause
