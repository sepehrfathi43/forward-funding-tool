@echo off
cd /d "%~dp0"
if not exist ".venv-local\Scripts\python.exe" (
  echo The local Python environment is missing. Please complete setup first.
  pause
  exit /b 1
)
".venv-local\Scripts\python.exe" -m streamlit run app.py --server.address localhost --browser.gatherUsageStats false
if errorlevel 1 pause
