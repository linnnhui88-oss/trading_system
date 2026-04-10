#!/usr/bin/env python3
"""
测试仪表盘数据修复
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading_core.exchange_client import get_exchange_client
from trading_core.risk_manager import get_risk_manager
from trading_core.order_executor import get_order_executor

def test_dashboard_data():
    """测试仪表盘数据"""
    print("=" * 50)
    print("测试仪表盘数据修复")
    print("=" * 50)
    
    # 测试交易所连接
    print("\n1. 测试交易所连接...")
    try:
        exchange = get_exchange_client()
        balance = exchange.get_balance()
        print(f"   ✓ 余额: {balance}")
    except Exception as e:
        print(f"   ✗ 交易所连接失败: {e}")
        return
    
    # 测试持仓数据
    print("\n2. 测试持仓数据...")
    try:
        positions = exchange.get_positions()
        print(f"   ✓ 持仓数量: {len(positions)}")
        for pos in positions:
            print(f"     - {pos['symbol']}: {pos['side']} x{pos['leverage']}, "
                  f"数量:{pos['contracts']:.4f}, 盈亏:{pos['unrealized_pnl']:.2f}")
    except Exception as e:
        print(f"   ✗ 获取持仓失败: {e}")
    
    # 测试风险管理状态
    print("\n3. 测试风险管理状态...")
    try:
        risk_manager = get_risk_manager()
        risk_status = risk_manager.get_status()
        print(f"   ✓ 交易状态: {'启用' if risk_status['trading_enabled'] else '禁用'}")
        print(f"   ✓ 今日交易: {risk_status['daily_trades']} 笔")
        print(f"   ✓ 今日盈亏: {risk_status['daily_pnl']:.2f} USDT")
        print(f"   ✓ 止损比例: {risk_status['stop_loss_percent']}%")
        print(f"   ✓ 止盈比例: {risk_status['take_profit_percent']}%")
    except Exception as e:
        print(f"   ✗ 获取风险状态失败: {e}")
    
    # 测试订单执行器状态
    print("\n4. 测试订单执行器状态...")
    try:
        order_executor = get_order_executor()
        executor_status = order_executor.get_status()
        print(f"   ✓ 自动交易: {'运行中' if executor_status['auto_trading'] else '已停止'}")
        print(f"   ✓ 最近交易: {executor_status['recent_trades_count']} 条")
    except Exception as e:
        print(f"   ✗ 获取执行器状态失败: {e}")
    
    print("\n" + "=" * 50)
    print("测试完成")
    print("=" * 50)

if __name__ == '__main__':
    test_dashboard_data()
