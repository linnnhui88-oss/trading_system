@echo off
chcp 65001 >nul
title 量化交易系统 - 停止脚本

REM ==========================================
REM 量化交易系统 - 跨平台停止脚本
REM 特点：
REM - 通过PID文件精确停止进程
REM - 支持优雅停止和强制停止
REM - 自动清理残留进程
REM ==========================================

echo ==========================================
echo    量化交易系统 - 停止脚本
echo ==========================================
echo.

REM 设置工作目录为脚本所在目录
cd /d "%~dp0"
set "SCRIPT_DIR=%~dp0"
set "PID_FILE=%SCRIPT_DIR%data\trading_service.pid"
set "STOP_TIMEOUT=10"

echo [信息] 工作目录: %SCRIPT_DIR%
echo.

REM ==========================================
REM 步骤1: 尝试优雅停止（通过API）
REM ==========================================
echo [1/4] 尝试通过API优雅停止...

curl -s -X POST http://localhost:5000/api/trading/stop >nul 2>&1
if %errorlevel% == 0 (
    echo [OK] 已发送停止交易信号
) else (
    echo [信息] API未响应，可能服务未运行
)
timeout /t 1 /nobreak >nul

REM ==========================================
REM 步骤2: 通过PID文件停止主进程
REM ==========================================
echo.
echo [2/4] 停止服务进程...

set "STOPPED_COUNT=0"

REM 方法1: 使用PID文件
if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    if not "!PID!"=="" (
        echo [信息] 发现PID文件，尝试停止 PID: !PID!
        tasklist /fi "PID eq !PID!" 2>nul | findstr "!PID!" >nul
        if !errorlevel! == 0 (
            taskkill /PID !PID! /T >nul 2>&1
            if !errorlevel! == 0 (
                echo [OK] 已停止进程 PID: !PID!
                set /a STOPPED_COUNT+=1
            ) else (
                echo [警告] 无法停止 PID: !PID!，尝试强制终止
                taskkill /PID !PID! /F /T >nul 2>&1
            )
        )
    )
    del "%PID_FILE%" 2>nul
)

REM ==========================================
REM 步骤3: 查找并停止所有相关Python进程
REM ==========================================
echo.
echo [3/4] 清理残留进程...

REM 查找包含特定命令行的Python进程（更精确）
for /f "tokens=2 delims=," %%a in ('wmic process where "name='python.exe' and CommandLine like '%%web_admin%%'" get ProcessId /format:csv 2^>nul ^| findstr "[0-9]"') do (
    if not "%%a"=="" (
        echo [信息] 发现相关进程 PID: %%a
        taskkill /PID %%a /F /T >nul 2>&1
        if !errorlevel! == 0 (
            echo [OK] 已停止 PID: %%a
            set /a STOPPED_COUNT+=1
        )
    )
)

REM 备用方案：查找监听5000端口的进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING"') do (
    if not "%%a"=="0" (
        echo [信息] 发现端口占用进程 PID: %%a
        taskkill /PID %%a /F /T >nul 2>&1
        if !errorlevel! == 0 (
            echo [OK] 已停止 PID: %%a
            set /a STOPPED_COUNT+=1
        )
    )
)

REM ==========================================
REM 步骤4: 验证停止结果
REM ==========================================
echo.
echo [4/4] 验证停止结果...
timeout /t 2 /nobreak >nul

set "STILL_RUNNING=0"

REM 检查是否还有Python进程在运行web_admin
wmic process where "name='python.exe' and CommandLine like '%%web_admin%%'" get ProcessId 2>nul | findstr "[0-9]" >nul
if %errorlevel% == 0 set "STILL_RUNNING=1"

REM 检查端口是否仍被占用
netstat -ano | findstr ":5000" | findstr "LISTENING" >nul
if %errorlevel% == 0 set "STILL_RUNNING=1"

echo.
if %STILL_RUNNING%==0 (
    echo ==========================================
    echo    ✅ 服务已完全停止
    echo ==========================================
    if %STOPPED_COUNT% gtr 0 (
        echo [信息] 共停止 %STOPPED_COUNT% 个进程
    )
) else (
    echo ==========================================
    echo    ⚠️ 部分进程可能仍在运行
    echo ==========================================
    echo.
    echo [手动停止方法]
    echo 1. 打开任务管理器（Ctrl+Shift+Esc）
    echo 2. 找到Python进程
    echo 3. 右键点击，选择"结束任务"
    echo.
    echo [或使用命令强制停止所有Python]
    echo taskkill /f /im python.exe
    echo.
    echo [当前运行的Python进程]
    tasklist /fi "imagename eq python.exe" 2>nul
)

echo.
pause
exit /b 0
