@echo off
echo ==========================================
echo    量化交易系统启动脚本
echo ==========================================
echo.

REM 检查Python环境
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请先安装Python 3.8+
    pause
    exit /b 1
)

REM 检查虚拟环境
if not exist venv (
    echo [1/4] 创建虚拟环境...
    python -m venv venv
)

echo [2/4] 激活虚拟环境...
call venv\Scripts\activate.bat

REM 安装依赖
echo [3/4] 安装依赖...
pip install -q -r requirements.txt

REM 检查.env文件
if not exist .env (
    echo [警告] 未找到.env文件，使用示例配置
    copy .env.example .env
    echo 请编辑.env文件配置您的API密钥
)

echo.
echo ==========================================
echo    启动选项:
echo ==========================================
echo [1] 启动Web管理页面 (默认端口5000)
echo [2] 启动策略引擎 (后台交易)
echo [3] 同时启动Web和策略引擎
echo.
set /p choice="请选择 (1-3): "

if "%choice%"=="1" goto start_web
if "%choice%"=="2" goto start_strategy
if "%choice%"=="3" goto start_both

echo 无效选择，默认启动Web管理页面

:start_web
echo.
echo [4/4] 启动Web管理页面...
echo 访问地址: http://localhost:5000
echo.
python web_admin/app.py
goto end

:start_strategy
echo.
echo [4/4] 启动策略引擎...
python strategy/strategy_engine.py
goto end

:start_both
echo.
echo [4/4] 同时启动Web和策略引擎...
start python web_admin/app.py
start python strategy/strategy_engine.py
echo.
echo Web管理页面: http://localhost:5000
echo 策略引擎已在后台启动
echo.

:end
pause
