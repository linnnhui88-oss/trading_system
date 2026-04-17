#!/bin/bash

# ==========================================
# 量化交易系统 - 跨平台启动脚本 (Linux/Mac)
# ==========================================

# 设置颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 设置工作目录为脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="$SCRIPT_DIR/data/trading_service.pid"
LOG_FILE="$SCRIPT_DIR/data/service.log"

# 确保data目录存在
mkdir -p "$SCRIPT_DIR/data"

echo "=========================================="
echo "   量化交易系统 - 启动脚本"
echo "=========================================="
echo ""
echo -e "${GREEN}[信息]${NC} 工作目录: $SCRIPT_DIR"
echo ""

# ==========================================
# 步骤1: 检查环境
# ==========================================
echo "[1/4] 检查运行环境..."

# 检查虚拟环境
if [ ! -f "$SCRIPT_DIR/venv/bin/python" ]; then
    echo -e "${RED}[错误]${NC} 虚拟环境不存在！"
    echo ""
    echo "[解决方案]"
    echo "1. 创建虚拟环境:"
    echo "   cd \"$SCRIPT_DIR\""
    echo "   python3 -m venv venv"
    echo ""
    echo "2. 安装依赖:"
    echo "   ./venv/bin/pip install -r requirements.txt"
    echo ""
    read -p "按任意键继续..."
    exit 1
fi

PYTHON="$SCRIPT_DIR/venv/bin/python"
echo -e "${GREEN}[OK]${NC} Python路径: $PYTHON"

# 检查 .env 文件
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo -e "${YELLOW}[警告]${NC} .env 文件不存在"
    echo "[提示] 建议复制 .env.example 为 .env 并配置您的API密钥"
    echo ""
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        read -p "是否复制 .env.example 到 .env? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
            echo -e "${GREEN}[OK]${NC} 已创建 .env 文件，请编辑配置您的API密钥"
        fi
    fi
    echo ""
fi

# ==========================================
# 步骤2: 检查是否已在运行
# ==========================================
echo ""
echo "[2/4] 检查服务状态..."

ALREADY_RUNNING=0

# 方法1: 检查PID文件
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        ALREADY_RUNNING=1
        echo -e "${YELLOW}[警告]${NC} 检测到服务已在运行 (PID: $PID)"
    fi
fi

# 方法2: 检查端口占用
if lsof -Pi :5000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    ALREADY_RUNNING=1
    echo -e "${YELLOW}[警告]${NC} 检测到端口5000已被占用"
fi

if [ $ALREADY_RUNNING -eq 1 ]; then
    echo ""
    echo "[提示] 服务可能已在运行"
    echo "[提示] 如需重启，请先运行 ./stop_trading.sh"
    echo ""
    read -p "是否继续启动? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 0
    fi
    echo ""
fi

# ==========================================
# 步骤3: 启动服务
# ==========================================
echo ""
echo "[3/4] 正在启动Web服务..."

echo -e "${GREEN}[信息]${NC} 启动Python服务..."

# 在后台启动服务
nohup "$PYTHON" -m web_admin.app > "$LOG_FILE" 2>&1 &
NEW_PID=$!

# 记录PID
echo $NEW_PID > "$PID_FILE"

echo -e "${GREEN}[OK]${NC} 服务已启动，PID: $NEW_PID"
echo -e "${GREEN}[信息]${NC} 日志文件: $LOG_FILE"

# ==========================================
# 步骤4: 等待并验证
# ==========================================
echo ""
echo "[4/4] 等待服务启动..."

RETRY_COUNT=0
MAX_RETRY=10

while [ $RETRY_COUNT -lt $MAX_RETRY ]; do
    sleep 1
    
    # 尝试连接API
    if curl -s http://localhost:5000/api/status >/dev/null 2>&1; then
        echo ""
        echo "=========================================="
        echo -e "   ${GREEN}✅ 服务启动成功！${NC}"
        echo "=========================================="
        echo ""
        echo "📊 仪表盘地址: http://localhost:5000"
        echo "📡 API地址: http://localhost:5000/api/status"
        echo "📝 日志文件: data/service.log"
        echo "🔢 进程PID: $NEW_PID"
        echo ""
        
        read -p "按任意键打开浏览器访问仪表盘..."
        
        # 尝试打开浏览器
        if command -v xdg-open >/dev/null 2>&1; then
            xdg-open http://localhost:5000
        elif command -v open >/dev/null 2>&1; then
            open http://localhost:5000
        fi
        
        exit 0
    fi
    
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "  等待服务响应... ($RETRY_COUNT/$MAX_RETRY)"
done

# 启动失败
echo ""
echo "=========================================="
echo -e "   ${RED}❌ 服务启动失败或超时${NC}"
echo "=========================================="
echo ""
echo "[可能原因]"
echo "1. 端口5000被其他程序占用"
echo "2. 依赖包未正确安装"
echo "3. .env配置错误"
echo ""
echo "[解决方案]"
echo "1. 检查端口占用: lsof -i :5000"
echo "2. 重新安装依赖: ./venv/bin/pip install -r requirements.txt"
echo "3. 检查日志文件: tail -f data/service.log"
echo ""
read -p "按任意键继续..."
exit 1
