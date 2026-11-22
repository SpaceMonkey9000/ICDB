@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-qt\Scripts\python.exe" (echo Run setup_qt_windows.bat first. & pause & exit /b 1)
.venv-qt\Scripts\python.exe icdb_qt.py %*
if errorlevel 1 (echo ICDB Qt exited with an error. & pause)
