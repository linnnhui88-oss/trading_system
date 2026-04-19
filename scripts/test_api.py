import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading_core.exchange_client import get_exchange_client
from datetime import datetime, timedelta

exchange = get_exchange_client()

# 获取过去30天的成交记录
since_ms = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)

print("测试获取 ETH/USDT 成交记录...")
try:
    trades = exchange.get_recent_account_trades('ETH/USDT:USDT', since_ms=since_ms, limit=1000)
    print(f"获取到 {len(trades)} 笔成交")
    for t in trades[:3]:
        print(f"  {t.get('datetime')} | {t.get('symbol')} | {t.get('side')} | 数量: {t.get('amount')} | 价格: {t.get('price')}")
except Exception as e:
    print(f"错误: {e}")

print("\n测试获取所有成交记录（不指定symbol）...")
try:
    trades = exchange.get_recent_account_trades(None, since_ms=since_ms, limit=1000)
    print(f"获取到 {len(trades)} 笔成交")
except Exception as e:
    print(f"错误: {e}")
