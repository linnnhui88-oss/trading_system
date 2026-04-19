import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading_core.trade_fill_repository import TradeFillRepository

repo = TradeFillRepository()

# 获取所有记录
all_fills = repo.list_fills(limit=100)

print(f"数据库中共有 {len(all_fills)} 条记录\n")
print("="*100)
print(f"{'时间':20} | {'交易对':12} | {'方向':4} | {'类型':10} | {'数量':12} | {'价格':10} | {'来源':15}")
print("="*100)

for f in all_fills[:20]:  # 只显示前20条
    time_str = f['executed_at'][:19] if f['executed_at'] else 'N/A'
    symbol = f['symbol'][:12]
    side = f['side'][:4]
    action = f['action_type'][:10]
    qty = f['quantity']
    price = f['price']
    source = f.get('signal_source', '')[:15]
    print(f"{time_str:20} | {symbol:12} | {side:4} | {action:10} | {qty:12.4f} | ${price:9.2f} | {source:15}")

if len(all_fills) > 20:
    print(f"\n... 还有 {len(all_fills) - 20} 条记录 ...")

print("="*100)

# 按交易对统计
from collections import Counter
symbols = [f['symbol'] for f in all_fills]
symbol_counts = Counter(symbols)

print(f"\n📊 按交易对统计:")
for symbol, count in symbol_counts.most_common():
    print(f"  {symbol}: {count} 笔")
