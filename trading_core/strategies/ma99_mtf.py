"""
MA99 MTF 多周期共振策略
基于MA99趋势过滤 + 多时间框架共振 + RSI过滤 + AI决策 + Telegram提醒
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import logging
import os
import requests

logger = logging.getLogger(__name__)

# 尝试导入Gemini
try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("Google Gemini SDK 未安装，AI分析功能将不可用")


@dataclass
class Signal:
    """交易信号"""
    symbol: str
    timeframe: str
    action: str  # 'LONG' or 'SHORT'
    price: float
    rsi: float
    ma99: float
    atr: float
    timestamp: datetime
    htf_aligned: bool  # 大周期是否共振
    confidence: float  # 信号置信度 0-1


class MA99MTFStrategy:
    """
    MA99多周期共振策略
    
    核心逻辑：
    1. MA99趋势过滤 - 只做大趋势方向
    2. MTF多周期共振 - 小周期信号需大周期确认
    3. RSI过滤 - 避免超买超卖区域入场
    4. 回调入场 - 价格回踩MA99附近入场
    5. AI决策分析
    6. Telegram实时提醒
    """
    
    def __init__(self, 
                 ma_length: int = 99,
                 ma_short: int = 25,
                 rsi_period: int = 14,
                 rsi_long_range: Tuple[float, float] = (40, 65),
                 rsi_short_range: Tuple[float, float] = (35, 60),
                 atr_multiplier: float = 0.5,
                 min_bars: int = 150,
                 enable_ai: bool = True,
                 enable_telegram: bool = True):
        """
        初始化策略参数
        
        Args:
            ma_length: MA均线周期，默认99
            ma_short: 短期MA周期，默认25
            rsi_period: RSI周期
            rsi_long_range: 做多时RSI允许范围
            rsi_short_range: 做空时RSI允许范围
            atr_multiplier: ATR倍数，用于判断回调幅度
            min_bars: 最小K线数量要求
        """
        self.ma_length = ma_length
        self.ma_short = ma_short
        self.rsi_period = rsi_period
        self.rsi_long_range = rsi_long_range
        self.rsi_short_range = rsi_short_range
        self.atr_multiplier = atr_multiplier
        self.min_bars = min_bars
        self.enable_ai = enable_ai
        self.enable_telegram = enable_telegram
        
        # 大周期映射表
        self.htf_map = {
            '15m': ['1h', '4h'],
            '1h': ['4h'],
            '4h': ['1d'],
            '1d': []
        }
        
        # 信号记忆（防止重复信号）
        self.signal_memory = {}
        
        # AI客户端
        self.ai_client = None
        if self.enable_ai and GEMINI_AVAILABLE:
            api_key = os.getenv('GEMINI_API_KEY')
            if api_key and api_key != '你的GEMINI_API_KEY':
                try:
                    self.ai_client = genai.Client(api_key=api_key)
                    logger.info("✅ AI分析功能已启用")
                except Exception as e:
                    logger.error(f"AI客户端初始化失败: {e}")
            else:
                logger.warning("⚠️ GEMINI_API_KEY 未设置，AI分析功能已禁用")
        
        # Telegram配置
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        if self.enable_telegram and (not self.telegram_token or self.telegram_token == '你的TELEGRAM_BOT_TOKEN'):
            logger.warning("⚠️ Telegram配置未设置，消息推送已禁用")
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        df = df.copy()
        
        # MA均线
        df['MA99'] = df['close'].rolling(window=self.ma_length).mean()
        df['MA25'] = df['close'].rolling(window=self.ma_short).mean()
        
        # ATR
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(14).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0).ewm(alpha=1/self.rsi_period, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/self.rsi_period, adjust=False).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        return df
    
    def check_htf_alignment(self, 
                           exchange, 
                           symbol: str, 
                           timeframe: str, 
                           action: str) -> Tuple[bool, List[str]]:
        """
        检查大周期共振
        
        Returns:
            (是否共振, 检查过的大周期列表)
        """
        htfs = self.htf_map.get(timeframe, [])
        if not htfs:
            return True, []
        
        checked_htfs = []
        
        for htf in htfs:
            try:
                # 获取大周期数据
                bars = exchange.get_ohlcv(symbol, timeframe=htf, limit=120)
                if not bars or len(bars) < self.ma_length:
                    logger.warning(f"{symbol} {htf} 数据不足")
                    return False, checked_htfs
                
                df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df = df.iloc[:-1]  # 抛弃未走完的K线
                df['MA99'] = df['close'].rolling(window=self.ma_length).mean()
                
                current_htf_close = df.iloc[-1]['close']
                current_htf_ma99 = df.iloc[-1]['MA99']
                
                checked_htfs.append(f"{htf}(close={current_htf_close:.2f}, ma99={current_htf_ma99:.2f})")
                
                # 一票否决制
                if action == "LONG" and current_htf_close < current_htf_ma99:
                    logger.info(f"🚫 拦截伪信号: {symbol} {timeframe} 做多，但大周期 {htf} 为空头趋势")
                    return False, checked_htfs
                
                if action == "SHORT" and current_htf_close > current_htf_ma99:
                    logger.info(f"🚫 拦截伪信号: {symbol} {timeframe} 做空，但大周期 {htf} 为多头趋势")
                    return False, checked_htfs
                
            except Exception as e:
                logger.error(f"大周期 {htf} 获取异常: {e}")
                return False, checked_htfs
        
        return True, checked_htfs
    
    def generate_signal(self, 
                       exchange,
                       symbol: str, 
                       timeframe: str) -> Optional[Signal]:
        """
        生成交易信号
        
        Args:
            exchange: CCXT交易所实例
            symbol: 交易对，如 'BTC/USDT'
            timeframe: 时间周期，如 '1h'
            
        Returns:
            Signal对象或None
        """
        try:
            # 获取K线数据
            bars = exchange.get_ohlcv(symbol, timeframe=timeframe, limit=200)
            if not bars or len(bars) < self.min_bars:
                return None
            
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df = df.iloc[:-1].copy()  # 抛弃未走完的K线
            
            # 计算指标
            df = self.calculate_indicators(df)
            
            current = df.iloc[-1]
            
            # 检查做多条件
            is_bull_trend = current['MA25'] > current['MA99']
            long_pullback = (current['low'] <= current['MA99'] + (self.atr_multiplier * current['ATR'])) and \
                           (current['close'] > current['MA99'])
            long_rsi_ok = self.rsi_long_range[0] < current['RSI'] < self.rsi_long_range[1]
            
            if is_bull_trend and long_pullback and long_rsi_ok:
                action = "LONG"
                htf_aligned, htf_info = self.check_htf_alignment(exchange, symbol, timeframe, action)
                
                if htf_aligned:
                    confidence = self._calculate_confidence(current, action)
                    return Signal(
                        symbol=symbol,
                        timeframe=timeframe,
                        action=action,
                        price=current['close'],
                        rsi=current['RSI'],
                        ma99=current['MA99'],
                        atr=current['ATR'],
                        timestamp=datetime.now(),
                        htf_aligned=True,
                        confidence=confidence
                    )
            
            # 检查做空条件
            is_bear_trend = current['MA25'] < current['MA99']
            short_pullback = (current['high'] >= current['MA99'] - (self.atr_multiplier * current['ATR'])) and \
                            (current['close'] < current['MA99'])
            short_rsi_ok = self.rsi_short_range[0] < current['RSI'] < self.rsi_short_range[1]
            
            if is_bear_trend and short_pullback and short_rsi_ok:
                action = "SHORT"
                htf_aligned, htf_info = self.check_htf_alignment(exchange, symbol, timeframe, action)
                
                if htf_aligned:
                    confidence = self._calculate_confidence(current, action)
                    return Signal(
                        symbol=symbol,
                        timeframe=timeframe,
                        action=action,
                        price=current['close'],
                        rsi=current['RSI'],
                        ma99=current['MA99'],
                        atr=current['ATR'],
                        timestamp=datetime.now(),
                        htf_aligned=True,
                        confidence=confidence
                    )
            
            return None
            
        except Exception as e:
            logger.error(f"生成信号失败 {symbol} {timeframe}: {e}")
            return None
    
    def _calculate_confidence(self, current: pd.Series, action: str) -> float:
        """计算信号置信度"""
        confidence = 0.5  # 基础置信度
        
        # RSI偏离50的程度（越接近50越中性，偏离越大趋势越强）
        rsi_deviation = abs(current['RSI'] - 50) / 50
        confidence += rsi_deviation * 0.2
        
        # 价格与MA99的距离（越近置信度越高）
        price_ma_distance = abs(current['close'] - current['MA99']) / current['MA99']
        if price_ma_distance < 0.005:  # 0.5%以内
            confidence += 0.15
        elif price_ma_distance < 0.01:  # 1%以内
            confidence += 0.1
        
        # ATR相对大小（波动率适中更好）
        atr_ratio = current['ATR'] / current['close']
        if 0.005 < atr_ratio < 0.02:  # 波动率适中
            confidence += 0.15
        
        return min(confidence, 1.0)
    
    def is_duplicate_signal(self, signal: Signal) -> bool:
        """检查是否为重复信号"""
        memory_key = f"{signal.symbol}_{signal.timeframe}_{signal.action}"
        current_bar_time = int(signal.timestamp.timestamp() / 60)  # 按分钟取整
        
        if self.signal_memory.get(memory_key) == current_bar_time:
            return True
        
        self.signal_memory[memory_key] = current_bar_time
        return False
    
    def clear_old_memory(self, max_age_minutes: int = 60):
        """清理过期的信号记忆"""
        current_time = int(datetime.now().timestamp() / 60)
        self.signal_memory = {
            k: v for k, v in self.signal_memory.items() 
            if current_time - v < max_age_minutes
        }
    
    def get_signal_description(self, signal: Signal) -> str:
        """获取信号描述"""
        emoji = "🟢" if signal.action == "LONG" else "🔴"
        return (f"{emoji} {signal.symbol} ({signal.timeframe}) {signal.action} | "
                f"价格: ${signal.price:.2f} | RSI: {signal.rsi:.1f} | "
                f"置信度: {signal.confidence:.0%}")
    
    def get_ai_analysis(self, signal: Signal) -> str:
        """
        使用Gemini AI分析信号
        
        Returns:
            AI分析结果文本
        """
        if not self.ai_client:
            return "⚠️ AI分析未启用"
        
        try:
            prompt = f"""
你是一位拥有10年经验的量化交易员。当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}。

交易标的：{signal.symbol} ({signal.timeframe} 级别)
当前价格：${signal.price:.2f}
技术面：触发【{signal.action}】信号，已通过大周期(MTF)顺势共振审查
RSI指标：{signal.rsi:.1f}
信号置信度：{signal.confidence:.0%}

请给出100字以内的极简操作建议，包括：
1. 入场建议
2. 止损位参考
3. 盈亏比评估

要求：客观理性，直接给结论，不要废话。
"""
            response = self.ai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            return response.text.strip()
            
        except Exception as e:
            logger.error(f"AI分析失败: {e}")
            return "⚠️ AI分析暂时不可用，请严格带好止损独立决策。"
    
    def send_telegram_alert(self, signal: Signal, ai_advice: str = ""):
        """
        发送Telegram提醒
        
        Args:
            signal: 交易信号
            ai_advice: AI分析建议
        """
        if not self.enable_telegram or not self.telegram_token or not self.telegram_chat_id:
            return
        
        if self.telegram_token == '你的TELEGRAM_BOT_TOKEN':
            return
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            action_str = "🟢 做多 (LONG)" if signal.action == 'LONG' else "🔴 做空 (SHORT)"
            
            text = f"""🚨 <b>MTF 共振狙击预警</b> 🚨

📌 <b>标的:</b> {signal.symbol} | <b>信号周期:</b> {signal.timeframe}
🎯 <b>方向:</b> {action_str} (已确认大趋势顺向)
💰 <b>现价:</b> ${signal.price:.2f}
📊 <b>动能:</b> RSI = {signal.rsi:.1f}
🎲 <b>置信度:</b> {signal.confidence:.0%}
⏰ <b>时间:</b> {datetime.now().strftime('%H:%M:%S')}
"""
            
            if ai_advice and ai_advice != "⚠️ AI分析未启用":
                text += f"\n🧠 <b>AI 战术板:</b>\n<i>{ai_advice}</i>"
            
            response = requests.post(
                url,
                json={
                    "chat_id": self.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML"
                },
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Telegram提醒已发送: {signal.symbol}")
            else:
                logger.warning(f"⚠️ Telegram发送失败: {response.text}")
                
        except Exception as e:
            logger.error(f"Telegram推送失败: {e}")
