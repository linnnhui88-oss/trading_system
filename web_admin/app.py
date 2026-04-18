import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 鍏堝姞杞界幆澧冨彉閲忥紝纭繚GEMINI_API_KEY绛夐厤缃彲鐢?
from dotenv import load_dotenv, dotenv_values

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import logging
from threading import Thread, Lock
import time
import json
import hashlib
from datetime import datetime, timezone

from trading_core.exchange_client import get_exchange_client
from trading_core.risk_manager import get_risk_manager
from trading_core.order_executor import get_order_executor
from trading_core.strategy_engine_adapter import get_strategy_manager, StrategyConfig
from trading_core.ai_model_registry import get_all_ai_models
from trading_core.ai_provider_config_manager import AIProviderConfigManager
from trading_core.market_data_service import MarketDataService
from trading_core.trade_fill_repository import TradeFillRepository
from trading_core.strategy_config_repository import StrategyConfigRepository

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(ENV_FILE, override=False)

# 閰嶇疆鏃ュ織
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
app.config['TEMPLATES_AUTO_RELOAD'] = True  # 寮€鍙戞ā寮忎笅鑷姩閲嶈浇妯℃澘
socketio = SocketIO(app, cors_allowed_origins="*")

# 鑾峰彇鏍稿績缁勪欢锛堝欢杩熷垵濮嬪寲锛?
_exchange = None
_risk_manager = None
_order_executor = None
_strategy_manager = None

# AI閰嶇疆绠＄悊鍣紙鐙珛鍒濆鍖栵紝涓嶅奖鍝嶄氦鏄撶郴缁燂級
_ai_config_manager = None

# 鏂板鐨勬暟鎹粨搴撲笌鏈嶅姟
_market_data_service = None
_trade_fill_repo = None
_strategy_config_repo = None
_trade_sync_lock = Lock()
_trade_sync_state_file = os.path.join(PROJECT_ROOT, 'data', 'trade_sync_state.json')


def _read_env_values():
    """Read latest values from .env with os.environ fallback."""
    file_values = dotenv_values(ENV_FILE) if os.path.exists(ENV_FILE) else {}
    merged = {}
    for key, value in file_values.items():
        merged[key] = '' if value is None else str(value)
    return merged


def _env_get(env_values, key, default=''):
    value = env_values.get(key)
    if value is None:
        value = os.getenv(key, default)
    return default if value is None else value


def _to_int(value, default):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_ai_config_manager():
    """Get AI provider config manager lazily."""
    global _ai_config_manager
    
    if _ai_config_manager is None:
        _ai_config_manager = AIProviderConfigManager()
        logger.info('[AI] AIProviderConfigManager initialized')
    
    return _ai_config_manager

def get_market_data_service():
    global _market_data_service
    if _market_data_service is None:
        _market_data_service = MarketDataService()
    return _market_data_service

def get_trade_fill_repo():
    global _trade_fill_repo
    if _trade_fill_repo is None:
        _trade_fill_repo = TradeFillRepository()
    return _trade_fill_repo

def get_strategy_config_repo():
    global _strategy_config_repo
    if _strategy_config_repo is None:
        _strategy_config_repo = StrategyConfigRepository()
    return _strategy_config_repo


def _normalize_symbol_for_exchange(symbol: str) -> str:
    """
    Normalize symbol to ccxt style, e.g. BTCUSDT -> BTC/USDT.
    """
    raw = (symbol or '').strip().upper().replace(' ', '')
    if not raw:
        return ''
    if '/' in raw:
        return raw
    if raw.endswith('USDT') and len(raw) > 4:
        return f"{raw[:-4]}/USDT"
    return raw


def _normalize_symbol_for_fill(symbol: str) -> str:
    return (symbol or '').strip().upper().replace('/', '')


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _trade_to_fill_payload(trade: dict) -> dict:
    info = trade.get('info') or {}
    raw_symbol = trade.get('symbol') or info.get('symbol') or ''
    symbol = _normalize_symbol_for_fill(raw_symbol)
    side = (trade.get('side') or info.get('side') or '').strip().upper()
    if side not in {'BUY', 'SELL'}:
        side = 'BUY'

    position_side = (info.get('positionSide') or '').strip().upper()
    if position_side == 'BOTH':
        position_side = ''

    realized_pnl = _safe_float(
        trade.get('realizedPnl', info.get('realizedPnl', info.get('realizedProfit', 0))),
        0.0
    )
    fee = _safe_float(trade.get('fee', {}).get('cost') if isinstance(trade.get('fee'), dict) else trade.get('fee', 0), 0.0)
    fee_asset = ''
    if isinstance(trade.get('fee'), dict):
        fee_asset = (trade.get('fee', {}).get('currency') or '').strip().upper()
    if not fee_asset:
        fee_asset = (info.get('commissionAsset') or '').strip().upper()

    qty = _safe_float(trade.get('amount', info.get('qty', info.get('executedQty', 0))), 0.0)
    price = _safe_float(trade.get('price', info.get('price', 0)), 0.0)

    timestamp_ms = trade.get('timestamp')
    if timestamp_ms:
        executed_at = datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=timezone.utc).isoformat()
    else:
        executed_at = (trade.get('datetime') or '').strip() or datetime.utcnow().isoformat()

    exchange_trade_id = str(trade.get('id') or info.get('id') or '').strip()
    if not exchange_trade_id:
        fingerprint = '|'.join([
            str(raw_symbol),
            str(side),
            str(trade.get('order') or info.get('orderId') or ''),
            str(timestamp_ms or ''),
            str(qty),
            str(price),
        ])
        exchange_trade_id = f"sync_{hashlib.sha1(fingerprint.encode('utf-8')).hexdigest()[:24]}"

    action_type = 'close' if abs(realized_pnl) > 0 else 'open'

    return {
        "strategy_name": "ACCOUNT_SYNC",
        "symbol": symbol,
        "side": side,
        "position_side": position_side,
        "action_type": action_type,
        "order_id": str(trade.get('order') or info.get('orderId') or ''),
        "exchange_trade_id": exchange_trade_id,
        "quantity": qty,
        "price": price,
        "realized_pnl": realized_pnl,
        "fee": fee,
        "fee_asset": fee_asset,
        "ai_model": "",
        "ai_decision": "EXECUTE",
        "signal_source": "exchange_sync",
        "signal_reason": "synced_from_exchange_account_trades",
        "executed_at": executed_at,
    }


def _trade_timestamp_ms(trade: dict) -> int:
    ts = trade.get('timestamp')
    if ts is None:
        dt = (trade.get('datetime') or '').strip()
        if dt:
            try:
                if dt.endswith('Z'):
                    dt = dt[:-1] + '+00:00'
                return int(datetime.fromisoformat(dt).timestamp() * 1000)
            except Exception:
                return 0
        return 0
    try:
        return int(ts)
    except Exception:
        return 0


def _load_trade_sync_state() -> dict:
    try:
        if os.path.exists(_trade_sync_state_file):
            with open(_trade_sync_state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception as e:
        logger.warning(f"[TradeSync] load state failed: {e}")
    return {'last_sync_ms': 0}


def _save_trade_sync_state(state: dict):
    try:
        os.makedirs(os.path.dirname(_trade_sync_state_file), exist_ok=True)
        with open(_trade_sync_state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[TradeSync] save state failed: {e}")


def _build_trade_sync_symbols(strategy_manager=None) -> list:
    symbols = []
    if strategy_manager and getattr(strategy_manager, 'strategies', None):
        for cfg in strategy_manager.strategies.values():
            for sym in getattr(cfg, 'symbols', []) or []:
                n = _normalize_symbol_for_exchange(sym)
                if n and n not in symbols:
                    symbols.append(n)

    # Default mainstream symbols for backfill safety.
    for sym in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT']:
        if sym not in symbols:
            symbols.append(sym)
    return symbols


def _fetch_trades_paginated(exchange, symbol: str, since_ms: int, limit: int = 200, max_pages: int = 30) -> list:
    all_items = []
    cursor = max(0, int(since_ms or 0))
    stagnant_rounds = 0

    for _ in range(max_pages):
        batch = exchange.get_recent_account_trades(symbol=symbol, since_ms=cursor, limit=limit) or []
        if not batch:
            break

        all_items.extend(batch)

        max_ts = max((_trade_timestamp_ms(t) for t in batch), default=0)
        if max_ts <= cursor:
            stagnant_rounds += 1
            if stagnant_rounds >= 2:
                break
            cursor = cursor + 1
        else:
            stagnant_rounds = 0
            cursor = max_ts + 1

        if len(batch) < limit:
            break

    return all_items


def _sync_account_trades_to_fills(
    symbol_filter: str = '',
    force_backfill: bool = False,
    backfill_days: int = 365
) -> dict:
    """
    Sync exchange account trades into trade_fills table.
    This captures both manual and automated trades under the same API account.
    """
    if not _trade_sync_lock.acquire(blocking=False):
        return {'success': True, 'busy': True, 'fetched': 0, 'inserted': 0, 'skipped': 0}

    try:
        exchange, _, _, strategy_manager = get_components()
        repo = get_trade_fill_repo()
        state = _load_trade_sync_state()
        last_sync_ms = int(state.get('last_sync_ms') or 0)
        now_ms = int(time.time() * 1000)
        default_backfill_since = now_ms - int(max(1, backfill_days) * 86400 * 1000)
        since_ms = default_backfill_since if (force_backfill or last_sync_ms <= 0) else max(default_backfill_since, last_sync_ms - 5 * 60 * 1000)

        normalized_filter = _normalize_symbol_for_exchange(symbol_filter)
        symbols = [normalized_filter] if normalized_filter else _build_trade_sync_symbols(strategy_manager)

        trades = []

        # Some exchanges require explicit symbol for fetch_my_trades, so use per-symbol paginated pulls.
        for sym in symbols[:50]:
            try:
                partial = _fetch_trades_paginated(exchange, sym, since_ms=since_ms, limit=200, max_pages=40)
                if partial:
                    trades.extend(partial)
            except Exception as e:
                logger.warning(f"[TradeSync] pull failed for {sym}: {e}")
                continue

        dedup = {}
        for t in trades or []:
            key = str(t.get('id') or '') or f"{t.get('symbol')}|{t.get('order')}|{t.get('timestamp')}|{t.get('amount')}|{t.get('price')}|{t.get('side')}"
            dedup[key] = t
        unique_trades = list(dedup.values())

        inserted = 0
        skipped = 0
        max_trade_ts = last_sync_ms
        for trade in unique_trades:
            payload = _trade_to_fill_payload(trade)
            trade_ts = _trade_timestamp_ms(trade)
            if trade_ts > max_trade_ts:
                max_trade_ts = trade_ts
            if payload['quantity'] <= 0 or payload['price'] <= 0 or not payload['symbol']:
                skipped += 1
                continue
            if payload.get('exchange_trade_id'):
                exists = repo.get_fill_by_exchange_trade_id(payload['exchange_trade_id'])
                if exists:
                    skipped += 1
                    continue
            repo.create_fill_if_not_exists(payload)
            inserted += 1

        if max_trade_ts > last_sync_ms:
            state['last_sync_ms'] = max_trade_ts
            _save_trade_sync_state(state)

        logger.info(
            f"[TradeSync] symbols={len(symbols)} since={since_ms} fetched={len(unique_trades)} inserted={inserted} skipped={skipped} last_sync_ms={state.get('last_sync_ms', last_sync_ms)}"
        )

        return {
            'success': True,
            'busy': False,
            'symbols': len(symbols),
            'since_ms': since_ms,
            'fetched': len(unique_trades),
            'inserted': inserted,
            'skipped': skipped,
            'last_sync_ms': int(state.get('last_sync_ms') or last_sync_ms),
        }
    except Exception as e:
        logger.warning(f"[TradeSync] sync failed: {e}")
        return {'success': False, 'busy': False, 'error': str(e), 'fetched': 0, 'inserted': 0, 'skipped': 0}
    finally:
        _trade_sync_lock.release()

def get_components():
    """寤惰繜鑾峰彇鏍稿績缁勪欢"""
    global _exchange, _risk_manager, _order_executor, _strategy_manager
    
    # 濡傛灉浠讳綍缁勪欢涓篘one锛岄噸鏂板垵濮嬪寲
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
                
                # 娉ㄥ唽榛樿MA99_MTF绛栫暐
                _register_default_strategy()
                
        except Exception as e:
            logger.error(f"[Components] 缁勪欢鍒濆鍖栧け璐? {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    return _exchange, _risk_manager, _order_executor, _strategy_manager

def _register_default_strategy():
    """Register MA99_MTF strategy as default signal source."""
    global _strategy_manager
    if _strategy_manager is None:
        return
    
    # 妫€鏌ユ槸鍚﹀凡娉ㄥ唽
    if 'MA99_MTF' not in _strategy_manager.strategies:
        # 浣跨敤鍘熷绛栫暐浠ｇ爜涓殑甯佺鍜屽懆鏈?
        config = StrategyConfig(
            name='MA99_MTF',
            strategy_type='ma99_mtf',
            symbols=[
                'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
                'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'DOGE/USDT', 'DOT/USDT'
            ],
            timeframes=['15m', '1h', '4h'],  # 澶氬懆鏈熺洃鎺?
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
            max_positions=1,  # 姣忎釜甯佺鏈€澶?涓寔浠?
            position_size_usdt=float(os.getenv('MAX_POSITION_USDT', 50))  # 鍗曟鏈€澶?0USDT
        )
        _strategy_manager.register_strategy(config)
        logger.info("[Strategy] MA99_MTF strategy registered as default")
        logger.info(f"[Strategy] Monitoring symbols: {len(config.symbols)}")
        logger.info(f"鈴?鐩戞帶鍛ㄦ湡: {', '.join(config.timeframes)}")

# ==================== 椤甸潰璺敱 ====================

@app.route('/')
def dashboard():
    """涓讳华琛ㄧ洏椤甸潰"""
    return render_template('dashboard.html')

@app.route('/trades')
def trades_page():
    """浜ゆ槗璁板綍椤甸潰"""
    return render_template('trades.html')

@app.route('/signals')
def signals_page():
    """淇彿璁板綍椤甸潰"""
    return render_template('signals.html')

@app.route('/settings')
def settings_page():
    """璁剧疆椤甸潰"""
    return render_template('settings.html')

# ==================== API璺敱 ====================

@app.route('/api/status')
def api_status():
    """Get system status."""
    try:
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        
        if exchange is None:
            return jsonify({'success': False, 'error': 'Exchange connection failed, please check proxy settings'})
        
        balance = exchange.get_balance()
        positions = exchange.get_positions()
        risk_status = risk_manager.get_status()
        executor_status = order_executor.get_status()
        strategy_status = strategy_manager.get_status() if strategy_manager else {}
        
        # 璁＄畻鎬荤泩浜?
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
        logger.error(f"鑾峰彇鐘舵€佸け璐? {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trades')
def api_trades():
    """鑾峰彇浜ゆ槗璁板綍 (鍗囩骇涓哄睍绀哄疄闄呮垚浜?Trade Fills)"""
    try:
        repo = get_trade_fill_repo()
        limit = request.args.get('limit', 50, type=int)
        force_backfill = repo.count_fills() == 0
        _sync_account_trades_to_fills(force_backfill=force_backfill)
        # list_fills 鏀寔杩斿洖鎵€鏈?action_type 鐨勫疄闄呮垚浜よ褰?鍖呭惈閮ㄥ垎骞充粨)
        fills = repo.list_fills(limit=limit)
        return jsonify({'success': True, 'data': fills})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/trades/fills', methods=['GET'])
def api_trade_fills():
    """Get trade fills with pagination and filters."""
    try:
        repo = get_trade_fill_repo()

        symbol = _normalize_symbol_for_fill(request.args.get('symbol') or '')
        strategy_name = (request.args.get('strategy_name') or '').strip()
        action_type = (request.args.get('action_type') or '').strip().lower()
        start_time = (request.args.get('start_time') or '').strip()
        end_time = (request.args.get('end_time') or '').strip()

        page = request.args.get('page', 1, type=int) or 1
        page_size = request.args.get('page_size', 50, type=int) or 50
        page = max(1, page)
        page_size = min(500, max(1, page_size))
        offset = (page - 1) * page_size

        # Empty table first query does full backfill, then incremental sync.
        force_backfill = repo.count_fills() == 0
        sync_result = _sync_account_trades_to_fills(symbol_filter=symbol, force_backfill=force_backfill)

        items = repo.list_fills(
            symbol=symbol,
            strategy_name=strategy_name,
            action_type=action_type,
            start_time=start_time,
            end_time=end_time,
            limit=page_size,
            offset=offset,
        )
        total = repo.count_fills(
            symbol=symbol,
            strategy_name=strategy_name,
            action_type=action_type,
            start_time=start_time,
            end_time=end_time,
        )
        total_pages = max(1, (total + page_size - 1) // page_size)

        return jsonify({
            'success': True,
            'data': {
                'items': items,
                'pagination': {
                    'page': page,
                    'page_size': page_size,
                    'total': total,
                    'total_pages': total_pages,
                },
                'summary': repo.get_summary(),
                'sync': sync_result,
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/trades/sync', methods=['POST'])
def api_trades_sync():
    """Manual trigger for account trades backfill/incremental sync."""
    try:
        payload = request.get_json(silent=True) or {}
        force_backfill = bool(payload.get('force_backfill', False))
        backfill_days = int(payload.get('backfill_days', 365) or 365)
        symbol = _normalize_symbol_for_fill(payload.get('symbol') or '')
        result = _sync_account_trades_to_fills(
            symbol_filter=symbol,
            force_backfill=force_backfill,
            backfill_days=backfill_days
        )
        return jsonify({'success': bool(result.get('success')), 'data': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/signals')
def api_signals():
    """鑾峰彇淇彿璁板綍"""
    try:
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        limit = request.args.get('limit', 50, type=int)
        
        # 鑾峰彇绛栫暐淇彿鍜屾暟鎹簱淇彿
        strategy_signals = strategy_manager.get_signals(limit) if strategy_manager else []
        db_signals = order_executor.get_recent_signals(limit)
        
        # 鍚堝苟淇彿锛堢瓥鐣ヤ俊鍙蜂紭鍏堬級
        all_signals = strategy_signals + db_signals
        all_signals = sorted(all_signals, key=lambda x: x.get('timestamp', ''), reverse=True)[:limit]
        
        return jsonify({'success': True, 'data': all_signals})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# 淇彿鏃ュ織鏂囦欢璺緞锛堜笌 StrategyLogger 涓€鑷达級
SIGNAL_LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'trade_signals.json')

@app.route('/api/signal_logs')
def api_signal_logs():
    """鑾峰彇绛栫暐鐩戞帶淇彿鏃ュ織"""
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
                            # 鏃ュ織鏉＄洰鐩存帴鍖呭惈鎵€鏈夊瓧娈碉紙QuantJSONFormatter 鏍煎紡锛?
                            if 'event_type' in log_entry:
                                logs.append(log_entry)
                        except json.JSONDecodeError:
                            continue
        
        # 鎸夋椂闂村€掑簭鎺掑垪
        logs = sorted(logs, key=lambda x: x.get('timestamp', ''), reverse=True)[:limit]
        
        return jsonify({'success': True, 'data': logs})
    except Exception as e:
        logger.error(f"Failed to load signal logs: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trading/start', methods=['POST'])
def start_trading():
    """鍚姩鑷姩浜ゆ槗"""
    try:
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        
        # 1. 鍚姩绛栫暐绠＄悊鍣紙鍏堝惎鍔ㄦ壂鎻忓惊鐜級
        if strategy_manager:
            if not strategy_manager._running:
                strategy_manager.start(interval=60)
                logger.info("[API] Strategy engine started")
            strategy_manager.start_all()
            logger.info("[API] 鎵€鏈夌瓥鐣ュ凡鍚姩")
        
        # 2. 鍚姩璁㈠崟鎵ц鍣紙鍏佽鎵ц浜ゆ槗锛?
        order_executor.start_auto_trading()
        logger.info("[API] Auto trading enabled")
        
        return jsonify({'success': True, 'message': 'Auto trading started'})
    except Exception as e:
        logger.error(f"[API] 鍚姩浜ゆ槗澶辫触: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trading/stop', methods=['POST'])
def stop_trading():
    """鍋滄鑷姩浜ゆ槗"""
    try:
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        
        # 1. 鍋滄璁㈠崟鎵ц鍣紙闃绘鏂颁氦鏄擄級
        order_executor.stop_auto_trading()
        logger.info("[API] 璁㈠崟鎵ц鍣ㄥ凡鍋滄")
        
        # 2. 鍋滄绛栫暐绠＄悊鍣紙鍋滄鎵弿寰幆锛?
        if strategy_manager:
            strategy_manager.stop()
            logger.info("[API] Strategy engine stopped")
        
        return jsonify({'success': True, 'message': 'Auto trading stopped'})
    except Exception as e:
        logger.error(f"[API] 鍋滄浜ゆ槗澶辫触: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trading/emergency_stop', methods=['POST'])
def emergency_stop():
    """Emergency stop trading and close all positions."""
    try:
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        
        # 鍏堝仠姝㈢瓥鐣ョ鐞嗗櫒
        if strategy_manager:
            strategy_manager.stop()
        
        success = order_executor.emergency_stop()
        return jsonify({
            'success': success,
            'message': 'Emergency stop executed, all positions closed' if success else 'Emergency stop execution failed'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/position/close', methods=['POST'])
def close_position():
    """Close position for a specific symbol."""
    try:
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        data = request.get_json()
        symbol = data.get('symbol')
        
        if not symbol:
            return jsonify({'success': False, 'error': '缂哄皯symbol鍙傛暟'})

        result = order_executor.close_position_manual(symbol)
        success = bool(result.get('success'))
        return jsonify({
            'success': success,
            'message': f'{symbol} 骞充粨鎴愬姛' if success else f'{symbol} 骞充粨澶辫触',
            'data': result
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/position/close_all', methods=['POST'])
def close_all_positions():
    """Close all positions."""
    try:
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        result = order_executor.close_all_positions_manual()
        success = bool(result.get('success'))
        return jsonify({
            'success': success,
            'message': '鎵€鏈夋寔浠撳凡骞充粨' if success else '閮ㄥ垎鎸佷粨骞充粨澶辫触',
            'data': result
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ==================== AI妯瀷閰嶇疆API ====================

@app.route('/api/ai/models', methods=['GET'])
def api_ai_models():
    """Get all AI models and their availability."""
    try:
        manager = get_ai_config_manager()
        data = manager.list_models_with_status()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"鑾峰彇AI妯瀷鍒楄〃澶辫触: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/ai/providers/<provider_key>', methods=['GET'])
def api_get_ai_provider(provider_key):
    """鑾峰彇鎸囧畾AI妯瀷閰嶇疆"""
    try:
        manager = get_ai_config_manager()
        data = manager.get_provider_config(provider_key)
        
        if not data:
            return jsonify({'success': False, 'error': '鏈壘鍒拌AI妯瀷閰嶇疆'})
        
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"鑾峰彇AI妯瀷閰嶇疆澶辫触: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/ai/providers/<provider_key>', methods=['POST'])
def api_save_ai_provider(provider_key):
    """淇濆瓨AI妯瀷閰嶇疆"""
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
            'message': f'{provider_key} config saved',
            'data': saved
        })
    except Exception as e:
        logger.error(f"淇濆瓨AI妯瀷閰嶇疆澶辫触: {e}")
        return jsonify({'success': False, 'error': str(e)})

# ==================== WebSocket ====================

@app.route('/api/ohlcv')
def api_ohlcv():
    """Get OHLCV data."""
    try:
        symbol = request.args.get('symbol', 'BTC/USDT')
        timeframe = request.args.get('timeframe', '1h')
        limit = request.args.get('limit', 100, type=int)
        
        exchange, _, _, _ = get_components()
        
        if exchange is None:
            return jsonify({'success': False, 'error': '浜ゆ槗鎵€杩炴帴澶辫触'})
        
        ohlcv = exchange.get_ohlcv(symbol, timeframe=timeframe, limit=limit)
        
        if ohlcv is None:
            return jsonify({'success': False, 'error': 'Failed to fetch OHLCV data'})
        
        # 杞崲涓哄墠绔渶瑕佺殑鏍煎紡
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
        logger.error(f"鑾峰彇K绾挎暟鎹け璐? {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get settings from latest .env values with runtime fallbacks."""
    try:
        from trading_core.risk_manager import get_risk_manager
        risk_manager = get_risk_manager()
        env_values = _read_env_values()

        settings = {
            # API 配置
            'binance_api_key': _env_get(env_values, 'BINANCE_API_KEY', ''),
            'binance_secret_key': _env_get(env_values, 'BINANCE_SECRET_KEY', ''),
            'telegram_bot_token': _env_get(env_values, 'TELEGRAM_BOT_TOKEN', ''),
            'telegram_chat_id': _env_get(env_values, 'TELEGRAM_CHAT_ID', ''),

            # AI API Key
            'gpt_api_key': _env_get(env_values, 'OPENAI_API_KEY', ''),
            'gemini_api_key': _env_get(env_values, 'GEMINI_API_KEY', ''),
            'claude_api_key': _env_get(env_values, 'CLAUDE_API_KEY', ''),
            'qwen_api_key': _env_get(env_values, 'QWEN_API_KEY', ''),
            'kimi_api_key': _env_get(env_values, 'KIMI_API_KEY', ''),
            'deepseek_api_key': _env_get(env_values, 'DEEPSEEK_API_KEY', ''),

            # 邮件配置
            'email_enabled': str(_env_get(env_values, 'EMAIL_ENABLED', 'false')).lower() == 'true',
            'email_host': _env_get(env_values, 'EMAIL_HOST', 'smtp.gmail.com'),
            'email_port': _to_int(_env_get(env_values, 'EMAIL_PORT', 587), 587),
            'email_user': _env_get(env_values, 'EMAIL_USER', ''),
            'email_password': _env_get(env_values, 'EMAIL_PASSWORD', ''),
            'email_to': _env_get(env_values, 'EMAIL_TO', ''),

            # 交易参数
            'max_position_usdt': _to_float(
                _env_get(env_values, 'MAX_POSITION_USDT', risk_manager.max_position_usdt),
                risk_manager.max_position_usdt
            ),
            'max_daily_loss_usdt': _to_float(
                _env_get(env_values, 'MAX_DAILY_LOSS_USDT', risk_manager.max_daily_loss_usdt),
                risk_manager.max_daily_loss_usdt
            ),
            'default_leverage': _to_int(
                _env_get(env_values, 'DEFAULT_LEVERAGE', risk_manager.default_leverage),
                risk_manager.default_leverage
            ),
            'stop_loss_percent': _to_float(
                _env_get(env_values, 'STOP_LOSS_PERCENT', risk_manager.stop_loss_percent),
                risk_manager.stop_loss_percent
            ),
            'take_profit_percent': _to_float(
                _env_get(env_values, 'TAKE_PROFIT_PERCENT', risk_manager.take_profit_percent),
                risk_manager.take_profit_percent
            ),
            'trailing_stop_percent': _to_float(
                _env_get(env_values, 'TRAILING_STOP_PERCENT', risk_manager.trailing_stop_percent),
                risk_manager.trailing_stop_percent
            ),
            'trailing_stop_enabled': str(_env_get(env_values, 'TRAILING_STOP_ENABLED', 'true')).lower() == 'true',
            'max_positions_count': _to_int(
                _env_get(env_values, 'MAX_POSITIONS_COUNT', risk_manager.max_positions_count),
                risk_manager.max_positions_count
            ),

            # 系统设置
            'web_port': _to_int(_env_get(env_values, 'WEB_PORT', 5000), 5000),
            'log_level': _env_get(env_values, 'LOG_LEVEL', 'INFO'),
            'default_strategy': _env_get(env_values, 'DEFAULT_STRATEGY', 'MA99_MTF'),
            'use_consensus': str(_env_get(env_values, 'USE_CONSENSUS_STRATEGY', 'false')).lower() == 'true',
        }
        return jsonify({'success': True, 'data': settings})
    except Exception as e:
        logger.error(f"获取设置失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/settings', methods=['POST'])
def save_settings():
    """保存设置到 .env 文件，并同步到运行时环境。"""
    try:
        data = request.get_json() or {}

        env_lines = []
        if os.path.exists(ENV_FILE):
            with open(ENV_FILE, 'r', encoding='utf-8') as f:
                env_lines = f.readlines()

        new_config = {
            'MAX_POSITION_USDT': data.get('max_position_usdt', 50),
            'MAX_DAILY_LOSS_USDT': data.get('max_daily_loss_usdt', 30),
            'DEFAULT_LEVERAGE': data.get('default_leverage', 3),
            'STOP_LOSS_PERCENT': data.get('stop_loss_percent', 2),
            'TAKE_PROFIT_PERCENT': data.get('take_profit_percent', 4),
            'TRAILING_STOP_PERCENT': data.get('trailing_stop_percent', 1.0),
            'TRAILING_STOP_ENABLED': 'true' if data.get('trailing_stop_enabled', True) else 'false',
            'MAX_POSITIONS_COUNT': data.get('max_positions_count', 2),
            'EMAIL_ENABLED': 'true' if data.get('email_enabled') else 'false',
            'EMAIL_HOST': data.get('email_host', ''),
            'EMAIL_PORT': data.get('email_port', 587),
            'EMAIL_USER': data.get('email_user', ''),
            'EMAIL_PASSWORD': data.get('email_password', ''),
            'EMAIL_TO': data.get('email_to', ''),
            'DEFAULT_STRATEGY': data.get('default_strategy', 'MA99_MTF'),
            'USE_CONSENSUS_STRATEGY': 'true' if data.get('use_consensus') else 'false',
            'WEB_PORT': data.get('web_port', 5000),
            'LOG_LEVEL': data.get('log_level', 'INFO'),
        }

        # API keys support empty string overwrite so clearing values can be saved
        if 'api_key' in data:
            new_config['BINANCE_API_KEY'] = data.get('api_key', '')
        if 'api_secret' in data:
            new_config['BINANCE_SECRET_KEY'] = data.get('api_secret', '')
        if 'telegram_token' in data:
            new_config['TELEGRAM_BOT_TOKEN'] = data.get('telegram_token', '')
        if 'telegram_chat_id' in data:
            new_config['TELEGRAM_CHAT_ID'] = data.get('telegram_chat_id', '')

        if 'gpt_api_key' in data:
            new_config['OPENAI_API_KEY'] = data.get('gpt_api_key', '')
        if 'gemini_api_key' in data:
            new_config['GEMINI_API_KEY'] = data.get('gemini_api_key', '')
        if 'claude_api_key' in data:
            new_config['CLAUDE_API_KEY'] = data.get('claude_api_key', '')
        if 'qwen_api_key' in data:
            new_config['QWEN_API_KEY'] = data.get('qwen_api_key', '')
        if 'kimi_api_key' in data:
            new_config['KIMI_API_KEY'] = data.get('kimi_api_key', '')
        if 'deepseek_api_key' in data:
            new_config['DEEPSEEK_API_KEY'] = data.get('deepseek_api_key', '')

        updated_lines = []
        existing_keys = set()

        for line in env_lines:
            original_line = line.rstrip('\n')
            stripped = original_line.strip()

            if '=' in stripped and not stripped.startswith('#'):
                key = stripped.split('=', 1)[0].strip()
                if key in new_config:
                    updated_lines.append(f"{key}={new_config[key]}")
                    existing_keys.add(key)
                else:
                    updated_lines.append(original_line)
            else:
                updated_lines.append(original_line)

        for key, value in new_config.items():
            if key not in existing_keys:
                updated_lines.append(f"{key}={value}")

        with open(ENV_FILE, 'w', encoding='utf-8') as f:
            f.write('\n'.join(updated_lines) + '\n')

        try:
            from trading_core.risk_manager import get_risk_manager
            risk_manager = get_risk_manager()
            risk_manager.max_position_usdt = _to_float(data.get('max_position_usdt', 100), 100.0)
            risk_manager.max_daily_loss_usdt = _to_float(data.get('max_daily_loss_usdt', 50), 50.0)
            risk_manager.default_leverage = _to_int(data.get('default_leverage', 3), 3)
            risk_manager.max_positions_count = _to_int(data.get('max_positions_count', 1), 1)
            risk_manager.stop_loss_percent = _to_float(data.get('stop_loss_percent', 2), 2.0)
            risk_manager.take_profit_percent = _to_float(data.get('take_profit_percent', 4), 4.0)
            risk_manager.trailing_stop_percent = _to_float(data.get('trailing_stop_percent', 1.0), 1.0)

            for key, value in new_config.items():
                os.environ[key] = str(value)

            logger.info("✅ 设置已保存并同步到运行时环境")
        except Exception as e:
            logger.warning(f"运行时组件更新失败（将在重启后生效）: {e}")

        return jsonify({'success': True, 'message': '设置已保存并生效'})

    except Exception as e:
        logger.error(f"保存设置失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

# ==================== 绛栫暐AI閰嶇疆API ====================

@app.route('/api/strategy/ai-config', methods=['POST'])
def save_strategy_ai_config():
    """淇濆瓨绛栫暐AI鍙婅繍琛岄厤缃?(宸插崌绾т负鎺ュ叆 SQLite 鏁版嵁搴?"""
    try:
        data = request.get_json() or {}
        
        strategy_key = data.get('strategy_key')
        if not strategy_key:
            return jsonify({'success': False, 'error': 'strategy_key涓嶈兘涓虹┖'})

        repo = get_strategy_config_repo()
        
        saved = repo.upsert_strategy_config(
            strategy_key=strategy_key,
            strategy_name=data.get('strategy_name', strategy_key),
            symbol=data.get('symbol', 'BTCUSDT'),
            interval=data.get('interval', '5m'),
            ai_enabled=bool(data.get('ai_enabled', False)),
            ai_model=data.get('ai_model', ''),
            telegram_notify=bool(data.get('telegram_notify', True)),
            auto_trade_follow_global=bool(data.get('follow_global', True)),
            status=data.get('status', 'stopped')
        )

        return jsonify({
            'success': True,
            'message': 'Strategy AI config saved',
            'data': saved
        })

    except Exception as e:
        logger.error(f"淇濆瓨绛栫暐AI閰嶇疆澶辫触: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategy/ai-config/<strategy_key>', methods=['GET'])
def get_strategy_ai_config(strategy_key):
    """鑾峰彇绛栫暐璇︾粏閰嶇疆"""
    try:
        repo = get_strategy_config_repo()
        config = repo.get_strategy_config(strategy_key)
        
        return jsonify({
            'success': True,
            'data': config or {}
        })

    except Exception as e:
        logger.error(f"鑾峰彇绛栫暐AI閰嶇疆澶辫触: {e}")
        return jsonify({'success': False, 'error': str(e)})

@socketio.on('connect')
def handle_connect():
    """Handle client websocket connection."""
    logger.info('瀹㈡埛绔凡杩炴帴')
    emit('connected', {'data': 'Connected to trading server'})

@socketio.on('heartbeat')
def handle_heartbeat(data):
    """Handle client heartbeat."""
    logger.debug(f'鏀跺埌蹇冭烦: {data}')
    emit('heartbeat_ack', {'timestamp': time.time(), 'status': 'ok'})

def broadcast_status():
    """Background thread for periodic status broadcast."""
    while True:
        try:
            exchange, risk_manager, order_executor, strategy_manager = get_components()
            
            if exchange is None:
                socketio.emit('status_update', {
                    'error': 'Exchange is not connected',
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
            
            # 鏇存柊 risk_status 涓殑鎸佷粨鏁伴噺
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
            
            time.sleep(5)  # 姣?绉掓洿鏂颁竴娆?
        except Exception as e:
            logger.error(f"骞挎挱鐘舵€佸け璐? {e}")
            time.sleep(5)


def broadcast_signal_logs():
    """鍚庡彴绾跨▼锛氱洃鎺у苟骞挎挱鏂扮殑淇彿鏃ュ織"""
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
                                # 鍙箍鎾寘鍚?event_type 鐨勬棩蹇楁潯鐩?
                                if 'event_type' in log_entry:
                                    logger.debug(f'[SignalLogBroadcast] Broadcasting {log_entry["event_type"]} log')
                                    socketio.emit('signal_log_update', log_entry)
                            except json.JSONDecodeError:
                                continue
            
            time.sleep(1)  # 姣忕妫€鏌ヤ竴娆℃柊鏃ュ織
        except Exception as e:
            logger.error(f"骞挎挱淇彿鏃ュ織澶辫触: {e}")
            time.sleep(5)


# ==================== 甯傚満琛屾儏鎺ュ彛 (鎺ュ叆 MarketDataService) ====================

def background_trade_sync():
    """Periodic account-trade incremental sync worker."""
    while True:
        try:
            repo = get_trade_fill_repo()
            force_backfill = repo.count_fills() == 0
            _sync_account_trades_to_fills(force_backfill=force_backfill)
        except Exception as e:
            logger.warning(f"[TradeSync] background worker error: {e}")
        time.sleep(60)


@app.route('/api/market/symbols', methods=['GET'])
def api_market_symbols():
    """Get available tradable symbols."""
    try:
        quote = request.args.get('quote_asset', 'USDT')
        res = get_market_data_service().get_symbols(quote_asset=quote)
        return jsonify(res)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/market/dashboard', methods=['GET'])
def api_market_dashboard():
    """Get dashboard market snapshot."""
    try:
        symbol = request.args.get('symbol', 'BTCUSDT')
        interval = request.args.get('interval', '5m')
        # kline_limit 鍜?depth_limit 鍧囧凡鍦?service 閲屾湁榛樿璁惧畾
        res = get_market_data_service().get_dashboard_snapshot(symbol, interval=interval)
        return jsonify(res)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ==================== 绛栫暐閰嶇疆绠＄悊 ====================

# 绛栫暐閰嶇疆鏂囦欢璺緞
STRATEGY_CONFIG_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'strategy_config.json')

def load_strategy_config():
    """鍔犺浇绛栫暐閰嶇疆"""
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
                # 鍚堝苟榛樿閰嶇疆
                return {**default_config, **config}
    except Exception as e:
        logger.error(f"鍔犺浇绛栫暐閰嶇疆澶辫触: {e}")
    
    return default_config

def save_strategy_config(config):
    """淇濆瓨绛栫暐閰嶇疆"""
    try:
        os.makedirs(os.path.dirname(STRATEGY_CONFIG_FILE), exist_ok=True)
        with open(STRATEGY_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"淇濆瓨绛栫暐閰嶇疆澶辫触: {e}")
        return False

@app.route('/api/strategy/config', methods=['GET'])
def get_strategy_config():
    """鑾峰彇绛栫暐閰嶇疆"""
    try:
        config = load_strategy_config()
        return jsonify({'success': True, 'data': config})
    except Exception as e:
        logger.error(f"鑾峰彇绛栫暐閰嶇疆澶辫触: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/strategy/config', methods=['POST'])
def update_strategy_config():
    """鏇存柊绛栫暐閰嶇疆"""
    try:
        data = request.get_json()
        
        # 楠岃瘉鏁版嵁
        if not data or 'mode' not in data:
            return jsonify({'success': False, 'error': '缂哄皯蹇呰鍙傛暟'})
        
        # 鍔犺浇鐜版湁閰嶇疆
        config = load_strategy_config()
        
        # 鏇存柊閰嶇疆
        config['mode'] = data.get('mode', config['mode'])
        config['singleStrategy'] = data.get('singleStrategy', config['singleStrategy'])
        config['consensusStrategies'] = data.get('consensusStrategies', config['consensusStrategies'])
        config['consensusThreshold'] = data.get('consensusThreshold', config['consensusThreshold'])
        
        # 淇濆瓨閰嶇疆
        if save_strategy_config(config):
            logger.info(f"鉁?绛栫暐閰嶇疆宸叉洿鏂? {config['mode']} 妯紡")
            return jsonify({'success': True, 'message': 'Strategy config saved'})
        else:
            return jsonify({'success': False, 'error': '淇濆瓨閰嶇疆澶辫触'})
            
    except Exception as e:
        logger.error(f"鏇存柊绛栫暐閰嶇疆澶辫触: {e}")
        return jsonify({'success': False, 'error': str(e)})

# ==================== 绛栫暐绠＄悊API ====================

@app.route('/api/strategies', methods=['GET'])
def get_strategies():
    """Get all strategy status."""
    try:
        global _strategy_manager
        
        if _strategy_manager is None:
            return jsonify({'success': False, 'error': 'Strategy manager not initialized'})
        
        status = _strategy_manager.get_status()
        
        # 娣诲姞绛栫暐閰嶇疆淇℃伅锛堝竵绉嶃€佸懆鏈熺瓑锛?
        from trading_core.strategy_engine_adapter import SYMBOLS, TIMEFRAMES
        status['monitored_symbols'] = SYMBOLS
        status['monitored_timeframes'] = TIMEFRAMES
        status['scan_interval'] = 60  # 鎵弿闂撮殧锛堢锛?
        
        return jsonify({'success': True, 'data': status})
    except Exception as e:
        logger.error(f"鑾峰彇绛栫暐鍒楄〃澶辫触: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/engine/start', methods=['POST'])
def start_strategy_engine():
    """鍚姩绛栫暐寮曟搸锛堟壂鎻忓惊鐜級"""
    try:
        # 浣跨敤鍏ㄥ眬鍙橀噺纭繚瀹炰緥涓€鑷存€?
        global _exchange, _risk_manager, _order_executor, _strategy_manager
        
        # 鍒濆鍖栫粍浠?
        if _exchange is None:
            _exchange = get_exchange_client()
        if _risk_manager is None:
            _risk_manager = get_risk_manager()
        if _order_executor is None:
            _order_executor = get_order_executor()
        if _strategy_manager is None:
            _strategy_manager = get_strategy_manager(_exchange, _risk_manager, _order_executor)
            # 娉ㄥ唽榛樿绛栫暐
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
            return jsonify({'success': False, 'error': '绛栫暐绠＄悊鍣ㄥ垵濮嬪寲澶辫触'})
        
        # 妫€鏌ユ槸鍚﹀凡鍦ㄨ繍琛?
        if _strategy_manager._running:
            return jsonify({'success': True, 'message': 'Strategy engine already running'})
        
        # 鍚姩绛栫暐鎵弿寰幆
        logger.info(f'[API] Before start(), _running={_strategy_manager._running}')
        _strategy_manager.start(interval=60)
        logger.info(f'[API] After start(), _running={_strategy_manager._running}')
        _strategy_manager.start_all()
        logger.info(f'[API] After start_all(), _running={_strategy_manager._running}')
        
        # 楠岃瘉鍚姩鐘舵€?
        if _strategy_manager._running:
            logger.info('[API] Strategy engine started')
            return jsonify({'success': True, 'message': 'Strategy engine started'})
        else:
            logger.error('[API] Strategy engine failed to start')
            return jsonify({'success': False, 'error': 'Strategy engine failed to start, check logs'})
            
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        logger.error(f"鍚姩绛栫暐寮曟搸澶辫触: {e}\n{error_detail}")
        return jsonify({'success': False, 'error': str(e), 'detail': error_detail})


@app.route('/api/strategies/engine/stop', methods=['POST'])
def stop_strategy_engine():
    """鍋滄绛栫暐寮曟搸锛堟壂鎻忓惊鐜級"""
    try:
        global _strategy_manager
        
        if _strategy_manager is None:
            return jsonify({'success': False, 'error': 'Strategy manager not initialized'})
        
        if not _strategy_manager._running:
            return jsonify({'success': True, 'message': 'Strategy engine already stopped'})
        
        _strategy_manager.stop()
        
        logger.info('[API] Strategy engine stopped')
        return jsonify({'success': True, 'message': 'Strategy engine stopped'})
    except Exception as e:
        logger.error(f"鍋滄绛栫暐寮曟搸澶辫触: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/<name>/start', methods=['POST'])
def start_strategy(name):
    """鍚姩鎸囧畾绛栫暐"""
    try:
        _, _, _, strategy_manager = get_components()
        if strategy_manager is None:
            return jsonify({'success': False, 'error': 'Strategy manager not initialized'})
        
        success = strategy_manager.start_strategy(name)
        return jsonify({
            'success': success,
            'message': f'Strategy {name} started' if success else f'Failed to start strategy {name}'
        })
    except Exception as e:
        logger.error(f"鍚姩绛栫暐澶辫触: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/<name>/stop', methods=['POST'])
def stop_strategy(name):
    """鍋滄鎸囧畾绛栫暐"""
    try:
        _, _, _, strategy_manager = get_components()
        if strategy_manager is None:
            return jsonify({'success': False, 'error': 'Strategy manager not initialized'})
        
        success = strategy_manager.stop_strategy(name)
        return jsonify({
            'success': success,
            'message': f'Strategy {name} stopped' if success else f'Failed to stop strategy {name}'
        })
    except Exception as e:
        logger.error(f"鍋滄绛栫暐澶辫触: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/<name>/update', methods=['POST'])
def update_strategy(name):
    """鏇存柊绛栫暐鍙傛暟"""
    try:
        _, _, _, strategy_manager = get_components()
        if strategy_manager is None:
            return jsonify({'success': False, 'error': 'Strategy manager not initialized'})
        
        data = request.get_json()
        config = strategy_manager.configs.get(name)
        
        if config is None:
            return jsonify({'success': False, 'error': f'Strategy {name} does not exist'})
        
        # 鏇存柊閰嶇疆
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
        
        return jsonify({'success': True, 'message': f'Strategy {name} updated'})
    except Exception as e:
        logger.error(f"鏇存柊绛栫暐澶辫触: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies/stats', methods=['GET'])
def get_strategy_stats():
    """鑾峰彇MA99绛栫暐淇彿缁熻"""
    try:
        _, _, _, strategy_manager = get_components()
        if strategy_manager is None:
            return jsonify({'success': False, 'error': 'Strategy manager not initialized'})
        
        days = request.args.get('days', 7, type=int)
        stats = strategy_manager.get_signal_stats(days)
        
        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        logger.error(f"鑾峰彇绛栫暐缁熻澶辫触: {e}")
        return jsonify({'success': False, 'error': str(e)})


def auto_start_strategy():
    """鑷姩鍚姩绛栫暐"""
    try:
        time.sleep(3)  # 绛夊緟鏈嶅姟鍣ㄥ惎鍔?
        logger.info('[AutoStart] 姝ｅ湪鍒濆鍖栫瓥鐣ョ鐞嗗櫒...')
        
        exchange, risk_manager, order_executor, strategy_manager = get_components()
        
        if strategy_manager is None:
            logger.error('[AutoStart] 绛栫暐绠＄悊鍣ㄥ垵濮嬪寲澶辫触')
            return
        
        # 鍚姩绛栫暐鎵弿寰幆
        strategy_manager.start(interval=60)
        strategy_manager.start_all()
        
        logger.info('[AutoStart] Strategies auto-started, scan interval: 60s')
    except Exception as e:
        logger.error(f'[AutoStart] 鑷姩鍚姩绛栫暐澶辫触: {e}')

if __name__ == '__main__':
    # 鍚姩鐘舵€佸箍鎾嚎绋?
    status_thread = Thread(target=broadcast_status, daemon=True)
    status_thread.start()
    
    # 鍚姩淇彿鏃ュ織骞挎挱绾跨▼
    log_thread = Thread(target=broadcast_signal_logs, daemon=True)
    log_thread.start()

    trade_sync_thread = Thread(target=background_trade_sync, daemon=True)
    trade_sync_thread.start()
    
    # 鍚姩绛栫暐鑷姩鍚姩绾縟a绋?
    auto_start_thread = Thread(target=auto_start_strategy, daemon=True)
    auto_start_thread.start()
    
    # 鍚姩Flask鏈嶅姟鍣?
    host = os.getenv('WEB_HOST', '0.0.0.0')
    port = int(os.getenv('WEB_PORT', 5000))
    
    logger.info(f"馃寪 Web绠＄悊椤甸潰鍚姩: http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)




