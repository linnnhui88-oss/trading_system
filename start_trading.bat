@echo off
chcp 65001 >nul
title 量化交易系统 - 启动脚本
echo ==========================================
echo    量化交易系统 - 启动脚本
echo ==========================================
echo.

REM 设置工作目录
cd /d "%~dp0"

REM 检查虚拟环境
if not exist ".\venv\Scripts\python.exe" (
    echo [错误] 虚拟环境不存在，请先创建虚拟环境
    pause
    exit /b 1
)

REM 检查 .env 文件
if not exist ".\.env" (
    echo [警告] .env 文件不存在，将使用默认配置
    echo [提示] 建议复制 .env.example 为 .env 并配置您的API密钥
    echo.
)

echo [1/3] 正在检查服务状态...
REM 检查是否已有服务在运行
for /f "tokens=1" %%a in ('tasklist ^| findstr /i "python" ^| find /c /v ""') do (
    if %%a gtr 0 (
        echo [警告] 检测到已有Python进程运行，可能服务已在运行
        echo [提示] 如需重启，请先运行 stop_trading.bat
        echo.
        choice /c YN /m "是否继续启动"
        if errorlevel 2 exit /b 0
    )
)

echo [2/3] 正在启动Web服务...
start "量化交易Web服务" /min .\venv\Scripts\python web_admin\app.py

echo [3/3] 等待服务启动...
timeout /t 3 /nobreak >nul

REM 检查服务是否启动成功
curl -s http://localhost:5000/api/status >nul 2>&1
if %errorlevel% == 0 (
    echo.
    echo ==========================================
    echo    ✅ 服务启动成功！
    echo ==========================================
    echo.
    echo 📊 仪表盘地址: http://localhost:5000
    echo 📡 API地址: http://localhost:5000/api/status
    echo.
    echo [提示] 按任意键打开浏览器访问仪表盘
    pause >nul
    start http://localhost:5000
) else (
    echo.
    echo ==========================================
    echo    ❌ 服务启动失败
    echo ==========================================
    echo.
    echo [提示] 请检查日志文件: data\web_admin.log
    pause
)
