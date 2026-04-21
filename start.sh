#!/bin/bash

echo "=========================================="
echo "   量化交易系统启动脚本"
echo "=========================================="
echo ""

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到Python3，请先安装Python 3.8+"
    exit 1
fi

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "[1/4] 创建虚拟环境..."
    python3 -m venv venv
fi

echo "[2/4] 激活虚拟环境..."
source venv/bin/activate

# 安装依赖
echo "[3/4] 安装依赖..."
pip install -q -r requirements.txt

# 检查.env文件
if [ ! -f ".env" ]; then
    echo "[警告] 未找到.env文件，使用示例配置"
    cp .env.example .env
    echo "请编辑.env文件配置您的API密钥"
fi

echo ""
echo "=========================================="
echo "   启动选项:"
echo "=========================================="
echo "[1] 启动Web管理页面 (默认端口5000)"
echo "[2] 启动策略引擎 (后台交易)"
echo "[3] 同时启动Web和策略引擎"
echo ""
read -p "请选择 (1-3): " choice

case $choice in
    1)
        echo ""
        echo "[4/4] 启动Web管理页面..."
        echo "访问地址: http://localhost:5000"
        echo ""
        python web_admin/app.py
        ;;
    2)
        echo ""
        echo "[4/4] 启动策略引擎..."
        python strategy/strategy_engine.py
        ;;
    3)
        echo ""
        echo "[4/4] 同时启动Web和策略引擎..."
        python web_admin/app.py &
        python strategy/strategy_engine.py &
        echo ""
        echo "Web管理页面: http://localhost:5000"
        echo "策略引擎已在后台启动"
        echo ""
        wait
        ;;
    *)
        echo "无效选择，默认启动Web管理页面"
        python web_admin/app.py
        ;;
esac
