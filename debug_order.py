# debug_order.py - 调试下单问题
import sys
sys.path.insert(0, r'C:\Users\TUF\.openclaw\workspace\trading_system')

from trading_core.exchange_client import get_exchange_client
from trading_core.risk_manager import get_risk_manager

print('=== Debug Order Creation ===')
print()

exchange = get_exchange_client()
risk = get_risk_manager()

# 当前配置
print(f'Max Position: {risk.max_position_usdt} USDT')
print(f'Leverage: {risk.default_leverage}x')

# 计算仓位
symbol = 'BTC/USDT'
price = 69183.2  # 币安显示的价格
confidence = 1.0

amount = risk.calculate_position_size(symbol, price, confidence)
print(f'\nPrice: ${price}')
print(f'Confidence: {confidence}')
print(f'Calculated amount: {amount} BTC')
print(f'Value: ${amount * price} USDT')

# 检查币安的最小下单量
print('\n=== Binance Requirements ===')
try:
    market = exchange.exchange.market(symbol)
    market_id = market.get('id', 'N/A')
    print(f'Market: {market_id}')
    limits = market.get('limits', {})
    print(f'Amount limits: {limits.get("amount", {})}')
    print(f'Cost limits: {limits.get("cost", {})}')
    print(f'Precision: {market.get("precision", {})}')
except Exception as e:
    print(f'Error: {e}')

# 测试下单
try:
    print('\n=== Testing Create Order ===')
    # 先设置杠杆
    exchange.set_leverage(symbol, 3)
    # 尝试下单 0.002 BTC
    order = exchange.create_order(symbol, 'buy', 0.002, order_type='market')
    print(f'Order result: {order}')
except Exception as e:
    print(f'Order error: {e}')

print('\n=== Done ===')
