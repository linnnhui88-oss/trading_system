# 量化交易系统

基于MA99多时间框架共振策略的自动化加密货币交易系统。

## 功能特性

- 📊 **MTF策略引擎** - 多时间框架共振确认交易信号
- 🤖 **自动交易** - 信号触发自动下单
- 🌐 **Web管理页面** - 实时监控和操作
- 📱 **Telegram通知** - 实时推送交易信号
- 🧠 **AI分析** - Gemini AI提供交易建议
- ⚡ **风险控制** - 仓位管理、止损止盈

## 系统要求

- Python 3.8+
- Windows/Linux/macOS
- 代理（国内访问币安需要）

## 快速开始

### 1. 克隆仓库
```bash
git clone https://github.com/yourusername/trading_system.git
cd trading_system
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 文件，填入你的API密钥
```

### 4. 启动系统
```bash
# Windows
start.bat

# Linux/Mac
./start.sh
```

### 5. 访问管理页面
打开浏览器访问 http://localhost:5000

## 配置说明

编辑 `.env` 文件：

```env
# 币安API密钥（需要合约交易权限）
BINANCE_API_KEY=your_api_key
BINANCE_SECRET_KEY=your_secret_key

# Telegram通知（可选）
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Gemini AI（可选）
GEMINI_API_KEY=your_gemini_key

# 代理配置（国内需要）
PROXY_URL=http://127.0.0.1:7897

# 交易参数
MAX_POSITION_USDT=1000        # 最大持仓金额
MAX_DAILY_LOSS_USDT=500       # 每日最大亏损
DEFAULT_LEVERAGE=3            # 默认杠杆
STOP_LOSS_PERCENT=2           # 止损比例
TAKE_PROFIT_PERCENT=4         # 止盈比例
```

## 项目结构

```
trading_system/
├── trading_core/          # 核心交易模块
│   ├── exchange_client.py # 交易所API封装
│   ├── risk_manager.py    # 风险管理
│   └── order_executor.py  # 订单执行
├── strategy/              # 策略模块
│   └── strategy_engine.py # MA99策略引擎
├── web_admin/             # Web管理页面
│   ├── app.py            # Flask后端
│   └── templates/        # HTML页面
├── data/                  # 数据存储
├── .env.example          # 环境变量示例
├── requirements.txt      # Python依赖
├── start.bat            # Windows启动脚本
├── start.sh             # Linux/Mac启动脚本
└── README.md            # 说明文档
```

## 安全提示

⚠️ **重要安全提醒：**

1. **API密钥安全**
   - 只开启"读取"和"合约交易"权限
   - 不要开启"提现"权限
   - 绑定IP白名单

2. **资金安全**
   - 先用测试网验证策略
   - 只投入可承受亏损的资金
   - 设置合理的风险控制参数

3. **隐私保护**
   - `.env` 文件包含敏感信息，不要上传到GitHub
   - 已添加到 `.gitignore`

## 免责声明

本系统仅供学习和研究使用，不构成投资建议。加密货币交易风险极高，可能导致全部本金损失。使用本系统产生的任何盈亏由用户自行承担。

## 许可证

MIT License
