import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import logging
from threading import Thread
import time

from trading_core.exchange_client import get_exchange_client
from trading_core.risk_manager import get_risk_manager
from trading_core.order_executor import get_order_executor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*")

# 获取核心组件（延迟初始化）
exchange = None
risk_manager = None
order_executor = None

def get_components():
    """延迟获取核心组件"""
    global exchange, risk_manager, order_executor
    if exchange is None:
        try:
            exchange = get_exchange_client()
            risk_manager = get_risk_manager()
            order_executor = get_order_executor()
        except Exception as e:
            logger.error(f"组件初始化失败: {e}")
    return exchange, risk_manager, order_executor

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
        exchange, risk_manager, order_executor = get_components()
        
        if exchange is None:
            return jsonify({'success': False, 'error': '交易所连接失败，请检查代理设置'})
        
        balance = exchange.get_balance()
        positions = exchange.get_positions()
        risk_status = risk_manager.get_status()
        executor_status = order_executor.get_status()
        
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
        exchange, risk_manager, order_executor = get_components()
        limit = request.args.get('limit', 50, type=int)
        trades = order_executor.get_recent_trades(limit)
        return jsonify({'success': True, 'data': trades})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/signals')
def api_signals():
    """获取信号记录"""
    try:
        exchange, risk_manager, order_executor = get_components()
        limit = request.args.get('limit', 50, type=int)
        signals = order_executor.get_recent_signals(limit)
        return jsonify({'success': True, 'data': signals})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trading/start', methods=['POST'])
def start_trading():
    """启动自动交易"""
    try:
        exchange, risk_manager, order_executor = get_components()
        order_executor.start_auto_trading()
        return jsonify({'success': True, 'message': '自动交易已启动'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trading/stop', methods=['POST'])
def stop_trading():
    """停止自动交易"""
    try:
        exchange, risk_manager, order_executor = get_components()
        order_executor.stop_auto_trading()
        return jsonify({'success': True, 'message': '自动交易已停止'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/trading/emergency_stop', methods=['POST'])
def emergency_stop():
    """紧急停止 - 停止交易并平仓"""
    try:
        exchange, risk_manager, order_executor = get_components()
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
        exchange, risk_manager, order_executor = get_components()
        data = request.get_json()
        symbol = data.get('symbol')
        
        if not symbol:
            return jsonify({'success': False, 'error': '缺少symbol参数'})
        
        success = exchange.close_position(symbol)
        return jsonify({
            'success': success,
            'message': f'{symbol} 平仓成功' if success else f'{symbol} 平仓失败'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/position/close_all', methods=['POST'])
def close_all_positions():
    """平掉所有持仓"""
    try:
        exchange, risk_manager, order_executor = get_components()
        success = exchange.close_all_positions()
        return jsonify({
            'success': success,
            'message': '所有持仓已平仓' if success else '部分持仓平仓失败'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ==================== WebSocket ====================

@app.route('/api/ohlcv')
def api_ohlcv():
    """获取K线数据"""
    try:
        symbol = request.args.get('symbol', 'BTC/USDT')
        timeframe = request.args.get('timeframe', '1h')
        limit = request.args.get('limit', 100, type=int)
        
        exchange, _, _ = get_components()
        
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


@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    logger.info('客户端已连接')
    emit('connected', {'data': 'Connected to trading server'})

def broadcast_status():
    """后台线程：定期广播状态更新"""
    while True:
        try:
            exchange, risk_manager, order_executor = get_components()
            
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
            
            total_unrealized = sum(p.get('unrealized_pnl', 0) for p in positions)
            
            socketio.emit('status_update', {
                'balance': balance,
                'positions': positions,
                'position_count': len(positions),
                'total_unrealized_pnl': round(total_unrealized, 2),
                'risk_status': risk_status,
                'auto_trading': order_executor.auto_trading,
                'timestamp': time.time()
            })
            
            time.sleep(5)  # 每5秒更新一次
        except Exception as e:
            logger.error(f"广播状态失败: {e}")
            time.sleep(5)

if __name__ == '__main__':
    # 启动状态广播线程
    status_thread = Thread(target=broadcast_status, daemon=True)
    status_thread.start()
    
    # 启动Flask服务器
    host = os.getenv('WEB_HOST', '0.0.0.0')
    port = int(os.getenv('WEB_PORT', 5000))
    
    logger.info(f"🌐 Web管理页面启动: http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=False)
