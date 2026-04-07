@echo off
echo ==========================================
echo  Trading System - Stop
echo ==========================================
echo.

echo [1/2] Stopping system...
taskkill /F /IM python.exe >nul 2>&1
echo [OK] System stopped
echo.

echo [2/2] Cleaning port 5000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    echo Killing PID: %%a
    taskkill /F /PID %%a >nul 2>&1
)
echo [OK] Port released
echo.
echo ==========================================
echo  System Stopped!
echo ==========================================
echo.
echo Now you can:
echo - Update code
echo - Run start_trading.bat to restart
echo.
pause
