# Web页面启动/停止策略引擎 - 修复完成

## 问题原因
Web服务器进程和API调用使用了不同的策略管理器实例，导致启动/停止操作无法生效。

## 解决方案
修改了 `web_admin/app.py`，使用全局变量 `_strategy_manager` 来确保所有API调用使用同一个策略管理器实例。

## 修改的文件
1. `web_admin/app.py`
   - 使用全局变量 `_exchange`, `_risk_manager`, `_order_executor`, `_strategy_manager`
   - 修改了 `start_strategy_engine()` API
   - 修改了 `stop_strategy_engine()` API
   - 修改了 `get_strategies()` API

## 测试验证
重启Web服务器后，API测试通过：
- ✅ 启动策略引擎成功
- ✅ 停止策略引擎成功
- ✅ 获取策略状态正常

## 使用方法
1. 打开信号监控页面 `http://127.0.0.1:5000/signals`
2. 点击"▶️ 启动策略"按钮启动策略引擎
3. 点击"⏸️ 停止策略"按钮停止策略引擎

## 注意事项
- Web服务器重启后，策略引擎默认不会自动启动（除非点击启动按钮）
- 策略引擎启动后会每60秒扫描一次市场
- 策略状态会实时显示在页面上
