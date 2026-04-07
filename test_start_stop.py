import requests
import time

BASE_URL = 'http://127.0.0.1:5000'

def test_start_stop():
    print('=== 测试启动/停止策略引擎 ===')
    print()
    
    # 1. 获取初始状态
    print('1. 获取初始状态...')
    resp = requests.get(f'{BASE_URL}/api/strategies', timeout=10)
    data = resp.json()
    initial_status = data['data']['running'] if data.get('success') else False
    print(f"   初始状态: {'运行中' if initial_status else '已停止'}")
    
    # 2. 如果已运行则停止，如果已停止则启动
    if initial_status:
        print('2. 停止策略引擎...')
        resp = requests.post(f'{BASE_URL}/api/strategies/engine/stop', timeout=10)
        data = resp.json()
        print(f"   结果: {data.get('message')}")
        
        print('3. 验证停止状态...')
        time.sleep(1)
        resp = requests.get(f'{BASE_URL}/api/strategies', timeout=10)
        data = resp.json()
        new_status = data['data']['running'] if data.get('success') else False
        print(f"   当前状态: {'运行中' if new_status else '已停止'}")
        
        if not new_status:
            print('   ✅ 停止成功')
        else:
            print('   ❌ 停止失败')
    else:
        print('2. 启动策略引擎...')
        resp = requests.post(f'{BASE_URL}/api/strategies/engine/start', timeout=10)
        data = resp.json()
        print(f"   结果: {data.get('message')}")
        
        print('3. 验证启动状态...')
        time.sleep(1)
        resp = requests.get(f'{BASE_URL}/api/strategies', timeout=10)
        data = resp.json()
        new_status = data['data']['running'] if data.get('success') else False
        print(f"   当前状态: {'运行中' if new_status else '已停止'}")
        
        if new_status:
            print('   ✅ 启动成功')
        else:
            print('   ❌ 启动失败')
    
    print()
    print('=== 测试完成 ===')

if __name__ == '__main__':
    test_start_stop()
