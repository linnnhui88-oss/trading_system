"""
策略引擎适配器 - 将 strategy_engine.py 集成到Web系统
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import threading
import time
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json

# 导入原策略引擎
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'strategy'))
from strategy_engine import (
    SYMBOLS, TIMEFRAMES, check_ma99_strategy, verify_htf_alignment,
    get_ai_analysis, send_telegram_alert, load_memory, save_memory
)

# 导入策略日志记录器
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))
from StrategyLogger import StrategyLogger
from trading_core.strategy_config_repository import StrategyConfigRepository
from trading_core.llm_service import LLMService

logger = logging.getLogger(__name__)

# 策略配置文件路径
STRATEGY_CONFIG_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'strategy_config.json')

def load_strategy_config():
    """加载策略配置"""
    default_config = {
        'mode': 'single',
        'singleStrategy': 'MA99_MTF',
        'consensusStrategies': ['MA99_MTF'],
        'consensusThreshold': 0.66
    }
    
    try:
        if os.path.exists(STRATEGY_CONFIG_FILE):
            with open(STRATEGY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return {**default_config, **config}
    except Exception as e:
        logger.error(f"加载策略配置失败: {e}")
    
    return default_config


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
    strategy_type: str
    symbols: List[str]
    timeframes: List[str]
    enabled: bool = True
    params: Dict = field(default_factory=dict)
    max_positions: int = 1
    position_size_usdt: float = 100.0


class StrategyEngineAdapter:
    """
    策略引擎适配器 - 包装 strategy_engine.py 使其兼容Web系统
    """
    
    def __init__(self, exchange, risk_manager, order_executor):
        """
        初始化适配器
        
        Args:
            exchange: ExchangeClient实例
            risk_manager: RiskManager实例
            order_executor: OrderExecutor实例
        """
        self.exchange = exchange
        self.risk_manager = risk_manager
        self.order_executor = order_executor
        
        # 策略状态
        self.strategies: Dict[str, StrategyConfig] = {}
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
        
        # 信号记忆（从文件加载）
        self.signal_memory = load_memory()
        
        # 策略日志记录器
        self.strategy_logger = StrategyLogger("MA99_MTF")
        self.strategy_repo = StrategyConfigRepository()
        self.llm_service = LLMService()
        
        # 注册默认MA99策略
        self._register_default_strategy()
        
        logger.info("✅ 策略引擎适配器初始化完成 - 使用原始MA99策略核心")
    
    def _register_default_strategy(self):
        """注册默认MA99策略"""
        config = StrategyConfig(
            name='MA99_MTF',
            strategy_type='ma99_mtf',
            symbols=SYMBOLS,
            timeframes=TIMEFRAMES,
            enabled=True,
            params={},
            max_positions=1,
            position_size_usdt=float(os.getenv('MAX_POSITION_USDT', 50))
        )
        self.strategies[config.name] = config
        self.status[config.name] = StrategyStatus.STOPPED
        logger.info(f"✅ MA99_MTF策略已注册 - 使用 strategy_engine.py 核心代码")

    def _get_runtime_scan_targets(self) -> List[Dict]:
        """Get runtime scan targets from strategy configs."""
        try:
            configs = self.strategy_repo.list_strategy_configs(status='running')
            targets = []
            for cfg in configs:
                symbol = (cfg.get('symbol') or '').strip().upper()
                interval = (cfg.get('interval') or '5m').strip()
                if not symbol:
                    continue
                if interval not in TIMEFRAMES:
                    interval = '5m'
                merged = dict(cfg)
                merged['symbol'] = symbol
                merged['interval'] = interval
                targets.append(merged)
            return targets
        except Exception as e:
            logger.warning(f"Load runtime strategy configs failed: {e}")
            return []
    
    def register_strategy(self, config: StrategyConfig) -> bool:
        """注册策略"""
        try:
            with self._lock:
                self.strategies[config.name] = config
                self.status[config.name] = StrategyStatus.STOPPED
                logger.info(f"策略 '{config.name}' 注册成功")
                return True
        except Exception as e:
            logger.error(f"注册策略失败: {e}")
            return False
    
    def start_strategy(self, name: str) -> bool:
        """启动指定策略"""
        with self._lock:
            if name not in self.strategies:
                logger.error(f"策略 '{name}' 不存在")
                return False
            
            config = self.strategies[name]
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
    
    def start_all(self):
        """启动所有策略"""
        for name in self.strategies:
            self.start_strategy(name)
    
    def stop_all(self):
        """停止所有策略"""
        for name in self.strategies:
            self.stop_strategy(name)
    
    def add_signal_callback(self, callback: Callable):
        """添加信号回调"""
        self.signal_callbacks.append(callback)
    
    def scan_once(self):
        """执行一次扫描 - 根据配置使用单策略或多策略共识模式"""
        # 加载策略配置
        strategy_config = load_strategy_config()
        mode = strategy_config.get('mode', 'single')
        
        # 广播扫描开始
        self._broadcast_scan_start()
        
        with self._lock:
            if mode == 'single':
                # 单策略模式
                self._scan_single_strategy(strategy_config)
            else:
                # 多策略共识模式
                self._scan_consensus_strategy(strategy_config)
        
        # 广播扫描完成
        self._broadcast_scan_complete()
    
    def _broadcast_scan_start(self):
        """广播扫描开始"""
        try:
            from flask_socketio import emit
            from web_admin.app import socketio
            socketio.emit('strategy_scan_start', {
                'timestamp': datetime.now().isoformat(),
                'symbols': SYMBOLS,
                'timeframes': TIMEFRAMES
            })
        except Exception as e:
            logger.debug(f'广播扫描开始失败: {e}')
    
    def _broadcast_scan_complete(self):
        """广播扫描完成"""
        try:
            from flask_socketio import emit
            from web_admin.app import socketio
            socketio.emit('strategy_scan_complete', {
                'timestamp': datetime.now().isoformat(),
                'next_scan': (datetime.now().timestamp() + 60) * 1000  # 下次扫描时间戳
            })
        except Exception as e:
            logger.debug(f'广播扫描完成失败: {e}')
    
    def _scan_single_strategy(self, strategy_config):
        """???????????????????????"""
        runtime_targets = self._get_runtime_scan_targets()

        # ????????????????????
        if not runtime_targets:
            single_strategy = strategy_config.get('singleStrategy', 'MA99_MTF')
            runtime_targets = []
            for symbol in SYMBOLS:
                for timeframe in TIMEFRAMES:
                    runtime_targets.append({
                        'strategy_key': single_strategy,
                        'strategy_name': single_strategy,
                        'symbol': symbol,
                        'interval': timeframe,
                        'ai_enabled': True,
                        'ai_model': '',
                        'telegram_notify': True,
                        'auto_trade_follow_global': True,
                    })

        for target in runtime_targets:
            symbol = target.get('symbol', '')
            timeframe = target.get('interval', '5m')
            strategy_name = target.get('strategy_name') or target.get('strategy_key') or 'MA99_MTF'
            trace_id = None
            try:
                if strategy_name != 'MA99_MTF':
                    continue

                trace_id = self.strategy_logger.log_scanned(
                    symbol=symbol,
                    timeframe=timeframe,
                    indicators={},
                    current_price=0
                )

                signal, last_bar, rsi = check_ma99_strategy(symbol, timeframe)

                if not signal or last_bar is None:
                    self.strategy_logger.log_skipped(
                        trace_id=trace_id,
                        symbol=symbol,
                        reason="NoSignal",
                        details={"timeframe": timeframe}
                    )
                    continue

                current_price = last_bar['close']

                if not verify_htf_alignment(symbol, timeframe, signal):
                    self.strategy_logger.log_skipped(
                        trace_id=trace_id,
                        symbol=symbol,
                        reason="HTF_Misalignment",
                        details={"signal": signal, "price": current_price}
                    )
                    continue

                memory_key = f"{symbol}_{timeframe}_{signal}"
                current_bar_time = last_bar['timestamp']

                if self.signal_memory.get(memory_key) == current_bar_time:
                    self.strategy_logger.log_skipped(
                        trace_id=trace_id,
                        symbol=symbol,
                        reason="DuplicateSignal",
                        details={"signal": signal, "bar_time": current_bar_time}
                    )
                    continue

                self.signal_memory[memory_key] = current_bar_time
                save_memory(self.signal_memory)

                logger.info(f"?? [{strategy_name}] ?????{symbol} ({timeframe}) -> {signal}??? {last_bar['close']}")

                config = self.strategies.get('MA99_MTF')
                if config:
                    self._on_signal(config, symbol, timeframe, signal, last_bar, rsi, trace_id, runtime_cfg=target)

            except Exception as e:
                logger.error(f"?????? {symbol} {timeframe}: {e}")
                if trace_id:
                    self.strategy_logger.log_system_error(
                        component="StrategyEngine",
                        error_msg=str(e)
                    )

    def _scan_consensus_strategy(self, strategy_config):
        """多策略共识扫描"""
        consensus_strategies = strategy_config.get('consensusStrategies', ['MA99_MTF'])
        threshold = strategy_config.get('consensusThreshold', 0.66)
        
        for symbol in SYMBOLS:
            for timeframe in TIMEFRAMES:
                try:
                    # 收集各策略信号
                    strategy_signals = {}
                    
                    # MA99策略
                    if 'MA99_MTF' in consensus_strategies:
                        signal, last_bar, rsi = check_ma99_strategy(symbol, timeframe)
                        if signal and last_bar is not None:
                            # 大周期审查
                            if verify_htf_alignment(symbol, timeframe, signal):
                                strategy_signals['MA99_MTF'] = {
                                    'signal': signal,
                                    'last_bar': last_bar,
                                    'rsi': rsi
                                }
                    
                    # TODO: 添加其他策略的信号检测
                    # if 'MACD' in consensus_strategies: ...
                    # if 'RSI' in consensus_strategies: ...
                    
                    # 检查是否达到共识阈值
                    if len(strategy_signals) > 0:
                        total = len(consensus_strategies)
                        agreeing = len(strategy_signals)
                        consensus_ratio = agreeing / total
                        
                        # 检查信号方向是否一致
                        signals_list = list(strategy_signals.values())
                        first_signal = signals_list[0]['signal']
                        all_same_direction = all(s['signal'] == first_signal for s in signals_list)
                        
                        if consensus_ratio >= threshold and all_same_direction and len(signals_list) >= 2:
                            # 达到共识，执行信号
                            first_data = signals_list[0]
                            signal = first_signal
                            last_bar = first_data['last_bar']
                            rsi = first_data['rsi']
                            
                            # 检查重复信号
                            memory_key = f"CONSENSUS_{symbol}_{timeframe}_{signal}"
                            current_bar_time = last_bar['timestamp']
                            
                            if self.signal_memory.get(memory_key) == current_bar_time:
                                continue
                            
                            # 记录信号
                            self.signal_memory[memory_key] = current_bar_time
                            save_memory(self.signal_memory)
                            
                            logger.info(f"🎯 [共识模式] 信号确认！{symbol} ({timeframe}) -> {signal} "
                                      f"({agreeing}/{total} 策略同意，{consensus_ratio:.0%})，现价 {last_bar['close']}")
                            
                            # 处理信号
                            config = self.strategies.get('MA99_MTF')
                            if config:
                                self._on_signal(config, symbol, timeframe, signal, last_bar, rsi)
                        
                except Exception as e:
                    logger.error(f"共识扫描失败 {symbol} {timeframe}: {e}")
    
    
    def _on_signal(self, config: StrategyConfig, symbol: str, timeframe: str,
                   action: str, last_bar: Dict, rsi: float, trace_id: str = None, runtime_cfg: Dict = None):
        """????"""
        runtime_cfg = runtime_cfg or {}
        ai_enabled = bool(runtime_cfg.get('ai_enabled', True))
        ai_model = (runtime_cfg.get('ai_model') or '').strip()
        telegram_notify = bool(runtime_cfg.get('telegram_notify', True))
        auto_trade_follow_global = bool(runtime_cfg.get('auto_trade_follow_global', True))
        strategy_name = runtime_cfg.get('strategy_name') or config.name

        # ??????????K?????
        try:
            ticker = self.exchange.get_ticker(symbol)
            price = ticker['last'] if ticker else last_bar['close']
        except Exception as e:
            logger.warning(f"???????????K????: {e}")
            price = last_bar['close']

        # AI ???????????
        ai_advice = get_ai_analysis(symbol, timeframe, action, price, rsi)
        ai_confidence = 0.5
        ai_decision = "EXECUTE"

        if ai_enabled and ai_model:
            try:
                llm_payload = {
                    'symbol': symbol.replace('/', '').upper(),
                    'interval': timeframe,
                    'signal': 'BUY' if action == 'LONG' else 'SELL',
                    'strategy_name': strategy_name,
                    'price': price,
                    'indicators': {'rsi': rsi},
                    'risk_context': {'global_auto_trading': bool(self.order_executor.auto_trading)}
                }
                llm_result = self.llm_service.analyze_trade(ai_model, llm_payload)
                if llm_result.get('success'):
                    ai_confidence = float(llm_result.get('confidence', ai_confidence) or ai_confidence)
                    ai_decision = str(llm_result.get('decision', 'SKIP')).upper()
                    ai_reason = llm_result.get('reason', '')
                    ai_advice = f"[{ai_model}] {ai_decision}: {ai_reason}"
                else:
                    ai_decision = 'SKIP'
                    ai_advice = f"[{ai_model}] SKIP: {llm_result.get('reason', 'LLM unavailable')}"
            except Exception as e:
                ai_decision = 'SKIP'
                ai_advice = f"[{ai_model}] SKIP: AI call failed ({e})"

        if ai_advice:
            logger.info(f"?? AI??: {ai_advice[:120]}")

        # ??AI????
        if trace_id:
            self.strategy_logger.log_ai_decision(
                trace_id=trace_id,
                symbol=symbol,
                action=action,
                confidence_score=ai_confidence,
                prompt_tokens=0
            )

        # ????????????????
        executed = False
        api_latency = 0
        should_execute_by_ai = ai_decision in {'EXECUTE', 'REDUCE'}
        can_execute = self.order_executor.auto_trading if auto_trade_follow_global else True

        if can_execute and should_execute_by_ai:
            start_time = time.time()
            executed = self.order_executor.execute_signal(
                symbol=symbol,
                timeframe=timeframe,
                action=action,
                price=price,
                rsi=rsi,
                confidence=ai_confidence,
                strategy=strategy_name,
                ai_model=ai_model,
                ai_decision=ai_decision,
                signal_source='strategy_signal',
                signal_reason=ai_advice
            )
            api_latency = int((time.time() - start_time) * 1000)

        # ??????????????
        if executed and trace_id:
            try:
                positions = self.exchange.get_positions()
                position = next((p for p in positions if p['symbol'] == symbol), None)
                if position:
                    self.strategy_logger.log_position_open(
                        trace_id=trace_id,
                        symbol=symbol,
                        side=action,
                        entry_price=price,
                        size=position.get('size', 0),
                        leverage=position.get('leverage', config.params.get('leverage', 3)),
                        api_latency_ms=api_latency
                    )
            except Exception as e:
                logger.error(f"????????: {e}")
        elif not executed and trace_id:
            if not should_execute_by_ai:
                skip_reason = "AIRejected"
            elif not can_execute and auto_trade_follow_global:
                skip_reason = "GlobalAutoTradingOff"
            else:
                skip_reason = "ExecutionFailed"
            self.strategy_logger.log_skipped(
                trace_id=trace_id,
                symbol=symbol,
                reason=skip_reason,
                details={"action": action, "price": price, "ai_decision": ai_decision}
            )

        # ??Telegram???????????????
        if telegram_notify:
            send_telegram_alert(symbol, timeframe, action, price, rsi, ai_advice, executed)

        signal_record = {
            'timestamp': datetime.now().isoformat(),
            'strategy': strategy_name,
            'symbol': symbol,
            'timeframe': timeframe,
            'action': action,
            'price': price,
            'rsi': rsi,
            'executed': executed,
            'ai_advice': ai_advice,
            'ai_model': ai_model,
            'ai_decision': ai_decision,
            'auto_trade_follow_global': auto_trade_follow_global,
            'global_auto_trading': bool(self.order_executor.auto_trading),
            'can_execute': can_execute
        }
        
        self.signal_history.append(signal_record)
        if len(self.signal_history) > self.max_history:
            self.signal_history = self.signal_history[-self.max_history:]
        
        # 保存到文件
        self._save_signal_to_file(signal_record)
        
        # 调用回调
        for callback in self.signal_callbacks:
            try:
                callback(config, signal_record)
            except Exception as e:
                logger.error(f"信号回调执行失败: {e}")
    
    def _save_signal_to_file(self, signal_record: Dict):
        """保存信号到文件"""
        try:
            # 使用项目根目录下的data文件夹
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            log_file = os.path.join(project_root, 'data', 'signals_history.jsonl')
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(signal_record, ensure_ascii=False) + '\n')
            logger.info(f"✅ 信号已保存: {signal_record.get('symbol')} @ ${signal_record.get('price')}")
        except Exception as e:
            logger.error(f"❌ 保存信号历史失败: {e}")
    
    def start(self, interval: int = 60):
        """启动策略扫描循环"""
        with self._lock:
            if self._running:
                logger.warning("策略引擎已在运行")
                return True
            
            self._running = True
            
            def run_loop():
                logger.info(f"🚀 MA99策略引擎已启动，扫描间隔: {interval}秒")
                while self._running:
                    try:
                        self.scan_once()
                    except Exception as e:
                        logger.error(f"扫描循环出错: {e}")
                    
                    time.sleep(interval)
                logger.info("🛑 策略扫描循环已停止")
            
            self._thread = threading.Thread(target=run_loop, daemon=True)
            self._thread.start()
            
            logger.info("✅ 策略扫描线程已启动")
            return True
    
    def stop(self):
        """停止策略扫描"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("✅ 策略引擎已停止")
    
    def get_status(self) -> Dict:
        """获取策略状态"""
        return {
            'running': self._running,
            'strategies': {
                name: {
                    'status': self.status[name].value,
                    'config': {
                        'type': self.strategies[name].strategy_type,
                        'symbols': self.strategies[name].symbols,
                        'timeframes': self.strategies[name].timeframes,
                        'enabled': self.strategies[name].enabled
                    }
                }
                for name in self.strategies
            },
            'recent_signals': self.signal_history[-20:]
        }
    
    def get_signals(self, limit: int = 50) -> List[Dict]:
        """获取最近信号"""
        signals = []
        
        # 从文件读取
        try:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            log_file = os.path.join(project_root, 'data', 'signals_history.jsonl')
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
        
        # 合并内存中的信号
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
        
        # 按时间排序
        signals = sorted(signals, key=lambda x: x.get('timestamp', ''), reverse=True)
        return signals[:limit]
    
    def get_signal_stats(self, days: int = 7) -> Dict:
        """获取信号统计"""
        try:
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


# 全局实例
_strategy_engine_adapter = None


def get_strategy_manager(exchange=None, risk_manager=None, order_executor=None):
    """获取策略管理器单例"""
    global _strategy_engine_adapter
    if _strategy_engine_adapter is None:
        if exchange is None or risk_manager is None or order_executor is None:
            raise ValueError("首次初始化需要提供exchange, risk_manager, order_executor")
        _strategy_engine_adapter = StrategyEngineAdapter(exchange, risk_manager, order_executor)
    return _strategy_engine_adapter
