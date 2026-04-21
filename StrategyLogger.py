import logging
import json
import os
import time
import uuid
from datetime import datetime

class QuantJSONFormatter(logging.Formatter):
    """自定义 JSON 日志格式化器，专为量化系统设计"""
    def format(self, record):
        log_record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        # 提取传入的额外交易上下文数据 (extra_data)
        if hasattr(record, 'trade_data'):
            log_record.update(record.trade_data)
            
        return json.dumps(log_record, ensure_ascii=False)

def setup_signal_logger():
    logger = logging.getLogger("TTC_Signal")
    logger.setLevel(logging.DEBUG)
    
    # 防止日志重复传播到根logger
    logger.propagate = False
    
    # 清除已有的handler（避免重复）
    logger.handlers = []
    
    # 使用绝对路径，确保日志文件在项目根目录的data文件夹
    # StrategyLogger.py 在 trading_system/ 下，所以只需要向上1层到项目根目录
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(current_file_dir, 'data')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'trade_signals.json')
    
    print(f"[StrategyLogger] Log file: {log_file}")
    
    # 存入专门的信号日志文件
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(QuantJSONFormatter())
    logger.addHandler(file_handler)
    
    # 同时输出到控制台（方便调试）
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(QuantJSONFormatter())
    logger.addHandler(console_handler)
    
    return logger

signal_log = setup_signal_logger()

class StrategyLogger:
    """策略信号日志封装类"""
    
    def __init__(self, strategy_name="MA99_MTF"):
        self.logger = signal_log
        self.strategy_name = strategy_name

    def _generate_trace_id(self):
        """生成唯一追踪码，用于将同一次行情的扫描、决策、下单串联起来"""
        return uuid.uuid4().hex[:8]

    def log_scanned(self, symbol, timeframe, indicators, current_price):
        """1. 扫描日志：记录当前抓取到的底层数据状态"""
        trace_id = self._generate_trace_id()
        data = {
            "event_type": "SCAN",
            "trace_id": trace_id,
            "strategy": self.strategy_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "current_price": current_price,
            "indicators": indicators # 例如: {"ma99": 65000.5, "rsi": 45}
        }
        self.logger.info(f"行情扫描: {symbol} @ {current_price}", extra={'trade_data': data})
        return trace_id

    def log_skipped(self, trace_id, symbol, reason, details=None):
        """2. 跳过日志：记录为何没有开仓 (极度重要，用于回测对比)"""
        data = {
            "event_type": "SKIP",
            "trace_id": trace_id,
            "symbol": symbol,
            "reason": reason, # 例如: "SpreadTooHigh", "TrendNotAligned", "InsufficientMargin"
            "details": details or {}
        }
        self.logger.info(f"忽略信号: {symbol} - {reason}", extra={'trade_data': data})

    def log_ai_decision(self, trace_id, symbol, action, confidence_score, prompt_tokens=0):
        """3. AI 决策日志：记录模型评分和参数"""
        data = {
            "event_type": "AI_INFERENCE",
            "trace_id": trace_id,
            "symbol": symbol,
            "ai_action": action, # "LONG", "SHORT", "HOLD"
            "confidence_score": round(confidence_score, 4),
            "latency_ms": 120, # 记录请求大模型 API 或本地推理的耗时
            "prompt_tokens": prompt_tokens
        }
        self.logger.info(f"AI决策: {symbol} -> {action} (得分: {confidence_score})", extra={'trade_data': data})

    def log_position_open(self, trace_id, symbol, side, entry_price, size, leverage, api_latency_ms):
        """4. 开仓记录：记录真实的执行结果"""
        data = {
            "event_type": "OPEN_POSITION",
            "trace_id": trace_id,
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "size": size,
            "leverage": leverage,
            "notional_value": entry_price * size,
            "exchange_api_latency": api_latency_ms # 监控代理或网络是否卡顿
        }
        self.logger.info(f"成功开仓: {side} {symbol} @ {entry_price}", extra={'trade_data': data})

    def log_position_close(self, symbol, side, exit_price, pnl, close_reason):
        """5. 平仓记录：止盈、止损或风控强平"""
        data = {
            "event_type": "CLOSE_POSITION",
            "symbol": symbol,
            "side": side, # 原持仓方向
            "exit_price": exit_price,
            "realized_pnl": pnl, # 真实盈亏
            "close_reason": close_reason # "TAKE_PROFIT", "STOP_LOSS", "TIME_EXIT", "FORCE_KILL"
        }
        self.logger.info(f"平仓结算: {symbol} - 盈亏: {pnl} ({close_reason})", extra={'trade_data': data})

    def log_system_error(self, component, error_msg, raw_response=None):
        """6. 系统异常日志：专门捕捉 API 鉴权失败、断网等底层问题"""
        data = {
            "event_type": "SYSTEM_ERROR",
            "component": component, # "CCXT_API", "WebSocket", "TelegramBot"
            "error_msg": error_msg,
            "raw_response": raw_response # 存放完整的报错体，方便排查 API Key 错误等问题
        }
        self.logger.error(f"系统异常: [{component}] {error_msg}", extra={'trade_data': data})

# ================= 使用示例 =================
if __name__ == "__main__":
    tracker = StrategyLogger()
    
    # 1. 扫描到行情
    trace_id = tracker.log_scanned("BTC/USDT", "15m", {"ma99": 68000.00}, 68500.00)
    
    # 2. 假设 AI 介入分析
    tracker.log_ai_decision(trace_id, "BTC/USDT", "LONG", 0.89)
    
    # 3. 假设触发风控跳过
    # tracker.log_skipped(trace_id, "BTC/USDT", "InsufficientMargin", {"balance": 100, "required": 500})
    
    # 4. 假设执行开仓
    tracker.log_position_open(trace_id, "BTC/USDT", "LONG", 68510.50, 0.1, 10, api_latency_ms=45)
    
    # 5. 假设数小时后平仓
    tracker.log_position_close("BTC/USDT", "LONG", 69000.00, 48.95, "TAKE_PROFIT")
    
    # 6. 假设遇到 API 报错
    tracker.log_system_error("CCXT_API", "Invalid API Key or Permissions", '{"code": -2015, "msg": "Invalid API-key, IP, or permissions for action."}')