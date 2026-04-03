import logging
import json
import sqlite3
from datetime import datetime
from typing import Dict, Optional, List
from pathlib import Path
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading_core.exchange_client import get_exchange_client
from trading_core.risk_manager import get_risk_manager

logger = logging.getLogger(__name__)

class OrderExecutor:
    """订单执行引擎"""
    
    def __init__(self):
        self.exchange = get_exchange_client()
        self.risk_manager = get_risk_manager()
        self.db_path = Path(__file__).parent.parent / 'data' / 'trade_history.db'
        self._init_db()
        self.auto_trading = False
    
    def _init_db(self):
        """初始化数据库"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                action TEXT NOT NULL,
                amount REAL,
                price REAL,
                order_id TEXT,
                status TEXT,
                pnl REAL,
                strategy TEXT,
                timeframe TEXT,
                rsi REAL,
                notes TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                action TEXT NOT NULL,
                price REAL,
                rsi REAL,
                executed BOOLEAN DEFAULT 0,
                execution_time TEXT,
                order_id TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ 数据库初始化完成")
    
    def execute_signal(self, symbol: str, timeframe: str, action: str, 
                       price: float, rsi: float = 50, confidence: float = 1.0,
                       strategy: str = 'MA99_MTF') -> bool:
        """
        执行交易信号
        
        Args:
            symbol: 交易对
            timeframe: 时间周期
            action: 'LONG' 或 'SHORT'
            price: 当前价格
            rsi: RSI值
            confidence: 信号置信度
        """
        # 检查自动交易是否启用
        if not self.auto_trading:
            logger.info(f"⏸️ 自动交易已暂停，信号未执行: {symbol} {action}")
            self._record_signal(symbol, timeframe, action, price, rsi, executed=False)
            return False
        
        # 检查风险限制
        balance = self.exchange.get_balance()
        positions = self.exchange.get_positions()
        risk_check = self.risk_manager.check_risk_limits(balance, positions)
        
        if not risk_check['can_trade']:
            logger.warning(f"🚫 风险限制阻止交易: {', '.join(risk_check['reasons'])}")
            self._record_signal(symbol, timeframe, action, price, rsi, executed=False, 
                              notes=f"Risk blocked: {', '.join(risk_check['reasons'])}")
            return False
        
        # 检查是否已有同方向持仓
        for pos in positions:
            if pos['symbol'] == symbol and pos['side'] == action:
                logger.info(f"⏭️ 已有{action}持仓，跳过信号: {symbol}")
                return False
        
        # 如果有反向持仓，先平仓
        for pos in positions:
            if pos['symbol'] == symbol and pos['side'] != action:
                logger.info(f"🔄 检测到反向持仓，先平仓: {symbol}")
                self.exchange.close_position(symbol)
        
        # 计算仓位大小
        amount = self.risk_manager.calculate_position_size(symbol, price, confidence)
        
        # 设置杠杆
        self.exchange.set_leverage(symbol, self.risk_manager.default_leverage)
        
        # 计算止损止盈价格
        stop_loss = None
        take_profit = None
        if action == 'LONG':
            stop_loss = price * (1 - self.risk_manager.stop_loss_percent / 100)
            take_profit = price * (1 + self.risk_manager.take_profit_percent / 100)
        else:  # SHORT
            stop_loss = price * (1 + self.risk_manager.stop_loss_percent / 100)
            take_profit = price * (1 - self.risk_manager.take_profit_percent / 100)
        
        # 执行下单
        side = 'buy' if action == 'LONG' else 'sell'
        order = self.exchange.create_order(
            symbol=symbol,
            side=side,
            amount=amount,
            order_type='market'
        )
        
        if order:
            # 记录持仓信息
            logger.info(f"持仓记录: {symbol} {action} 数量{amount} 止损{stop_loss} 止盈{take_profit}")
            
            # 记录交易
            self._record_trade(symbol, action, amount, price, order['order_id'], 
                             timeframe, rsi)
            self._record_signal(symbol, timeframe, action, price, rsi, 
                              executed=True, order_id=order['order_id'])
            
            logger.info(f"✅ 信号执行成功: {symbol} {action} @ ${price:.2f}")
            return True
        else:
            self._record_signal(symbol, timeframe, action, price, rsi, 
                              executed=False, notes="Order failed")
            logger.error("订单执行失败")
            return False
    
    def _record_trade(self, symbol: str, action: str, amount: float, 
                     price: float, order_id: str, timeframe: str, rsi: float):
        """记录交易到数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO trades (timestamp, symbol, side, action, amount, price, 
                                  order_id, status, strategy, timeframe, rsi)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                symbol,
                'buy' if action == 'LONG' else 'sell',
                action,
                amount,
                price,
                order_id,
                'filled',
                'MA99_MTF',
                timeframe,
                rsi
            ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"记录交易失败: {e}")
    
    def _record_signal(self, symbol: str, timeframe: str, action: str,
                      price: float, rsi: float, executed: bool = False,
                      order_id: str = None, notes: str = None):
        """记录信号到数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO signals (timestamp, symbol, timeframe, action, price, 
                                   rsi, executed, execution_time, order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                symbol,
                timeframe,
                action,
                price,
                rsi,
                executed,
                datetime.now().isoformat() if executed else None,
                order_id
            ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"记录信号失败: {e}")
    
    def get_recent_trades(self, limit: int = 50) -> List[Dict]:
        """获取最近交易记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"获取交易记录失败: {e}")
            return []
    
    def get_recent_signals(self, limit: int = 50) -> List[Dict]:
        """获取最近信号记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"获取信号记录失败: {e}")
            return []
    
    def start_auto_trading(self):
        """启动自动交易"""
        self.auto_trading = True
        logger.info("🚀 自动交易已启动")
    
    def stop_auto_trading(self):
        """停止自动交易"""
        self.auto_trading = False
        logger.info("⏹️ 自动交易已停止")
    
    def check_positions(self):
        """检查所有持仓的止盈止损状态"""
        try:
            positions = self.position_tracker.get_all_positions()
            for pos in positions:
                symbol = pos['symbol']
                current_price = self.exchange.get_current_price(symbol)
                if current_price is None:
                    continue
                
                should_close, reason, close_price = self.position_tracker.update_position(
                    symbol, current_price
                )
                
                if should_close:
                    # 执行平仓
                    success = self.exchange.close_position(symbol)
                    if success:
                        # 计算盈亏
                        entry_price = pos['entry_price']
                        amount = pos['amount']
                        if pos['side'] == 'LONG':
                            pnl = (close_price - entry_price) * amount
                        else:
                            pnl = (entry_price - close_price) * amount
                        
                        # 更新持仓跟踪
                        self.position_tracker.close_position(symbol, close_price, pnl)
                        
                        # 记录盈亏
                        self.risk_manager.record_trade(pnl)
                        
                        # 发送通知
                        if reason == 'STOP_LOSS':
                            self.email_notifier.notify_stop_loss(
                                symbol, entry_price, close_price, abs(pnl) if pnl < 0 else 0
                            )
                        elif reason == 'TAKE_PROFIT':
                            self.email_notifier.notify_take_profit(
                                symbol, entry_price, close_price, pnl if pnl > 0 else 0
                            )
                        
                        logger.trade(f'CLOSE_{reason}', symbol, close_price, amount, pnl)
                        logger.info(f"✅ 自动平仓: {symbol} 原因:{reason} 盈亏:{pnl:.4f}")
                        
        except Exception as e:
            logger.error(f"检查持仓失败: {e}")
    
    def emergency_stop(self):
        """紧急停止 - 停止交易并平掉所有持仓"""
        self.stop_auto_trading()
        logger.warning("🚨 紧急停止触发！正在平仓...")
        
        # 发送紧急通知
        self.email_notifier.notify_error(
            "紧急停止已触发，系统正在平掉所有持仓",
            context="用户手动触发或风控系统自动触发"
        )
        
        success = self.exchange.close_all_positions()
        if success:
            logger.info("✅ 所有持仓已平仓")
            # 清空持仓跟踪
            for pos in self.position_tracker.get_all_positions():
                self.position_tracker.remove_position(pos['symbol'])
        else:
            logger.error("❌ 部分持仓平仓失败，请手动检查")
        
        return success
    
    def get_status(self) -> Dict:
        """获取执行器状态"""
        return {
            'auto_trading': self.auto_trading,
            'recent_trades_count': len(self.get_recent_trades(100)),
            'recent_signals_count': len(self.get_recent_signals(100))
        }

# 单例模式
_order_executor = None

def get_order_executor() -> OrderExecutor:
    """获取订单执行器实例"""
    global _order_executor
    if _order_executor is None:
        _order_executor = OrderExecutor()
    return _order_executor
