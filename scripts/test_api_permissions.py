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
print("API权限检查")
print("="*60)

# 获取账户信息
try:
    # 使用CCXT的标准方法
    balance = exchange.fetch_balance()
    print(f"\n✅ fetch_balance: 成功")
    print(f"   USDT: {balance.get('USDT', {}).get('free', 0)}")
except Exception as e:
    print(f"\n❌ fetch_balance: {e}")

# 检查持仓
try:
    positions = exchange.fetch_positions()
    print(f"\n✅ fetch_positions: 成功 ({len(positions)} 个持仓)")
except Exception as e:
    print(f"\n❌ fetch_positions: {e}")

# 测试获取订单历史 - 使用不同参数组合
print("\n" + "="*60)
print("测试不同参数组合获取订单")
print("="*60)

symbol = 'ETH/USDT:USDT'
since_ms = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)

# 测试1: 基本调用
print(f"\n测试1: fetch_orders({symbol})")
try:
    orders = exchange.fetch_orders(symbol)
    print(f"   结果: {len(orders)} 笔订单")
except Exception as e:
    print(f"   错误: {e}")

# 测试2: 带since参数
print(f"\n测试2: fetch_orders({symbol}, since={since_ms})")
try:
    orders = exchange.fetch_orders(symbol, since=since_ms)
    print(f"   结果: {len(orders)} 笔订单")
except Exception as e:
    print(f"   错误: {e}")

# 测试3: 带limit参数
print(f"\n测试3: fetch_orders({symbol}, limit=1000)")
try:
    orders = exchange.fetch_orders(symbol, limit=1000)
    print(f"   结果: {len(orders)} 笔订单")
except Exception as e:
    print(f"   错误: {e}")

# 测试4: 获取我的成交
print(f"\n测试4: fetch_my_trades({symbol})")
try:
    trades = exchange.fetch_my_trades(symbol)
    print(f"   结果: {len(trades)} 笔成交")
except Exception as e:
    print(f"   错误: {e}")

# 测试5: 获取所有历史订单（包括已取消）
print(f"\n测试5: fetch_closed_orders({symbol})")
try:
    orders = exchange.fetch_closed_orders(symbol)
    print(f"   结果: {len(orders)} 笔已关闭订单")
except Exception as e:
    print(f"   错误: {e}")

print("\n" + "="*60)
print("结论")
print("="*60)
print("如果以上测试都返回0条记录，可能的原因：")
print("1. API密钥没有'读取订单历史'权限")
print("2. 这些交易是在现货账户，不是合约账户")
print("3. 交易是在子账户或不同的币安账户")
print("4. 币安API对历史数据有3个月或6个月的限制")
