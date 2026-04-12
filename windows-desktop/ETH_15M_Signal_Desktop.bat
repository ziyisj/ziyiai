@echo off
setlocal
cd /d %~dp0\..

if exist "%LocalAppData%\Programs\Python\Python311\pythonw.exe" (
  set "PYW=%LocalAppData%\Programs\Python\Python311\pythonw.exe"
) else (
  set "PYW=pythonw"
)

%PYW% windows-desktop\eth_signal_desktop.pyw
if errorlevel 1 (
  echo.
  echo Failed to launch desktop app. Make sure Python 3.11+ is installed and on PATH.
  pause
)
