@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import PIL, tkinter, resvg_py" >nul 2>&1
if errorlevel 1 (
  echo ICDB requires Python 3.10+ with Tkinter, Pillow and resvg_py.
  echo Run: py -3 -m pip install -r requirements.txt
  pause
  exit /b 1
)
py -3 launch.py
if errorlevel 1 pause
