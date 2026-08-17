@echo off
rem Double-click this to start the to-do app.
cd /d "%~dp0"
python server.py
if errorlevel 1 (
  echo.
  echo Could not start. Is Python installed and on your PATH?
  pause
)
