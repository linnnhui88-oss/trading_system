"""
测试Web API是否能正确启动策略引擎
"""
import requests
import time

BASE_URL = 'http://127.0.0.1:5000'

def test_api():
    print('=== 测试策略引擎API ===')
    print()
    
    # 1. 获取当前状态
    print('1. 获取当前策略状态...')
    try:
        resp = requests.get(f'{BASE_URL}/api/strategies', timeout=10)
        data = resp.json()
        if data.get('success'):
            status = data['data']
            print(f"   运行状态: {'运行中' if status.get('running') else '已停止'}")
            print(f"   策略数量: {len(status.get('strategies', {}))}")
        else:
            print(f"   错误: {data.get('error')}")
    except Exception as e:
        print(f"   请求失败: {e}")
    
    print()
    
    # 2. 启动策略引擎
    print('2. 启动策略引擎...')
    try:
        resp = requests.post(f'{BASE_URL}/api/strategies/engine/start', timeout=10)
        data = resp.json()
        print(f"   状态码: {resp.status_code}")
        print(f"   成功: {data.get('success')}")
        print(f"   消息: {data.get('message')}")
        print(f"   错误: {data.get('error')}")
        if 'detail' in data:
            print(f"   详情: {data.get('detail')}")
    except Exception as e:
        print(f"   请求失败: {e}")
    
    print()
    
    # 3. 再次获取状态
    print('3. 再次获取策略状态...')
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

if __name__ == '__main__':
    test_api()
