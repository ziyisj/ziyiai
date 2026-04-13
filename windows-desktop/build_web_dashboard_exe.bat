@echo off
setlocal
cd /d %~dp0\..

py -3.11 -m pip install -r requirements-desktop.txt
if errorlevel 1 goto :error

py -3.11 -m PyInstaller --noconfirm --clean windows-desktop\ETH_15M_Web_Dashboard.spec
if errorlevel 1 goto :error

echo.
echo Build complete.
echo EXE path: %cd%\dist\ETH策略系统.exe
pause
exit /b 0

:error
echo.
echo Build failed.
pause
exit /b 1
