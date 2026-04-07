"""
策略管理器 - 管理多个交易策略的运行
"""
import logging
import threading
import time
import json
import os
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .ma99_mtf import MA99MTFStrategy, Signal

logger = logging.getLogger(__name__)


class StrategyStatus(Enum):
    """策略状态"""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class StrategyConfig:
    """策略配置"""
    name: str
    strategy_type: str  # 'ma99_mtf', etc.
    symbols: List[str]
    timeframes: List[str]
    enabled: bool = True
    params: Dict = field(default_factory=dict)
    max_positions: int = 1  # 该策略最大持仓数
    position_size_usdt: float = 100.0  # 单次开仓金额


class StrategyManager:
    """
    策略管理器
    
    功能：
    1. 管理多个策略实例
    2. 定期扫描生成信号
    3. 信号去重和过滤
    4. 与OrderExecutor集成执行交易
    """
    
    def __init__(self, exchange, risk_manager, order_executor):
        """
        初始化策略管理器
        
        Args:
            exchange: CCXT交易所实例
            risk_manager: 风控管理器
            order_executor: 订单执行器
        """
        self.exchange = exchange
        self.risk_manager = risk_manager
        self.order_executor = order_executor
        
        # 策略实例
        self.strategies: Dict[str, MA99MTFStrategy] = {}
        self.configs: Dict[str, StrategyConfig] = {}
        self.status: Dict[str, StrategyStatus] = {}
        
        # 信号回调
        self.signal_callbacks: List[Callable] = []
        
        # 运行控制
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # 信号历史
        self.signal_history: List[Dict] = []
        self.max_history = 1000
        
        logger.info("策略管理器初始化完成")
    
    def register_strategy(self, config: StrategyConfig) -> bool:
        """
        注册策略
        
        Args:
            config: 策略配置
            
        Returns:
            是否成功
        """
        try:
            with self._lock:
                if config.strategy_type == 'ma99_mtf':
                    strategy = MA99MTFStrategy(**config.params)
                else:
                    logger.error(f"未知策略类型: {config.strategy_type}")
                    return False
                
                self.strategies[config.name] = strategy
                self.configs[config.name] = config
                self.status[config.name] = StrategyStatus.STOPPED
                
                logger.info(f"策略 '{config.name}' ({config.strategy_type}) 注册成功")
                return True
                
        except Exception as e:
            logger.error(f"注册策略失败: {e}")
            return False
    
    def unregister_strategy(self, name: str) -> bool:
        """注销策略"""
        with self._lock:
            if name in self.strategies:
                self.stop_strategy(name)
                del self.strategies[name]
                del self.configs[name]
                del self.status[name]
                logger.info(f"策略 '{name}' 已注销")
                return True
            return False
    
    def start_strategy(self, name: str) -> bool:
        """启动指定策略"""
        with self._lock:
            if name not in self.strategies:
                logger.error(f"策略 '{name}' 不存在")
                return False
            
            config = self.configs[name]
            if not config.enabled:
                logger.warning(f"策略 '{name}' 已被禁用")
                return False
            
            self.status[name] = StrategyStatus.RUNNING
            logger.info(f"策略 '{name}' 已启动")
            return True
    
    def stop_strategy(self, name: str) -> bool:
        """停止指定策略"""
        with self._lock:
            if name in self.status:
                self.status[name] = StrategyStatus.STOPPED
                logger.info(f"策略 '{name}' 已停止")
                return True
            return False
    
    def pause_strategy(self, name: str) -> bool:
        """暂停策略（保持持仓）"""
        with self._lock:
            if name in self.status:
                self.status[name] = StrategyStatus.PAUSED
                logger.info(f"策略 '{name}' 已暂停")
                return True
            return False
    
    def start_all(self):
        """启动所有策略"""
        for name in self.strategies:
            self.start_strategy(name)
    
    def stop_all(self):
        """停止所有策略"""
        for name in self.strategies:
            self.stop_strategy(name)
    
    def add_signal_callback(self, callback: Callable):
        """添加信号回调函数"""
        self.signal_callbacks.append(callback)
    
    def remove_signal_callback(self, callback: Callable):
        """移除信号回调函数"""
        if callback in self.signal_callbacks:
            self.signal_callbacks.remove(callback)
    
    def _on_signal(self, config: StrategyConfig, signal: Signal, strategy: MA99MTFStrategy):
        """处理信号"""
        # 获取AI分析
        ai_advice = ""
        if strategy.enable_ai and strategy.ai_client:
            ai_advice = strategy.get_ai_analysis(signal)
            logger.info(f"🧠 AI分析: {ai_advice[:100]}...")
        
        # 发送Telegram提醒
        if strategy.enable_telegram:
            strategy.send_telegram_alert(signal, ai_advice)
        
        # 记录信号（初始状态为PENDING）
        signal_record = {
            'timestamp': datetime.now().isoformat(),
            'strategy': config.name,
            'symbol': signal.symbol,
            'timeframe': signal.timeframe,
            'action': signal.action,
            'price': signal.price,
            'rsi': signal.rsi,
            'confidence': signal.confidence,
            'executed': False,  # 初始未执行
            'status': 'PENDING',
            'ai_advice': ai_advice
        }
        
        # 立即保存到文件（确保持久化）
        self._save_signal_to_file(signal_record)
        
        self.signal_history.append(signal_record)
        if len(self.signal_history) > self.max_history:
            self.signal_history = self.signal_history[-self.max_history:]
        
        # 调用回调
        for callback in self.signal_callbacks:
            try:
                callback(config, signal, ai_advice)
            except Exception as e:
                logger.error(f"信号回调执行失败: {e}")
        
        # 自动执行交易（如果配置允许）
        executed = False
        if config.position_size_usdt > 0:
            executed = self._execute_signal(config, signal)
        
        # 更新信号记录状态并保存
        signal_record['executed'] = executed
        signal_record['status'] = 'EXECUTED' if executed else 'SKIPPED'
        self._save_signal_to_file(signal_record)
    
    def _execute_signal(self, config: StrategyConfig, signal: Signal):
        """
        执行信号对应的交易 - MA99_MTF策略专用
        所有开单必须通过此策略信号
        """
        try:
            # 1. 检查风控
            if not self.risk_manager.can_open_position(signal.symbol):
                logger.warning(f"🚫 风控阻止: 无法开仓 {signal.symbol}")
                self._record_signal_execution(signal, "REJECTED_RISK", None)
                return
            
            # 2. 检查是否已有同向持仓
            current_positions = self.exchange.get_positions()
            symbol_positions = [p for p in current_positions if p['symbol'] == signal.symbol]
            
            if len(symbol_positions) >= config.max_positions:
                logger.info(f"⏭️ 已达最大持仓限制: {signal.symbol} (当前{len(symbol_positions)}个)")
                self._record_signal_execution(signal, "SKIPPED_MAX_POSITIONS", None)
                return
            
            # 3. 检查是否有反向持仓 - 如果有先平仓
            for pos in symbol_positions:
                pos_side = 'LONG' if pos.get('side', '').upper() in ['LONG', 'BUY'] else 'SHORT'
                if pos_side != signal.action:
                    logger.info(f"🔄 检测到反向持仓，先平仓: {signal.symbol} {pos_side}")
                    self.exchange.close_position(signal.symbol)
                    time.sleep(1)  # 等待平仓完成
            
            # 4. 计算仓位大小
            side = 'buy' if signal.action == 'LONG' else 'sell'
            
            # 5. 执行下单（使用ATR动态止盈止损）
            logger.info(f"🎯 MA99信号执行: {signal.symbol} {signal.action} @ ${signal.price:.2f}")
            logger.info(f"📊 信号ATR: ${signal.atr:.2f} | 动态SL: 1.5x | 动态TP: 3.0x")
            
            order = self.order_executor.open_position(
                symbol=signal.symbol,
                side=side,
                usdt_amount=config.position_size_usdt,
                leverage=int(os.getenv('DEFAULT_LEVERAGE', 3)),
                atr_value=signal.atr,  # 传递ATR值
                stop_loss_atr=1.5,     # 1.5倍ATR止损
                take_profit_atr=3.0    # 3.0倍ATR止盈
            )
            
            if order:
                logger.info(f"✅ 信号执行成功: {signal.symbol} {signal.action} 订单ID:{order.get('order_id', 'N/A')}")
                self._record_signal_execution(signal, "EXECUTED", order)
                return True
            else:
                logger.error(f"❌ 信号执行失败: {signal.symbol} {signal.action}")
                self._record_signal_execution(signal, "FAILED", None)
                return False
                
        except Exception as e:
            logger.error(f"❌ 执行信号时出错: {e}")
            self._record_signal_execution(signal, "ERROR", None)
            return False
    
    def _record_signal_execution(self, signal: Signal, status: str, order: Optional[Dict]):
        """记录信号执行结果，用于后期统计胜率"""
        execution_record = {
            'timestamp': datetime.now().isoformat(),
            'symbol': signal.symbol,
            'timeframe': signal.timeframe,
            'action': signal.action,
            'price': signal.price,
            'rsi': signal.rsi,
            'confidence': signal.confidence,
            'status': status,
            'order_id': order.get('order_id') if order else None
        }
        
        # 保存到文件以便分析
        try:
            import json
            log_file = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'signal_execution_log.jsonl')
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(execution_record, ensure_ascii=False) + '\n')
        except Exception as e:
            logger.error(f"记录信号执行结果失败: {e}")
    
    def _save_signal_to_file(self, signal_record: Dict):
        """保存信号到文件（用于前端显示历史）"""
        try:
            log_file = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'signals_history.jsonl')
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(signal_record, ensure_ascii=False) + '\n')
        except Exception as e:
            logger.error(f"保存信号历史失败: {e}")
    
    def get_signal_stats(self, days: int = 7) -> Dict:
        """获取信号统计信息"""
        try:
            import json
            from datetime import datetime, timedelta
            
            log_file = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'signal_execution_log.jsonl')
            if not os.path.exists(log_file):
                return {'error': '暂无统计数据'}
            
            cutoff_date = datetime.now() - timedelta(days=days)
            stats = {
                'total_signals': 0,
                'executed': 0,
                'rejected_risk': 0,
                'skipped': 0,
                'failed': 0,
                'by_symbol': {},
                'by_timeframe': {}
            }
            
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        record_date = datetime.fromisoformat(record['timestamp'])
                        if record_date < cutoff_date:
                            continue
                        
                        stats['total_signals'] += 1
                        status = record['status']
                        
                        if status == 'EXECUTED':
                            stats['executed'] += 1
                        elif status == 'REJECTED_RISK':
                            stats['rejected_risk'] += 1
                        elif status == 'SKIPPED_MAX_POSITIONS':
                            stats['skipped'] += 1
                        elif status in ['FAILED', 'ERROR']:
                            stats['failed'] += 1
                        
                        # 按币种统计
                        symbol = record['symbol']
                        if symbol not in stats['by_symbol']:
                            stats['by_symbol'][symbol] = {'total': 0, 'executed': 0}
                        stats['by_symbol'][symbol]['total'] += 1
                        if status == 'EXECUTED':
                            stats['by_symbol'][symbol]['executed'] += 1
                        
                        # 按周期统计
                        tf = record['timeframe']
                        if tf not in stats['by_timeframe']:
                            stats['by_timeframe'][tf] = {'total': 0, 'executed': 0}
                        stats['by_timeframe'][tf]['total'] += 1
                        if status == 'EXECUTED':
                            stats['by_timeframe'][tf]['executed'] += 1
                            
                    except Exception:
                        continue
            
            return stats
            
        except Exception as e:
            logger.error(f"获取信号统计失败: {e}")
            return {'error': str(e)}
    
    def scan_once(self):
        """执行一次扫描"""
        with self._lock:
            for name, strategy in self.strategies.items():
                if self.status.get(name) != StrategyStatus.RUNNING:
                    continue
                
                config = self.configs[name]
                
                for symbol in config.symbols:
                    for timeframe in config.timeframes:
                        try:
                            signal = strategy.generate_signal(self.exchange, symbol, timeframe)
                            
                            if signal and not strategy.is_duplicate_signal(signal):
                                logger.info(strategy.get_signal_description(signal))
                                self._on_signal(config, signal, strategy)
                                
                        except Exception as e:
                            logger.error(f"扫描信号失败 {symbol} {timeframe}: {e}")
                
                # 清理过期记忆
                strategy.clear_old_memory()
    
    def start(self, interval: int = 60):
        """
        启动策略扫描循环
        
        Args:
            interval: 扫描间隔（秒）
        """
        if self._running:
            logger.warning("策略管理器已在运行")
            return
        
        self._running = True
        
        def run_loop():
            while self._running:
                try:
                    self.scan_once()
                except Exception as e:
                    logger.error(f"扫描循环出错: {e}")
                
                time.sleep(interval)
        
        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()
        
        logger.info(f"策略管理器已启动，扫描间隔: {interval}秒")
    
    def stop(self):
        """停止策略扫描"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("策略管理器已停止")
    
    def get_status(self) -> Dict:
        """获取策略管理器状态"""
        return {
            'running': self._running,
            'strategies': {
                name: {
                    'status': self.status[name].value,
                    'config': {
                        'type': self.configs[name].strategy_type,
                        'symbols': self.configs[name].symbols,
                        'timeframes': self.configs[name].timeframes,
                        'enabled': self.configs[name].enabled
                    }
                }
                for name in self.strategies
            },
            'recent_signals': self.signal_history[-20:]
        }
    
    def get_signals(self, limit: int = 50) -> List[Dict]:
        """获取最近信号 - 从文件和内存合并读取"""
        signals = []
        
        # 1. 从signals_history文件读取（用于前端显示）
        try:
            log_file = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'signals_history.jsonl')
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    for line in lines[-limit:]:
                        try:
                            record = json.loads(line.strip())
                            signals.append({
                                'timestamp': record.get('timestamp', ''),
                                'symbol': record.get('symbol', ''),
                                'timeframe': record.get('timeframe', ''),
                                'action': record.get('action', ''),
                                'price': record.get('price', 0),
                                'rsi': record.get('rsi', 0),
                                'executed': record.get('executed', False),
                                'strategy': record.get('strategy', 'MA99_MTF')
                            })
                        except:
                            continue
        except Exception as e:
            logger.error(f"从文件读取信号失败: {e}")
        
        # 2. 合并内存中的信号（去重）
        existing_keys = {(s.get('timestamp'), s.get('symbol'), s.get('action')) for s in signals}
        for s in self.signal_history:
            key = (s.get('timestamp'), s.get('symbol'), s.get('action'))
            if key not in existing_keys:
                signals.append({
                    'timestamp': s.get('timestamp', ''),
                    'symbol': s.get('symbol', ''),
                    'timeframe': s.get('timeframe', ''),
                    'action': s.get('action', ''),
                    'price': s.get('price', 0),
                    'rsi': s.get('rsi', 0),
                    'executed': s.get('executed', False),
                    'strategy': s.get('strategy', 'MA99_MTF')
                })
        
        # 按时间排序，返回最新的
        signals = sorted(signals, key=lambda x: x.get('timestamp', ''), reverse=True)
        return signals[:limit]


# 全局实例
_strategy_manager = None


def get_strategy_manager(exchange=None, risk_manager=None, order_executor=None):
    """获取策略管理器单例"""
    global _strategy_manager
    if _strategy_manager is None:
        if exchange is None or risk_manager is None or order_executor is None:
            raise ValueError("首次初始化需要提供exchange, risk_manager, order_executor")
        _strategy_manager = StrategyManager(exchange, risk_manager, order_executor)
    return _strategy_manager
