#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币安交易历史CSV导入工具
适配币安导出的【交易历史】CSV格式
"""

import os
import sys
import csv
import re
from datetime import datetime
from typing import Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading_core.trade_fill_repository import TradeFillRepository


def parse_datetime(time_str: str) -> datetime:
    """解析币安CSV时间格式: 26-04-19 11:20:49"""
    year = int("20" + time_str[:2])
    month = int(time_str[3:5])
    day = int(time_str[6:8])
    hour = int(time_str[9:11])
    minute = int(time_str[12:14])
    second = int(time_str[15:17])
    return datetime(year, month, day, hour, minute, second)


def parse_fee(fee_str: str) -> tuple:
    """解析手续费字符串: 0.00871162USDT -> (0.00871162, 'USDT')"""
    match = re.match(r'([\d.]+)([A-Za-z]+)', fee_str.replace(' ', ''))
    if match:
        return float(match.group(1)), match.group(2)
    return 0.0, ''


def parse_csv_row(row: Dict) -> Optional[Dict]:
    """解析币安交易历史CSV行"""
    try:
        # 币安交易历史CSV列名
        time_str = row.get('时间', '')
        symbol = row.get('代币名称/币种名称/币对', '')
        side = row.get('方向', '')  # BUY, SELL
        price = row.get('价格', '0')
        quantity = row.get('数量', '0')
        amount = row.get('金额', '0')
        fee_str = row.get('手续费', '0')
        realized_pnl = row.get('已实现利润', '0')
        trade_id = row.get('交易 ID', '')
        order_id = row.get('订单编号', '')
        
        # 解析时间
        dt = parse_datetime(time_str)
        
        # 解析手续费
        fee, fee_asset = parse_fee(fee_str)
        
        # 确定action_type（根据方向简单判断）
        side_upper = side.upper()
        action_type = 'open' if side_upper == 'BUY' else 'close'
        
        fill_data = {
            'strategy_name': 'manual_trading',
            'symbol': symbol,
            'side': side_upper,
            'position_side': 'BOTH',
            'action_type': action_type,
            'order_id': str(order_id),
            'exchange_trade_id': str(trade_id),
            'quantity': float(quantity),
            'price': float(price),
            'realized_pnl': float(realized_pnl),
            'fee': fee,
            'fee_asset': fee_asset,
            'ai_model': '',
            'ai_decision': '',
            'signal_source': 'csv_import',
            'signal_reason': '币安交易历史CSV导入',
            'executed_at': dt.isoformat(),
        }
        
        return fill_data
    except Exception as e:
        print(f"  ⚠️ 解析行失败: {e}")
        return None


def import_csv(csv_file: str) -> Dict:
    """导入CSV文件"""
    repo = TradeFillRepository()
    
    imported = 0
    failed = 0
    
    with open(csv_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    print(f"📄 CSV文件共有 {len(rows)} 行数据\n")
    
    for row in rows:
        try:
            fill_data = parse_csv_row(row)
            if not fill_data:
                failed += 1
                continue
            
            # 创建记录
            repo.create_fill(fill_data)
            imported += 1
            
            if imported % 20 == 0:
                print(f"  已导入 {imported} 笔...")
                
        except Exception as e:
            failed += 1
            print(f"  ⚠️ 导入失败: {e}")
    
    return {'imported': imported, 'failed': failed, 'total': len(rows)}


def main():
    csv_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'binance_trades.csv')
    
    if not os.path.exists(csv_file):
        print(f"❌ 文件不存在: {csv_file}")
        return 1
    
    print(f"\n{'='*60}")
    print(f"🚀 币安交易历史CSV导入")
    print(f"{'='*60}")
    print(f"文件: {csv_file}")
    print(f"{'='*60}\n")
    
    result = import_csv(csv_file)
    
    print(f"\n{'='*60}")
    print(f"📊 导入结果")
    print(f"{'='*60}")
    print(f"✅ 成功导入: {result['imported']}")
    print(f"❌ 导入失败: {result['failed']}")
    print(f"📈 总计: {result['total']}")
    print(f"{'='*60}\n")
    
    # 显示汇总
    repo = TradeFillRepository()
    summary = repo.get_summary()
    print(f"📊 数据库汇总:")
    print(f"  总成交数: {summary['total_fills']}")
    print(f"  总盈亏: ${summary['total_realized_pnl']:.2f}")
    print(f"  总手续费: ${summary['total_fee']:.4f}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
