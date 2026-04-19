#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币安交易同步服务

功能：
1. 定期从币安API获取成交记录
2. 自动导入到 trade_fills 表
3. 支持增量同步（只同步新记录）
4. 可配置同步间隔和交易对

使用方法：
    # 作为独立脚本运行
    python binance_trade_sync.py --interval 300
    
    # 一次性同步
    python binance_trade_sync.py --once
    
    # 在后台线程中运行（从app.py调用）
    from scripts.binance_trade_sync import start_sync_service
    start_sync_service(interval=300)
"""

import os
import sys
import time
import argparse
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading_core.exchange_client import get_exchange_client
from trading_core.trade_fill_repository import TradeFillRepository
import logging

logger = logging.getLogger(__name__)


class BinanceTradeSync:
    """币安交易同步器"""
    
    def __init__(self):
        self.exchange = None
        self.repo = TradeFillRepository()
        self._stop_event = threading.Event()
        self._sync_thread = None
        self.last_sync_time = None
        
    def connect(self) -> bool:
        """连接交易所"""
        try:
            self.exchange = get_exchange_client()
            # 测试连接
            balance = self.exchange.get_balance()
            usdt_balance = 0
            if isinstance(balance, dict):
                usdt_info = balance.get('USDT', {})
                if isinstance(usdt_info, dict):
                    usdt_balance = usdt_info.get('free', 0)
                else:
                    usdt_balance = usdt_info
            logger.info(f"✅ 币安交易同步服务已连接 | USDT余额: {usdt_balance:.2f}")
            return True
        except Exception as e:
            logger.error(f"❌ 连接币安失败: {e}")
            return False
    
    def get_recent_trades_from_exchange(self, symbol: str = None, 
                                        since_ms: int = None,
                                        limit: int = 1000) -> List[Dict]:
        """从交易所获取成交记录（支持分页获取所有数据）"""
        all_trades = []
        
        try:
            # 币安API限制，需要分页获取
            while True:
                trades = self.exchange.get_recent_account_trades(
                    symbol=symbol,
                    since_ms=since_ms,
                    limit=limit
                )
                
                if not trades:
                    break
                
                all_trades.extend(trades)
                
                # 如果返回数量小于limit，说明没有更多数据了
                if len(trades) < limit:
                    break
                
                # 更新since_ms为最后一条记录的时间+1ms，继续获取下一页
                last_timestamp = trades[-1].get('timestamp', 0)
                if last_timestamp:
                    since_ms = last_timestamp + 1
                else:
                    break
                
                logger.debug(f"  分页获取: 已获取 {len(all_trades)} 笔，继续...")
                
        except Exception as e:
            logger.warning(f"获取 {symbol or '全部'} 成交记录失败: {e}")
        
        return all_trades
    
    def convert_trade_to_fill(self, trade: Dict) -> Optional[Dict]:
        """将CCXT交易记录转换为trade_fill格式"""
        try:
            info = trade.get('info', {})
            symbol = trade.get('symbol', '').replace('/', '').replace(':USDT', '')
            side = trade.get('side', '').upper()
            
            # 判断是开平仓
            # 币安期货：根据buyer/maker字段判断
            is_buyer = info.get('buyer', False)
            position_side = info.get('positionSide', 'BOTH')
            
            # 确定action_type
            if position_side == 'LONG':
                action_type = 'close' if side == 'SELL' else 'open'
            elif position_side == 'SHORT':
                action_type = 'close' if side == 'BUY' else 'open'
            else:
                # 单向模式，简单判断
                action_type = 'open' if side == 'BUY' else 'close'
            
            # 获取盈亏
            realized_pnl = float(info.get('realizedPnl', 0))
            
            # 获取手续费
            fee_cost = 0.0
            fee_asset = ''
            fee_info = trade.get('fee', {})
            if fee_info:
                fee_cost = float(fee_info.get('cost', 0))
                fee_asset = fee_info.get('currency', '')
            
            fill_data = {
                'strategy_name': 'exchange_sync',  # 标记为交易所同步
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
                'signal_reason': '自动同步自币安交易所',
                'executed_at': datetime.fromtimestamp(trade.get('timestamp', 0) / 1000).isoformat(),
            }
            
            return fill_data
        except Exception as e:
            logger.warning(f"转换交易记录失败: {e}")
            return None
    
    def sync_trades(self, symbols: List[str] = None, 
                   since_hours: int = 24,
                   full_sync: bool = False) -> Dict[str, int]:
        """
        同步交易记录
        
        Args:
            symbols: 指定交易对列表，None则同步所有
            since_hours: 同步过去多少小时的记录
            full_sync: 是否全量同步（忽略数据库中已有记录的时间）
        """
        if not self.exchange:
            if not self.connect():
                return {'imported': 0, 'skipped': 0, 'failed': 0, 'total': 0}
        
        # 计算起始时间
        since_ms = int((datetime.now() - timedelta(hours=since_hours)).timestamp() * 1000)
        
        # 如果不是全量同步，获取数据库中最新记录的时间（用于增量同步）
        if not full_sync:
            try:
                latest_fills = self.repo.list_fills(limit=1)
                if latest_fills:
                    latest_time = latest_fills[0].get('executed_at', '')
                    if latest_time:
                        latest_ms = int(datetime.fromisoformat(latest_time).timestamp() * 1000)
                        since_ms = max(since_ms, latest_ms)
                        logger.info(f"📅 增量同步: 从 {latest_time} 开始")
            except Exception as e:
                logger.warning(f"获取最新记录时间失败: {e}")
        else:
            logger.info(f"📅 全量同步: 从 {since_hours}小时前开始")
        
        all_trades = []
        
        if symbols:
            # 同步指定交易对
            for symbol in symbols:
                logger.info(f"📡 正在同步 {symbol}...")
                trades = self.get_recent_trades_from_exchange(symbol, since_ms)
                if trades:
                    logger.info(f"  ✅ {symbol}: {len(trades)} 笔成交")
                    all_trades.extend(trades)
        else:
            # 同步主要交易对 - 扩展列表覆盖更多币种
            major_symbols = [
                'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'BNB/USDT:USDT',
                'XRP/USDT:USDT', 'ADA/USDT:USDT', 'DOGE/USDT:USDT', 'LINK/USDT:USDT',
                'AVAX/USDT:USDT', 'DOT/USDT:USDT', 'MATIC/USDT:USDT', 'LTC/USDT:USDT',
                'UNI/USDT:USDT', 'ATOM/USDT:USDT', 'ETC/USDT:USDT', 'FIL/USDT:USDT',
                'TRX/USDT:USDT', 'SHIB/USDT:USDT', 'MANA/USDT:USDT', 'SAND/USDT:USDT',
                'AXS/USDT:USDT', 'APE/USDT:USDT', 'GMT/USDT:USDT', 'FTM/USDT:USDT',
                'NEAR/USDT:USDT', 'ALGO/USDT:USDT', 'VET/USDT:USDT', 'ICP/USDT:USDT',
                'THETA/USDT:USDT', 'XLM/USDT:USDT', 'EOS/USDT:USDT', 'BCH/USDT:USDT',
                'SUSHI/USDT:USDT', 'AAVE/USDT:USDT', 'COMP/USDT:USDT', 'MKR/USDT:USDT'
            ]
            
            for symbol in major_symbols:
                trades = self.get_recent_trades_from_exchange(symbol, since_ms)
                if trades:
                    logger.info(f"✅ {symbol}: {len(trades)} 笔成交")
                    all_trades.extend(trades)
        
        if not all_trades:
            logger.info("📭 没有新的交易记录需要同步")
            return {'imported': 0, 'skipped': 0, 'failed': 0, 'total': 0}
        
        # 导入到数据库
        return self._import_trades(all_trades)
    
    def _import_trades(self, trades: List[Dict]) -> Dict[str, int]:
        """导入交易记录到数据库"""
        imported = 0
        skipped = 0
        failed = 0
        
        logger.info(f"\n📥 开始导入 {len(trades)} 笔交易记录...")
        
        for trade in trades:
            try:
                fill_data = self.convert_trade_to_fill(trade)
                if not fill_data:
                    failed += 1
                    continue
                
                # 检查是否已存在
                existing = self.repo.get_fill_by_exchange_trade_id(
                    fill_data['exchange_trade_id']
                )
                if existing:
                    skipped += 1
                    continue
                
                # 创建记录
                self.repo.create_fill(fill_data)
                imported += 1
                
            except Exception as e:
                failed += 1
                logger.warning(f"导入失败: {e}")
        
        self.last_sync_time = datetime.now()
        
        logger.info(f"📊 同步完成: 导入 {imported}, 跳过 {skipped}, 失败 {failed}")
        
        return {
            'imported': imported,
            'skipped': skipped,
            'failed': failed,
            'total': len(trades)
        }
    
    def start_background_sync(self, interval: int = 300):
        """
        启动后台同步线程
        
        Args:
            interval: 同步间隔（秒），默认5分钟
        """
        if self._sync_thread and self._sync_thread.is_alive():
            logger.warning("同步服务已在运行中")
            return
        
        self._stop_event.clear()
        
        def sync_loop():
            logger.info(f"🔄 币安交易同步服务已启动 (间隔: {interval}秒)")
            
            while not self._stop_event.is_set():
                try:
                    result = self.sync_trades(since_hours=24)
                    logger.info(f"⏰ 下次同步: {interval}秒后")
                except Exception as e:
                    logger.error(f"同步失败: {e}")
                
                # 等待下一次同步
                self._stop_event.wait(interval)
            
            logger.info("🛑 币安交易同步服务已停止")
        
        self._sync_thread = threading.Thread(target=sync_loop, daemon=True)
        self._sync_thread.start()
    
    def stop_background_sync(self):
        """停止后台同步"""
        self._stop_event.set()
        if self._sync_thread:
            self._sync_thread.join(timeout=5)
        logger.info("✅ 同步服务已停止")


# 全局实例
_sync_instance = None

def start_sync_service(interval: int = 300):
    """启动同步服务（供外部调用）"""
    global _sync_instance
    if _sync_instance is None:
        _sync_instance = BinanceTradeSync()
    _sync_instance.start_background_sync(interval)
    return _sync_instance

def stop_sync_service():
    """停止同步服务"""
    global _sync_instance
    if _sync_instance:
        _sync_instance.stop_background_sync()

def get_sync_status():
    """获取同步状态"""
    global _sync_instance
    if _sync_instance:
        return {
            'running': _sync_instance._sync_thread is not None and _sync_instance._sync_thread.is_alive(),
            'last_sync': _sync_instance.last_sync_time.isoformat() if _sync_instance.last_sync_time else None
        }
    return {'running': False, 'last_sync': None}


def main():
    parser = argparse.ArgumentParser(description='币安交易同步服务')
    parser.add_argument('--once', action='store_true',
                        help='只同步一次，不启动后台服务')
    parser.add_argument('--interval', type=int, default=300,
                        help='同步间隔（秒），默认300秒（5分钟）')
    parser.add_argument('--hours', type=int, default=24,
                        help='同步过去多少小时的记录，默认24小时')
    parser.add_argument('--symbols', type=str, default=None,
                        help='指定交易对，逗号分隔，如 BTC/USDT:USDT,ETH/USDT:USDT')
    parser.add_argument('--full', action='store_true',
                        help='全量同步（忽略已同步记录，重新获取所有数据）')
    
    args = parser.parse_args()
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s'
    )
    
    # 创建同步器
    sync = BinanceTradeSync()
    
    # 解析交易对
    symbols = None
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(',')]
    
    if args.once:
        # 单次同步
        logger.info("🚀 开始单次同步...")
        result = sync.sync_trades(symbols=symbols, since_hours=args.hours, full_sync=args.full)
        logger.info(f"\n{'='*50}")
        logger.info(f"📊 同步结果")
        logger.info(f"{'='*50}")
        logger.info(f"✅ 成功导入: {result['imported']}")
        logger.info(f"⏭️  已存在跳过: {result['skipped']}")
        logger.info(f"❌ 导入失败: {result['failed']}")
        logger.info(f"📈 总计: {result['total']}")
        logger.info(f"{'='*50}")
    else:
        # 启动后台服务
        sync.start_background_sync(interval=args.interval)
        
        try:
            # 保持运行
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n👋 收到停止信号...")
            sync.stop_background_sync()


if __name__ == '__main__':
    main()
