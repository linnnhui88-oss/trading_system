import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 先加载环境变量，确保GEMINI_API_KEY等配置可用
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import logging
from threading import Thread, Lock
import time
import json
import sqlite3

from trading_core.exchange_client import get_exchange_client
from trading_core.risk_manager import get_risk_manager
from trading_core.order_executor import get_order_executor
from trading_core.strategy_engine_adapter import get_strategy_manager, StrategyConfig
from trading_core.ai_model_registry import get_all_ai_models
from trading_core.ai_provider_config_manager import AIProviderConfigManager
from trading_core.market_data_service import MarketDataService
from trading_core.trade_fill_repository import TradeFillRepository
from trading_core.llm_service import LLMService
from trading_core.strategy_config_repository import StrategyConfigRepository

# 配置日志
log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'web_admin.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.info(f'Web admin log file: {log_file}')

template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
app = Flask(__name__, template_folder=template_dir)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['TEMPLATES_AUTO_RELOAD'] = True  # 开发模式下自动重载模板
socketio = SocketIO(app, cors_allowed_origins="*")

# 获取核心组件（延迟初始化）
_exchange = None
_risk_manager = None
_order_executor = None
_strategy_manager = None

# AI配置管理器（独立初始化，不影响交易系统）
_ai_config_manager = None
_market_data_service = None
_trade_fill_repository = None
_strategy_config_repo = None
_market_subscriptions = {}
_market_subscriptions_lock = Lock()

def normalize_symbol(symbol: str, default: str = 'BTCUSDT') -> str:
    normalized = (symbol or '').strip().upper().replace('/', '')
    return normalized or default

def get_ai_config_manager():
    """延迟获取AI配置管理器"""
    global _ai_config_manager
    
    if _ai_config_manager is None:
        _ai_config_manager = AIProviderConfigManager()
        logger.info('[AI] AIProviderConfigManager initialized')
    
    return _ai_config_manager

def get_market_data_service():
    """延迟获取市场行情服务"""
    global _market_data_service

    if _market_data_service is None:
        _market_data_service = MarketDataService()
        logger.info('[Market] MarketDataService initialized')

    return _market_data_service

def get_trade_fill_repository():
    """延迟获取成交明细仓储"""
    global _trade_fill_repository

    if _trade_fill_repository is None:
        _trade_fill_repository = TradeFillRepository()
        logger.info('[TradeFill] TradeFillRepository initialized')

    return _trade_fill_repository

def get_strategy_config_repo():
    """延迟获取策略配置仓储"""
    global _strategy_config_repo

    if _strategy_config_repo is None:
        _strategy_config_repo = StrategyConfigRepository()
        logger.info('[StrategyConfig] StrategyConfigRepository initialized')

    return _strategy_config_repo

def get_components():
    """延迟获取核心组件"""
    global _exchange, _risk_manager, _order_executor, _strategy_manager
    
    # 如果任何组件为None，重新初始化
    if _exchange is None or _risk_manager is None or _order_executor is None or _strategy_manager is None:
        try:
            logger.info('[Components] Initializing components...')
            
            if _exchange is None:
                _exchange = get_exchange_client()
                logger.info('[Components] Exchange client initialized')
            
            if _risk_manager is None:
                _risk_manager = get_risk_manager()
                logger.info('[Components] Risk manager initialized')
            
            if _order_executor is None:
                _order_executor = get_order_executor()
                logger.info('[Components] Order executor initialized')
            
            if _strategy_manager is None:
                _strategy_manager = get_strategy_manager(_exchange, _risk_manager, _order_executor)
                logger.info('[Components] Strategy manager initialized')
                
                # 注册默认MA99_MTF策略
                _register_default_strategy()
                
        except Exception as e:
            logger.error(f"[Components] 组件初始化失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    return _exchange, _risk_manager, _order_executor, _strategy_manager

def _register_default_strategy():
    """注册MA99_MTF策略 - 作为唯一信号源"""
    global _strategy_manager
    if _strategy_manager is None:
        return
    
    # 检查是否已注册
    if 'MA99_MTF' not in _strategy_manager.strategies:
        # 使用原始策略代码中的币种和周期
        config = StrategyConfig(
            name='MA99_MTF',
            strategy_type='ma99_mtf',
            symbols=[
                'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
                'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'DOGE/USDT', 'DOT/USDT'
            ],
            timeframes=['15m', '1h', '4h'],  # 多周期监控
            enabled=True,
            params={
                'ma_length': 99,
                'ma_short': 25,
                'rsi_period': 14,
                'rsi_long_range': [40, 65],
                'rsi_short_range': [35, 60],
                'atr_multiplier': 0.5,
                'enable_ai': True,
                'enable_telegram': True
            },
            max_positions=1,  # 每个币种最多1个持仓
            position_size_usdt=float(os.getenv('MAX_POSITION_USDT', 50))  # 单次最大50USDT
        )
        _strategy_manager.register_strategy(config)
        logger.info("✅ MA99_MTF策略已注册 - 作为唯一信号源")
        logger.info(f"📊 监控币种: {len(config.symbols)}个")
        logger.info(f"⏰ 监控周期: {', '.join(config.timeframes)}")

# ==================== 页面路由 ====================

@app.route('/')
def dashboard():
    """主仪表盘页面"""
    return render_template('dashboard.html')

@app.route('/trades')
def trades_page():
    """交易记录页面"""
    return render_template('trades.html')

@app.route('/signals')
def signals_page():
    """信号记录页面"""
    return render_template('signals.html')

@app.route('/settings')
def settings_page():
    """设置页面"""
    return render_template('settings.html')

# ==================== API路由 ====================

@app.route('/api/status')
def api_status():
    """获取系统状态"""
    try:
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        
        if exchange is None:
            return jsonify({'success': False, 'error': '交易所连接失败，请检查代理设置'})
        
        balance = exchange.get_balance()
        positions = exchange.get_positions()
        risk_status = risk_manager.get_status()
        executor_status = order_executor.get_status()
        strategy_status = strategy_manager.get_status() if strategy_manager else {}
        
        # 计算总盈亏
        total_unrealized = sum(p.get('unrealized_pnl', 0) for p in positions)
        
        return jsonify({
            'success': True,
            'data': {
                'balance': balance,
                'positions': positions,
                'position_count': len(positions),
                'total_unrealized_pnl': round(total_unrealized, 2),
                'risk_status': risk_status,
                'auto_trading': executor_status['auto_trading'],
                'strategies': strategy_status,
                'timestamp': time.time()
            }
        })
    except Exception as e:
        logger.error(f"获取状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trades')
def api_trades():
    """获取交易记录"""
    try:
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        limit = request.args.get('limit', 50, type=int)
        trades = order_executor.get_recent_trades(limit)
        return jsonify({'success': True, 'data': trades})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/signals')
def api_signals():
    """获取信号记录"""
    try:
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        limit = request.args.get('limit', 50, type=int)
        
        # 获取策略信号和数据库信号
        strategy_signals = strategy_manager.get_signals(limit) if strategy_manager else []
        db_signals = order_executor.get_recent_signals(limit)
        
        # 合并信号（策略信号优先）
        all_signals = strategy_signals + db_signals
        all_signals = sorted(all_signals, key=lambda x: x.get('timestamp', ''), reverse=True)[:limit]
        
        return jsonify({'success': True, 'data': all_signals})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/market/symbols', methods=['GET'])
def api_market_symbols():
    """获取可交易币种列表"""
    try:
        market_service = get_market_data_service()
        quote_asset = request.args.get('quote_asset', 'USDT')
        only_trading = request.args.get('only_trading', 'true').lower() != 'false'
        result = market_service.get_symbols(quote_asset=quote_asset, only_trading=only_trading)

        if result.get('success'):
            return jsonify({'success': True, 'data': result.get('data', [])})
        return jsonify({'success': False, 'error': result.get('message', '获取币种失败')})
    except Exception as e:
        logger.error(f"获取市场币种失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/market/ticker', methods=['GET'])
def api_market_ticker():
    """获取单个币种ticker快照"""
    try:
        symbol = normalize_symbol(request.args.get('symbol'), default='BTCUSDT')
        market_service = get_market_data_service()
        result = market_service.get_ticker(symbol)

        if result.get('success'):
            return jsonify({'success': True, 'data': result.get('data', {})})
        return jsonify({'success': False, 'error': result.get('message', '获取ticker失败')})
    except Exception as e:
        logger.error(f"获取ticker失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/market/klines', methods=['GET'])
def api_market_klines():
    """获取K线数据"""
    try:
        symbol = normalize_symbol(request.args.get('symbol'), default='BTCUSDT')
        interval = (request.args.get('interval') or '5m').strip()
        limit = request.args.get('limit', 200, type=int)

        market_service = get_market_data_service()
        result = market_service.get_klines(symbol=symbol, interval=interval, limit=limit)

        if result.get('success'):
            return jsonify({'success': True, 'data': result.get('data', {})})
        return jsonify({'success': False, 'error': result.get('message', '获取K线失败')})
    except Exception as e:
        logger.error(f"获取K线失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/market/depth', methods=['GET'])
def api_market_depth():
    """获取买卖盘深度"""
    try:
        symbol = normalize_symbol(request.args.get('symbol'), default='BTCUSDT')
        limit = request.args.get('limit', 5, type=int)

        market_service = get_market_data_service()
        result = market_service.get_depth(symbol=symbol, limit=limit)

        if result.get('success'):
            return jsonify({'success': True, 'data': result.get('data', {})})
        return jsonify({'success': False, 'error': result.get('message', '获取深度失败')})
    except Exception as e:
        logger.error(f"获取深度失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/market/snapshot', methods=['GET'])
def api_market_snapshot():
    """获取仪表盘行情快照（ticker + klines + depth）"""
    try:
        symbol = normalize_symbol(request.args.get('symbol'), default='BTCUSDT')
        interval = (request.args.get('interval') or '5m').strip()
        kline_limit = request.args.get('kline_limit', 200, type=int)
        depth_limit = request.args.get('depth_limit', 5, type=int)

        market_service = get_market_data_service()
        result = market_service.get_dashboard_snapshot(
            symbol=symbol,
            interval=interval,
            kline_limit=kline_limit,
            depth_limit=depth_limit
        )

        if result.get('success'):
            return jsonify({'success': True, 'data': result.get('data', {})})
        return jsonify({'success': False, 'error': result.get('message', '获取行情快照失败')})
    except Exception as e:
        logger.error(f"获取行情快照失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trades/fills', methods=['GET'])
def api_trade_fills():
    """获取成交明细（支持分页/筛选）"""
    try:
        repo = get_trade_fill_repository()

        symbol = (request.args.get('symbol') or '').strip().upper().replace('/', '')
        strategy_name = (request.args.get('strategy_name') or '').strip()
        action_type = (request.args.get('action_type') or '').strip().lower()
        start_time = (request.args.get('start_time') or '').strip()
        end_time = (request.args.get('end_time') or '').strip()

        page = max(1, request.args.get('page', 1, type=int))
        page_size = max(1, min(500, request.args.get('page_size', 20, type=int)))
        offset = (page - 1) * page_size

        items = repo.list_fills(
            symbol=symbol,
            strategy_name=strategy_name,
            action_type=action_type,
            start_time=start_time,
            end_time=end_time,
            limit=page_size,
            offset=offset
        )
        total = repo.count_fills(
            symbol=symbol,
            strategy_name=strategy_name,
            action_type=action_type,
            start_time=start_time,
            end_time=end_time
        )

        return jsonify({
            'success': True,
            'data': {
                'items': items,
                'page': page,
                'page_size': page_size,
                'total': total,
                'total_pages': (total + page_size - 1) // page_size
            }
        })
    except Exception as e:
        logger.error(f"获取成交明细失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trades/fills/summary', methods=['GET'])
def api_trade_fills_summary():
    """获取成交明细汇总"""
    try:
        repo = get_trade_fill_repository()
        return jsonify({'success': True, 'data': repo.get_summary()})
    except Exception as e:
        logger.error(f"获取成交汇总失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trades/sync', methods=['POST'])
def api_sync_binance_trades():
    """手动触发币安交易同步"""
    try:
        from scripts.binance_trade_sync import BinanceTradeSync
        
        data = request.get_json() or {}
        hours = data.get('hours', 24)
        symbols = data.get('symbols')
        
        sync = BinanceTradeSync()
        result = sync.sync_trades(
            symbols=symbols,
            since_hours=hours
        )
        
        return jsonify({
            'success': True,
            'message': f'同步完成: 导入 {result["imported"]} 笔, 跳过 {result["skipped"]} 笔',
            'data': result
        })
    except Exception as e:
        logger.error(f"手动同步失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trades/sync/status', methods=['GET'])
def api_get_sync_status():
    """获取同步服务状态"""
    try:
        from scripts.binance_trade_sync import get_sync_status
        status = get_sync_status()
        return jsonify({'success': True, 'data': status})
    except Exception as e:
        logger.error(f"获取同步状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


# 信号日志文件路径（与 StrategyLogger 一致）
SIGNAL_LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'trade_signals.json')

@app.route('/api/signal_logs')
def api_signal_logs():
    """获取策略监控信号日志"""
    try:
        limit = request.args.get('limit', 100, type=int)
        logs = []
        
        if os.path.exists(SIGNAL_LOG_FILE):
            with open(SIGNAL_LOG_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            log_entry = json.loads(line)
                            # 日志条目直接包含所有字段（QuantJSONFormatter 格式）
                            if 'event_type' in log_entry:
                                logs.append(log_entry)
                        except json.JSONDecodeError:
                            continue
        
        # 按时间倒序排列
        logs = sorted(logs, key=lambda x: x.get('timestamp', ''), reverse=True)[:limit]
        
        return jsonify({'success': True, 'data': logs})
    except Exception as e:
        logger.error(f"获取信号日志失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trading/start', methods=['POST'])
def start_trading():
    """启动自动交易"""
    try:
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        
        # 1. 启动策略管理器（先启动扫描循环）
        if strategy_manager:
            if not strategy_manager._running:
                strategy_manager.start(interval=60)
                logger.info("[API] 策略引擎已启动")
            strategy_manager.start_all()
            logger.info("[API] 所有策略已启动")
        
        # 2. 启动订单执行器（允许执行交易）
        order_executor.start_auto_trading()
        logger.info("[API] 订单执行器已启动，自动交易已开启")
        
        return jsonify({'success': True, 'message': '自动交易已启动'})
    except Exception as e:
        logger.error(f"[API] 启动交易失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trading/stop', methods=['POST'])
def stop_trading():
    """停止自动交易"""
    try:
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        
        # 1. 停止订单执行器（阻止新交易）
        order_executor.stop_auto_trading()
        logger.info("[API] 订单执行器已停止")
        
        # 2. 停止策略管理器（停止扫描循环）
        if strategy_manager:
            strategy_manager.stop()
            logger.info("[API] 策略引擎已停止")
        
        return jsonify({'success': True, 'message': '自动交易已停止'})
    except Exception as e:
        logger.error(f"[API] 停止交易失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trading/emergency_stop', methods=['POST'])
def emergency_stop():
    """紧急停止 - 停止交易并平仓"""
    try:
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        
        # 先停止策略管理器
        if strategy_manager:
            strategy_manager.stop()
        
        success = order_executor.emergency_stop()
        return jsonify({
            'success': success,
            'message': '紧急停止已执行，所有持仓已平仓' if success else '紧急停止执行失败'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/position/close', methods=['POST'])
def close_position():
    """平仓指定交易对"""
    try:
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        data = request.get_json()
        symbol = data.get('symbol')
        
        if not symbol:
            return jsonify({'success': False, 'error': '缺少symbol参数'})

        result = order_executor.close_position_manual(symbol)
        if result.get('success'):
            return jsonify({
                'success': True,
                'message': f'{symbol} 平仓成功',
                'data': result
            })
        return jsonify({
            'success': False,
            'error': result.get('error', f'{symbol} 平仓失败')
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/position/close_all', methods=['POST'])
def close_all_positions():
    """平掉所有持仓"""
    try:
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        result = order_executor.close_all_positions_manual()
        if result.get('success'):
            return jsonify({
                'success': True,
                'message': f'已平仓 {result.get("closed_count", 0)} 个持仓',
                'data': result
            })
        return jsonify({
            'success': False,
            'error': result.get('error', '部分持仓平仓失败'),
            'data': result
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ==================== AI模型配置API ====================

@app.route('/api/ai/models', methods=['GET'])
def api_ai_models():
    """获取所有AI模型及可用状态"""
    try:
        manager = get_ai_config_manager()
        data = manager.list_models_with_status()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"获取AI模型列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/ai/providers/<provider_key>', methods=['GET'])
def api_get_ai_provider(provider_key):
    """获取指定AI模型配置"""
    try:
        manager = get_ai_config_manager()
        data = manager.get_provider_config(provider_key)
        
        if not data:
            return jsonify({'success': False, 'error': '未找到该AI模型配置'})
        
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"获取AI模型配置失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/ai/providers/<provider_key>', methods=['POST'])
def api_save_ai_provider(provider_key):
    """保存AI模型配置"""
    try:
        manager = get_ai_config_manager()
        data = request.get_json() or {}

        api_key = (data.get('api_key') or '').strip()
        base_url = (data.get('base_url') or '').strip()
        model_name = (data.get('model_name') or '').strip()
        is_enabled = bool(data.get('is_enabled', False))

        saved = manager.save_provider_config(
            provider_key=provider_key,
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            is_enabled=is_enabled
        )

        return jsonify({
            'success': True,
            'message': f'{provider_key} 配置已保存',
            'data': saved
        })
    except Exception as e:
        logger.error(f"保存AI模型配置失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/ai/providers/<provider_key>/disable', methods=['POST'])
def api_disable_ai_provider(provider_key):
    """禁用指定AI模型"""
    try:
        manager = get_ai_config_manager()
        disabled = manager.disable_provider(provider_key)
        return jsonify({
            'success': True,
            'message': f'{provider_key} 已禁用',
            'data': disabled
        })
    except Exception as e:
        logger.error(f"禁用AI模型失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/ai/providers/<provider_key>/test', methods=['POST'])
def api_test_ai_provider(provider_key):
    """测试指定AI模型连通性"""
    try:
        llm_service = LLMService()
        payload = {
            'symbol': 'BTCUSDT',
            'interval': '5m',
            'signal': 'BUY',
            'strategy_name': 'API_CONNECTIVITY_TEST',
            'price': 100000.0,
            'indicators': {'rsi': 50.0},
            'risk_context': {'global_auto_trading': False}
        }

        result = llm_service.analyze_trade(provider_key, payload)
        if result.get('success'):
            return jsonify({
                'success': True,
                'message': f'{provider_key} 连接测试成功',
                'data': result
            })
        return jsonify({
            'success': False,
            'error': result.get('reason') or result.get('error') or '模型测试失败',
            'data': result
        })
    except Exception as e:
        logger.error(f"测试AI模型失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

# ==================== WebSocket ====================

@app.route('/api/ohlcv')
def api_ohlcv():
    """获取K线数据"""
    try:
        symbol = request.args.get('symbol', 'BTC/USDT')
        timeframe = request.args.get('timeframe', '1h')
        limit = request.args.get('limit', 100, type=int)
        
        exchange, _, _, _ = get_components()
        
        if exchange is None:
            return jsonify({'success': False, 'error': '交易所连接失败'})
        
        ohlcv = exchange.get_ohlcv(symbol, timeframe=timeframe, limit=limit)
        
        if ohlcv is None:
            return jsonify({'success': False, 'error': '获取K线数据失败'})
        
        # 转换为前端需要的格式
        data = []
        for candle in ohlcv:
            data.append({
                'time': candle[0],  # timestamp
                'open': candle[1],
                'high': candle[2],
                'low': candle[3],
                'close': candle[4],
                'volume': candle[5]
            })
        
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"获取K线数据失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/settings', methods=['GET'])
def get_settings():
    """获取设置 - 从运行中的组件和环境变量读取实时值"""
    try:
        # 从运行中的risk_manager读取实时配置
        from trading_core.risk_manager import get_risk_manager
        risk_manager = get_risk_manager()
        
        settings = {
            # API配置（从环境变量读取）
            'binance_api_key': os.getenv('BINANCE_API_KEY', ''),
            'binance_secret_key': '',  # 不返回secret
            'telegram_bot_token': os.getenv('TELEGRAM_BOT_TOKEN', ''),
            'telegram_chat_id': os.getenv('TELEGRAM_CHAT_ID', ''),
            # 邮件配置（从环境变量读取）
            'email_enabled': os.getenv('EMAIL_ENABLED', 'false').lower() == 'true',
            'email_host': os.getenv('EMAIL_HOST', 'smtp.gmail.com'),
            'email_port': int(os.getenv('EMAIL_PORT', 587)),
            'email_user': os.getenv('EMAIL_USER', ''),
            'email_password': '',  # 不返回密码
            'email_to': os.getenv('EMAIL_TO', ''),
            # 交易参数（从运行中的组件读取实时值）
            'max_position_usdt': risk_manager.max_position_usdt,
            'max_daily_loss_usdt': risk_manager.max_daily_loss_usdt,
            'default_leverage': risk_manager.default_leverage,
            'stop_loss_percent': risk_manager.stop_loss_percent,
            'take_profit_percent': risk_manager.take_profit_percent,
            'trailing_stop_percent': risk_manager.trailing_stop_percent,
            'max_positions_count': risk_manager.max_positions_count,
        }

        return jsonify({'success': True, 'data': settings})
    except Exception as e:
        logger.error(f"获取设置失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/settings', methods=['POST'])
def save_settings():
    """保存设置到 .env 文件"""
    try:
        data = request.get_json()
        env_file = os.path.join(os.path.dirname(__file__), '..', '.env')
        
        # 读取现有 .env 内容
        env_lines = []
        if os.path.exists(env_file):
            with open(env_file, 'r', encoding='utf-8') as f:
                env_lines = f.readlines()
        
        # 构建新的配置字典
        new_config = {
            'MAX_POSITION_USDT': data.get('max_position_usdt', 50),
            'MAX_DAILY_LOSS_USDT': data.get('max_daily_loss_usdt', 30),
            'DEFAULT_LEVERAGE': data.get('default_leverage', 3),
            'STOP_LOSS_PERCENT': data.get('stop_loss_percent', 2),
            'TAKE_PROFIT_PERCENT': data.get('take_profit_percent', 4),
            'TRAILING_STOP_PERCENT': data.get('trailing_stop_percent', 1.0),
            'MAX_POSITIONS_COUNT': data.get('max_positions_count', 2),
            'EMAIL_ENABLED': 'true' if data.get('email_enabled') else 'false',
            'EMAIL_HOST': data.get('email_host', ''),
            'EMAIL_PORT': data.get('email_port', 587),
            'EMAIL_USER': data.get('email_user', ''),
            'EMAIL_TO': data.get('email_to', ''),
            'DEFAULT_STRATEGY': data.get('default_strategy', 'MA99_MTF'),
            'USE_CONSENSUS_STRATEGY': 'true' if data.get('use_consensus') else 'false',
            'WEB_PORT': data.get('web_port', 5000),
            'LOG_LEVEL': data.get('log_level', 'INFO'),
        }
        
        # 更新 API 密钥（如果提供了）
        if data.get('api_key'):
            new_config['BINANCE_API_KEY'] = data['api_key']
        if data.get('api_secret'):
            new_config['BINANCE_SECRET_KEY'] = data['api_secret']
        if data.get('telegram_token'):
            new_config['TELEGRAM_BOT_TOKEN'] = data['telegram_token']
        if data.get('telegram_chat_id'):
            new_config['TELEGRAM_CHAT_ID'] = data['telegram_chat_id']
        
        # 更新 .env 文件
        updated_lines = []
        existing_keys = set()
        
        for line in env_lines:
            line = line.rstrip()
            if '=' in line and not line.startswith('#'):
                key = line.split('=')[0]
                if key in new_config:
                    updated_lines.append(f"{key}={new_config[key]}")
                    existing_keys.add(key)
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)
        
        # 添加新配置项
        for key, value in new_config.items():
            if key not in existing_keys:
                updated_lines.append(f"{key}={value}")
        
        # 写回文件
        with open(env_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(updated_lines) + '\n')
        
        # 同时更新运行中的组件和全局环境变量
        try:
            # 更新交易参数
            from trading_core.risk_manager import get_risk_manager
            risk_manager = get_risk_manager()
            risk_manager.max_position_usdt = float(data.get('max_position_usdt', 100))
            risk_manager.max_daily_loss_usdt = float(data.get('max_daily_loss_usdt', 50))
            risk_manager.default_leverage = int(data.get('default_leverage', 3))
            risk_manager.max_positions_count = int(data.get('max_positions_count', 1))
            risk_manager.stop_loss_percent = float(data.get('stop_loss_percent', 2))
            risk_manager.take_profit_percent = float(data.get('take_profit_percent', 4))
            risk_manager.trailing_stop_percent = float(data.get('trailing_stop_percent', 1.0))
            
            # 更新全局环境变量（让其他组件也能读取新值）
            os.environ['MAX_POSITION_USDT'] = str(data.get('max_position_usdt', 100))
            os.environ['MAX_DAILY_LOSS_USDT'] = str(data.get('max_daily_loss_usdt', 50))
            os.environ['DEFAULT_LEVERAGE'] = str(data.get('default_leverage', 3))
            os.environ['MAX_POSITIONS_COUNT'] = str(data.get('max_positions_count', 1))
            os.environ['STOP_LOSS_PERCENT'] = str(data.get('stop_loss_percent', 2))
            os.environ['TAKE_PROFIT_PERCENT'] = str(data.get('take_profit_percent', 4))
            os.environ['TRAILING_STOP_PERCENT'] = str(data.get('trailing_stop_percent', 1.0))
            os.environ['EMAIL_ENABLED'] = 'true' if data.get('email_enabled') else 'false'
            os.environ['EMAIL_HOST'] = data.get('email_host', '')
            os.environ['EMAIL_PORT'] = str(data.get('email_port', 587))
            os.environ['EMAIL_USER'] = data.get('email_user', '')
            os.environ['EMAIL_TO'] = data.get('email_to', '')
            
            # 更新API密钥
            if data.get('api_key'):
                os.environ['BINANCE_API_KEY'] = data['api_key']
            if data.get('api_secret'):
                os.environ['BINANCE_SECRET_KEY'] = data['api_secret']
            if data.get('telegram_token'):
                os.environ['TELEGRAM_BOT_TOKEN'] = data['telegram_token']
            if data.get('telegram_chat_id'):
                os.environ['TELEGRAM_CHAT_ID'] = data['telegram_chat_id']

            logger.info("✅ 运行中组件和环境变量已更新")
        except Exception as e:
            logger.warning(f"运行中组件更新失败（将在重启后生效）: {e}")
        
        logger.info("✅ 设置已保存并生效")
        return jsonify({'success': True, 'message': '设置已保存并生效'})
        
    except Exception as e:
        logger.error(f"保存设置失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/reset_settings', methods=['POST'])
def reset_settings():
    """恢复默认配置并写回.env"""
    default_settings = {
        'max_position_usdt': 50,
        'max_daily_loss_usdt': 30,
        'default_leverage': 3,
        'max_positions_count': 2,
        'stop_loss_percent': 2,
        'take_profit_percent': 4,
        'trailing_stop_percent': 1.0,
        'email_enabled': False,
        'email_host': 'smtp.gmail.com',
        'email_port': 587,
        'email_user': '',
        'email_to': '',
        'web_port': int(os.getenv('WEB_PORT', 5000)),
        'log_level': os.getenv('LOG_LEVEL', 'INFO'),
        'default_strategy': 'MA99_MTF',
        'use_consensus': False
    }

    with app.test_request_context(json=default_settings):
        response = save_settings()
        payload = response.get_json()
        if payload and payload.get('success'):
            payload['message'] = '已恢复默认设置'
        return response

@app.route('/api/clear_data', methods=['POST'])
def clear_data():
    """清理交易与信号数据（保留配置）"""
    try:
        # 1) 清理 order_executor 的本地历史库
        trade_history_db = os.path.join(log_dir, 'trade_history.db')
        if os.path.exists(trade_history_db):
            conn = sqlite3.connect(trade_history_db)
            cur = conn.cursor()
            cur.execute("DELETE FROM trades")
            cur.execute("DELETE FROM signals")
            conn.commit()
            conn.close()

        # 2) 清理统一业务库中的成交明细
        main_db = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'trading_system.db')
        if os.path.exists(main_db):
            conn = sqlite3.connect(main_db)
            cur = conn.cursor()
            cur.execute("DELETE FROM trade_fills")
            conn.commit()
            conn.close()

        # 3) 删除信号日志文件
        for file_path in [
            os.path.join(log_dir, 'trade_signals.json'),
            os.path.join(log_dir, 'signals_history.jsonl')
        ]:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass

        return jsonify({'success': True, 'message': '交易数据已清除'})
    except Exception as e:
        logger.error(f"清除交易数据失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

# ==================== 策略AI配置API ====================

@app.route('/api/strategy/ai-config', methods=['POST'])
def save_strategy_ai_config():
    """保存策略AI配置（不影响交易执行，仅存储）"""
    try:
        data = request.get_json() or {}

        strategy_key = data.get('strategy_key')
        ai_model = data.get('ai_model')
        ai_enabled = bool(data.get('ai_enabled', False))
        follow_global = bool(data.get('follow_global', True))

        if not strategy_key:
            return jsonify({'success': False, 'error': 'strategy_key不能为空'})

        config_file = os.path.join(log_dir, 'strategy_ai_config.json')

        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                configs = json.load(f)
        else:
            configs = {}

        configs[strategy_key] = {
            'ai_model': ai_model,
            'ai_enabled': ai_enabled,
            'follow_global': follow_global,
            'updated_at': time.time()
        }

        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(configs, f, ensure_ascii=False, indent=2)

        return jsonify({
            'success': True,
            'message': '策略AI配置已保存',
            'data': configs[strategy_key]
        })

    except Exception as e:
        logger.error(f"保存策略AI配置失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategy/ai-config/<strategy_key>', methods=['GET'])
def get_strategy_ai_config(strategy_key):
    """获取策略AI配置"""
    try:
        config_file = os.path.join(log_dir, 'strategy_ai_config.json')

        if not os.path.exists(config_file):
            return jsonify({'success': True, 'data': {}})

        with open(config_file, 'r', encoding='utf-8') as f:
            configs = json.load(f)

        return jsonify({
            'success': True,
            'data': configs.get(strategy_key, {})
        })

    except Exception as e:
        logger.error(f"获取策略AI配置失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/strategies/configs', methods=['GET'])
def list_strategy_runtime_configs():
    """列出策略运行配置（strategy_configs 表）"""
    try:
        repo = get_strategy_config_repo()
        status = (request.args.get('status') or '').strip().lower()
        configs = repo.list_strategy_configs(status=status)
        return jsonify({'success': True, 'data': configs})
    except Exception as e:
        logger.error(f"获取策略配置列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/strategies/configs/<strategy_key>', methods=['GET'])
def get_strategy_runtime_config(strategy_key):
    """获取单个策略运行配置"""
    try:
        repo = get_strategy_config_repo()
        config = repo.get_strategy_config(strategy_key)
        if not config:
            return jsonify({'success': False, 'error': f'未找到策略配置: {strategy_key}'})
        return jsonify({'success': True, 'data': config})
    except Exception as e:
        logger.error(f"获取策略配置失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/strategies/configs', methods=['POST'])
def upsert_strategy_runtime_config():
    """新增/更新策略运行配置"""
    try:
        data = request.get_json() or {}
        repo = get_strategy_config_repo()

        strategy_key = (data.get('strategy_key') or '').strip()
        strategy_name = (data.get('strategy_name') or strategy_key or '').strip()
        symbol = (data.get('symbol') or '').strip().upper().replace('/', '')
        interval = (data.get('interval') or '5m').strip()
        ai_enabled = bool(data.get('ai_enabled', True))
        ai_model = (data.get('ai_model') or '').strip()
        telegram_notify = bool(data.get('telegram_notify', True))
        auto_trade_follow_global = bool(data.get('auto_trade_follow_global', True))
        status = (data.get('status') or 'stopped').strip().lower()
        config_json = data.get('config_json') or ''

        if not strategy_key:
            return jsonify({'success': False, 'error': 'strategy_key不能为空'})
        if not symbol:
            return jsonify({'success': False, 'error': 'symbol不能为空'})

        saved = repo.upsert_strategy_config(
            strategy_key=strategy_key,
            strategy_name=strategy_name,
            symbol=symbol,
            interval=interval,
            ai_enabled=ai_enabled,
            ai_model=ai_model,
            telegram_notify=telegram_notify,
            auto_trade_follow_global=auto_trade_follow_global,
            status=status,
            config_json=config_json
        )
        return jsonify({'success': True, 'message': '策略配置已保存', 'data': saved})
    except Exception as e:
        logger.error(f"保存策略配置失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/strategies/configs/<strategy_key>/status', methods=['POST'])
def update_strategy_runtime_status(strategy_key):
    """更新策略运行状态（running/stopped/paused）"""
    try:
        data = request.get_json() or {}
        status = (data.get('status') or '').strip().lower()
        if status not in {'running', 'stopped', 'paused'}:
            return jsonify({'success': False, 'error': 'status必须是 running/stopped/paused'})

        repo = get_strategy_config_repo()
        updated = repo.update_status(strategy_key, status)
        if not updated:
            return jsonify({'success': False, 'error': f'未找到策略配置: {strategy_key}'})
        return jsonify({'success': True, 'message': '策略状态已更新', 'data': updated})
    except Exception as e:
        logger.error(f"更新策略状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    logger.info('客户端已连接')
    emit('connected', {'data': 'Connected to trading server'})

@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开，清理行情订阅"""
    sid = request.sid
    with _market_subscriptions_lock:
        sub = _market_subscriptions.pop(sid, None)
    if sub:
        room = f"market:{sub.get('symbol')}:{sub.get('interval')}"
        try:
            leave_room(room)
        except Exception:
            pass

@socketio.on('subscribe_market')
def handle_subscribe_market(data):
    """订阅行情推送（按币种+周期分房间）"""
    sid = request.sid
    symbol = normalize_symbol((data or {}).get('symbol'), default='BTCUSDT')
    interval = ((data or {}).get('interval') or '5m').strip()
    if interval not in get_market_data_service().get_supported_intervals():
        interval = '5m'

    with _market_subscriptions_lock:
        old = _market_subscriptions.get(sid)
        if old:
            old_room = f"market:{old.get('symbol')}:{old.get('interval')}"
            leave_room(old_room)
        _market_subscriptions[sid] = {'symbol': symbol, 'interval': interval}

    room = f"market:{symbol}:{interval}"
    join_room(room)
    emit('market_subscribed', {'symbol': symbol, 'interval': interval})

@socketio.on('unsubscribe_market')
def handle_unsubscribe_market():
    """取消行情订阅"""
    sid = request.sid
    with _market_subscriptions_lock:
        old = _market_subscriptions.pop(sid, None)
    if old:
        room = f"market:{old.get('symbol')}:{old.get('interval')}"
        leave_room(room)
    emit('market_unsubscribed', {'success': True})

@socketio.on('heartbeat')
def handle_heartbeat(data):
    """处理客户端心跳"""
    logger.debug(f'收到心跳: {data}')
    emit('heartbeat_ack', {'timestamp': time.time(), 'status': 'ok'})

def broadcast_status():
    """后台线程：定期广播状态更新"""
    while True:
        try:
            exchange, risk_manager, order_executor, strategy_manager = get_components()
            
            if exchange is None:
                socketio.emit('status_update', {
                    'error': '交易所未连接',
                    'timestamp': time.time()
                })
                time.sleep(5)
                continue
            
            balance = exchange.get_balance()
            positions = exchange.get_positions()
            risk_status = risk_manager.get_status()
            strategy_status = strategy_manager.get_status() if strategy_manager else {}
            executor_status = order_executor.get_status() if order_executor else {'auto_trading': False}
            
            total_unrealized = sum(p.get('unrealized_pnl', 0) for p in positions)
            
            # 更新 risk_status 中的持仓数量
            risk_status['current_positions_count'] = len(positions)
            
            socketio.emit('status_update', {
                'balance': balance,
                'positions': positions,
                'position_count': len(positions),
                'total_unrealized_pnl': round(total_unrealized, 2),
                'risk_status': risk_status,
                'auto_trading': executor_status.get('auto_trading', False),
                'strategies': strategy_status,
                'timestamp': time.time()
            })
            
            time.sleep(5)  # 每5秒更新一次
        except Exception as e:
            logger.error(f"广播状态失败: {e}")
            time.sleep(5)


def broadcast_signal_logs():
    """后台线程：监控并广播新的信号日志"""
    last_position = 0
    logger.info(f'[SignalLogBroadcast] Starting monitor for {SIGNAL_LOG_FILE}')
    
    while True:
        try:
            if os.path.exists(SIGNAL_LOG_FILE):
                with open(SIGNAL_LOG_FILE, 'r', encoding='utf-8') as f:
                    f.seek(last_position)
                    new_lines = f.readlines()
                    if new_lines:
                        logger.debug(f'[SignalLogBroadcast] Found {len(new_lines)} new lines')
                    last_position = f.tell()
                    
                    for line in new_lines:
                        line = line.strip()
                        if line:
                            try:
                                log_entry = json.loads(line)
                                # 只广播包含 event_type 的日志条目
                                if 'event_type' in log_entry:
                                    logger.debug(f'[SignalLogBroadcast] Broadcasting {log_entry["event_type"]} log')
                                    socketio.emit('signal_log_update', log_entry)
                            except json.JSONDecodeError:
                                continue
            
            time.sleep(1)  # 每秒检查一次新日志
        except Exception as e:
            logger.error(f"广播信号日志失败: {e}")
            time.sleep(5)

def broadcast_market_updates():
    """后台线程：按订阅房间推送行情"""
    while True:
        try:
            with _market_subscriptions_lock:
                active_pairs = {(v.get('symbol'), v.get('interval')) for v in _market_subscriptions.values()}

            if not active_pairs:
                time.sleep(1)
                continue

            market_service = get_market_data_service()
            for symbol, interval in active_pairs:
                room = f"market:{symbol}:{interval}"
                ticker = market_service.get_ticker(symbol)
                depth = market_service.get_depth(symbol, limit=5)
                payload = {
                    'symbol': symbol,
                    'interval': interval,
                    'ticker': ticker.get('data') if ticker.get('success') else None,
                    'depth': depth.get('data') if depth.get('success') else None,
                    'last_kline': None,
                    'timestamp': time.time()
                }
                socketio.emit('market_update', payload, room=room)

            time.sleep(1)
        except Exception as e:
            logger.error(f"广播行情失败: {e}")
            time.sleep(1.5)


# ==================== 策略配置管理 ====================

# 策略配置文件路径
STRATEGY_CONFIG_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'strategy_config.json')

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
                # 合并默认配置
                return {**default_config, **config}
    except Exception as e:
        logger.error(f"加载策略配置失败: {e}")
    
    return default_config

def save_strategy_config(config):
    """保存策略配置"""
    try:
        os.makedirs(os.path.dirname(STRATEGY_CONFIG_FILE), exist_ok=True)
        with open(STRATEGY_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存策略配置失败: {e}")
        return False

@app.route('/api/strategy/config', methods=['GET'])
def get_strategy_config():
    """获取策略配置"""
    try:
        config = load_strategy_config()
        return jsonify({'success': True, 'data': config})
    except Exception as e:
        logger.error(f"获取策略配置失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/strategy/config', methods=['POST'])
def update_strategy_config():
    """更新策略配置"""
    try:
        data = request.get_json()
        
        # 验证数据
        if not data or 'mode' not in data:
            return jsonify({'success': False, 'error': '缺少必要参数'})
        
        # 加载现有配置
        config = load_strategy_config()
        
        # 更新配置
        config['mode'] = data.get('mode', config['mode'])
        config['singleStrategy'] = data.get('singleStrategy', config['singleStrategy'])
        config['consensusStrategies'] = data.get('consensusStrategies', config['consensusStrategies'])
        config['consensusThreshold'] = data.get('consensusThreshold', config['consensusThreshold'])
        
        # 保存配置
        if save_strategy_config(config):
            logger.info(f"✅ 策略配置已更新: {config['mode']} 模式")
            return jsonify({'success': True, 'message': '策略配置已保存'})
        else:
            return jsonify({'success': False, 'error': '保存配置失败'})
            
    except Exception as e:
        logger.error(f"更新策略配置失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

# ==================== 策略管理API ====================

@app.route('/api/strategies', methods=['GET'])
def get_strategies():
    """获取所有策略状态"""
    try:
        global _strategy_manager
        
        if _strategy_manager is None:
            return jsonify({'success': False, 'error': '策略管理器未初始化'})
        
        status = _strategy_manager.get_status()
        
        # 添加策略配置信息（币种、周期等）
        from trading_core.strategy_engine_adapter import SYMBOLS, TIMEFRAMES
        status['monitored_symbols'] = SYMBOLS
        status['monitored_timeframes'] = TIMEFRAMES
        status['scan_interval'] = 60  # 扫描间隔（秒）
        status['runtime_configs'] = get_strategy_config_repo().list_strategy_configs()
        
        return jsonify({'success': True, 'data': status})
    except Exception as e:
        logger.error(f"获取策略列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/engine/start', methods=['POST'])
def start_strategy_engine():
    """启动策略引擎（扫描循环）"""
    try:
        # 使用全局变量确保实例一致性
        global _exchange, _risk_manager, _order_executor, _strategy_manager
        
        # 初始化组件
        if _exchange is None:
            _exchange = get_exchange_client()
        if _risk_manager is None:
            _risk_manager = get_risk_manager()
        if _order_executor is None:
            _order_executor = get_order_executor()
        if _strategy_manager is None:
            _strategy_manager = get_strategy_manager(_exchange, _risk_manager, _order_executor)
            # 注册默认策略
            if 'MA99_MTF' not in _strategy_manager.strategies:
                from trading_core.strategy_engine_adapter import StrategyConfig
                config = StrategyConfig(
                    name='MA99_MTF',
                    strategy_type='ma99_mtf',
                    symbols=['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
                             'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'DOGE/USDT', 'DOT/USDT'],
                    timeframes=['15m', '1h', '4h'],
                    enabled=True,
                    params={},
                    max_positions=1,
                    position_size_usdt=float(os.getenv('MAX_POSITION_USDT', 50))
                )
                _strategy_manager.register_strategy(config)
        
        if _strategy_manager is None:
            return jsonify({'success': False, 'error': '策略管理器初始化失败'})

        repo = get_strategy_config_repo()
        running_configs = repo.list_strategy_configs(status='running')
        if not running_configs:
            repo.seed_default_strategy_if_missing(
                strategy_key='MA99_MTF_MAIN',
                strategy_name='MA99_MTF',
                symbol='BTCUSDT',
                interval='5m',
                ai_enabled=True,
                ai_model='',
                telegram_notify=True,
                auto_trade_follow_global=True,
                status='running'
            )
            logger.info('[API] 无运行时策略配置，已创建默认配置 MA99_MTF_MAIN')
        
        # 检查是否已在运行
        if _strategy_manager._running:
            return jsonify({'success': True, 'message': '策略引擎已在运行中'})
        
        # 启动策略扫描循环
        logger.info(f'[API] Before start(), _running={_strategy_manager._running}')
        _strategy_manager.start(interval=60)
        logger.info(f'[API] After start(), _running={_strategy_manager._running}')
        _strategy_manager.start_all()
        logger.info(f'[API] After start_all(), _running={_strategy_manager._running}')
        
        # 验证启动状态
        if _strategy_manager._running:
            logger.info('[API] 策略引擎已启动')
            return jsonify({'success': True, 'message': '策略引擎已启动'})
        else:
            logger.error('[API] 策略引擎启动后状态仍为停止')
            return jsonify({'success': False, 'error': '策略引擎启动失败，请检查日志'})
            
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        logger.error(f"启动策略引擎失败: {e}\n{error_detail}")
        return jsonify({'success': False, 'error': str(e), 'detail': error_detail})


@app.route('/api/strategies/engine/stop', methods=['POST'])
def stop_strategy_engine():
    """停止策略引擎（扫描循环）"""
    try:
        global _strategy_manager
        
        if _strategy_manager is None:
            return jsonify({'success': False, 'error': '策略管理器未初始化'})
        
        if not _strategy_manager._running:
            return jsonify({'success': True, 'message': '策略引擎已停止'})
        
        _strategy_manager.stop()
        
        logger.info('[API] 策略引擎已停止')
        return jsonify({'success': True, 'message': '策略引擎已停止'})
    except Exception as e:
        logger.error(f"停止策略引擎失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/<name>/start', methods=['POST'])
def start_strategy(name):
    """启动指定策略"""
    try:
        _, _, _, strategy_manager = get_components()
        if strategy_manager is None:
            return jsonify({'success': False, 'error': '策略管理器未初始化'})
        
        success = strategy_manager.start_strategy(name)
        return jsonify({
            'success': success,
            'message': f'策略 {name} 已启动' if success else f'启动策略 {name} 失败'
        })
    except Exception as e:
        logger.error(f"启动策略失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/<name>/stop', methods=['POST'])
def stop_strategy(name):
    """停止指定策略"""
    try:
        _, _, _, strategy_manager = get_components()
        if strategy_manager is None:
            return jsonify({'success': False, 'error': '策略管理器未初始化'})
        
        success = strategy_manager.stop_strategy(name)
        return jsonify({
            'success': success,
            'message': f'策略 {name} 已停止' if success else f'停止策略 {name} 失败'
        })
    except Exception as e:
        logger.error(f"停止策略失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/<name>/update', methods=['POST'])
def update_strategy(name):
    """更新策略参数"""
    try:
        _, _, _, strategy_manager = get_components()
        if strategy_manager is None:
            return jsonify({'success': False, 'error': '策略管理器未初始化'})
        
        data = request.get_json()
        config = strategy_manager.configs.get(name)
        
        if config is None:
            return jsonify({'success': False, 'error': f'策略 {name} 不存在'})
        
        # 更新配置
        if 'symbols' in data:
            config.symbols = data['symbols']
        if 'timeframes' in data:
            config.timeframes = data['timeframes']
        if 'position_size_usdt' in data:
            config.position_size_usdt = float(data['position_size_usdt'])
        if 'max_positions' in data:
            config.max_positions = int(data['max_positions'])
        if 'enabled' in data:
            config.enabled = bool(data['enabled'])
        if 'params' in data:
            config.params.update(data['params'])
        
        return jsonify({'success': True, 'message': f'策略 {name} 已更新'})
    except Exception as e:
        logger.error(f"更新策略失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/stats', methods=['GET'])
def get_strategy_stats():
    """获取MA99策略信号统计"""
    try:
        _, _, _, strategy_manager = get_components()
        if strategy_manager is None:
            return jsonify({'success': False, 'error': '策略管理器未初始化'})
        
        days = request.args.get('days', 7, type=int)
        stats = strategy_manager.get_signal_stats(days)
        
        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        logger.error(f"获取策略统计失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


def auto_start_strategy():
    """自动启动策略"""
    try:
        time.sleep(3)  # 等待服务器启动
        logger.info('[AutoStart] 正在初始化策略管理器...')
        
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        
        if strategy_manager is None:
            logger.error('[AutoStart] 策略管理器初始化失败')
            return
        
        # 启动策略扫描循环
        strategy_manager.start(interval=60)
        strategy_manager.start_all()
        
        logger.info('[AutoStart] 策略已自动启动，扫描间隔: 60秒')
    except Exception as e:
        logger.error(f'[AutoStart] 自动启动策略失败: {e}')

if __name__ == '__main__':
    # 启动状态广播线程
    status_thread = Thread(target=broadcast_status, daemon=True)
    status_thread.start()
    
    # 启动信号日志广播线程
    log_thread = Thread(target=broadcast_signal_logs, daemon=True)
    log_thread.start()

    # 启动行情广播线程
    market_thread = Thread(target=broadcast_market_updates, daemon=True)
    market_thread.start()
    
    # 启动策略自动启动线程
    auto_start_thread = Thread(target=auto_start_strategy, daemon=True)
    auto_start_thread.start()
    
    # 启动币安交易同步服务（每5分钟同步一次）
    try:
        from scripts.binance_trade_sync import start_sync_service
        start_sync_service(interval=300)
        logger.info("🔄 币安交易同步服务已启动")
    except Exception as e:
        logger.warning(f"币安交易同步服务启动失败: {e}")
    
    # 启动Flask服务器
    host = os.getenv('WEB_HOST', '0.0.0.0')
    port = int(os.getenv('WEB_PORT', 5000))
    
    logger.info(f"🌐 Web管理页面启动: http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=False)
