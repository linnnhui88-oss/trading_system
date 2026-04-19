#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币安CSV交易记录导入工具
适配币安导出的中文CSV格式
"""

import os
import sys
import csv
from datetime import datetime
from typing import Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading_core.trade_fill_repository import TradeFillRepository


def parse_datetime(time_str: str) -> datetime:
    """解析币安CSV时间格式: 26-04-19 11:20:49"""
    # 格式: YY-MM-DD HH:MM:SS
    year = int("20" + time_str[:2])
    month = int(time_str[3:5])
    day = int(time_str[6:8])
    hour = int(time_str[9:11])
    minute = int(time_str[12:14])
    second = int(time_str[15:17])
    return datetime(year, month, day, hour, minute, second)


def parse_csv_row(row: Dict) -> Optional[Dict]:
    """解析币安CSV行"""
    try:
        # 币安CSV列名（中文）
        time_str = row.get('时间', '')
        order_id = row.get('订单编号', '')
        symbol = row.get('代币名称/币种名称/币对', '')
        order_type = row.get('类型', '')  # MARKET, LIMIT等
        side = row.get('方向', '')  # BUY, SELL
        price = row.get('价格', '0')  # 委托价格
        avg_price = row.get('平均价格', '0')  # 实际成交价格
        amount = row.get('金额', '0')  # 委托数量
        executed = row.get('执行金额', '0')  # 实际成交数量
        status = row.get('状态', '')  # FILLED, CANCELED等
        
        # 只导入已成交的订单
        if status != 'FILLED':
            return None
        
        # 解析时间
        dt = parse_datetime(time_str)
        
        # 确定action_type
        side_upper = side.upper()
        # 币安CSV没有positionSide信息，根据side判断
        action_type = 'open' if side_upper == 'BUY' else 'close'
        
        # 使用实际成交价格和数量
        fill_price = float(avg_price) if avg_price else float(price)
        fill_qty = float(executed) if executed else float(amount)
        
        if fill_price <= 0 or fill_qty <= 0:
            return None
        
        fill_data = {
            'strategy_name': 'manual_trading',
            'symbol': symbol,
            'side': side_upper,
            'position_side': 'BOTH',  # CSV中没有这个信息
            'action_type': action_type,
            'order_id': str(order_id),
            'exchange_trade_id': str(order_id),
            'quantity': fill_qty,
            'price': fill_price,
            'realized_pnl': 0,  # CSV中没有盈亏信息
            'fee': 0,
            'fee_asset': '',
            'ai_model': '',
            'ai_decision': '',
            'signal_source': 'csv_import',
            'signal_reason': f'币安CSV导入 ({order_type})',
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
    skipped = 0
    failed = 0
    
    with open(csv_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    print(f"📄 CSV文件共有 {len(rows)} 行数据\n")
    
    for row in rows:
        try:
            fill_data = parse_csv_row(row)
            if not fill_data:
                skipped += 1
                continue
            
            # 检查是否已存在
            existing = repo.get_fill_by_exchange_trade_id(fill_data['exchange_trade_id'])
            if existing:
                skipped += 1
                continue
            
            # 创建记录
            repo.create_fill(fill_data)
            imported += 1
            
            if imported % 10 == 0:
                print(f"  已导入 {imported} 笔...")
                
        except Exception as e:
            failed += 1
            print(f"  ⚠️ 导入失败: {e}")
    
    return {'imported': imported, 'skipped': skipped, 'failed': failed, 'total': len(rows)}


def main():
    csv_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'binance_history.csv')
    
    if not os.path.exists(csv_file):
        print(f"❌ 文件不存在: {csv_file}")
        print("请将币安导出的CSV文件放到 data/binance_history.csv")
        return 1
    
    print(f"\n{'='*60}")
    print(f"🚀 币安CSV交易记录导入")
    print(f"{'='*60}")
    print(f"文件: {csv_file}")
    print(f"{'='*60}\n")
    
    result = import_csv(csv_file)
    
    print(f"\n{'='*60}")
    print(f"📊 导入结果")
    print(f"{'='*60}")
    print(f"✅ 成功导入: {result['imported']}")
    print(f"⏭️  跳过(非成交/重复): {result['skipped']}")
    print(f"❌ 导入失败: {result['failed']}")
    print(f"📈 总计: {result['total']}")
    print(f"{'='*60}\n")
    
    # 显示汇总
    repo = TradeFillRepository()
    summary = repo.get_summary()
    print(f"📊 数据库汇总:")
    print(f"  总成交数: {summary['total_fills']}")
    print(f"  总盈亏: ${summary['total_realized_pnl']:.2f}")
    print(f"  总手续费: ${summary['total_fee']:.2f}")
    
    return 0 if result['imported'] > 0 else 1


if __name__ == '__main__':
    sys.exit(main())
