import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Exchange API Configuration (支持多种环境变量名)
    EXCHANGE_ID = os.getenv('EXCHANGE_ID', 'binance')
    # 优先使用 BINANCE_API_KEY，如果不存在则使用 API_KEY
    API_KEY = os.getenv('BINANCE_API_KEY') or os.getenv('API_KEY', '')
    API_SECRET = os.getenv('BINANCE_SECRET_KEY') or os.getenv('API_SECRET', '')
    
    # Trading Configuration
    SYMBOL = os.getenv('SYMBOL', 'BTC/USDT')
    TIMEFRAME = os.getenv('TIMEFRAME', '1h')
    TRADE_AMOUNT = float(os.getenv('TRADE_AMOUNT', '0.001'))
    
    # Risk Management
    STOP_LOSS_PERCENT = float(os.getenv('STOP_LOSS_PERCENT', '2.0'))
    TAKE_PROFIT_PERCENT = float(os.getenv('TAKE_PROFIT_PERCENT', '4.0'))
    TRAILING_STOP_PERCENT = float(os.getenv('TRAILING_STOP_PERCENT', '1.0'))
    MAX_POSITION_SIZE = float(os.getenv('MAX_POSITION_SIZE', '1000'))
    
    # Email Notification
    EMAIL_ENABLED = os.getenv('EMAIL_ENABLED', 'false').lower() == 'true'
    EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
    EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
    EMAIL_USER = os.getenv('EMAIL_USER', '')
    EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')
    EMAIL_TO = os.getenv('EMAIL_TO', '')
    
    # Web Server
    WEB_HOST = os.getenv('WEB_HOST', '0.0.0.0')
    WEB_PORT = int(os.getenv('WEB_PORT', '5000'))
    DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', 'logs/trading.log')
    
    # Strategy
    DEFAULT_STRATEGY = os.getenv('DEFAULT_STRATEGY', 'macd')
    STRATEGIES_ENABLED = os.getenv('STRATEGIES_ENABLED', 'macd,rsi,bollinger').split(',')
