#!/bin/bash

# ==========================================
# 量化交易系统 - 跨平台停止脚本 (Linux/Mac)
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
STOP_TIMEOUT=10

echo "=========================================="
echo "   量化交易系统 - 停止脚本"
echo "=========================================="
echo ""
echo -e "${GREEN}[信息]${NC} 工作目录: $SCRIPT_DIR"
echo ""

STOPPED_COUNT=0

# ==========================================
# 步骤1: 尝试优雅停止（通过API）
# ==========================================
echo "[1/4] 尝试通过API优雅停止..."

if curl -s -X POST http://localhost:5000/api/trading/stop >/dev/null 2>&1; then
    echo -e "${GREEN}[OK]${NC} 已发送停止交易信号"
else
    echo -e "${YELLOW}[信息]${NC} API未响应，可能服务未运行"
fi
sleep 1

# ==========================================
# 步骤2: 通过PID文件停止主进程
# ==========================================
echo ""
echo "[2/4] 停止服务进程..."

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if [ -n "$PID" ]; then
        if kill -0 "$PID" 2>/dev/null; then
            echo -e "${GREEN}[信息]${NC} 发现PID文件，尝试停止 PID: $PID"
            
            # 尝试优雅停止
            kill "$PID" 2>/dev/null
            
            # 等待进程停止
            WAIT_COUNT=0
            while [ $WAIT_COUNT -lt $STOP_TIMEOUT ]; do
                if ! kill -0 "$PID" 2>/dev/null; then
                    echo -e "${GREEN}[OK]${NC} 已停止进程 PID: $PID"
                    STOPPED_COUNT=$((STOPPED_COUNT + 1))
                    break
                fi
                sleep 1
                WAIT_COUNT=$((WAIT_COUNT + 1))
            done
            
            # 如果还在运行，强制停止
            if kill -0 "$PID" 2>/dev/null; then
                echo -e "${YELLOW}[警告]${NC} 进程未响应，强制终止 PID: $PID"
                kill -9 "$PID" 2>/dev/null
                STOPPED_COUNT=$((STOPPED_COUNT + 1))
            fi
        fi
    fi
    rm -f "$PID_FILE"
fi

# ==========================================
# 步骤3: 查找并停止所有相关Python进程
# ==========================================
echo ""
echo "[3/4] 清理残留进程..."

# 查找包含web_admin的Python进程
PIDS=$(pgrep -f "web_admin" 2>/dev/null)
if [ -n "$PIDS" ]; then
    for PID in $PIDS; do
        echo -e "${GREEN}[信息]${NC} 发现相关进程 PID: $PID"
        kill -9 "$PID" 2>/dev/null
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}[OK]${NC} 已停止 PID: $PID"
            STOPPED_COUNT=$((STOPPED_COUNT + 1))
        fi
    done
fi

# 备用方案：查找监听5000端口的进程
if command -v lsof >/dev/null 2>&1; then
    PID=$(lsof -Pi :5000 -sTCP:LISTEN -t 2>/dev/null)
    if [ -n "$PID" ]; then
        echo -e "${GREEN}[信息]${NC} 发现端口占用进程 PID: $PID"
        kill -9 "$PID" 2>/dev/null
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}[OK]${NC} 已停止 PID: $PID"
            STOPPED_COUNT=$((STOPPED_COUNT + 1))
        fi
    fi
fi

# ==========================================
# 步骤4: 验证停止结果
# ==========================================
echo ""
echo "[4/4] 验证停止结果..."
sleep 2

STILL_RUNNING=0

# 检查是否还有相关进程
if pgrep -f "web_admin" >/dev/null 2>&1; then
    STILL_RUNNING=1
fi

# 检查端口是否仍被占用
if command -v lsof >/dev/null 2>&1; then
    if lsof -Pi :5000 -sTCP:LISTEN -t >/dev/null 2>&1; then
        STILL_RUNNING=1
    fi
fi

echo ""
if [ $STILL_RUNNING -eq 0 ]; then
    echo "=========================================="
    echo -e "   ${GREEN}✅ 服务已完全停止${NC}"
    echo "=========================================="
    if [ $STOPPED_COUNT -gt 0 ]; then
        echo -e "${GREEN}[信息]${NC} 共停止 $STOPPED_COUNT 个进程"
    fi
else
    echo "=========================================="
    echo -e "   ${YELLOW}⚠️ 部分进程可能仍在运行${NC}"
    echo "=========================================="
    echo ""
    echo "[手动停止方法]"
    echo "1. 查找进程: pgrep -f web_admin"
    echo "2. 停止进程: kill -9 <PID>"
    echo ""
    echo "[或使用命令强制停止所有Python]"
    echo "pkill -f python"
    echo ""
    echo "[当前运行的Python进程]"
    pgrep -f "web_admin" -a 2>/dev/null || echo "无"
fi

echo ""
read -p "按任意键继续..."
exit 0
