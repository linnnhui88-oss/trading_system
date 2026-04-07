import sys
import os
sys.path.insert(0, r'C:\Users\TUF\.openclaw\workspace\trading_system')

import requests

print('=== Checking Strategy Engine Status ===')
print()

try:
    response = requests.get('http://127.0.0.1:5000/api/strategies', timeout=10)
    data = response.json()
    
    if data['success']:
        status = data['data']
        print(f"Engine Running: {status.get('running', False)}")
        print(f"Strategies: {list(status.get('strategies', {}).keys())}")
        for name, s in status.get('strategies', {}).items():
            print(f"  - {name}: {s.get('status')}")
        print(f"Monitored Symbols: {len(status.get('monitored_symbols', []))}")
        print(f"Monitored Timeframes: {status.get('monitored_timeframes', [])}")
    else:
        print(f"Error: {data.get('error')}")
except Exception as e:
    print(f"Request failed: {e}")
