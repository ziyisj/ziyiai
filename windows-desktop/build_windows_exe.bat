@echo off
setlocal
cd /d %~dp0\..

py -3.11 -m pip install -r requirements-desktop.txt
if errorlevel 1 goto :error

py -3.11 -m PyInstaller --noconfirm --clean windows-desktop\ETH_15M_Signal_Desktop.spec
if errorlevel 1 goto :error

echo.
echo Build complete.
echo EXE path: %cd%\dist\ETH_15M_Signal_Desktop.exe
pause
exit /b 0

:error
echo.
echo Build failed.
pause
exit /b 1
