@echo off
echo ==========================================
echo  Trading System - Start
echo ==========================================
echo.

cd /d "C:\Users\TUF\.openclaw\workspace\trading_system"

echo [1/3] Checking port 5000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    echo Found PID: %%a, killing...
    taskkill /F /PID %%a >nul 2>&1
)
echo [OK] Port cleared
echo.

echo [2/3] Starting system...
start "TradingSystem" /min cmd /c "cd /d C:\Users\TUF\.openclaw\workspace\trading_system && .\venv\Scripts\python.exe web_admin\app.py"

timeout /t 3 /nobreak >nul

echo [3/3] Opening browser...
start http://localhost:5000

echo.
echo ==========================================
echo  System Started!
echo  URL: http://localhost:5000
echo ==========================================
echo.
echo Note: Click "Start Auto Trading" on webpage to enable trading
echo.
pause
