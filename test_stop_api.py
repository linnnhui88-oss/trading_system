import requests

BASE_URL = 'http://127.0.0.1:5000'

print('=== 测试停止策略引擎 ===')
print()

# 停止策略引擎
print('1. 停止策略引擎...')
try:
    resp = requests.post(f'{BASE_URL}/api/strategies/engine/stop', timeout=10)
    data = resp.json()
    print(f"   状态码: {resp.status_code}")
    print(f"   成功: {data.get('success')}")
    print(f"   消息: {data.get('message')}")
except Exception as e:
    print(f"   请求失败: {e}")

print()

# 获取状态
print('2. 获取策略状态...')
try:
    resp = requests.get(f'{BASE_URL}/api/strategies', timeout=10)
    data = resp.json()
    if data.get('success'):
        status = data['data']
        print(f"   运行状态: {'运行中' if status.get('running') else '已停止'}")
    else:
        print(f"   错误: {data.get('error')}")
except Exception as e:
    print(f"   请求失败: {e}")

print()
print('=== 测试完成 ===')
