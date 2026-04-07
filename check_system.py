import sys
import os
sys.path.insert(0, r'C:\Users\TUF\.openclaw\workspace\trading_system')

from trading_core.exchange_client import get_exchange_client
from trading_core.risk_manager import get_risk_manager
from trading_core.order_executor import get_order_executor
from trading_core.strategy_engine_adapter import get_strategy_manager

print('=== 检查交易系统状态 ===')
print()

# 检查交易所连接
print('1. 检查交易所连接...')
try:
    exchange = get_exchange_client()
    balance = exchange.get_balance()
    print(f'   [OK] 交易所连接正常')
    print(f'   余额: {balance}')
except Exception as e:
    print(f'   [ERROR] 交易所连接失败: {e}')

print()

# 检查风险管理器
print('2. 检查风险管理器...')
try:
    risk = get_risk_manager()
    print(f'   [OK] 风险管理器正常')
    print(f'   最大持仓: {risk.max_position_usdt} USDT')
except Exception as e:
    print(f'   [ERROR] 风险管理器错误: {e}')

print()

# 检查订单执行器
print('3. 检查订单执行器...')
try:
    executor = get_order_executor()
    print(f'   [OK] 订单执行器正常')
    print(f'   自动交易: {"开启" if executor.auto_trading else "关闭"}')
except Exception as e:
    print(f'   [ERROR] 订单执行器错误: {e}')

print()

# 检查策略管理器
print('4. 检查策略管理器...')
try:
    strategy = get_strategy_manager(exchange, risk, executor)
    status = strategy.get_status()
    print(f'   [OK] 策略管理器正常')
    print(f'   运行状态: {"运行中" if status["running"] else "已停止"}')
    print(f'   策略数量: {len(status["strategies"])}')
    for name, s in status['strategies'].items():
        print(f'   - {name}: {s["status"]}')
except Exception as e:
    print(f'   [ERROR] 策略管理器错误: {e}')
    import traceback
    traceback.print_exc()

print()
print('=== 检查完成 ===')
