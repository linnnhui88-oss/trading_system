@echo off
chcp 65001 >nul
title 量化交易系统 - 启动脚本

REM ==========================================
REM 量化交易系统 - 跨平台启动脚本
REM 特点：
REM - 自动检测脚本所在目录
REM - 支持任意路径部署
REM - 自动创建PID文件便于管理
REM ==========================================

echo ==========================================
echo    量化交易系统 - 启动脚本
echo ==========================================
echo.

REM 设置工作目录为脚本所在目录（关键：确保在任何路径下都能运行）
cd /d "%~dp0"
set "SCRIPT_DIR=%~dp0"
set "PID_FILE=%SCRIPT_DIR%data\trading_service.pid"
set "LOG_FILE=%SCRIPT_DIR%data\service.log"

REM 确保data目录存在
if not exist "%SCRIPT_DIR%data" mkdir "%SCRIPT_DIR%data"

echo [信息] 工作目录: %SCRIPT_DIR%
echo.

REM ==========================================
REM 步骤1: 检查环境
REM ==========================================
echo [1/4] 检查运行环境...

REM 检查虚拟环境
if not exist "%SCRIPT_DIR%venv\Scripts\python.exe" (
    echo [错误] 虚拟环境不存在！
    echo.
    echo [解决方案]
    echo 1. 创建虚拟环境:
    echo    cd /d "%SCRIPT_DIR%"
    echo    python -m venv venv
    echo.
    echo 2. 安装依赖:
    echo    .\venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

set "PYTHON=%SCRIPT_DIR%venv\Scripts\python.exe"
echo [OK] Python路径: %PYTHON%

REM 检查 .env 文件
if not exist "%SCRIPT_DIR%.env" (
    echo [警告] .env 文件不存在
    echo [提示] 建议复制 .env.example 为 .env 并配置您的API密钥
    echo.
    if exist "%SCRIPT_DIR%.env.example" (
        choice /c YN /m "是否复制 .env.example 到 .env"
        if errorlevel 1 if not errorlevel 2 (
            copy "%SCRIPT_DIR%.env.example" "%SCRIPT_DIR%.env" >nul
            echo [OK] 已创建 .env 文件，请编辑配置您的API密钥
            notepad "%SCRIPT_DIR%.env"
        )
    )
    echo.
)

REM ==========================================
REM 步骤2: 检查是否已在运行
REM ==========================================
echo.
echo [2/4] 检查服务状态...

set "ALREADY_RUNNING=0"

REM 方法1: 检查PID文件
if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    if not "!PID!"=="" (
        tasklist /fi "PID eq !PID!" 2>nul | findstr "!PID!" >nul
        if !errorlevel! == 0 (
            set "ALREADY_RUNNING=1"
            echo [警告] 检测到服务已在运行 (PID: !PID!)
        )
    )
)

REM 方法2: 检查端口占用
netstat -ano | findstr ":5000" | findstr "LISTENING" >nul
if %errorlevel% == 0 (
    set "ALREADY_RUNNING=1"
    echo [警告] 检测到端口5000已被占用
)

if %ALREADY_RUNNING%==1 (
    echo.
    echo [提示] 服务可能已在运行
    echo [提示] 如需重启，请先运行 stop_trading.bat
    echo.
    choice /c YN /m "是否继续启动"
    if errorlevel 2 exit /b 0
    echo.
)

REM ==========================================
REM 步骤3: 启动服务
REM ==========================================
echo.
echo [3/4] 正在启动Web服务...

REM 使用wmic获取唯一进程ID（比start命令更可靠）
echo [信息] 启动Python服务...

REM 使用start /b 在后台运行，并记录PID
start /b "" "%PYTHON%" -m web_admin.app > "%LOG_FILE%" 2>&1

REM 获取刚启动的进程PID
for /f "tokens=2 delims=," %%a in ('tasklist /fi "imagename eq python.exe" /fo csv ^| findstr /v "PID"') do (
    echo %%~a > "%PID_FILE%"
    set "NEW_PID=%%~a"
)

echo [OK] 服务已启动，PID: %NEW_PID%
echo [信息] 日志文件: %LOG_FILE%

REM ==========================================
REM 步骤4: 等待并验证
REM ==========================================
echo.
echo [4/4] 等待服务启动...

set "RETRY_COUNT=0"
set "MAX_RETRY=10"

:CHECK_LOOP
timeout /t 1 /nobreak >nul

REM 尝试连接API
curl -s http://localhost:5000/api/status >nul 2>&1
if %errorlevel% == 0 (
    goto START_SUCCESS
)

set /a RETRY_COUNT+=1
if %RETRY_COUNT% lss %MAX_RETRY% (
    echo   等待服务响应... (%RETRY_COUNT%/%MAX_RETRY%)
    goto CHECK_LOOP
)

goto START_FAILED

:START_SUCCESS
echo.
echo ==========================================
echo    ✅ 服务启动成功！
echo ==========================================
echo.
echo 📊 仪表盘地址: http://localhost:5000
echo 📡 API地址: http://localhost:5000/api/status
echo 📝 日志文件: data\service.log
echo 🔢 进程PID: %NEW_PID%
echo.
echo [提示] 按任意键打开浏览器访问仪表盘
pause >nul
start http://localhost:5000
exit /b 0

:START_FAILED
echo.
echo ========================================== 
echo    ❌ 服务启动失败或超时
echo ==========================================
echo.
echo [可能原因]
echo 1. 端口5000被其他程序占用
echo 2. 依赖包未正确安装
echo 3. .env配置错误
echo.
echo [解决方案]
echo 1. 检查端口占用: netstat -ano ^| findstr :5000
echo 2. 重新安装依赖: .\venv\Scripts\pip install -r requirements.txt
echo 3. 检查日志文件: data\service.log
echo.
pause
exit /b 1
