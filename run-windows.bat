@echo off
rem Double-click me to run OutLoud from source on Windows.
rem Needs Python 3 from https://www.python.org/downloads/ (tick "Add to PATH").
cd /d "%~dp0"
where uv >nul 2>nul && ( uv run outloud %* & exit /b )
if not exist .venv\Scripts\python.exe (
  echo First run: setting up, about a minute...
  py -3 -m venv .venv || python -m venv .venv || ( echo Install Python 3 from python.org first. & pause & exit /b 1 )
  .venv\Scripts\pip install -q -e . winocr
)
start "" .venv\Scripts\pythonw.exe -m outloud %*
