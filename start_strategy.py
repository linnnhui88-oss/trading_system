import sys
import os
# 使用相对路径，确保在任何机器上都能运行
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trading_core.exchange_client import get_exchange_client
from trading_core.risk_manager import get_risk_manager
from trading_core.order_executor import get_order_executor
from trading_core.strategy_engine_adapter import get_strategy_manager

print('=== 启动交易策略 ===')
print()

# 获取组件
print('1. 初始化组件...')
exchange = get_exchange_client()
risk = get_risk_manager()
executor = get_order_executor()
strategy = get_strategy_manager(exchange, risk, executor)
print('   [OK] 组件初始化完成')

print()

# 检查当前状态
status = strategy.get_status()
print(f'2. 当前策略状态: {"运行中" if status["running"] else "已停止"}')

print()

# 启动策略
print('3. 启动策略...')
strategy.start(interval=60)  # 60秒扫描间隔
strategy.start_all()  # 启动所有策略

print('   [OK] 策略已启动')

print()

# 验证状态
status = strategy.get_status()
print(f'4. 验证策略状态: {"运行中" if status["running"] else "已停止"}')

for name, s in status['strategies'].items():
    print(f'   - {name}: {s["status"]}')

print()
print('=== 策略启动完成 ===')
print('策略将每60秒扫描一次市场')
print('按 Ctrl+C 停止')

# 保持运行
try:
    import time
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print()
    print('=== 停止策略 ===')
    strategy.stop()
    print('策略已停止')
