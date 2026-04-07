import requests

print('Testing Strategy Engine API...')
print()

try:
    response = requests.post('http://127.0.0.1:5000/api/strategies/engine/start', timeout=10)
    data = response.json()
    
    print(f'Status Code: {response.status_code}')
    print(f'Success: {data.get("success")}')
    print(f'Message: {data.get("message")}')
    print(f'Error: {data.get("error")}')
    if 'debug' in data:
        print(f'Debug: {data["debug"]}')
    if 'detail' in data:
        print(f'Detail: {data["detail"]}')
except Exception as e:
    print(f'ERROR: {e}')
