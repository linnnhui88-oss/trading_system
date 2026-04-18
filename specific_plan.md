# 交易系统总体改造方案（完整版）

## 一、 总体改造思路
建议将此次升级拆分为三个层次，由浅入深进行开发，以确保系统在升级过程中的稳定性：

1. **第一层：展示与配置层（非核心逻辑）**
   * **核心目标**：增加后台展示和配置，不动核心下单逻辑。
   * **具体任务**：增强仪表盘、展示完整交易记录、在策略页增加币种/策略/AI模型选择、在设置页增加 AI API 配置。
   * **优势**：系统看起来更像成品，且最不容易导致核心功能崩溃。

2. **第二层：策略执行链路接入**
   * **具体任务**：实现策略绑定 AI 模型、AI 返回结构化决策、通过自动交易开关控制“只提醒”或“真下单”。

3. **第三层：行情与性能增强**
   * **具体任务**：接入 WebSocket 实时行情、同步 K 线周期、展示买卖盘 1-5 档、优化图表至 Binance 风格。
   * **注意**：此层需单独进行，因为实时流最容易消耗系统资源并影响稳定性。

---

## 二、 仪表盘页面改造方案 (Dashboard)
**目标**：支持更多币种、与币安同步、实时跳动、UI 接近 Binance 风格。

### 1.1 新增独立行情服务模块
* **新增文件**：`trading_core/market_data_service.py`
* **主要职责**：
    * 拉取币安行情（Ticker：最新价、涨跌幅、24h 高低、成交量）。
    * 拉取 K 线数据（Klines）。
    * 拉取深度档位（Depth：买卖 1-5 档）。
    * 维护内存缓存，为 Web 页面提供实时数据。
* **支持周期**：与 Binance 一致（1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d, 1w）。

### 1.2 稳定性与性能建议
* **按需推送**：首页默认显示用户选中币种。仅对当前查看的币种开启高频实时推送，其余币种使用低频快照，避免 SocketIO 负载过载。
* **前端图表**：建议使用 `lightweight-charts` 库，其性能稳定且风格自然接近交易所。

### 1.3 后端接口设计
* `GET /api/market/symbols`：获取可选币种。
* `GET /api/market/ticker?symbol=BTCUSDT`：获取单个币种行情快照。
* `GET /api/market/klines?symbol=BTCUSDT&interval=5m&limit=200`：获取 K 线。
* `GET /api/market/depth?symbol=BTCUSDT&limit=5`：获取买卖盘。

---

## 三、 交易记录页面改造方案 (Trade History)
**核心要求**：必须将“成交/执行事件”单独记录，以支持展示部分平仓数据和历史细节。

### 2.1 新增数据表：trade_fills (成交明细表)

    CREATE TABLE IF NOT EXISTS trade_fills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_name TEXT,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        position_side TEXT,
        action_type TEXT NOT NULL,
        order_id TEXT,
        exchange_trade_id TEXT,
        quantity REAL NOT NULL,
        price REAL NOT NULL,
        realized_pnl REAL DEFAULT 0,
        fee REAL DEFAULT 0,
        fee_asset TEXT,
        ai_model TEXT,
        ai_decision TEXT,
        signal_source TEXT,
        signal_reason TEXT,
        executed_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

### 2.2 逻辑修改点
* **修改文件**：`trading_core/order_executor.py`。
* **逻辑实现**：在开仓、部分平仓、止盈止损、手动平仓等动作执行成功后，统一调用新增的私有方法 `_record_trade_fill` 写入上述数据表。

---

## 四、 策略信号页面改造方案 (Strategy)
**目标**：手动选择盯盘币种、策略及 AI 模型。

### 3.1 策略表扩展字段

    ALTER TABLE strategies ADD COLUMN symbol TEXT;
    ALTER TABLE strategies ADD COLUMN interval TEXT DEFAULT '5m';
    ALTER TABLE strategies ADD COLUMN ai_enabled INTEGER DEFAULT 1;
    ALTER TABLE strategies ADD COLUMN ai_model TEXT;
    ALTER TABLE strategies ADD COLUMN telegram_notify INTEGER DEFAULT 1;
    ALTER TABLE strategies ADD COLUMN auto_trade_follow_global INTEGER DEFAULT 1;
    ALTER TABLE strategies ADD COLUMN status TEXT DEFAULT 'stopped';

### 3.2 核心执行逻辑
* **自动交易关闭**：策略发现信号 -> AI 分析 -> Telegram 推送分析结果 -> **不下单**。
* **自动交易开启**：策略发现信号 -> AI 分析 -> AI 判定执行 -> 风控检查 -> **自动下单** -> Telegram 推送执行结果。

---

## 五、 设置页面 AI 配置方案 (Settings)
**原则**：做成“模型提供商管理”模式，支持多模型灵活切换。

### 4.1 数据表：ai_provider_configs

    CREATE TABLE IF NOT EXISTS ai_provider_configs (
        provider_key TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        api_key TEXT,
        base_url TEXT,
        model_name TEXT,
        is_enabled INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
    );

---

## 六、 最小改造清单（按文件分）

### 6.1 新增文件
* `trading_core/market_data_service.py`：负责行情同步。
* `trading_core/ai_model_registry.py`：模型名与标签注册。
* `trading_core/ai_provider_config_manager.py`：管理数据库中的 AI 配置。
* `trading_core/llm_service.py`：统一的 AI 调用入口。
* `trading_core/trade_fill_repository.py`：成交明细的增删改查。

### 6.2 重点修改文件
* `web_admin/app.py`：新增相关 API 接口，负责前端与后端数据交互。
* `trading_core/order_executor.py`：在执行交易后增加记录写入逻辑。
* `trading_core/strategy_engine_adapter.py`：适配新的币种、周期和 AI 模型配置，并引入全局交易开关控制。

---

## 七、 推荐开发与上线顺序
1. **第 1 步**：数据库扩展（创建 ai_provider_configs、trade_fills 表，修改 strategies 字段）。
2. **第 2 步**：后端接口开发（AI 模型管理接口、历史记录接口、市场基础接口）。
3. **第 3 步**：前端页面构建（Settings 配置页、Strategy 策略控制页、History 记录页）。
4. **第 4 步**：对接实时行情（接入 WebSocket 订阅，实现仪表盘实时跳动）。
5. **第 5 步**：AI 执行链路闭环（最后将 AI 的决策真正接入 order_executor 自动下单逻辑）。

---
**最终建议**：坚持“先加展示与配置 -> 再加成交记录 -> 再加实时行情 -> 最后接入 AI 自动下单”的开发路径，确保每一步都能单独运行测试，防止量化系统崩溃。