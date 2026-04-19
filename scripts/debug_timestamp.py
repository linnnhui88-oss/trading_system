import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

config = {
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'recvWindow': 60000,
        'adjustForTimeDifference': True
    }
}

proxy_url = os.getenv('PROXY_URL', '')
if proxy_url:
    config['proxies'] = {'http': proxy_url, 'https': proxy_url}

exchange = ccxt.binance(config)
exchange.load_time_difference()

print("="*60)
print("时间戳问题诊断")
print("="*60)

# 当前时间
now = datetime.now()
print(f"\n当前本地时间: {now}")
print(f"当前时间戳: {int(now.timestamp() * 1000)}")

# 30天前
past = now - timedelta(days=30)
past_ms = int(past.timestamp() * 1000)
print(f"\n30天前本地时间: {past}")
print(f"30天前时间戳: {past_ms}")

# 测试获取ETH订单 - 不使用since参数
symbol = 'ETH/USDT:USDT'
print(f"\n" + "="*60)
print(f"获取 {symbol} 所有订单（不使用since）")
print("="*60)

try:
    orders = exchange.fetch_orders(symbol)
    print(f"✅ 获取到 {len(orders)} 笔订单\n")
    
    for order in orders:
        ts = order.get('timestamp', 0)
        dt = datetime.fromtimestamp(ts / 1000)
        print(f"订单ID: {order.get('id')}")
        print(f"  时间: {dt} (时间戳: {ts})")
        print(f"  交易对: {order.get('symbol')}")
        print(f"  方向: {order.get('side')}")
        print(f"  状态: {order.get('status')}")
        print(f"  数量: {order.get('amount')}")
        print(f"  已成交: {order.get('filled')}")
        print(f"  价格: {order.get('price')}")
        print()
except Exception as e:
    print(f"❌ 错误: {e}")
