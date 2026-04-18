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
            
            # 设置环境变量代理
            os.environ['HTTP_PROXY'] = proxy
            os.environ['HTTPS_PROXY'] = proxy
            
            exchange_config = {
                'enableRateLimit': True,
                'proxies': {
                    'http': proxy,
                    'https': proxy,
                },
                'options': {
                    'adjustForTimeDifference': True,  # 自动调整时间差
                    'recvWindow': 60000,  # 增加接收窗口到60秒
                }
            }
            
            if not api_key or not secret:
                logger.warning("⚠️ API密钥未配置，将以只读模式运行")
                self.exchange = ccxt.binanceus(exchange_config)
            else:
                # 合并options而不是覆盖
                exchange_config['apiKey'] = api_key
                exchange_config['secret'] = secret
                exchange_config['options']['defaultType'] = 'future'  # 使用合约交易
                self.exchange = ccxt.binance(exchange_config)
            
            # 同步服务器时间
            try:
                self.exchange.load_time_difference()
                logger.info(f"⏰ 时间差已同步: {self.exchange.options.get('timeDifference', 0)}ms")
            except Exception as e:
                logger.warning(f"⚠️ 时间同步失败: {e}")
            
            # 测试连接 - 使用公开API
            try:
                self.exchange.fetch_ticker('BTC/USDT')
                logger.info("✅ 交易所连接成功")
            except Exception as e:
                logger.warning(f"⚠️ 交易所连接测试失败: {e}")
            
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
            # 优先使用 fetch_balance 获取持仓信息（更可靠）
            balance = self.exchange.fetch_balance()
            positions_info = balance.get('info', {}).get('positions', [])
            logger.info(f"[Exchange] Balance positions: {len(positions_info)}")
            
            active_positions = []
            
            # 处理 balance 返回的持仓数据
            if positions_info:
                for pos in positions_info:
                    position_amt = float(pos.get('positionAmt', 0))
                    if position_amt != 0:
                        # 修复杠杆倍数获取逻辑
                        leverage_val = pos.get('leverage')
                        if leverage_val is None or leverage_val == '':
                            leverage_val = 1
                        else:
                            try:
                                leverage_val = int(float(leverage_val))
                            except (ValueError, TypeError):
                                leverage_val = 1
                        
                        # 确保所有数值字段都有默认值
                        entry_price = float(pos.get('entryPrice') or 0)
                        mark_price = float(pos.get('markPrice') or 0)
                        unrealized_pnl = float(pos.get('unrealizedProfit') or 0)
                        
                        active_positions.append({
                            'symbol': pos.get('symbol', ''),
                            'side': 'LONG' if position_amt > 0 else 'SHORT',
                            'contracts': abs(position_amt),
                            'entry_price': entry_price,
                            'mark_price': mark_price,
                            'unrealized_pnl': unrealized_pnl,
                            'leverage': leverage_val,
                            'liquidation_price': float(pos.get('liquidationPrice') or 0)
                        })
            
            # 如果 balance 没有返回数据，尝试使用 fetch_positions
            if not active_positions:
                positions = self.exchange.fetch_positions()
                logger.info(f"[Exchange] fetch_positions returned: {len(positions)} positions")
                
                for pos in positions:
                    contracts = float(pos.get('contracts', 0))
                    notional = float(pos.get('notional', 0))
                    
                    # 使用 contracts 或 notional 来判断是否有持仓
                    if contracts != 0 or abs(notional) > 0.01:
                        # 修复杠杆倍数获取逻辑
                        leverage_val = pos.get('leverage')
                        if leverage_val is None or leverage_val == '':
                            leverage_val = 1
                        else:
                            try:
                                leverage_val = int(float(leverage_val))
                            except (ValueError, TypeError):
                                leverage_val = 1
                        
                        # 确保所有数值字段都有默认值
                        entry_price = float(pos.get('entryPrice') or pos.get('entry_price') or 0)
                        mark_price = float(pos.get('markPrice') or pos.get('mark_price') or 0)
                        unrealized_pnl = float(pos.get('unrealizedPnl') or pos.get('unrealized_pnl') or 0)
                        
                        active_positions.append({
                            'symbol': pos.get('symbol', ''),
                            'side': 'LONG' if (contracts > 0 or notional > 0) else 'SHORT',
                            'contracts': abs(contracts) if contracts != 0 else abs(notional),
                            'entry_price': entry_price,
                            'mark_price': mark_price,
                            'unrealized_pnl': unrealized_pnl,
                            'leverage': leverage_val,
                            'liquidation_price': float(pos.get('liquidationPrice') or 0)
                        })
            
            logger.info(f"[Exchange] Final active positions: {len(active_positions)}")
            for p in active_positions:
                logger.info(f"[Exchange] Active: {p['symbol']} {p['side']} x{p['leverage']} PnL:{p['unrealized_pnl']:.2f}")
            
            return active_positions
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
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
                'last': ticker.get('last'),
                'bid': ticker.get('bid'),
                'ask': ticker.get('ask'),
                'high': ticker.get('high'),
                'low': ticker.get('low'),
                'volume': ticker.get('volume'),
                'change': ticker.get('change'),
                'percentage': ticker.get('percentage')
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
            precision = market.get('precision', {}).get('amount', 8)
            amount = self._adjust_precision(amount, precision)
            
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
    
    def _adjust_precision(self, value: float, precision) -> float:
        """调整数值精度
        
        Args:
            value: 原始数值
            precision: 精度（可以是整数位数，也可以是最小精度如0.001）
        """
        try:
            # 如果 precision 是小于1的小数（如0.001），转换为整数位数
            if isinstance(precision, float) and precision < 1:
                # 计算小数位数（0.001 -> 3）
                precision = len(str(precision).split('.')[-1])
            elif isinstance(precision, str):
                precision = int(precision)
            else:
                precision = int(precision) if precision is not None else 8
            
            quantize_str = '0.' + '0' * precision
            result = float(Decimal(str(value)).quantize(Decimal(quantize_str), rounding=ROUND_DOWN))
            return result
        except Exception as e:
            logger.warning(f"精度调整失败: {e}, 返回原始值")
            return float(value)

    def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        ticker = self.get_ticker(symbol)
        return ticker['last'] if ticker else None

    def get_recent_account_trades(
        self,
        symbol: Optional[str] = None,
        since_ms: Optional[int] = None,
        limit: int = 200
    ) -> List[Dict]:
        """Fetch recent account trades from exchange."""
        def _fetch_once(sym: Optional[str]) -> List[Dict]:
            kwargs = {
                'symbol': sym if sym else None,
                'since': since_ms,
                'limit': limit
            }
            return self.exchange.fetch_my_trades(**kwargs) or []

        if not symbol:
            try:
                return _fetch_once(None)
            except Exception as e:
                logger.warning(f"Fetch account trades without symbol failed: {e}")
                return []

        symbol_raw = (symbol or '').strip().upper()
        variants = []
        if symbol_raw:
            variants.append(symbol_raw)
            if '/USDT' in symbol_raw and ':USDT' not in symbol_raw:
                variants.append(symbol_raw.replace('/USDT', '/USDT:USDT'))
            if '/' in symbol_raw:
                variants.append(symbol_raw.replace('/', ''))

        # Try matched market symbol names from loaded markets
        try:
            markets = self.exchange.load_markets()
            target_key = symbol_raw.replace('/', '').replace(':USDT', '')
            for market_symbol in markets.keys():
                key = market_symbol.upper().replace('/', '').replace(':USDT', '')
                if key == target_key and market_symbol not in variants:
                    variants.append(market_symbol)
        except Exception:
            pass

        last_error = None
        for sym in variants:
            try:
                return _fetch_once(sym)
            except Exception as e:
                last_error = e
                continue

        logger.warning(f"Fetch account trades failed (symbol={symbol}, variants={variants}): {last_error}")
        return []

# 单例模式
_exchange_client = None

def get_exchange_client() -> ExchangeClient:
    """获取交易所客户端实例"""
    global _exchange_client
    if _exchange_client is None:
        _exchange_client = ExchangeClient()
    return _exchange_client
