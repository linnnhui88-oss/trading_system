from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from dataclasses import dataclass
from enum import Enum

class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

@dataclass
class Signal:
    """交易信号"""
    symbol: str
    timeframe: str
    signal_type: SignalType
    price: float
    confidence: float = 1.0
    metadata: Dict = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

class BaseStrategy(ABC):
    """策略基类"""
    
    def __init__(self, name: str, params: Dict = None):
        self.name = name
        self.params = params or {}
        self.enabled = True
    
    @abstractmethod
    def analyze(self, df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Signal]:
        """
        分析市场数据并生成信号
        
        Args:
            df: OHLCV数据DataFrame
            symbol: 交易对
            timeframe: 时间周期
            
        Returns:
            Signal对象或None
        """
        pass
    
    def get_required_data(self) -> int:
        """返回所需的最小数据条数"""
        return 100
    
    def set_params(self, params: Dict):
        """设置策略参数"""
        self.params.update(params)
    
    def enable(self):
        """启用策略"""
        self.enabled = True
    
    def disable(self):
        """禁用策略"""
        self.enabled = False

class MACDStrategy(BaseStrategy):
    """MACD策略"""
    
    def __init__(self, params: Dict = None):
        default_params = {
            'fast': 12,
            'slow': 26,
            'signal': 9,
            'threshold': 0.0
        }
        if params:
            default_params.update(params)
        super().__init__('MACD', default_params)
    
    def analyze(self, df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Signal]:
        if len(df) < self.get_required_data():
            return None
        
        fast = self.params['fast']
        slow = self.params['slow']
        signal_period = self.params['signal']
        
        # 计算MACD
        exp1 = df['close'].ewm(span=fast, adjust=False).mean()
        exp2 = df['close'].ewm(span=slow, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=signal_period, adjust=False).mean()
        histogram = macd - signal
        
        current_macd = macd.iloc[-1]
        current_signal = signal.iloc[-1]
        prev_macd = macd.iloc[-2]
        prev_signal = signal.iloc[-2]
        
        # MACD金叉
        if prev_macd < prev_signal and current_macd > current_signal:
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                signal_type=SignalType.BUY,
                price=df['close'].iloc[-1],
                confidence=abs(current_macd - current_signal) / abs(current_signal) if current_signal != 0 else 0.5,
                metadata={'macd': current_macd, 'signal': current_signal}
            )
        
        # MACD死叉
        if prev_macd > prev_signal and current_macd < current_signal:
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                signal_type=SignalType.SELL,
                price=df['close'].iloc[-1],
                confidence=abs(current_macd - current_signal) / abs(current_signal) if current_signal != 0 else 0.5,
                metadata={'macd': current_macd, 'signal': current_signal}
            )
        
        return None
    
    def get_required_data(self) -> int:
        return max(self.params['slow'], self.params['signal']) + 10

class RSIStrategy(BaseStrategy):
    """RSI策略"""
    
    def __init__(self, params: Dict = None):
        default_params = {
            'period': 14,
            'overbought': 70,
            'oversold': 30
        }
        if params:
            default_params.update(params)
        super().__init__('RSI', default_params)
    
    def analyze(self, df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Signal]:
        if len(df) < self.get_required_data():
            return None
        
        period = self.params['period']
        overbought = self.params['overbought']
        oversold = self.params['oversold']
        
        # 计算RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        current_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-2]
        
        # RSI从超卖区回升
        if prev_rsi < oversold and current_rsi >= oversold:
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                signal_type=SignalType.BUY,
                price=df['close'].iloc[-1],
                confidence=(oversold - current_rsi) / oversold if current_rsi < oversold else 0.5,
                metadata={'rsi': current_rsi}
            )
        
        # RSI从超买区回落
        if prev_rsi > overbought and current_rsi <= overbought:
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                signal_type=SignalType.SELL,
                price=df['close'].iloc[-1],
                confidence=(current_rsi - overbought) / (100 - overbought) if current_rsi > overbought else 0.5,
                metadata={'rsi': current_rsi}
            )
        
        return None
    
    def get_required_data(self) -> int:
        return self.params['period'] + 10

class BollingerBandsStrategy(BaseStrategy):
    """布林带策略"""
    
    def __init__(self, params: Dict = None):
        default_params = {
            'period': 20,
            'std_dev': 2.0
        }
        if params:
            default_params.update(params)
        super().__init__('BollingerBands', default_params)
    
    def analyze(self, df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Signal]:
        if len(df) < self.get_required_data():
            return None
        
        period = self.params['period']
        std_dev = self.params['std_dev']
        
        # 计算布林带
        sma = df['close'].rolling(window=period).mean()
        std = df['close'].rolling(window=period).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        
        current_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        current_lower = lower.iloc[-1]
        current_upper = upper.iloc[-1]
        
        # 价格触及下轨反弹
        if prev_close <= current_lower and current_close > current_lower:
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                signal_type=SignalType.BUY,
                price=current_close,
                confidence=0.7,
                metadata={'bb_lower': current_lower, 'bb_upper': current_upper}
            )
        
        # 价格触及上轨回落
        if prev_close >= current_upper and current_close < current_upper:
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                signal_type=SignalType.SELL,
                price=current_close,
                confidence=0.7,
                metadata={'bb_lower': current_lower, 'bb_upper': current_upper}
            )
        
        return None
    
    def get_required_data(self) -> int:
        return self.params['period'] + 10

class MA99Strategy(BaseStrategy):
    """MA99多周期共振策略"""
    
    def __init__(self, params: Dict = None):
        default_params = {
            'ma_length': 99,
            'ma_short': 25,
            'lookback': 15,
            'rsi_long_min': 40,
            'rsi_long_max': 65,
            'rsi_short_min': 35,
            'rsi_short_max': 60
        }
        if params:
            default_params.update(params)
        super().__init__('MA99_MTF', default_params)
    
    def analyze(self, df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Signal]:
        if len(df) < self.get_required_data():
            return None
        
        ma_length = self.params['ma_length']
        ma_short = self.params['ma_short']
        
        # 计算指标
        df['MA25'] = df['close'].rolling(window=ma_short).mean()
        df['MA99'] = df['close'].rolling(window=ma_length).mean()
        
        # 计算ATR
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(14).mean()
        
        # 计算RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        current = df.iloc[-1]
        
        # 多头信号
        is_bull_trend = current['MA25'] > current['MA99']
        long_pullback = (current['low'] <= current['MA99'] + (0.5 * current['ATR'])) and (current['close'] > current['MA99'])
        long_rsi_ok = self.params['rsi_long_min'] < current['RSI'] < self.params['rsi_long_max']
        
        if is_bull_trend and long_pullback and long_rsi_ok:
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                signal_type=SignalType.BUY,
                price=current['close'],
                confidence=0.85,
                metadata={
                    'ma99': current['MA99'],
                    'ma25': current['MA25'],
                    'rsi': current['RSI'],
                    'atr': current['ATR']
                }
            )
        
        # 空头信号
        is_bear_trend = current['MA25'] < current['MA99']
        short_pullback = (current['high'] >= current['MA99'] - (0.5 * current['ATR'])) and (current['close'] < current['MA99'])
        short_rsi_ok = self.params['rsi_short_min'] < current['RSI'] < self.params['rsi_short_max']
        
        if is_bear_trend and short_pullback and short_rsi_ok:
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                signal_type=SignalType.SELL,
                price=current['close'],
                confidence=0.85,
                metadata={
                    'ma99': current['MA99'],
                    'ma25': current['MA25'],
                    'rsi': current['RSI'],
                    'atr': current['ATR']
                }
            )
        
        return None
    
    def get_required_data(self) -> int:
        return max(self.params['ma_length'], 100) + 20

class StrategyManager:
    """策略管理器"""
    
    def __init__(self):
        self.strategies: Dict[str, BaseStrategy] = {}
        self._register_default_strategies()
    
    def _register_default_strategies(self):
        """注册默认策略"""
        self.register_strategy(MACDStrategy())
        self.register_strategy(RSIStrategy())
        self.register_strategy(BollingerBandsStrategy())
        self.register_strategy(MA99Strategy())
    
    def register_strategy(self, strategy: BaseStrategy):
        """注册策略"""
        self.strategies[strategy.name] = strategy
    
    def unregister_strategy(self, name: str):
        """注销策略"""
        if name in self.strategies:
            del self.strategies[name]
    
    def get_strategy(self, name: str) -> Optional[BaseStrategy]:
        """获取策略"""
        return self.strategies.get(name)
    
    def get_all_strategies(self) -> List[BaseStrategy]:
        """获取所有策略"""
        return list(self.strategies.values())
    
    def get_enabled_strategies(self) -> List[BaseStrategy]:
        """获取启用的策略"""
        return [s for s in self.strategies.values() if s.enabled]
    
    def analyze_all(self, df: pd.DataFrame, symbol: str, timeframe: str) -> List[Signal]:
        """使用所有启用的策略分析"""
        signals = []
        for strategy in self.get_enabled_strategies():
            try:
                signal = strategy.analyze(df, symbol, timeframe)
                if signal:
                    signals.append(signal)
            except Exception as e:
                print(f"策略 {strategy.name} 分析失败: {e}")
        return signals
    
    def get_consensus_signal(self, df: pd.DataFrame, symbol: str, 
                            timeframe: str, threshold: float = 0.5) -> Optional[Signal]:
        """
        获取共识信号（多策略投票）
        
        Args:
            threshold: 共识阈值，超过此比例的策略同意才产生信号
        """
        signals = self.analyze_all(df, symbol, timeframe)
        if not signals:
            return None
        
        buy_count = sum(1 for s in signals if s.signal_type == SignalType.BUY)
        sell_count = sum(1 for s in signals if s.signal_type == SignalType.SELL)
        total = len(self.get_enabled_strategies())
        
        if buy_count / total >= threshold:
            # 计算平均买入信号
            buy_signals = [s for s in signals if s.signal_type == SignalType.BUY]
            avg_price = sum(s.price for s in buy_signals) / len(buy_signals)
            avg_confidence = sum(s.confidence for s in buy_signals) / len(buy_signals)
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                signal_type=SignalType.BUY,
                price=avg_price,
                confidence=avg_confidence,
                metadata={'consensus': buy_count / total, 'strategies': [s.metadata for s in buy_signals]}
            )
        
        if sell_count / total >= threshold:
            sell_signals = [s for s in signals if s.signal_type == SignalType.SELL]
            avg_price = sum(s.price for s in sell_signals) / len(sell_signals)
            avg_confidence = sum(s.confidence for s in sell_signals) / len(sell_signals)
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                signal_type=SignalType.SELL,
                price=avg_price,
                confidence=avg_confidence,
                metadata={'consensus': sell_count / total, 'strategies': [s.metadata for s in sell_signals]}
            )
        
        return None

# 单例模式
_strategy_manager = None

def get_strategy_manager() -> StrategyManager:
    """获取策略管理器实例"""
    global _strategy_manager
    if _strategy_manager is None:
        _strategy_manager = StrategyManager()
    return _strategy_manager
