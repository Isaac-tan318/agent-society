@echo off
title AgentSociety Studio - keep this window open (close it to stop the Studio)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Could not find the Python environment in "%~dp0.venv".
  pause
  exit /b 1
)
".venv\Scripts\python.exe" ui\server.py
if errorlevel 1 pause
