import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt
from dotenv import load_dotenv

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

print("="*60)
print("账户信息检查")
print("="*60)

# 检查账户信息
try:
    balance = exchange.fetch_balance()
    print(f"\n✅ 账户连接成功")
    print(f"   USDT 可用: {balance.get('USDT', {}).get('free', 0)}")
    print(f"   USDT 冻结: {balance.get('USDT', {}).get('used', 0)}")
except Exception as e:
    print(f"❌ 获取余额失败: {e}")

# 检查持仓
try:
    positions = exchange.fetch_positions()
    print(f"\n✅ 当前持仓数量: {len(positions)}")
    for p in positions[:5]:
        if float(p.get('contracts', 0)) != 0:
            print(f"   {p.get('symbol')}: {p.get('contracts')} 张 | 方向: {p.get('side')}")
except Exception as e:
    print(f"❌ 获取持仓失败: {e}")

# 检查API权限
try:
    account_info = exchange.fapiPrivate_get_account()
    print(f"\n✅ 期货账户信息获取成功")
    print(f"   账户类型: {'全仓' if account_info.get('canTrade') else '受限'}")
except Exception as e:
    print(f"❌ 获取账户信息失败: {e}")

# 尝试获取所有成交记录（不指定symbol）
print("\n" + "="*60)
print("尝试获取所有成交记录")
print("="*60)
try:
    # 币安API不支持不指定symbol获取所有成交，需要逐个获取
    markets = exchange.load_markets()
    futures_symbols = [s for s in markets.keys() if ':USDT' in s]
    print(f"发现 {len(futures_symbols)} 个合约交易对")
    
    total_trades = 0
    for sym in ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'XRP/USDT:USDT', 'DOT/USDT:USDT', 'ADA/USDT:USDT']:
        try:
            trades = exchange.fetch_my_trades(sym, limit=1000)
            if trades:
                print(f"   {sym}: {len(trades)} 笔成交")
                total_trades += len(trades)
        except Exception as e:
            pass
    
    print(f"\n总计: {total_trades} 笔成交")
except Exception as e:
    print(f"❌ 错误: {e}")
