# 启动策略引擎
# 使用方法: .\venv\Scripts\python start_engine.py

import sys
import os
sys.path.insert(0, r'C:\Users\TUF\.openclaw\workspace\trading_system')

import requests
import time

print('=== 启动策略引擎 ===')
print()

# 调用API启动策略引擎
try:
    response = requests.post('http://127.0.0.1:5000/api/strategies/engine/start', timeout=10)
    data = response.json()
    
    if data['success']:
        print(f"[OK] {data['message']}")
        print()
        print('策略引擎已启动！')
        print('扫描间隔: 60秒')
        print()
        print('你可以通过以下方式查看策略状态:')
        print('1. 打开Web界面 http://127.0.0.1:5000/signals')
        print('2. 查看策略监控信号日志')
    else:
        print(f"[ERROR] 启动失败: {data.get('error', '未知错误')}")
        
except requests.exceptions.ConnectionError:
    print('[ERROR] 无法连接到Web服务器')
    print('请确保Web服务器正在运行 (python -m web_admin.app)')
except Exception as e:
    print(f'[ERROR] 请求失败: {e}')

print()
input('按回车键退出...')
