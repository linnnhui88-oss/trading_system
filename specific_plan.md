# 交易系统升级计划与当前进度（持续更新）

最后更新：2026-04-19

---

## 一、总体目标（与你确认的三点需求）
1. 仪表盘（Dashboard）
- K线更实时、更丝滑
- 下方/侧边行情信息更专业
- 右侧买卖盘 1-5
- 中间实时跳动当前价格

2. 信号监控页（Signals）
- 运行参数从手填改为卡片式选择
- 三个“重点盯盘币种”卡片（策略、周期多选、AI模型）
- 一个“多币种盯盘”大卡片（排除重点币种）
- 日志改纯文本盯盘风格，并接入 Telegram 提醒展示

3. 设置页（Settings）
- 去掉旧的“AI 大模型配置”模块（避免与“模型提供商管理”重复）
- 模型提供商中的 model_name 改为下拉选择，不再手填
- 每个提供商预置 <= 5 个主流模型

---

## 二、当前真实进度（按页面）

### 2.1 Dashboard（第1点）
当前状态：**功能在，UI已对齐参考风格，且左/右模块已恢复可见**

已完成：
- 实时 K 线链路可用（`/api/market/klines`）
- 实时行情快照可用（`/api/market/snapshot`）
- Socket 行情订阅可用（`subscribe_market` / `unsubscribe_market` / `market_update`）
- 中间实时价格跳动可用（`marketPriceMain` + 动画更新）
- 左侧交易信息模块可见（交易对、24h涨跌幅、高低、成交量、买一卖一等）
- 右侧买卖盘 1-5 模块可见（含中间价）
- 页面主体样式已按参考模板靠齐

注意：
- 该页面在迭代中经历过“误覆盖导致功能回退”，已通过恢复 DOM 绑定与接口修复到可用状态。
- 后续改 Dashboard 时必须遵守：**只改样式和结构，不删现有 JS 绑定 ID 与接口调用**。

相关文件：
- `web_admin/templates/dashboard.html`
- `web_admin/app.py`
- `trading_core/market_data_service.py`

### 2.2 Signals（第2点）
当前状态：**未开始功能级改造（仅有旧版能力）**

待做（完整实现）：
- 三个重点盯盘币种卡片（独立配置）
- 多币种盯盘大卡片（排除重点币种）
- 策略/周期/AI模型改为选择器（周期支持多选）
- 盯盘日志改纯文本样式，替换当前 JSON 风格输出
- 将 Telegram 提醒内容映射到页面日志展示

主要涉及：
- `web_admin/templates/signals.html`
- `web_admin/app.py`
- 策略配置持久化相关逻辑（策略配置读写）

### 2.3 Settings（第3点）
当前状态：**部分已具备基础能力，但核心目标尚未落地**

现状：
- 页面同时存在：
  - 旧模块：`🧠 AI 大模型配置`
  - 新模块：`🧩 模型提供商管理`
- 新模块中 `model_name` 仍是文本输入框（手填）

待做（完整实现）：
- 删除旧 `AI 大模型配置` 卡片
- `provider model_name` 改为下拉选择
- 按 provider 预置主流模型（每家 <= 5）
- 可选：后端加白名单校验（防止前端绕过）

主要涉及：
- `web_admin/templates/settings.html`
- `web_admin/app.py`（可选后端校验）

---

## 三、当前代码基线说明（防回滚丢功能）
1. Dashboard 当前必须保留的关键 DOM ID（脚本强依赖）
- `chartSymbol`, `chartTimeframe`, `candlestickChart`
- `marketPriceMain`, `marketPriceChange`, `marketUpdateTime`
- `marketSymbol`, `marketChange`, `marketHighLow`, `marketVolume`, `marketBidAsk`, `marketSpread`, `marketAvgPrice`, `marketOpenPrice`
- `asksTable`, `bidsTable`, `orderMidPrice`, `orderMidChange`
- `positionsTable`, `balanceValue`, `unrealizedPnl`, `positionCount`, `dailyPnl`
- `tradingStatus`, `tradingStatusText`, `tradingEnabled`, `dailyTrades`, `stopLossPercent`, `takeProfitPercent`, `trailingStopPercent`
- `connectionStatus`, `connectionText`, `logContainer`

2. Dashboard 当前必须保留的关键接口/事件
- `GET /api/market/klines`
- `GET /api/market/snapshot`
- `GET /api/status`
- `POST /api/trading/start`, `POST /api/trading/stop`, `POST /api/trading/emergency_stop`
- `POST /api/position/close`
- Socket: `market_update`, `subscribe_market`, `unsubscribe_market`, `heartbeat`

---

## 四、下一步执行顺序（建议）
1. **先做第3点（Settings）**
- 删除旧 AI 大模型配置卡片
- provider 的 model_name 改下拉（主流模型预置）
- 页面可保存/测试/禁用流程保持不变

2. **再做第2点（Signals）**
- 卡片式重构 + 多币种盯盘 + 文本日志 + Telegram 映射

3. Dashboard 只做微调
- 仅做样式细修，不再改接口和绑定逻辑

---

## 五、风险与约束
- 严禁再做“整页覆盖式替换”，改 UI 必须最小化 patch。
- 涉及中文文案改动时，统一按 UTF-8 写入，避免编码错乱。
- 每次改动后至少做一次：
  - DOM 绑定 ID 完整性检查
  - 关键接口名检查
  - 页面可见性回归（左信息 / 中K线 / 右买卖盘）

---

## 六、附：原始总体改造方案（保留）
本仓库最初方案分三层：
1) 展示与配置层
2) 策略执行链路
3) 行情与性能增强

当前实际开发已跨层推进，故以上“当前真实进度”优先作为下次接续依据。
