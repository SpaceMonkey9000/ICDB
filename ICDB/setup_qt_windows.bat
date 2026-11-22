@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (echo Python launcher not found. Install Python 3.11 x64. & pause & exit /b 1)
py -3.11 -m venv .venv-qt
if errorlevel 1 (echo Failed to create virtual environment. & pause & exit /b 1)
.venv-qt\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 (pause & exit /b 1)
.venv-qt\Scripts\python.exe -m pip install -r requirements-qt.txt
if errorlevel 1 (echo Dependency installation failed. & pause & exit /b 1)
echo Installation completed.
pause
