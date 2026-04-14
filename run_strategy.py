"""
独立启动策略引擎脚本
使用方法: .\venv\Scripts\python run_strategy.py
"""
import sys
import os
# 使用相对路径，确保在任何机器上都能运行
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trading_core.exchange_client import get_exchange_client
from trading_core.risk_manager import get_risk_manager
from trading_core.order_executor import get_order_executor
from trading_core.strategy_engine_adapter import get_strategy_manager
import time

print('=' * 60)
print('MA99 Multi-Timeframe Strategy Engine')
print('=' * 60)
print()

# 初始化组件
print('[1/4] Initializing exchange client...')
exchange = get_exchange_client()
print('      OK')

print('[2/4] Initializing risk manager...')
risk = get_risk_manager()
print('      OK')

print('[3/4] Initializing order executor...')
executor = get_order_executor()
print('      OK')

print('[4/4] Initializing strategy manager...')
strategy = get_strategy_manager(exchange, risk, executor)
print('      OK')

print()

# 检查当前状态
status = strategy.get_status()
print(f'Engine Status: {"RUNNING" if status["running"] else "STOPPED"}')
print(f'Strategies: {list(status["strategies"].keys())}')
for name, s in status['strategies'].items():
    print(f'  - {name}: {s["status"]}')
print()

if status['running']:
    print('Strategy engine is already running!')
    print('Exiting...')
    sys.exit(0)

# 启动策略引擎
print('Starting strategy engine...')
strategy.start(interval=60)  # 60秒扫描间隔
strategy.start_all()  # 启动所有策略

print()
print('Strategy engine started successfully!')
print('Scan interval: 60 seconds')
print('Press Ctrl+C to stop')
print()

# 保持运行
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print()
    print()
    print('Stopping strategy engine...')
    strategy.stop()
    print('Strategy engine stopped.')
    print()
    print('Goodbye!')
