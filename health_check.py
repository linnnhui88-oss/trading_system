# health_check.py - 系统健康检查
import sys
sys.path.insert(0, r'C:\Users\TUF\.openclaw\workspace\trading_system')

print('=== System Health Check ===')
print()

# 1. Check exchange connection
from trading_core.exchange_client import get_exchange_client
try:
    exchange = get_exchange_client()
    balance = exchange.get_balance()
    positions = exchange.get_positions()
    print('[OK] Exchange: Connected')
    print(f'     Balance: {balance.get("USDT", 0)} USDT')
    print(f'     Positions: {len(positions)}')
except Exception as e:
    print(f'[X] Exchange Error: {e}')

print()

# 2. Check order executor
from trading_core.order_executor import get_order_executor
try:
    executor = get_order_executor()
    print('[OK] Order Executor: Ready')
    print(f'     Auto Trading: {executor.auto_trading}')
except Exception as e:
    print(f'[X] Order Executor Error: {e}')

print()

# 3. Check risk manager config
from trading_core.risk_manager import get_risk_manager
try:
    risk = get_risk_manager()
    print('[OK] Risk Manager: Ready')
    print(f'     Max Position: {risk.max_position_usdt} USDT')
    print(f'     Max Positions: {risk.max_positions_count}')
except Exception as e:
    print(f'[X] Risk Manager Error: {e}')

print()

# 4. Test order creation
print('[TEST] Testing order creation...')
try:
    executor.auto_trading = True
    result = executor.execute_signal('BTC/USDT', '1h', 'LONG', 68000, 45, 0.8)
    print(f'     Result: {result}')
except Exception as e:
    print(f'     Error: {e}')

print()
print('=== Check Complete ===')
