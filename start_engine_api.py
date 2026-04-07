import sys
import os
sys.path.insert(0, r'C:\Users\TUF\.openclaw\workspace\trading_system')

import requests
import json

print('=== Starting Strategy Engine ===')
print()

try:
    # Call the API to start the engine
    response = requests.post(
        'http://127.0.0.1:5000/api/strategies/engine/start',
        timeout=10
    )
    
    print(f"Response status: {response.status_code}")
    print(f"Response: {response.text}")
    
    data = response.json()
    
    if data.get('success'):
        print(f"[OK] {data.get('message', 'Strategy engine started')}")
    else:
        print(f"[ERROR] {data.get('error', 'Unknown error')}")
        
except requests.exceptions.ConnectionError as e:
    print(f'[ERROR] Cannot connect to web server: {e}')
    print('Make sure the web server is running')
except Exception as e:
    print(f'[ERROR] Request failed: {e}')
    import traceback
    traceback.print_exc()
