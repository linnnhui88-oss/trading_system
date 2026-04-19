#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币安历史数据导入工具 - 支持订单和成交两种模式

币安API说明：
- fetch_orders: 获取订单历史（包括已成交、已取消、部分成交的订单）
- fetch_my_trades: 获取成交明细（只有实际发生的成交）

使用方法:
    # 从币安API导入成交记录
    python import_binance_history.py --mode trades --days 30
    
    # 从币安API导入订单历史
    python import_binance_history.py --mode orders --days 30
    
    # 从CSV文件导入
    python import_binance_history.py --mode csv --file "交易历史.csv"
"""

import os
import sys
import argparse
import ccxt
import csv
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading_core.trade_fill_repository import TradeFillRepository

load_dotenv()


class BinanceHistoryImporter:
    """币安历史数据导入器"""
    
    def __init__(self):
        self.exchange = None
        self.repo = TradeFillRepository()
        
    def connect(self):
        """连接币安交易所"""
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
            print(f"🌐 使用代理: {proxy_url}")
        
        self.exchange = ccxt.binance(config)
        self.exchange.load_time_difference()
        
        # 测试连接
        balance = self.exchange.fetch_balance()
        print(f"✅ 已连接到币安期货账户")
        print(f"   USDT余额: {balance.get('USDT', {}).get('free', 0):.2f}")
        return True
    
    def get_all_orders(self, since_ms: int, limit: int = 1000) -> List[Dict]:
        """获取所有订单历史（包括已成交和已取消）"""
        all_orders = []
        
        # 主要交易对列表
        symbols = [
            'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'BNB/USDT:USDT',
            'XRP/USDT:USDT', 'ADA/USDT:USDT', 'DOGE/USDT:USDT', 'LINK/USDT:USDT',
            'AVAX/USDT:USDT', 'DOT/USDT:USDT', 'MATIC/USDT:USDT', 'LTC/USDT:USDT',
            'UNI/USDT:USDT', 'ATOM/USDT:USDT', 'ETC/USDT:USDT', 'FIL/USDT:USDT',
            'TRX/USDT:USDT', 'SHIB/USDT:USDT', 'MANA/USDT:USDT', 'SAND/USDT:USDT',
            'AXS/USDT:USDT', 'APE/USDT:USDT', 'GMT/USDT:USDT', 'FTM/USDT:USDT',
            'NEAR/USDT:USDT', 'ALGO/USDT:USDT', 'VET/USDT:USDT', 'ICP/USDT:USDT',
            'THETA/USDT:USDT', 'XLM/USDT:USDT', 'EOS/USDT:USDT', 'BCH/USDT:USDT',
            'SUSHI/USDT:USDT', 'AAVE/USDT:USDT', 'COMP/USDT:USDT', 'MKR/USDT:USDT',
            'CRV/USDT:USDT', 'YFI/USDT:USDT', '1INCH/USDT:USDT', 'CHZ/USDT:USDT',
            'GRT/USDT:USDT', 'ENJ/USDT:USDT', 'BAT/USDT:USDT', 'ZIL/USDT:USDT',
            'LRC/USDT:USDT', 'COTI/USDT:USDT', 'DASH/USDT:USDT', 'NEO/USDT:USDT',
            'QTUM/USDT:USDT', 'IOST/USDT:USDT', 'RVN/USDT:USDT', 'ZEC/USDT:USDT',
            'ONT/USDT:USDT', 'IOTA/USDT:USDT', 'WAVES/USDT:USDT', 'KSM/USDT:USDT'
        ]
        
        print(f"\n📡 正在获取订单历史...")
        
        for symbol in symbols:
            try:
                # 不使用since参数，获取所有历史订单
                orders = self.exchange.fetch_orders(symbol, limit=limit)
                # 按时间过滤
                filtered_orders = [o for o in orders if o.get('timestamp', 0) >= since_ms]
                if filtered_orders:
                    print(f"  ✅ {symbol}: {len(filtered_orders)} 笔订单")
                    for order in filtered_orders:
                        order['symbol'] = symbol  # 确保symbol正确
                    all_orders.extend(filtered_orders)
            except Exception as e:
                pass  # 忽略无记录的币种
        
        return all_orders
    
    def get_all_trades(self, since_ms: int, limit: int = 1000) -> List[Dict]:
        """获取所有成交记录"""
        all_trades = []
        
        symbols = [
            'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'BNB/USDT:USDT',
            'XRP/USDT:USDT', 'ADA/USDT:USDT', 'DOGE/USDT:USDT', 'LINK/USDT:USDT',
            'AVAX/USDT:USDT', 'DOT/USDT:USDT', 'MATIC/USDT:USDT', 'LTC/USDT:USDT',
            'UNI/USDT:USDT', 'ATOM/USDT:USDT', 'ETC/USDT:USDT', 'FIL/USDT:USDT',
            'TRX/USDT:USDT', 'SHIB/USDT:USDT', 'MANA/USDT:USDT', 'SAND/USDT:USDT',
            'AXS/USDT:USDT', 'APE/USDT:USDT', 'GMT/USDT:USDT', 'FTM/USDT:USDT',
            'NEAR/USDT:USDT', 'ALGO/USDT:USDT', 'VET/USDT:USDT', 'ICP/USDT:USDT',
            'THETA/USDT:USDT', 'XLM/USDT:USDT', 'EOS/USDT:USDT', 'BCH/USDT:USDT',
            'SUSHI/USDT:USDT', 'AAVE/USDT:USDT', 'COMP/USDT:USDT', 'MKR/USDT:USDT',
            'CRV/USDT:USDT', 'YFI/USDT:USDT', '1INCH/USDT:USDT', 'CHZ/USDT:USDT',
            'GRT/USDT:USDT', 'ENJ/USDT:USDT', 'BAT/USDT:USDT', 'ZIL/USDT:USDT',
            'LRC/USDT:USDT', 'COTI/USDT:USDT', 'DASH/USDT:USDT', 'NEO/USDT:USDT',
            'QTUM/USDT:USDT', 'IOST/USDT:USDT', 'RVN/USDT:USDT', 'ZEC/USDT:USDT',
            'ONT/USDT:USDT', 'IOTA/USDT:USDT', 'WAVES/USDT:USDT', 'KSM/USDT:USDT'
        ]
        
        print(f"\n📡 正在获取成交记录...")
        
        for symbol in symbols:
            try:
                # 不使用since参数，获取所有历史成交
                trades = self.exchange.fetch_my_trades(symbol, limit=limit)
                # 按时间过滤
                filtered_trades = [t for t in trades if t.get('timestamp', 0) >= since_ms]
                if filtered_trades:
                    print(f"  ✅ {symbol}: {len(filtered_trades)} 笔成交")
                    all_trades.extend(filtered_trades)
            except Exception as e:
                pass
        
        return all_trades
    
    def convert_order_to_fill(self, order: Dict) -> Optional[Dict]:
        """将订单转换为fill格式"""
        try:
            symbol = order.get('symbol', '').replace('/', '').replace(':USDT', '')
            side = order.get('side', '').upper()
            status = order.get('status', '')
            
            # 只处理已成交的订单
            if status not in ['closed', 'FILLED']:
                return None
            
            # 判断action_type
            info = order.get('info', {})
            position_side = info.get('positionSide', 'BOTH')
            
            if position_side == 'LONG':
                action_type = 'close' if side == 'SELL' else 'open'
            elif position_side == 'SHORT':
                action_type = 'close' if side == 'BUY' else 'open'
            else:
                action_type = 'open' if side == 'BUY' else 'close'
            
            # 获取实际成交数量
            filled = float(order.get('filled', 0))
            if filled <= 0:
                return None
            
            # 获取成交均价
            price = float(order.get('average', order.get('price', 0)))
            if price <= 0:
                return None
            
            # 获取手续费
            fee_cost = 0.0
            fee_asset = ''
            fee_info = order.get('fee', {})
            if fee_info:
                fee_cost = float(fee_info.get('cost', 0))
                fee_asset = fee_info.get('currency', '')
            
            fill_data = {
                'strategy_name': 'manual_trading',
                'symbol': symbol,
                'side': side,
                'position_side': position_side,
                'action_type': action_type,
                'order_id': str(order.get('id', '')),
                'exchange_trade_id': str(order.get('id', '')),
                'quantity': filled,
                'price': price,
                'realized_pnl': 0,  # 订单API不返回盈亏
                'fee': fee_cost,
                'fee_asset': fee_asset,
                'ai_model': '',
                'ai_decision': '',
                'signal_source': 'exchange_sync',
                'signal_reason': f'币安订单导入 (状态: {status})',
                'executed_at': datetime.fromtimestamp(order.get('timestamp', 0) / 1000).isoformat(),
            }
            
            return fill_data
        except Exception as e:
            print(f"  ⚠️ 转换订单失败: {e}")
            return None
    
    def convert_trade_to_fill(self, trade: Dict) -> Optional[Dict]:
        """将成交记录转换为fill格式"""
        try:
            symbol = trade.get('symbol', '').replace('/', '').replace(':USDT', '')
            side = trade.get('side', '').upper()
            
            info = trade.get('info', {})
            position_side = info.get('positionSide', 'BOTH')
            
            if position_side == 'LONG':
                action_type = 'close' if side == 'SELL' else 'open'
            elif position_side == 'SHORT':
                action_type = 'close' if side == 'BUY' else 'open'
            else:
                action_type = 'open' if side == 'BUY' else 'close'
            
            realized_pnl = float(info.get('realizedPnl', 0))
            
            fee_cost = 0.0
            fee_asset = ''
            fee_info = trade.get('fee', {})
            if fee_info:
                fee_cost = float(fee_info.get('cost', 0))
                fee_asset = fee_info.get('currency', '')
            
            fill_data = {
                'strategy_name': 'manual_trading',
                'symbol': symbol,
                'side': side,
                'position_side': position_side,
                'action_type': action_type,
                'order_id': str(trade.get('order', '')),
                'exchange_trade_id': str(trade.get('id', '')),
                'quantity': float(trade.get('amount', 0)),
                'price': float(trade.get('price', 0)),
                'realized_pnl': realized_pnl,
                'fee': fee_cost,
                'fee_asset': fee_asset,
                'ai_model': '',
                'ai_decision': '',
                'signal_source': 'exchange_sync',
                'signal_reason': '币安成交记录导入',
                'executed_at': datetime.fromtimestamp(trade.get('timestamp', 0) / 1000).isoformat(),
            }
            
            return fill_data
        except Exception as e:
            print(f"  ⚠️ 转换成交记录失败: {e}")
            return None
    
    def import_items(self, items: List[Dict], item_type: str = 'trade') -> Dict[str, int]:
        """导入记录到数据库"""
        imported = 0
        skipped = 0
        failed = 0
        
        print(f"\n📥 开始导入 {len(items)} 条记录...")
        
        for item in items:
            try:
                if item_type == 'order':
                    fill_data = self.convert_order_to_fill(item)
                else:
                    fill_data = self.convert_trade_to_fill(item)
                
                if not fill_data:
                    skipped += 1
                    continue
                
                # 检查是否已存在
                existing = self.repo.get_fill_by_exchange_trade_id(fill_data['exchange_trade_id'])
                if existing:
                    skipped += 1
                    continue
                
                # 创建记录
                self.repo.create_fill(fill_data)
                imported += 1
                
                if imported % 10 == 0:
                    print(f"  已导入 {imported} 笔...")
                    
            except Exception as e:
                failed += 1
                print(f"  ⚠️ 导入失败: {e}")
        
        return {'imported': imported, 'skipped': skipped, 'failed': failed, 'total': len(items)}
    
    def import_from_csv(self, csv_file: str) -> Dict[str, int]:
        """从CSV文件导入"""
        if not os.path.exists(csv_file):
            print(f"❌ 文件不存在: {csv_file}")
            return {'imported': 0, 'skipped': 0, 'failed': 0, 'total': 0}
        
        items = []
        
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    item = self._parse_csv_row(row)
                    if item:
                        items.append(item)
                except Exception as e:
                    print(f"⚠️ 解析行失败: {e}")
        
        print(f"📄 CSV解析完成: {len(items)} 条记录")
        return self.import_items(items, 'order')
    
    def _parse_csv_row(self, row: Dict) -> Optional[Dict]:
        """解析CSV行"""
        # 币安CSV列名可能有不同变体
        date_col = row.get('Date(UTC)') or row.get('Date') or row.get('时间') or row.get('date')
        pair_col = row.get('Pair') or row.get('Symbol') or row.get('交易对') or row.get('symbol')
        side_col = row.get('Side') or row.get('side') or row.get('方向')
        price_col = row.get('Price') or row.get('price') or row.get('价格') or row.get('AvgPrice')
        amount_col = row.get('Amount') or row.get('Executed') or row.get('数量') or row.get('Quantity')
        status_col = row.get('Status') or row.get('status') or row.get('状态')
        
        if not pair_col:
            return None
        
        # 解析时间
        try:
            if date_col:
                if 'T' in date_col:
                    dt = datetime.fromisoformat(date_col.replace('Z', '+00:00'))
                else:
                    dt = datetime.strptime(date_col, '%Y-%m-%d %H:%M:%S')
            else:
                dt = datetime.now()
        except:
            dt = datetime.now()
        
        symbol = pair_col.replace('/', '')
        side = (side_col or 'BUY').upper()
        status = (status_col or 'FILLED').upper()
        
        return {
            'symbol': symbol,
            'side': side,
            'status': status,
            'price': float(price_col or 0),
            'filled': float(amount_col or 0),
            'average': float(price_col or 0),
            'timestamp': int(dt.timestamp() * 1000),
            'id': f"csv_{symbol}_{int(dt.timestamp())}",
            'info': {'positionSide': 'BOTH'}
        }
    
    def run(self, mode: str, days: int = 30, csv_file: str = None):
        """运行导入"""
        print(f"\n{'='*60}")
        print(f"🚀 币安历史数据导入工具")
        print(f"{'='*60}")
        print(f"模式: {mode}")
        if csv_file:
            print(f"文件: {csv_file}")
        else:
            print(f"时间范围: 过去 {days} 天")
        print(f"{'='*60}\n")
        
        if mode == 'csv':
            if not csv_file:
                print("❌ CSV模式需要指定文件路径")
                return False
            result = self.import_from_csv(csv_file)
        else:
            if not self.connect():
                return False
            
            since_ms = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
            
            if mode == 'orders':
                items = self.get_all_orders(since_ms)
            else:  # trades
                items = self.get_all_trades(since_ms)
            
            if not items:
                print("⚠️ 未找到记录")
                return False
            
            print(f"\n✅ 获取到 {len(items)} 条记录")
            result = self.import_items(items, mode)
        
        # 显示结果
        print(f"\n{'='*60}")
        print(f"📊 导入结果")
        print(f"{'='*60}")
        print(f"✅ 成功导入: {result['imported']}")
        print(f"⏭️  已存在跳过: {result['skipped']}")
        print(f"❌ 导入失败: {result['failed']}")
        print(f"📈 总计: {result['total']}")
        print(f"{'='*60}\n")
        
        return result['imported'] > 0


def main():
    parser = argparse.ArgumentParser(description='币安历史数据导入工具')
    parser.add_argument('--mode', choices=['trades', 'orders', 'csv'], default='orders',
                        help='导入模式: trades(成交记录), orders(订单历史), csv(CSV文件)')
    parser.add_argument('--days', type=int, default=30,
                        help='获取过去多少天的数据 (默认: 30)')
    parser.add_argument('--file', type=str, default=None,
                        help='CSV文件路径 (CSV模式使用)')
    
    args = parser.parse_args()
    
    importer = BinanceHistoryImporter()
    success = importer.run(mode=args.mode, days=args.days, csv_file=args.file)
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
