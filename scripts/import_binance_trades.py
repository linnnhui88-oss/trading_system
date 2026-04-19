#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币安交易数据导入工具 - 支持API和CSV两种方式

使用方法:
    # 从币安API导入
    python import_binance_trades.py --mode api --days 90
    
    # 从CSV文件导入 (币安导出格式)
    python import_binance_trades.py --mode csv --file "交易历史.csv"
    
    # 从通用CSV导入
    python import_binance_trades.py --mode csv --file "trades.csv" --format generic
"""

import os
import sys
import argparse
import ccxt
import sqlite3
import csv
from datetime import datetime, timedelta
from typing import List, Dict, Any
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading_core.trade_fill_repository import TradeFillRepository


class BinanceTradeImporter:
    """币安交易数据导入器"""
    
    def __init__(self, api_key: str = None, secret_key: str = None, testnet: bool = False):
        self.api_key = api_key or os.getenv('BINANCE_API_KEY', '')
        self.secret_key = secret_key or os.getenv('BINANCE_SECRET_KEY', '')
        self.testnet = testnet
        self.exchange = None
        self.repo = TradeFillRepository()
        
    def connect(self, mode: str = 'futures'):
        """连接币安交易所"""
        config = {
            'apiKey': self.api_key,
            'secret': self.secret_key,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future' if mode == 'futures' else 'spot'
            }
        }
        
        # 添加代理支持
        proxy_url = os.getenv('PROXY_URL', '')
        if proxy_url:
            config['proxies'] = {
                'http': proxy_url,
                'https': proxy_url
            }
            print(f"🌐 使用代理: {proxy_url}")
        
        # 设置recvWindow避免时间同步问题
        config['options']['recvWindow'] = 60000
        config['options']['adjustForTimeDifference'] = True
        
        if self.testnet:
            config['sandbox'] = True
            # 测试网URL
            if mode == 'futures':
                config['urls'] = {
                    'api': {
                        'public': 'https://testnet.binancefuture.com/fapi/v1',
                        'private': 'https://testnet.binancefuture.com/fapi/v1',
                    }
                }
        
        self.exchange = ccxt.binance(config)
        
        # 检查连接
        try:
            # 先同步服务器时间
            self.exchange.load_time_difference()
            print(f"⏰ 服务器时间差: {self.exchange.options.get('timeDifference', 0)}ms")
            
            self.exchange.load_markets()
            print(f"✅ 已连接到币安{'测试网' if self.testnet else '主网'} ({mode})")
            return True
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return False
    
    def get_futures_trades(self, symbol: str = None, since: int = None, limit: int = 1000) -> List[Dict]:
        """获取期货交易历史"""
        trades = []
        
        try:
            # 优先尝试获取账户所有成交历史
            try:
                print("📡 尝试获取账户所有成交历史...")
                # 使用CCXT的fetch_orders获取所有订单
                since_dt = datetime.fromtimestamp(since / 1000)
                print(f"   查询起始时间: {since_dt}")
                
                # 获取所有历史订单
                all_orders = []
                for sym in ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'BNB/USDT:USDT']:
                    try:
                        orders = self.exchange.fetch_orders(sym, since=since, limit=1000)
                        all_orders.extend(orders)
                        print(f"   {sym}: {len(orders)} 笔订单")
                    except Exception as e:
                        pass
                        
                if all_orders:
                    print(f"✅ 总共获取到 {len(all_orders)} 笔订单")
                    # 获取已成交订单的成交明细
                    for order in all_orders:
                        if order.get('status') in ['FILLED', 'PARTIALLY_FILLED']:
                            sym = order.get('symbol')
                            try:
                                order_trades = self.exchange.fetch_my_trades(sym, since=since, limit=1000)
                                trades.extend(order_trades)
                            except:
                                pass
            except Exception as e:
                print(f"⚠️ 全量获取失败，尝试逐个币种获取: {e}")
            
            if not trades:
                if symbol:
                    # 获取指定交易对的历史
                    raw_trades = self.exchange.fetch_my_trades(symbol, since=since, limit=limit)
                    trades.extend(raw_trades)
                else:
                    # 获取所有交易对的历史 - 先尝试主要币种
                    major_symbols = [
                        'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'BNB/USDT:USDT',
                        'XRP/USDT:USDT', 'ADA/USDT:USDT', 'DOGE/USDT:USDT', 'LINK/USDT:USDT',
                        'AVAX/USDT:USDT', 'DOT/USDT:USDT', 'MATIC/USDT:USDT', 'LTC/USDT:USDT'
                    ]
                    
                    print(f"📊 检查 {len(major_symbols)} 个主要币种...")
                    
                    for sym in major_symbols:
                        try:
                            raw_trades = self.exchange.fetch_my_trades(sym, since=since, limit=limit)
                            if raw_trades:
                                print(f"  ✅ {sym}: {len(raw_trades)} 笔成交")
                                trades.extend(raw_trades)
                        except Exception as e:
                            # 忽略无交易记录的币种
                            pass
                        
        except Exception as e:
            print(f"❌ 获取交易历史失败: {e}")
            
        return trades
    
    def get_spot_trades(self, symbol: str = None, since: int = None, limit: int = 1000) -> List[Dict]:
        """获取现货交易历史"""
        trades = []
        
        try:
            if symbol:
                raw_trades = self.exchange.fetch_my_trades(symbol, since=since, limit=limit)
                trades.extend(raw_trades)
            else:
                # 获取所有现货交易对
                markets = self.exchange.markets
                spot_symbols = [s for s in markets.keys() if '/USDT' in s and ':' not in s]
                
                print(f"📊 发现 {len(spot_symbols)} 个现货交易对")
                
                for sym in spot_symbols[:20]:
                    try:
                        raw_trades = self.exchange.fetch_my_trades(sym, since=since, limit=limit)
                        if raw_trades:
                            print(f"  - {sym}: {len(raw_trades)} 笔成交")
                            trades.extend(raw_trades)
                    except Exception as e:
                        pass
                        
        except Exception as e:
            print(f"❌ 获取现货交易历史失败: {e}")
            
        return trades
    
    def convert_to_fill_format(self, trade: Dict, mode: str = 'futures') -> Dict[str, Any]:
        """将CCXT交易记录转换为trade_fill格式"""
        symbol = trade.get('symbol', '').replace('/', '')
        side = trade.get('side', '').upper()
        
        # 判断是开平仓动作
        # 期货：BUY + 无持仓 = 开仓；SELL + 有持仓 = 平仓
        # 简化处理：根据side和info中的positionSide判断
        info = trade.get('info', {})
        position_side = info.get('positionSide', 'BOTH')
        
        # 判断action_type
        if mode == 'futures':
            if position_side == 'BOTH':
                # 单向持仓模式
                action_type = 'open' if side == 'BUY' else 'close'
            else:
                # 双向持仓模式 (LONG/SHORT)
                if position_side == 'LONG':
                    action_type = 'close' if side == 'SELL' else 'open'
                else:  # SHORT
                    action_type = 'close' if side == 'BUY' else 'open'
        else:
            # 现货简单处理
            action_type = 'open'  # 现货没有严格的开平仓概念
        
        # 计算realized_pnl（期货可能有）
        realized_pnl = 0.0
        if mode == 'futures':
            realized_pnl = float(info.get('realizedPnl', 0))
        
        fill_data = {
            'strategy_name': 'manual_trading',  # 手动交易标记
            'symbol': symbol,
            'side': side,
            'position_side': position_side if mode == 'futures' else '',
            'action_type': action_type,
            'order_id': str(trade.get('order', '')),
            'exchange_trade_id': str(trade.get('id', '')),
            'quantity': float(trade.get('amount', 0)),
            'price': float(trade.get('price', 0)),
            'realized_pnl': realized_pnl,
            'fee': float(trade.get('fee', {}).get('cost', 0)),
            'fee_asset': trade.get('fee', {}).get('currency', ''),
            'ai_model': '',
            'ai_decision': '',
            'signal_source': 'exchange_sync',  # 标记为交易所同步
            'signal_reason': f'币安{mode}历史成交导入',
            'executed_at': datetime.fromtimestamp(trade.get('timestamp', 0) / 1000).isoformat(),
        }
        
        return fill_data
    
    def import_trades(self, trades: List[Dict], mode: str = 'futures') -> Dict[str, int]:
        """导入交易记录到数据库"""
        imported = 0
        skipped = 0
        failed = 0
        
        print(f"\n📥 开始导入 {len(trades)} 笔交易记录...")
        
        for trade in trades:
            try:
                fill_data = self.convert_to_fill_format(trade, mode)
                
                # 检查是否已存在（通过exchange_trade_id）
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
        
        return {
            'imported': imported,
            'skipped': skipped,
            'failed': failed,
            'total': len(trades)
        }
    
    def import_from_csv(self, csv_file: str, format_type: str = 'binance') -> Dict[str, int]:
        """从CSV文件导入交易记录"""
        if not os.path.exists(csv_file):
            print(f"❌ 文件不存在: {csv_file}")
            return {'imported': 0, 'skipped': 0, 'failed': 0, 'total': 0}
        
        trades = []
        
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                try:
                    if format_type == 'binance':
                        # 币安导出格式
                        trade = self._parse_binance_csv_row(row)
                    else:
                        # 通用格式
                        trade = self._parse_generic_csv_row(row)
                    
                    if trade:
                        trades.append(trade)
                except Exception as e:
                    print(f"⚠️ 解析行失败: {e}")
        
        print(f"📄 CSV解析完成: {len(trades)} 条记录")
        return self.import_csv_trades(trades)
    
    def _parse_binance_csv_row(self, row: Dict) -> Dict:
        """解析币安CSV格式"""
        # 币安CSV列名可能有不同变体
        date_col = row.get('Date(UTC)') or row.get('Date') or row.get('时间')
        pair_col = row.get('Pair') or row.get('Symbol') or row.get('交易对')
        side_col = row.get('Side') or row.get('方向')
        price_col = row.get('Price') or row.get('价格')
        amount_col = row.get('Amount') or row.get('Executed') or row.get('数量')
        total_col = row.get('Total') or row.get('成交额')
        fee_col = row.get('Fee') or row.get('手续费')
        
        # 解析时间
        try:
            if 'Date(UTC)' in row:
                dt = datetime.strptime(date_col, '%Y-%m-%d %H:%M:%S')
            else:
                dt = datetime.fromisoformat(date_col.replace('Z', '+00:00'))
        except:
            dt = datetime.now()
        
        symbol = pair_col.replace('/', '') if pair_col else 'UNKNOWN'
        side = side_col.upper() if side_col else 'BUY'
        
        return {
            'symbol': symbol,
            'side': side,
            'price': float(price_col or 0),
            'amount': float(amount_col or 0),
            'fee': float(fee_col or 0),
            'timestamp': int(dt.timestamp() * 1000),
            'info': {
                'positionSide': 'BOTH'
            }
        }
    
    def _parse_generic_csv_row(self, row: Dict) -> Dict:
        """解析通用CSV格式"""
        # 尝试各种可能的列名
        symbol = row.get('symbol') or row.get('Symbol') or row.get('交易对') or 'UNKNOWN'
        side = (row.get('side') or row.get('Side') or row.get('方向') or 'BUY').upper()
        price = float(row.get('price') or row.get('Price') or row.get('价格') or 0)
        amount = float(row.get('amount') or row.get('Amount') or row.get('quantity') or row.get('数量') or 0)
        fee = float(row.get('fee') or row.get('Fee') or row.get('手续费') or 0)
        
        time_str = row.get('time') or row.get('Time') or row.get('timestamp') or row.get('时间') or ''
        try:
            if 'T' in time_str:
                dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            else:
                dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
        except:
            dt = datetime.now()
        
        return {
            'symbol': symbol.replace('/', ''),
            'side': side,
            'price': price,
            'amount': amount,
            'fee': fee,
            'timestamp': int(dt.timestamp() * 1000),
            'info': {
                'positionSide': 'BOTH'
            }
        }
    
    def import_csv_trades(self, trades: List[Dict]) -> Dict[str, int]:
        """导入CSV解析后的交易记录"""
        imported = 0
        skipped = 0
        failed = 0
        
        print(f"\n📥 开始导入 {len(trades)} 笔交易记录...")
        
        for trade in trades:
            try:
                # 生成唯一ID
                trade_id = f"csv_{trade['symbol']}_{trade['timestamp']}"
                
                fill_data = {
                    'strategy_name': 'manual_trading',
                    'symbol': trade['symbol'],
                    'side': trade['side'],
                    'position_side': trade.get('info', {}).get('positionSide', 'BOTH'),
                    'action_type': 'open' if trade['side'] == 'BUY' else 'close',
                    'order_id': trade_id,
                    'exchange_trade_id': trade_id,
                    'quantity': trade['amount'],
                    'price': trade['price'],
                    'realized_pnl': 0,
                    'fee': trade.get('fee', 0),
                    'fee_asset': '',
                    'ai_model': '',
                    'ai_decision': '',
                    'signal_source': 'csv_import',
                    'signal_reason': 'CSV文件导入',
                    'executed_at': datetime.fromtimestamp(trade['timestamp'] / 1000).isoformat(),
                }
                
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
        
        return {
            'imported': imported,
            'skipped': skipped,
            'failed': failed,
            'total': len(trades)
        }
    
    def run_api(self, mode: str = 'futures', days: int = 90, symbol: str = None):
        """运行API导入流程"""
        print(f"\n{'='*60}")
        print(f"🚀 币安交易数据导入工具 (API模式)")
        print(f"{'='*60}")
        print(f"模式: {mode}")
        print(f"时间范围: 过去 {days} 天")
        print(f"交易对: {symbol or '全部'}")
        print(f"{'='*60}\n")
        
        # 1. 连接交易所
        if not self.connect(mode):
            return False
        
        # 2. 计算时间戳
        since = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
        
        # 3. 获取交易历史
        print(f"\n📡 正在从币安获取交易历史...")
        if mode == 'futures':
            trades = self.get_futures_trades(symbol=symbol, since=since)
        else:
            trades = self.get_spot_trades(symbol=symbol, since=since)
        
        if not trades:
            print("⚠️ 未找到交易记录")
            return False
        
        print(f"\n✅ 获取到 {len(trades)} 笔交易记录")
        
        # 4. 导入到数据库
        result = self.import_trades(trades, mode)
        
        # 5. 显示结果
        print(f"\n{'='*60}")
        print(f"📊 导入结果")
        print(f"{'='*60}")
        print(f"✅ 成功导入: {result['imported']}")
        print(f"⏭️  已存在跳过: {result['skipped']}")
        print(f"❌ 导入失败: {result['failed']}")
        print(f"📈 总计: {result['total']}")
        print(f"{'='*60}\n")
        
        return True
    
    def run_csv(self, csv_file: str, format_type: str = 'binance'):
        """运行CSV导入流程"""
        print(f"\n{'='*60}")
        print(f"🚀 币安交易数据导入工具 (CSV模式)")
        print(f"{'='*60}")
        print(f"文件: {csv_file}")
        print(f"格式: {format_type}")
        print(f"{'='*60}\n")
        
        result = self.import_from_csv(csv_file, format_type)
        
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
    parser = argparse.ArgumentParser(description='币安历史交易数据导入工具')
    parser.add_argument('--mode', choices=['api', 'csv'], default='api',
                        help='导入模式: api(从币安API) 或 csv(从CSV文件)')
    parser.add_argument('--market', choices=['futures', 'spot'], default='futures',
                        help='市场类型 (API模式使用)')
    parser.add_argument('--days', type=int, default=90,
                        help='获取过去多少天的数据 (默认: 90)')
    parser.add_argument('--symbol', type=str, default=None,
                        help='指定交易对 (API模式使用)')
    parser.add_argument('--file', type=str, default=None,
                        help='CSV文件路径 (CSV模式使用)')
    parser.add_argument('--format', choices=['binance', 'generic'], default='binance',
                        help='CSV格式类型')
    parser.add_argument('--testnet', action='store_true',
                        help='使用测试网 (API模式使用)')
    
    args = parser.parse_args()
    
    # 创建导入器
    importer = BinanceTradeImporter(testnet=args.testnet)
    
    if args.mode == 'api':
        # 检查API密钥
        api_key = os.getenv('BINANCE_API_KEY', '')
        secret_key = os.getenv('BINANCE_SECRET_KEY', '')
        
        if not api_key or not secret_key:
            print("❌ 错误: 未设置币安API密钥")
            print("请在 .env 文件中设置:")
            print("  BINANCE_API_KEY=你的API密钥")
            print("  BINANCE_SECRET_KEY=你的Secret密钥")
            return 1
        
        success = importer.run_api(mode=args.market, days=args.days, symbol=args.symbol)
        
    else:  # csv mode
        if not args.file:
            print("❌ 错误: CSV模式需要指定 --file 参数")
            return 1
        
        success = importer.run_csv(args.file, args.format)
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
