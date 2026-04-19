import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading_core.trade_fill_repository import TradeFillRepository

repo = TradeFillRepository()
fills = repo.list_fills(limit=10)

print(f'数据库中共有 {len(fills)} 条记录：\n')
for f in fills[:5]:
    time_str = f['executed_at'][:19] if f['executed_at'] else 'N/A'
    symbol = f['symbol'][:12]
    side = f['side'][:4]
    action = f['action_type'][:12]
    qty = f['quantity']
    price = f['price']
    print(f"  {time_str} | {symbol:12} | {side:4} | {action:12} | 数量: {qty:.4f} | 价格: ${price:.2f}")

summary = repo.get_summary()
print(f"\n汇总统计:")
print(f"  总成交数: {summary['total_fills']}")
print(f"  总盈亏: ${summary['total_realized_pnl']:.2f}")
print(f"  总手续费: ${summary['total_fee']:.2f}")
