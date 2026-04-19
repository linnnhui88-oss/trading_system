import logging
import json
import sqlite3
import threading
import time
from datetime import datetime
from typing import Dict, Optional, List
from pathlib import Path
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading_core.exchange_client import get_exchange_client
from trading_core.risk_manager import get_risk_manager
from trading_core.trade_fill_repository import TradeFillRepository

logger = logging.getLogger(__name__)

# 策略日志记录器（延迟导入）
_strategy_logger = None

def get_strategy_logger():
    """获取策略日志记录器"""
    global _strategy_logger
    if _strategy_logger is None:
        try:
            from StrategyLogger import StrategyLogger
            _strategy_logger = StrategyLogger("MA99_MTF")
        except Exception as e:
            logger.warning(f"策略日志记录器初始化失败: {e}")
    return _strategy_logger

class OrderExecutor:
    """订单执行引擎 - 包含自动止盈止损监控"""
    
    def __init__(self):
        self.exchange = get_exchange_client()
        self.risk_manager = get_risk_manager()
        self.trade_fill_repo = TradeFillRepository()
        self.db_path = Path(__file__).parent.parent / 'data' / 'trade_history.db'
        self._init_db()
        self.auto_trading = False
        
        # 持仓跟踪 {symbol: {'side': 'LONG'/'SHORT', 'entry_price': float, 'amount': float, 
        #                    'stop_loss': float, 'take_profit': float, 'order_id': str}}
        self.positions = {}
        self.positions_lock = threading.Lock()
        
        # 数据库连接锁（线程安全）
        self._db_lock = threading.Lock()
        
        # 启动止盈止损监控线程
        self._monitor_thread = None
        self._stop_monitor = threading.Event()
        self._start_position_monitor()
        
        # 定期同步持仓（每5分钟）
        self._start_position_sync()
    
    def _init_db(self):
        """初始化数据库（添加索引优化）"""
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
        
        # 创建索引优化查询性能
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol)')
        
        conn.commit()
        conn.close()
        logger.info("✅ 数据库初始化完成")
    
    def execute_signal(self, symbol: str, timeframe: str, action: str,
                       price: float, rsi: float = 50, confidence: float = 1.0,
                       strategy: str = 'MA99_MTF', ai_model: str = '',
                       ai_decision: str = 'EXECUTE', signal_source: str = 'strategy_signal',
                       signal_reason: str = '') -> bool:
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
            self._record_trade(
                symbol,
                action,
                amount,
                price,
                order['order_id'],
                timeframe,
                rsi,
                strategy_name=strategy,
                ai_model=ai_model,
                ai_decision=ai_decision,
                signal_source=signal_source,
                signal_reason=signal_reason
            )
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
                     price: float, order_id: str, timeframe: str, rsi: float,
                     pnl: float = None, notes: str = None, strategy_name: str = 'MA99_MTF',
                     ai_model: str = '', ai_decision: str = 'EXECUTE',
                     signal_source: str = 'strategy_signal', signal_reason: str = ''):
        """记录交易到数据库（线程安全）"""
        with self._db_lock:
            conn = None
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT INTO trades (timestamp, symbol, side, action, amount, price, 
                                      order_id, status, strategy, timeframe, rsi, pnl, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    datetime.now().isoformat(),
                    symbol,
                    'buy' if action == 'LONG' else 'sell',
                    action,
                    amount,
                    price,
                    order_id,
                    'filled',
                    strategy_name or 'MA99_MTF',
                    timeframe,
                    rsi,
                    pnl,
                    notes
                ))
            
                conn.commit()
                conn.close()
                self._record_trade_fill(
                    symbol=symbol,
                    action=action,
                    amount=amount,
                    price=price,
                    order_id=order_id,
                    timeframe=timeframe,
                    pnl=pnl,
                    notes=notes,
                    strategy_name=strategy_name,
                    ai_model=ai_model,
                    ai_decision=ai_decision,
                    signal_source=signal_source,
                    signal_reason=signal_reason,
                )
            except Exception as e:
                logger.error(f"记录交易失败: {e}")
                if conn:
                    conn.close()

    def _record_trade_fill(
        self,
        symbol: str,
        action: str,
        amount: float,
        price: float,
        order_id: str,
        timeframe: str,
        pnl: float = None,
        notes: str = None,
        strategy_name: str = 'MA99_MTF',
        ai_model: str = '',
        ai_decision: str = 'EXECUTE',
        signal_source: str = 'strategy_signal',
        signal_reason: str = ''
    ):
        """Write normalized execution events into trade_fills."""
        try:
            action_upper = (action or "").strip().upper()
            is_close_event = pnl is not None
            if is_close_event:
                side = "SELL" if action_upper == "LONG" else "BUY"
            else:
                side = "BUY" if action_upper == "LONG" else "SELL"
            position_side = action_upper if action_upper in {"LONG", "SHORT"} else ""
            order_id_str = str(order_id or "")
            note_str = notes or ""

            action_type = "open"
            final_signal_source = signal_source or "strategy_signal"
            if pnl is not None:
                if order_id_str.startswith("tp_sl_"):
                    reason = order_id_str.replace("tp_sl_", "").upper()
                    if "TAKE_PROFIT" in reason:
                        action_type = "take_profit"
                    elif "STOP_LOSS" in reason:
                        action_type = "stop_loss"
                    else:
                        action_type = "close"
                    final_signal_source = "risk_manager"
                elif order_id_str.startswith("manual_"):
                    action_type = "manual_close"
                    final_signal_source = "manual"
                else:
                    action_type = "close"

            final_strategy_name = (strategy_name or '').strip() or "MA99_MTF"
            final_ai_decision = (ai_decision or "EXECUTE").strip().upper()
            if final_ai_decision not in {"EXECUTE", "SKIP", "REDUCE"}:
                final_ai_decision = "EXECUTE"
            final_signal_reason = (signal_reason or note_str or '').strip()

            self.trade_fill_repo.create_fill({
                "strategy_name": final_strategy_name,
                "symbol": (symbol or "").replace("/", "").upper(),
                "side": side,
                "position_side": position_side,
                "action_type": action_type,
                "order_id": order_id_str,
                "exchange_trade_id": "",
                "quantity": float(amount or 0),
                "price": float(price or 0),
                "realized_pnl": float(pnl or 0),
                "fee": 0,
                "fee_asset": "",
                "ai_model": (ai_model or "").strip(),
                "ai_decision": final_ai_decision,
                "signal_source": final_signal_source,
                "signal_reason": final_signal_reason,
            })
        except Exception as e:
            logger.warning(f"Trade fill write skipped: {e}")
    
    def _record_signal(self, symbol: str, timeframe: str, action: str,
                      price: float, rsi: float, executed: bool = False,
                      order_id: str = None, notes: str = None):
        """记录信号到数据库（线程安全）"""
        with self._db_lock:
            conn = None
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
                if conn:
                    conn.close()
    
    def get_recent_trades(self, limit: int = 50) -> List[Dict]:
        """获取最近交易记录（线程安全）"""
        with self._db_lock:
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
        """获取最近信号记录（线程安全）"""
        with self._db_lock:
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
    
    def _start_position_sync(self):
        """启动持仓同步线程（定期与交易所同步）"""
        def sync_loop():
            while not self._stop_monitor.is_set():
                try:
                    self._sync_positions_with_exchange()
                except Exception as e:
                    logger.error(f"持仓同步失败: {e}")
                
                # 每5分钟同步一次
                self._stop_monitor.wait(300)
        
        sync_thread = threading.Thread(target=sync_loop, daemon=True)
        sync_thread.start()
        logger.info("🔄 持仓同步线程已启动（每5分钟）")
    
    def _sync_positions_with_exchange(self):
        """与交易所同步持仓状态"""
        try:
            exchange_positions = self.exchange.get_positions()
            
            with self.positions_lock:
                # 清理已不存在的持仓
                current_symbols = {p['symbol'] for p in exchange_positions}
                for symbol in list(self.positions.keys()):
                    if symbol not in current_symbols:
                        logger.info(f"持仓同步: 移除已平仓 {symbol}")
                        del self.positions[symbol]
                
                # 更新现有持仓信息
                for pos in exchange_positions:
                    symbol = pos['symbol']
                    if symbol in self.positions:
                        # 更新价格和盈亏
                        self.positions[symbol]['mark_price'] = pos.get('mark_price', 0)
                        self.positions[symbol]['unrealized_pnl'] = pos.get('unrealized_pnl', 0)
                        
        except Exception as e:
            logger.error(f"同步持仓失败: {e}")
    
    def start_auto_trading(self):
        """启动自动交易"""
        self.auto_trading = True
        logger.info("🚀 自动交易已启动")
    
    def stop_auto_trading(self):
        """停止自动交易"""
        self.auto_trading = False
        logger.info("⏹️ 自动交易已停止")
    
    def _start_position_monitor(self):
        """启动持仓监控线程（自动止盈止损）"""
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            return
        
        self._stop_monitor.clear()
        
        def monitor_loop():
            logger.info("🔄 自动止盈止损监控已启动")
            while not self._stop_monitor.is_set():
                try:
                    self._check_positions_tp_sl()
                except Exception as e:
                    logger.error(f"监控线程出错: {e}")
                
                # 每5秒检查一次
                self._stop_monitor.wait(5)
            
            logger.info("🛑 自动止盈止损监控已停止")
        
        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()
    
    def _check_positions_tp_sl(self):
        """检查所有持仓的止盈止损状态"""
        with self.positions_lock:
            positions_copy = dict(self.positions)
        
        for symbol, pos in positions_copy.items():
            try:
                # 获取当前价格
                ticker = self.exchange.fetch_ticker(symbol)
                current_price = ticker['last']
                
                if current_price is None:
                    continue
                
                side = pos['side']
                entry_price = pos['entry_price']
                stop_loss = pos['stop_loss']
                take_profit = pos['take_profit']
                amount = pos['amount']
                
                should_close = False
                reason = None
                close_price = current_price
                
                # 检查止损
                if side == 'LONG':
                    if current_price <= stop_loss:
                        should_close = True
                        reason = 'STOP_LOSS'
                    elif current_price >= take_profit:
                        should_close = True
                        reason = 'TAKE_PROFIT'
                else:  # SHORT
                    if current_price >= stop_loss:
                        should_close = True
                        reason = 'STOP_LOSS'
                    elif current_price <= take_profit:
                        should_close = True
                        reason = 'TAKE_PROFIT'
                
                if should_close:
                    logger.info(f"🎯 触发{reason}: {symbol} 当前价:${current_price:.2f}")
                    
                    # 执行平仓
                    success = self.exchange.close_position(symbol)
                    
                    if success:
                        # 计算盈亏
                        if side == 'LONG':
                            pnl = (close_price - entry_price) * amount
                            pnl_percent = (close_price - entry_price) / entry_price * 100
                        else:
                            pnl = (entry_price - close_price) * amount
                            pnl_percent = (entry_price - close_price) / entry_price * 100
                        
                        # 移除持仓记录
                        with self.positions_lock:
                            if symbol in self.positions:
                                del self.positions[symbol]
                        
                        # 记录盈亏
                        self.risk_manager.record_trade(pnl)
                        
                        # 记录到数据库（包含盈亏）
                        self._record_trade(symbol, side, amount, close_price, 
                                         f"tp_sl_{reason}", 'MA99_MTF', 0, 
                                         pnl=pnl,
                                         notes=f"{reason} 盈亏:{pnl:.2f}USDT ({pnl_percent:+.2f}%)")
                        
                        # 记录策略平仓日志
                        try:
                            strategy_logger = get_strategy_logger()
                            if strategy_logger:
                                strategy_logger.log_position_close(
                                    symbol=symbol,
                                    side=side,
                                    exit_price=close_price,
                                    pnl=round(pnl, 2),
                                    close_reason=reason
                                )
                        except Exception as e:
                            logger.warning(f"记录平仓日志失败: {e}")
                        
                        # 发送Telegram通知
                        self._send_tp_sl_notification(symbol, side, reason, entry_price, 
                                                     close_price, pnl, pnl_percent)
                        
                        logger.info(f"✅ 自动平仓完成: {symbol} {reason} 盈亏:{pnl:.2f}USDT ({pnl_percent:+.2f}%)")
                    else:
                        logger.error(f"❌ 自动平仓失败: {symbol}")
                        
            except Exception as e:
                logger.error(f"检查持仓 {symbol} 失败: {e}")
    
    def _send_tp_sl_notification(self, symbol: str, side: str, reason: str, 
                                  entry_price: float, close_price: float, 
                                  pnl: float, pnl_percent: float):
        """发送止盈止损通知"""
        try:
            import requests
            
            token = os.getenv('TELEGRAM_BOT_TOKEN', '')
            chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
            
            if not token or not chat_id:
                return
            
            emoji = "🟢" if pnl > 0 else "🔴"
            action_emoji = "📈" if reason == 'TAKE_PROFIT' else "📉"
            
            text = f"""{action_emoji} <b>自动{reason}</b> {emoji}

📌 <b>标的:</b> {symbol}
🎯 <b>方向:</b> {side}
💰 <b>入场价:</b> ${entry_price:.2f}
💵 <b>平仓价:</b> ${close_price:.2f}
📊 <b>盈亏:</b> {pnl:+.2f} USDT ({pnl_percent:+.2f}%)
⏰ <b>时间:</b> {datetime.now().strftime('%H:%M:%S')}
"""
            
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            }, timeout=10)
            
        except Exception as e:
            logger.error(f"发送通知失败: {e}")
    
    def emergency_stop(self):
        """紧急停止 - 停止交易并平掉所有持仓"""
        self.stop_auto_trading()
        logger.warning("🚨 紧急停止触发！正在平仓...")
        
        # 平掉所有持仓
        success = self.exchange.close_all_positions()
        
        if success:
            logger.info("✅ 所有持仓已平仓")
            # 清空持仓跟踪
            with self.positions_lock:
                self.positions.clear()
        else:
            logger.error("❌ 部分持仓平仓失败，请手动检查")
        
        return success

    @staticmethod
    def _normalize_symbol_key(symbol: str) -> str:
        return (symbol or "").replace("/", "").upper().strip()

    def close_position_manual(self, symbol: str) -> Dict:
        """
        手动平仓（单个交易对），并写入交易记录。
        """
        try:
            target_key = self._normalize_symbol_key(symbol)
            if not target_key:
                return {'success': False, 'error': 'symbol is required'}

            positions = self.exchange.get_positions()
            target_pos = None
            for pos in positions:
                if self._normalize_symbol_key(pos.get('symbol', '')) == target_key:
                    target_pos = pos
                    break

            if not target_pos:
                return {'success': False, 'error': f'No active position found for {symbol}'}

            exchange_symbol = target_pos.get('symbol', symbol)
            side = target_pos.get('side', 'LONG')
            amount = float(target_pos.get('contracts') or 0)
            entry_price = float(target_pos.get('entry_price') or 0)

            if amount <= 0:
                return {'success': False, 'error': f'Invalid position size for {exchange_symbol}'}

            success = self.exchange.close_position(exchange_symbol)
            if not success:
                return {'success': False, 'error': f'Close position failed for {exchange_symbol}'}

            close_price = self.exchange.get_current_price(exchange_symbol) or float(target_pos.get('mark_price') or entry_price or 0)
            close_price = float(close_price or 0)
            if close_price <= 0:
                close_price = entry_price

            if side == 'LONG':
                pnl = (close_price - entry_price) * amount
            else:
                pnl = (entry_price - close_price) * amount

            order_id = f"manual_{int(time.time() * 1000)}"
            notes = f"MANUAL_CLOSE {exchange_symbol} entry={entry_price:.6f} close={close_price:.6f}"
            self._record_trade(
                exchange_symbol,
                side,
                amount,
                close_price,
                order_id,
                'MANUAL',
                0,
                pnl=pnl,
                notes=notes
            )
            self.risk_manager.record_trade(pnl)

            with self.positions_lock:
                remove_keys = [k for k in self.positions.keys() if self._normalize_symbol_key(k) == target_key]
                for key in remove_keys:
                    del self.positions[key]

            return {
                'success': True,
                'symbol': exchange_symbol,
                'side': side,
                'amount': amount,
                'entry_price': entry_price,
                'close_price': close_price,
                'pnl': pnl,
            }
        except Exception as e:
            logger.error(f"手动平仓失败: {e}")
            return {'success': False, 'error': str(e)}

    def close_all_positions_manual(self) -> Dict:
        """
        手动全平，并对每个持仓写入交易记录。
        """
        try:
            positions = self.exchange.get_positions()
            if not positions:
                return {'success': True, 'closed_count': 0, 'failed_count': 0, 'details': []}

            details = []
            seen = set()
            for pos in positions:
                symbol = pos.get('symbol', '')
                key = self._normalize_symbol_key(symbol)
                if not key or key in seen:
                    continue
                seen.add(key)
                details.append(self.close_position_manual(symbol))

            closed_count = sum(1 for item in details if item.get('success'))
            failed_count = sum(1 for item in details if not item.get('success'))

            return {
                'success': failed_count == 0,
                'closed_count': closed_count,
                'failed_count': failed_count,
                'details': details,
            }
        except Exception as e:
            logger.error(f"手动全平失败: {e}")
            return {'success': False, 'closed_count': 0, 'failed_count': 0, 'details': [], 'error': str(e)}
    
    def open_position(self, symbol: str, side: str, usdt_amount: float,
                     leverage: int = 3, atr_value: float = None,
                     stop_loss_atr: float = 1.5, take_profit_atr: float = 3.0) -> Optional[Dict]:
        """
        开仓接口（供策略管理器调用）- ATR动态止盈止损
        
        Args:
            symbol: 交易对，如 'BTC/USDT'
            side: 'buy' 或 'sell'
            usdt_amount: 开仓金额（USDT）
            leverage: 杠杆倍数
            atr_value: ATR值（从策略传入）
            stop_loss_atr: 止损ATR倍数（默认1.5）
            take_profit_atr: 止盈ATR倍数（默认3.0）
            
        Returns:
            订单信息或None
        """
        try:
            # 获取当前价格
            ticker = self.exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            
            # 如果没有提供ATR，获取K线计算ATR
            if atr_value is None:
                try:
                    import pandas as pd
                    ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=20)
                    if ohlcv and len(ohlcv) >= 14:
                        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        high_low = df['high'] - df['low']
                        high_close = (df['high'] - df['close'].shift()).abs()
                        low_close = (df['low'] - df['close'].shift()).abs()
                        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
                        atr_value = tr.rolling(14).mean().iloc[-1]
                    else:
                        atr_value = current_price * 0.02  # 默认2%
                except:
                    atr_value = current_price * 0.02  # 默认2%
            
            # 计算数量
            amount = usdt_amount / current_price
            
            # 设置杠杆
            self.exchange.set_leverage(symbol, leverage)
            
            # 执行市价单
            order = self.exchange.create_order(
                symbol=symbol,
                side=side,
                amount=amount,
                order_type='market'
            )
            
            if order:
                # 计算ATR动态止损止盈价格
                action = 'LONG' if side == 'buy' else 'SHORT'
                if action == 'LONG':
                    stop_loss = current_price - (atr_value * stop_loss_atr)
                    take_profit = current_price + (atr_value * take_profit_atr)
                else:
                    stop_loss = current_price + (atr_value * stop_loss_atr)
                    take_profit = current_price - (atr_value * take_profit_atr)
                
                # 计算百分比（用于显示）
                sl_percent = abs(stop_loss - current_price) / current_price * 100
                tp_percent = abs(take_profit - current_price) / current_price * 100
                
                logger.info(f"✅ 开仓成功: {symbol} {action} @ ${current_price:.2f}, "
                          f"数量: {amount:.6f}, 杠杆: {leverage}x")
                logger.info(f"🛡️ ATR动态止损止盈 | ATR: ${atr_value:.2f}")
                logger.info(f"📉 止损: ${stop_loss:.2f} ({sl_percent:.2f}%) | "
                          f"📈 止盈: ${take_profit:.2f} ({tp_percent:.2f}%) | "
                          f"盈亏比: 1:{tp_percent/sl_percent:.1f}")
                
                # 记录持仓信息（用于自动止盈止损监控）
                with self.positions_lock:
                    self.positions[symbol] = {
                        'side': action,
                        'entry_price': current_price,
                        'amount': amount,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'order_id': order.get('order_id', ''),
                        'leverage': leverage,
                        'open_time': datetime.now().isoformat()
                    }
                
                # 记录交易
                self._record_trade(symbol, action, amount, current_price, 
                                 order.get('order_id', ''), 'MA99_MTF', 50,
                                 notes=f"止损:{stop_loss:.2f} 止盈:{take_profit:.2f}")
                
                return order
            else:
                logger.error(f"❌ 开仓失败: {symbol}")
                return None
                
        except Exception as e:
            logger.error(f"开仓出错: {e}")
            return None
    
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
