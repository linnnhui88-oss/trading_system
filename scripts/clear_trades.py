#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清空交易记录数据库
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
from trading_core.trade_fill_repository import TradeFillRepository

repo = TradeFillRepository()

# 连接数据库并清空表
conn = sqlite3.connect(repo.db_path)
cursor = conn.cursor()

print("正在清空 trade_fills 表...")
cursor.execute("DELETE FROM trade_fills")
cursor.execute("DELETE FROM sqlite_sequence WHERE name='trade_fills'")
conn.commit()

# 验证
cursor.execute("SELECT COUNT(*) FROM trade_fills")
count = cursor.fetchone()[0]
conn.close()

print(f"✅ 已清空，当前记录数: {count}")
