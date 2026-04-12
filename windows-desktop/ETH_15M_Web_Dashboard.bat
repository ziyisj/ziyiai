@echo off
setlocal
cd /d %~dp0\..
set PYTHONPATH=%cd%\src
py -3.11 -m eth_backtester.dashboard_server
