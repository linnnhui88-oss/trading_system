# check_config.py - 检查系统配置
import os
import sys

sys.path.insert(0, r'C:\Users\TUF\.openclaw\workspace\trading_system')
os.chdir(r'C:\Users\TUF\.openclaw\workspace\trading_system')

from dotenv import load_dotenv
load_dotenv()

# 检查Telegram配置
token = os.getenv('TELEGRAM_BOT_TOKEN', '')
chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
gemini_key = os.getenv('GEMINI_API_KEY', '')

print('=== 系统配置检查 ===')
print()

# Telegram
if token and token != '你的TELEGRAM_BOT_TOKEN' and len(token) > 20:
    print(f'[OK] Telegram Token: 已设置 ({token[:15]}...)')
else:
    print(f'[X] Telegram Token: 未设置或无效')

if chat_id and chat_id != '你的CHAT_ID':
    print(f'[OK] Telegram Chat ID: {chat_id}')
else:
    print(f'[X] Telegram Chat ID: 未设置')

# Gemini AI
if gemini_key and '你的' not in gemini_key and len(gemini_key) > 20:
    print(f'[OK] Gemini API Key: 已设置 ({gemini_key[:15]}...)')
else:
    print(f'[X] Gemini API Key: 未设置或无效')

print()

# 测试Telegram连接
if token and chat_id and token != '你的TELEGRAM_BOT_TOKEN':
    import requests
    try:
        url = f'https://api.telegram.org/bot{token}/getMe'
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('ok'):
                bot_info = data['result']
                print(f'[OK] Telegram Bot: @{bot_info.get("username")} - 连接正常')
            else:
                print(f'[X] Telegram Bot: 连接失败 - {data}')
        else:
            print(f'[X] Telegram Bot: HTTP {resp.status_code}')
    except Exception as e:
        print(f'[X] Telegram Bot: 连接异常 - {e}')
else:
    print('[!] Telegram Bot: 配置不完整，跳过测试')

print()

# 测试Gemini AI
if gemini_key and '你的' not in gemini_key:
    try:
        from google import genai
        client = genai.Client(api_key=gemini_key)
        # 简单测试
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents='Hello, respond with OK only.'
        )
        if response and response.text:
            print(f'[OK] Gemini AI: 连接正常')
        else:
            print(f'[X] Gemini AI: 响应异常')
    except Exception as e:
        print(f'[X] Gemini AI: 连接异常 - {e}')
else:
    print('[!] Gemini AI: 配置不完整，跳过测试')

print()
print('=== 检查完成 ===')
