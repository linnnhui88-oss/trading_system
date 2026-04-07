import requests

try:
    resp = requests.get('http://localhost:5000/api/status', timeout=5)
    data = resp.json()
    if data.get('success'):
        d = data['data']
        print('=== Web API Status ===')
        status = 'ON' if d.get('auto_trading') else 'OFF'
        print(f'Auto Trading: {status}')
        print(f'Positions: {d.get("position_count", 0)}')
        print(f'Balance: {d.get("balance", {}).get("USDT", 0)} USDT')
        print(f'Unrealized PnL: {d.get("total_unrealized_pnl", 0)}')
    else:
        print('API Error:', data)
except Exception as e:
    print(f'Connection Error: {e}')
