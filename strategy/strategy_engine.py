import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import pandas as pd
import requests
import time
import json
from datetime import datetime
from google import genai

from trading_core.exchange_client import get_exchange_client
from trading_core.order_executor import get_order_executor

# ================= 1. 专业日志配置 =================
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

# ================= 2. 核心参数与 API 设置 =================
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'DOGE/USDT', 'DOT/USDT']
TIMEFRAMES = ['15m', '1h', '4h']       
MA_LENGTH = 99          
LOOKBACK_BARS = 15      

# 【V8 新增】大周期审查映射表
HTF_MAP = {
    '15m': ['1h', '4h'],
    '1h': ['4h'],
    '4h': ['1d']
}

# 🔑 你的三大核心密钥
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

MEMORY_FILE = "signal_memory.json"

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
exchange = get_exchange_client()
order_executor = get_order_executor()

# ================= 3. 记忆与 AI 模块 (保持不变) =================
def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r') as f: return json.load(f)
        except: pass
    return {}

def save_memory(memory_dict):
    try:
        with open(MEMORY_FILE, 'w') as f: json.dump(memory_dict, f)
    except: pass

def get_ai_analysis(symbol, timeframe, action, price, rsi):
    if not client:
        return "⚠️ AI 分析暂时不可用，请严格带好止损独立决策。"
    
    prompt = f"""
    你现在是一位拥有10年经验的量化交易员。当前时间：{datetime.now().strftime('%Y-%m-%d')}。
    交易标的：{symbol} ({timeframe} 级别)，当前价格：{price}
    技术面：当前触发【{action}】信号，且已通过大周期(MTF)的顺势共振审查！RSI为 {rsi:.1f}。
    请给出100字以内的极简操作建议、止损位和盈亏比参考。客观理性，直接给结论。
    """
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        return response.text.strip()
    except:
        return "⚠️ AI 分析暂时不可用，请严格带好止损独立决策。"

def send_telegram_alert(symbol, timeframe, action, price, rsi, ai_advice, executed=False):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    action_str = "🟢 做多 (LONG)" if action == 'LONG' else "🔴 做空 (SHORT)"
    exec_status = "✅ 已执行" if executed else "⏸️ 未执行(自动交易暂停或风控拦截)"
    
    text = f"🚨 <b>MTF 共振狙击预警</b> 🚨\n\n" \
           f"📌 <b>标的:</b> {symbol} | <b>信号周期:</b> {timeframe}\n" \
           f"🎯 <b>方向:</b> {action_str} (已确认大趋势顺向)\n" \
           f"💰 <b>现价:</b> ${price}\n" \
           f"📊 <b>动能:</b> RSI = {rsi:.1f}\n" \
           f"⏰ <b>时间:</b> {datetime.now().strftime('%H:%M:%S')}\n" \
           f"📋 <b>状态:</b> {exec_status}\n\n" \
           f"🧠 <b>AI 战术板:</b>\n<i>{ai_advice}</i>"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logger.error(f"Telegram 推送失败: {e}")

# ================= 4. 【V8 新增】大周期审查官 =================
def verify_htf_alignment(symbol, timeframe, action):
    htfs = HTF_MAP.get(timeframe, [])
    if not htfs: return True 
    
    for htf in htfs:
        try:
            bars = exchange.exchange.fetch_ohlcv(symbol, timeframe=htf, limit=120)
            if not bars or len(bars) < 100: return False
            
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df = df.iloc[:-1] # 抛弃未走完的 K 线
            df['MA99'] = df['close'].rolling(window=MA_LENGTH).mean()
            
            current_htf_close = df.iloc[-1]['close']
            current_htf_ma99 = df.iloc[-1]['MA99']
            
            # 【一票否决制】
            if action == "LONG" and current_htf_close < current_htf_ma99:
                logger.info(f"🚫 拦截伪信号: {symbol} {timeframe} 做多，但大周期 {htf} 为空头趋势 (被 MA99 压制)。")
                return False
            if action == "SHORT" and current_htf_close > current_htf_ma99:
                logger.info(f"🚫 拦截伪信号: {symbol} {timeframe} 做空，但大周期 {htf} 为多头趋势 (受 MA99 支撑)。")
                return False
                
        except Exception as e:
            logger.error(f"大周期 {htf} 获取异常: {e}")
            return False # 出错时安全第一，直接拦截
            
    return True # 所有大周期全部通过审查！

# ================= 5. 策略核心引擎 (原 V7 逻辑) =================
def check_ma99_strategy(symbol, timeframe):
    try:
        bars = exchange.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=200)
        if not bars or len(bars) < 150: return None, None, None

        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = df.iloc[:-1].copy() 
        
        df['MA25'] = df['close'].rolling(window=25).mean()
        df['MA99'] = df['close'].rolling(window=MA_LENGTH).mean()
        
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(14).mean()
        
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        current = df.iloc[-1]
        
        is_bull_trend = current['MA25'] > current['MA99']
        long_pullback = (current['low'] <= current['MA99'] + (0.5 * current['ATR'])) and (current['close'] > current['MA99'])
        long_rsi_ok = 40 < current['RSI'] < 65

        if is_bull_trend and long_pullback and long_rsi_ok:
            return "LONG", current, current['RSI']

        is_bear_trend = current['MA25'] < current['MA99']
        short_pullback = (current['high'] >= current['MA99'] - (0.5 * current['ATR'])) and (current['close'] < current['MA99'])
        short_rsi_ok = 35 < current['RSI'] < 60

        if is_bear_trend and short_pullback and short_rsi_ok:
            return "SHORT", current, current['RSI']
                
        return None, current, None
    except Exception as e:
        return None, None, None

# ================= 6. 守护进程中枢 =================
def run_strategy_loop():
    """运行策略主循环"""
    import warnings
    warnings.filterwarnings('ignore') 
    
    logger.info(f"🚀 V8 引擎 (含大周期上帝视角+自动交易) 启动！")
    signal_memory = load_memory()

    while True:
        try:
            for symbol in SYMBOLS:
                for tf in TIMEFRAMES:
                    signal, last_bar, rsi = check_ma99_strategy(symbol, tf)
                    
                    if not signal or last_bar is None: continue
                    
                    # 【V8 新增】：查大周期底牌！如果大周期不配合，直接抛弃该信号
                    if not verify_htf_alignment(symbol, tf, signal):
                        continue
                        
                    memory_key = f"{symbol}_{tf}_{signal}"
                    current_bar_time = last_bar['timestamp']
                    
                    if signal_memory.get(memory_key) == current_bar_time: continue
                        
                    signal_memory[memory_key] = current_bar_time
                    save_memory(signal_memory)

                    logger.info(f"🎯 黄金共振信号确认！{symbol} ({tf}) -> {signal}，现价 {last_bar['close']}")
                    
                    # 执行交易（如果自动交易开启且通过风控）
                    executed = order_executor.execute_signal(
                        symbol=symbol,
                        timeframe=tf,
                        action=signal,
                        price=last_bar['close'],
                        rsi=rsi,
                        confidence=1.0
                    )
                    
                    ai_advice = get_ai_analysis(symbol, tf, signal, last_bar['close'], rsi)
                    send_telegram_alert(symbol, tf, signal, last_bar['close'], rsi, ai_advice, executed)
            
            time.sleep(60)
        except Exception as e:
            logger.error(f"策略循环异常: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_strategy_loop()
