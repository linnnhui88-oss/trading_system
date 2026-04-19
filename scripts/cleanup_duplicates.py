#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清理重复的交易记录
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading_core.trade_fill_repository import TradeFillRepository
import sqlite3

repo = TradeFillRepository()

# 获取所有记录
all_fills = repo.list_fills(limit=1000)
print(f"当前共有 {len(all_fills)} 条记录")

# 找出重复项（基于exchange_trade_id）
seen_ids = {}
duplicates = []

for fill in all_fills:
    trade_id = fill.get('exchange_trade_id', '')
    if trade_id in seen_ids:
        duplicates.append(fill['id'])
    else:
        seen_ids[trade_id] = fill['id']

print(f"\n发现 {len(duplicates)} 条重复记录")

if duplicates:
    # 连接数据库删除重复项
    conn = sqlite3.connect(repo.db_path)
    cursor = conn.cursor()
    
    for dup_id in duplicates:
        cursor.execute("DELETE FROM trade_fills WHERE id = ?", (dup_id,))
        print(f"  删除重复记录 ID: {dup_id}")
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ 已清理 {len(duplicates)} 条重复记录")
    
    # 重新统计
    all_fills = repo.list_fills(limit=1000)
    print(f"\n清理后共有 {len(all_fills)} 条记录")
else:
    print("✅ 没有发现重复记录")

# 显示最终统计
summary = repo.get_summary()
print(f"\n汇总统计:")
print(f"  总成交数: {summary['total_fills']}")
print(f"  总盈亏: ${summary['total_realized_pnl']:.2f}")
print(f"  总手续费: ${summary['total_fee']:.2f}")
