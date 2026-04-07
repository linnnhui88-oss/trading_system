"""
诊断策略引擎启动问题
"""
import sys
import os
sys.path.insert(0, r'C:\Users\TUF\.openclaw\workspace\trading_system')

# 直接测试策略引擎适配器
from trading_core.exchange_client import get_exchange_client
from trading_core.risk_manager import get_risk_manager
from trading_core.order_executor import get_order_executor
from trading_core.strategy_engine_adapter import get_strategy_manager

print('=== 诊断策略引擎启动 ===')
print()

# 初始化组件
print('[1] 初始化交易所...')
exchange = get_exchange_client()
print(f'    Exchange: {exchange is not None}')

print('[2] 初始化风险管理器...')
risk = get_risk_manager()
print(f'    Risk Manager: {risk is not None}')

print('[3] 初始化订单执行器...')
executor = get_order_executor()
print(f'    Order Executor: {executor is not None}')

print('[4] 初始化策略管理器...')
strategy = get_strategy_manager(exchange, risk, executor)
print(f'    Strategy Manager: {strategy is not None}')

print()
print(f'当前运行状态: {strategy._running}')
print(f'策略数量: {len(strategy.strategies)}')
for name in strategy.strategies:
    print(f'  - {name}: {strategy.status[name].value}')

print()
print('[5] 启动策略引擎...')
if not strategy._running:
    strategy.start(interval=60)
    strategy.start_all()
    print(f'启动后状态: {strategy._running}')
else:
    print('策略引擎已在运行')

print()
print('=== 诊断完成 ===')

# 保持运行
import time
try:
    print('按 Ctrl+C 停止')
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print()
    print('停止策略引擎...')
    strategy.stop()
    print('已停止')
