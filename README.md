# 🤖 自动化交易生存指南 - 量化交易系统

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-2.0+-green.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

一个基于Python的加密货币量化交易系统，支持多策略信号、AI辅助决策、实时Web监控和自动交易执行。

## ✨ 功能特性

### 📊 策略系统
- **MA99多周期共振策略**：趋势跟踪 + 多周期共振过滤
- **多策略共识模式**：支持多个策略同时确认信号
- **AI辅助决策**：集成Gemini AI进行信号分析
- **信号记忆系统**：防止重复开仓

### 🌐 Web管理界面
- **实时仪表盘**：余额、持仓、盈亏实时监控
- **信号监控**：实时信号日志、策略运行状态
- **交易记录**：历史交易查询、盈利曲线
- **系统设置**：参数配置、风险管理

### ⚡ 实时功能
- **WebSocket实时推送**：信号、日志、状态实时更新
- **60秒心跳机制**：系统健康监控
- **自动刷新**：页面数据自动同步

### 🛡️ 风险管理
- **仓位控制**：最大持仓金额、数量限制
- **每日止损**：单日最大亏损限制
- **动态止盈止损**：基于ATR的动态计算
- **紧急停止**：一键平仓停止交易

### 📱 通知系统
- **Telegram通知**：交易信号、成交提醒
- **邮件通知**：支持SMTP邮件提醒
- **Web日志**：详细的策略执行日志

## 🚀 快速开始

### 环境要求
- Python 3.8+
- Windows/Linux/macOS

### 安装步骤

1. **克隆仓库**
```bash
git clone https://github.com/linnnhui88-oss/trading_system.git
cd trading_system
```

2. **创建虚拟环境**
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

3. **安装依赖**
```bash
pip install -r requirements.txt
```

4. **配置环境变量**
```bash
cp .env.example .env
# 编辑 .env 文件，填写你的API密钥和配置
```

5. **启动Web服务器**
```bash
python -m web_admin.app
```

6. **访问Web界面**
打开浏览器访问 http://127.0.0.1:5000

### 启动策略引擎

在Web界面的"信号监控"页面点击"▶️ 启动策略"按钮，或运行：
```bash
python run_strategy.py
```

## 📁 项目结构

```
trading_system/
├── web_admin/              # Web管理界面
│   ├── app.py             # Flask应用主文件
│   └── templates/         # HTML模板
│       ├── dashboard.html # 仪表盘
│       ├── signals.html   # 信号监控
│       ├── trades.html    # 交易记录
│       └── settings.html  # 系统设置
├── trading_core/          # 交易核心模块
│   ├── exchange_client.py # 交易所客户端
│   ├── risk_manager.py    # 风险管理器
│   ├── order_executor.py  # 订单执行器
│   ├── strategy_engine_adapter.py # 策略引擎适配器
│   └── strategies/        # 策略实现
├── strategy/              # 原始策略代码
│   └── strategy_engine.py # MA99策略引擎
├── data/                  # 数据文件
│   ├── trade_signals.json # 信号日志
│   └── signals_history.jsonl # 信号历史
├── .env.example           # 环境变量示例
├── requirements.txt       # Python依赖
└── README.md             # 项目说明
```

## ⚙️ 配置说明

### 交易所API配置
```env
BINANCE_API_KEY=your_binance_api_key
BINANCE_SECRET_KEY=your_binance_secret_key
PROXY_URL=http://127.0.0.1:7897  # 如果需要代理
```

### Telegram通知配置（可选）
```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 交易参数配置
```env
MAX_POSITION_USDT=50          # 最大持仓金额（USDT）
MAX_DAILY_LOSS_USDT=30        # 每日最大亏损
DEFAULT_LEVERAGE=3            # 默认杠杆倍数
MAX_POSITIONS_COUNT=1         # 最大持仓数量
```

## 🔒 安全提示

1. **保护API密钥**：不要将`.env`文件提交到GitHub
2. **使用代理**：建议通过代理连接交易所API
3. **限制IP**：在交易所设置IP白名单
4. **小额测试**：首次使用建议用小额资金测试
5. **定期备份**：定期备份交易数据和配置

## 🤝 贡献指南

欢迎提交Issue和Pull Request！


## ⚠️ 免责声明

本项目仅供学习和研究使用，不构成投资建议。加密货币交易风险极高，可能导致资金损失，请谨慎使用。

---

**注意**：使用本系统前请确保你了解量化交易的风险，并建议先用模拟账户或小资金进行测试。
