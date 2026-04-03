import ccxt
import logging
from typing import Dict, Optional, List
from decimal import Decimal, ROUND_DOWN
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class ExchangeClient:
    """交易所API客户端封装"""
    
    def __init__(self):
        self.exchange = None
        self._connect()
    
    def _connect(self):
        """连接交易所"""
        try:
            api_key = os.getenv('BINANCE_API_KEY')
            secret = os.getenv('BINANCE_SECRET_KEY')
            
            # 代理配置
            proxy = os.getenv('PROXY_URL', 'http://127.0.0.1:7897')
            
            exchange_config = {
                'enableRateLimit': True,
                'proxies': {
                    'http': proxy,
                    'https': proxy,
                }
            }
            
            if not api_key or not secret:
                logger.warning("⚠️ API密钥未配置，将以只读模式运行")
                self.exchange = ccxt.binanceus(exchange_config)
            else:
                exchange_config.update({
                    'apiKey': api_key,
                    'secret': secret,
                    'options': {
                        'defaultType': 'future',  # 使用合约交易
                    }
                })
                self.exchange = ccxt.binance(exchange_config)
            
            # 测试连接
            self.exchange.load_markets()
            logger.info("✅ 交易所连接成功")
            
        except Exception as e:
            logger.error(f"❌ 交易所连接失败: {e}")
            raise
    
    def get_balance(self) -> Dict:
        """获取账户余额"""
        try:
            balance = self.exchange.fetch_balance()
            return {
                'USDT': balance.get('USDT', {}).get('free', 0),
                'total_usdt': balance.get('USDT', {}).get('total', 0),
                'used_usdt': balance.get('USDT', {}).get('used', 0)
            }
        except Exception as e:
            logger.error(f"获取余额失败: {e}")
            return {'USDT': 0, 'total_usdt': 0, 'used_usdt': 0}
    
    def get_positions(self) -> List[Dict]:
        """获取当前持仓"""
        try:
            positions = self.exchange.fetch_positions()
            active_positions = []
            
            for pos in positions:
                contracts = float(pos.get('contracts', 0))
                if contracts != 0:
                    active_positions.append({
                        'symbol': pos['symbol'],
                        'side': 'LONG' if contracts > 0 else 'SHORT',
                        'contracts': abs(contracts),
                        'entry_price': float(pos.get('entryPrice', 0)),
                        'mark_price': float(pos.get('markPrice', 0)),
                        'unrealized_pnl': float(pos.get('unrealizedPnl', 0)),
                        'leverage': int(pos.get('leverage', 1)),
                        'liquidation_price': float(pos.get('liquidationPrice', 0))
                    })
            
            return active_positions
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return []
    
    def get_ohlcv(self, symbol: str, timeframe: str = '1h', limit: int = 100) -> Optional[List]:
        """获取K线数据"""
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            return ohlcv
        except Exception as e:
            logger.error(f"获取K线数据失败: {e}")
            return None
    
    def get_ticker(self, symbol: str) -> Optional[Dict]:
        """获取最新行情"""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return {
                'symbol': symbol,
                'last': ticker['last'],
                'bid': ticker['bid'],
                'ask': ticker['ask'],
                'high': ticker['high'],
                'low': ticker['low'],
                'volume': ticker['volume'],
                'change': ticker['change'],
                'percentage': ticker['percentage']
            }
        except Exception as e:
            logger.error(f"获取行情失败: {e}")
            return None
    
    def create_order(self, symbol: str, side: str, amount: float, 
                     price: Optional[float] = None, 
                     order_type: str = 'market',
                     params: Optional[Dict] = None) -> Optional[Dict]:
        """
        创建订单
        
        Args:
            symbol: 交易对，如 'BTC/USDT'
            side: 'buy' 或 'sell'
            amount: 下单数量
            price: 限价单价格（市价单不需要）
            order_type: 'market' 或 'limit'
            params: 额外参数
        """
        try:
            # 调整精度
            market = self.exchange.market(symbol)
            amount = self._adjust_precision(amount, market['precision']['amount'])
            
            order = self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=price,
                params=params or {}
            )
            
            logger.info(f"✅ 订单创建成功: {symbol} {side.upper()} {amount}")
            return {
                'order_id': order['id'],
                'symbol': symbol,
                'side': side,
                'amount': amount,
                'price': order.get('price', price),
                'status': order['status']
            }
            
        except Exception as e:
            logger.error(f"❌ 订单创建失败: {e}")
            return None
    
    def close_position(self, symbol: str) -> bool:
        """平仓指定交易对"""
        try:
            positions = self.get_positions()
            for pos in positions:
                if pos['symbol'] == symbol:
                    side = 'sell' if pos['side'] == 'LONG' else 'buy'
                    result = self.create_order(
                        symbol=symbol,
                        side=side,
                        amount=pos['contracts'],
                        order_type='market'
                    )
                    if result:
                        logger.info(f"✅ 平仓成功: {symbol}")
                        return True
            return False
        except Exception as e:
            logger.error(f"❌ 平仓失败: {e}")
            return False
    
    def close_all_positions(self) -> bool:
        """平掉所有持仓"""
        try:
            positions = self.get_positions()
            success_count = 0
            
            for pos in positions:
                if self.close_position(pos['symbol']):
                    success_count += 1
            
            logger.info(f"✅ 已平仓 {success_count}/{len(positions)} 个持仓")
            return success_count == len(positions)
            
        except Exception as e:
            logger.error(f"❌ 全部平仓失败: {e}")
            return False
    
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """设置杠杆倍数"""
        try:
            self.exchange.set_leverage(leverage, symbol)
            logger.info(f"✅ 杠杆设置成功: {symbol} {leverage}x")
            return True
        except Exception as e:
            logger.error(f"❌ 杠杆设置失败: {e}")
            return False
    
    def _adjust_precision(self, value: float, precision: int) -> float:
        """调整数值精度"""
        quantize_str = '0.' + '0' * precision
        return float(Decimal(str(value)).quantize(Decimal(quantize_str), rounding=ROUND_DOWN))

    def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        ticker = self.get_ticker(symbol)
        return ticker['last'] if ticker else None

# 单例模式
_exchange_client = None

def get_exchange_client() -> ExchangeClient:
    """获取交易所客户端实例"""
    global _exchange_client
    if _exchange_client is None:
        _exchange_client = ExchangeClient()
    return _exchange_client
