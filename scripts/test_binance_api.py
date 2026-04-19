import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

# 直接连接币安API
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

# 测试1: 获取ETH成交记录
print("="*60)
print("测试1: 获取 ETH/USDT:USDT 成交记录")
print("="*60)
since_ms = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
try:
    trades = exchange.fetch_my_trades('ETH/USDT:USDT', since=since_ms, limit=1000)
    print(f"✅ 获取到 {len(trades)} 笔成交")
    for t in trades[:5]:
        print(f"  {t.get('datetime')} | {t.get('symbol')} | {t.get('side')} | 数量: {t.get('amount')} | 价格: {t.get('price')}")
except Exception as e:
    print(f"❌ 错误: {e}")

# 测试2: 获取XRP成交记录（之前同步成功过）
print("\n" + "="*60)
print("测试2: 获取 XRP/USDT:USDT 成交记录")
print("="*60)
try:
    trades = exchange.fetch_my_trades('XRP/USDT:USDT', since=since_ms, limit=1000)
    print(f"✅ 获取到 {len(trades)} 笔成交")
    for t in trades[:5]:
        print(f"  {t.get('datetime')} | {t.get('symbol')} | {t.get('side')} | 数量: {t.get('amount')} | 价格: {t.get('price')}")
except Exception as e:
    print(f"❌ 错误: {e}")

# 测试3: 获取所有订单（不是成交）
print("\n" + "="*60)
print("测试3: 获取 ETH/USDT:USDT 订单历史")
print("="*60)
try:
    orders = exchange.fetch_orders('ETH/USDT:USDT', since=since_ms, limit=1000)
    print(f"✅ 获取到 {len(orders)} 笔订单")
    filled_orders = [o for o in orders if o.get('status') == 'closed']
    print(f"   其中已成交: {len(filled_orders)} 笔")
    for o in filled_orders[:5]:
        print(f"  {o.get('datetime')} | {o.get('symbol')} | {o.get('side')} | 状态: {o.get('status')} | 数量: {o.get('filled')}")
except Exception as e:
    print(f"❌ 错误: {e}")
