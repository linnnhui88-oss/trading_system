import logging
from typing import Dict, Optional
from datetime import datetime
import os

logger = logging.getLogger(__name__)

class RiskManager:
    """风险管理器"""
    
    def __init__(self):
        self.max_position_usdt = float(os.getenv('MAX_POSITION_USDT', 1000))
        self.max_daily_loss_usdt = float(os.getenv('MAX_DAILY_LOSS_USDT', 500))
        self.default_leverage = int(os.getenv('DEFAULT_LEVERAGE', 3))
        self.stop_loss_percent = float(os.getenv('STOP_LOSS_PERCENT', 2))
        self.take_profit_percent = float(os.getenv('TAKE_PROFIT_PERCENT', 4))
        self.trailing_stop_percent = float(os.getenv('TRAILING_STOP_PERCENT', 1.0))
        self.max_positions_count = int(os.getenv('MAX_POSITIONS_COUNT', 5))
        
        self.daily_pnl = 0
        self.daily_trades = 0
        self.last_reset_date = datetime.now().date()
        self.trading_enabled = True
        self.errors_today = 0
        self.max_errors_per_day = 10
        
    def check_risk_limits(self, balance: Dict, positions: list) -> Dict:
        """检查风险限制"""
        self._reset_daily_if_needed()
        
        result = {
            'can_trade': True,
            'reasons': [],
            'warnings': []
        }
        
        # 检查每日亏损限制
        if self.daily_pnl <= -self.max_daily_loss_usdt:
            result['can_trade'] = False
            result['reasons'].append(f"每日亏损已达上限: ${abs(self.daily_pnl):.2f}")
        
        # 检查总持仓价值
        total_position_value = sum(
            pos['contracts'] * pos['entry_price'] 
            for pos in positions
        )
        
        if total_position_value >= self.max_position_usdt:
            result['can_trade'] = False
            result['reasons'].append(f"总持仓已达上限: ${total_position_value:.2f}")
        
        # 检查可用余额
        available_usdt = balance.get('USDT', 0)
        if available_usdt < 50:  # 最小下单金额
            result['can_trade'] = False
            result['reasons'].append(f"可用余额不足: ${available_usdt:.2f}")
        
        # 检查持仓数量限制
        if len(positions) >= self.max_positions_count:
            result['can_trade'] = False
            result['reasons'].append(f"持仓数量已达上限: {len(positions)}/{self.max_positions_count}")
        
        # 检查错误次数
        if self.errors_today >= self.max_errors_per_day:
            result['can_trade'] = False
            result['reasons'].append(f"今日错误次数过多: {self.errors_today}/{self.max_errors_per_day}")
        
        # 警告
        if len(positions) >= self.max_positions_count - 1:
            result['warnings'].append(f"持仓数量接近上限: {len(positions)}/{self.max_positions_count}")
        
        if self.daily_trades >= 20:
            result['warnings'].append(f"今日交易频繁: {self.daily_trades}笔")
        
        self.trading_enabled = result['can_trade']
        return result
    
    def calculate_position_size(self, symbol: str, price: float, 
                               confidence: float = 1.0) -> float:
        """
        计算仓位大小
        
        Args:
            symbol: 交易对
            price: 当前价格
            confidence: 信号置信度 (0-1)
        """
        # 基础仓位 = 最大仓位 * 置信度
        base_position = self.max_position_usdt * confidence
        
        # 根据价格计算数量
        amount = base_position / price
        
        # 确保数量不小于最小下单量 (0.001 BTC)
        min_amount = 0.001
        if amount < min_amount:
            # 如果计算的金额太小，使用最小下单量
            amount = min_amount
            actual_value = amount * price
            logger.warning(f"⚠️ {symbol} 仓位计算结果({amount * price:.2f} USDT)太小，调整为最小下单量: {min_amount} ({actual_value:.2f} USDT)")
        
        logger.info(f"📊 仓位计算: {symbol} 价格${price:.2f} 数量{amount:.6f} (金额约${amount * price:.2f} USDT)")
        return amount
    
    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """计算止损价格"""
        if side == 'LONG':
            return entry_price * (1 - self.stop_loss_percent / 100)
        else:
            return entry_price * (1 + self.stop_loss_percent / 100)
    
    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """计算止盈价格"""
        if side == 'LONG':
            return entry_price * (1 + self.take_profit_percent / 100)
        else:
            return entry_price * (1 - self.take_profit_percent / 100)
    
    def record_trade(self, pnl: float):
        """记录交易盈亏"""
        self._reset_daily_if_needed()
        self.daily_pnl += pnl
        self.daily_trades += 1
        
        logger.info(f"📈 交易记录: PnL=${pnl:.2f}, 今日总计=${self.daily_pnl:.2f}")
    
    def _reset_daily_if_needed(self):
        """如果需要，重置每日统计"""
        today = datetime.now().date()
        if today != self.last_reset_date:
            self.daily_pnl = 0
            self.daily_trades = 0
            self.last_reset_date = today
            self.trading_enabled = True
            logger.info("🌅 新的一天，风险统计已重置")
    
    def record_error(self):
        """记录错误"""
        self._reset_daily_if_needed()
        self.errors_today += 1
        logger.warning(f"记录错误: {self.errors_today}/{self.max_errors_per_day}")
        
        if self.errors_today >= self.max_errors_per_day:
            self.trading_enabled = False
            logger.error(f"错误次数过多，已自动禁用交易")
    
    def get_status(self) -> Dict:
        """获取风险状态"""
        self._reset_daily_if_needed()
        return {
            'trading_enabled': self.trading_enabled,
            'daily_pnl': self.daily_pnl,
            'daily_trades': self.daily_trades,
            'max_daily_loss': self.max_daily_loss_usdt,
            'max_position': self.max_position_usdt,
            'stop_loss_percent': self.stop_loss_percent,
            'take_profit_percent': self.take_profit_percent,
            'trailing_stop_percent': self.trailing_stop_percent,
            'leverage': self.default_leverage,
            'max_positions_count': self.max_positions_count,
            'current_positions_count': None,  # 需要外部传入
            'errors_today': self.errors_today,
            'max_errors_per_day': self.max_errors_per_day
        }
    
    def enable_trading(self):
        """启用交易"""
        self.trading_enabled = True
        logger.info("✅ 交易已启用")
    
    def disable_trading(self):
        """禁用交易"""
        self.trading_enabled = False
        logger.info("⏹️ 交易已禁用")

# 单例模式
_risk_manager = None

def get_risk_manager() -> RiskManager:
    """获取风险管理器实例"""
    global _risk_manager
    if _risk_manager is None:
        _risk_manager = RiskManager()
    return _risk_manager
