@echo off
chcp 65001 >nul
title 量化交易系统 - 停止脚本
echo ==========================================
echo    量化交易系统 - 停止脚本
echo ==========================================
echo.

cd /d "%~dp0"

echo [1/3] 正在查找服务进程...

REM 查找Python进程
set "FOUND=0"
for /f "tokens=2 delims=," %%a in ('tasklist /fi "imagename eq python.exe" /fo csv ^| findstr /v "PID"') do (
    set "PID=%%~a"
    set "FOUND=1"
    echo   发现进程 PID: %%~a
)

if %FOUND%==0 (
    echo.
    echo [提示] 未检测到运行中的服务进程
    echo.
    pause
    exit /b 0
)

echo.
echo [2/3] 正在停止服务...

REM 先尝试通过API优雅停止
echo   尝试通过API停止自动交易...
curl -s -X POST http://localhost:5000/api/trading/stop >nul 2>&1
timeout /t 1 /nobreak >nul

echo   正在终止进程...
for /f "tokens=2 delims=," %%a in ('tasklist /fi "imagename eq python.exe" /fo csv ^| findstr /v "PID"') do (
    echo   正在终止 PID: %%~a
    taskkill /PID %%~a /F /T >nul 2>&1
)

echo.
echo [3/3] 验证进程是否已终止...
timeout /t 2 /nobreak >nul

set "STILL_RUNNING=0"
for /f %%a in ('tasklist ^| findstr /i "python.exe" ^| find /c /v ""') do (
    if %%a gtr 0 set "STILL_RUNNING=1"
)

if %STILL_RUNNING%==0 (
    echo.
    echo ==========================================
    echo    ✅ 服务已完全停止
    echo ==========================================
) else (
    echo.
    echo ==========================================
    echo    ⚠️ 部分进程可能仍在运行
    echo ==========================================
    echo.
    echo [提示] 请手动检查任务管理器中的Python进程
    tasklist /fi "imagename eq python.exe"
)

echo.
pause
