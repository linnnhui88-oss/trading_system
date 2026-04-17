# 启动/停止脚本使用说明

## 脚本文件

- `start_trading.bat` - Windows 启动脚本
- `stop_trading.bat` - Windows 停止脚本
- `start.sh` - Linux/Mac 启动脚本
- `stop.sh` - Linux/Mac 停止脚本

## 特点

✅ **跨平台兼容** - 支持 Windows、Linux、Mac  
✅ **自动检测路径** - 不依赖固定路径，可在任意位置运行  
✅ **PID文件管理** - 使用PID文件精确管理进程  
✅ **优雅停止** - 先尝试API停止，再强制终止  
✅ **自动检查** - 启动前检查环境，停止后验证结果  

## Windows 使用

### 启动系统
```batch
# 双击运行
start_trading.bat

# 或在命令行运行
.\start_trading.bat
```

### 停止系统
```batch
# 双击运行
stop_trading.bat

# 或在命令行运行
.\stop_trading.bat
```

## Linux/Mac 使用

### 赋予执行权限
```bash
chmod +x start.sh stop.sh
```

### 启动系统
```bash
./start.sh
```

### 停止系统
```bash
./stop.sh
```

## 环境要求

### 首次使用前的准备

1. **创建虚拟环境**
   ```bash
   # Windows
   python -m venv venv
   
   # Linux/Mac
   python3 -m venv venv
   ```

2. **安装依赖**
   ```bash
   # Windows
   .\venv\Scripts\pip install -r requirements.txt
   
   # Linux/Mac
   ./venv/bin/pip install -r requirements.txt
   ```

3. **配置环境变量**
   ```bash
   # 复制示例配置文件
   cp .env.example .env
   
   # 编辑 .env 文件，配置您的API密钥
   ```

## 故障排除

### 启动失败

1. **检查端口占用**
   ```bash
   # Windows
   netstat -ano | findstr :5000
   
   # Linux/Mac
   lsof -i :5000
   ```

2. **检查日志**
   ```bash
   tail -f data/service.log
   ```

3. **检查Python路径**
   - 确保 `venv/Scripts/python.exe` (Windows) 或 `venv/bin/python` (Linux/Mac) 存在

### 停止失败

1. **手动停止所有Python进程**
   ```bash
   # Windows
   taskkill /f /im python.exe
   
   # Linux/Mac
   pkill -f python
   ```

2. **清除PID文件**
   ```bash
   rm data/trading_service.pid
   ```

## 文件说明

| 文件 | 说明 |
|------|------|
| `data/trading_service.pid` | 服务进程ID文件 |
| `data/service.log` | 服务运行日志 |
| `data/web_admin.log` | Web后台详细日志 |

## 注意事项

1. **不要直接移动脚本** - 脚本使用相对路径，移动后需要重新配置
2. **保持目录结构** - 确保 `venv`、`data`、`web_admin` 目录在同一级
3. **权限问题** - Linux/Mac 用户需要确保脚本有执行权限
