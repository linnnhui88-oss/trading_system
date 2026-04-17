# -*- coding: utf-8 -*-
"""
Strategy config repository

作用：
1. 管理策略配置持久化
2. 支持每个策略单独设置：
   - 盯盘币种
   - K线周期
   - 策略名称
   - 是否启用 AI 分析
   - 使用哪个 AI 模型
   - 是否开启 Telegram 推送
   - 是否跟随全局自动交易开关
   - 策略运行状态
3. 为策略页提供稳定的数据来源

设计原则：
- 当前文件只负责“配置存储”
- 不直接耦合 strategy_engine_adapter / order_executor
- 即使后续策略执行逻辑还没接上，这个文件本身也不会影响系统现有运行
"""

import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from trading_core.ai_model_registry import is_supported_ai_model


class StrategyConfigRepository:
    def __init__(self, db_path: str = "trading_system.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()

    def _get_conn(self):
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategy_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_key TEXT UNIQUE NOT NULL,
                    strategy_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL DEFAULT '5m',
                    ai_enabled INTEGER DEFAULT 1,
                    ai_model TEXT,
                    telegram_notify INTEGER DEFAULT 1,
                    auto_trade_follow_global INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'stopped',
                    config_json TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_strategy_configs_strategy_key
                ON strategy_configs(strategy_key)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_strategy_configs_symbol
                ON strategy_configs(symbol)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_strategy_configs_status
                ON strategy_configs(status)
            """)

            conn.commit()
            conn.close()

    def upsert_strategy_config(
        self,
        strategy_key: str,
        strategy_name: str,
        symbol: str,
        interval: str = "5m",
        ai_enabled: bool = True,
        ai_model: str = "",
        telegram_notify: bool = True,
        auto_trade_follow_global: bool = True,
        status: str = "stopped",
        config_json: str = "",
    ) -> Dict[str, Any]:
        strategy_key = (strategy_key or "").strip()
        strategy_name = (strategy_name or "").strip()
        symbol = (symbol or "").strip().upper()
        interval = (interval or "5m").strip()
        ai_model = (ai_model or "").strip()
        status = (status or "stopped").strip().lower()
        config_json = config_json or ""

        self._validate_strategy_config(
            strategy_key=strategy_key,
            strategy_name=strategy_name,
            symbol=symbol,
            interval=interval,
            ai_model=ai_model,
            status=status,
        )

        now = datetime.utcnow().isoformat()

        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO strategy_configs (
                    strategy_key,
                    strategy_name,
                    symbol,
                    interval,
                    ai_enabled,
                    ai_model,
                    telegram_notify,
                    auto_trade_follow_global,
                    status,
                    config_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_key) DO UPDATE SET
                    strategy_name = excluded.strategy_name,
                    symbol = excluded.symbol,
                    interval = excluded.interval,
                    ai_enabled = excluded.ai_enabled,
                    ai_model = excluded.ai_model,
                    telegram_notify = excluded.telegram_notify,
                    auto_trade_follow_global = excluded.auto_trade_follow_global,
                    status = excluded.status,
                    config_json = excluded.config_json,
                    updated_at = excluded.updated_at
            """, (
                strategy_key,
                strategy_name,
                symbol,
                interval,
                1 if ai_enabled else 0,
                ai_model,
                1 if telegram_notify else 0,
                1 if auto_trade_follow_global else 0,
                status,
                config_json,
                now,
                now,
            ))

            conn.commit()
            conn.close()

        return self.get_strategy_config(strategy_key)

    def get_strategy_config(self, strategy_key: str) -> Optional[Dict[str, Any]]:
        strategy_key = (strategy_key or "").strip()
        if not strategy_key:
            return None

        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                id,
                strategy_key,
                strategy_name,
                symbol,
                interval,
                ai_enabled,
                ai_model,
                telegram_notify,
                auto_trade_follow_global,
                status,
                config_json,
                created_at,
                updated_at
            FROM strategy_configs
            WHERE strategy_key = ?
        """, (strategy_key,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return self._row_to_dict(row)

    def list_strategy_configs(self, status: str = "") -> List[Dict[str, Any]]:
        query = """
            SELECT
                id,
                strategy_key,
                strategy_name,
                symbol,
                interval,
                ai_enabled,
                ai_model,
                telegram_notify,
                auto_trade_follow_global,
                status,
                config_json,
                created_at,
                updated_at
            FROM strategy_configs
            WHERE 1 = 1
        """
        params = []

        if status:
            query += " AND status = ?"
            params.append(status.strip().lower())

        query += " ORDER BY updated_at DESC, id DESC"

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def delete_strategy_config(self, strategy_key: str) -> bool:
        strategy_key = (strategy_key or "").strip()
        if not strategy_key:
            return False

        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM strategy_configs
                WHERE strategy_key = ?
            """, (strategy_key,))
            affected = cursor.rowcount
            conn.commit()
            conn.close()

        return affected > 0

    def update_status(self, strategy_key: str, status: str) -> Optional[Dict[str, Any]]:
        current = self.get_strategy_config(strategy_key)
        if not current:
            return None

        return self.upsert_strategy_config(
            strategy_key=current["strategy_key"],
            strategy_name=current["strategy_name"],
            symbol=current["symbol"],
            interval=current["interval"],
            ai_enabled=current["ai_enabled"],
            ai_model=current["ai_model"],
            telegram_notify=current["telegram_notify"],
            auto_trade_follow_global=current["auto_trade_follow_global"],
            status=status,
            config_json=current["config_json"],
        )

    def seed_default_strategy_if_missing(
        self,
        strategy_key: str,
        strategy_name: str,
        symbol: str = "BTCUSDT",
        interval: str = "5m",
        ai_enabled: bool = True,
        ai_model: str = "",
        telegram_notify: bool = True,
        auto_trade_follow_global: bool = True,
        status: str = "stopped",
        config_json: str = "",
    ) -> Dict[str, Any]:
        existing = self.get_strategy_config(strategy_key)
        if existing:
            return existing

        return self.upsert_strategy_config(
            strategy_key=strategy_key,
            strategy_name=strategy_name,
            symbol=symbol,
            interval=interval,
            ai_enabled=ai_enabled,
            ai_model=ai_model,
            telegram_notify=telegram_notify,
            auto_trade_follow_global=auto_trade_follow_global,
            status=status,
            config_json=config_json,
        )

    def get_symbols_in_use(self) -> List[str]:
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT symbol
            FROM strategy_configs
            WHERE symbol IS NOT NULL AND symbol != ''
            ORDER BY symbol ASC
        """)

        rows = cursor.fetchall()
        conn.close()

        return [row[0] for row in rows if row and row[0]]

    def get_enabled_strategy_count(self) -> int:
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*)
            FROM strategy_configs
            WHERE status = 'running'
        """)

        count = cursor.fetchone()[0]
        conn.close()

        return int(count or 0)

    def _validate_strategy_config(
        self,
        strategy_key: str,
        strategy_name: str,
        symbol: str,
        interval: str,
        ai_model: str,
        status: str,
    ):
        if not strategy_key:
            raise ValueError("strategy_key 不能为空")

        if not strategy_name:
            raise ValueError("strategy_name 不能为空")

        if not symbol:
            raise ValueError("symbol 不能为空")

        allowed_intervals = {
            "1m", "3m", "5m", "15m", "30m",
            "1h", "2h", "4h", "6h", "12h",
            "1d", "1w"
        }
        if interval not in allowed_intervals:
            raise ValueError(f"interval 不合法，必须是 {sorted(list(allowed_intervals))}")

        allowed_status = {"running", "stopped", "paused"}
        if status not in allowed_status:
            raise ValueError(f"status 不合法，必须是 {sorted(list(allowed_status))}")

        if ai_model and not is_supported_ai_model(ai_model):
            raise ValueError(f"不支持的 ai_model: {ai_model}")

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        return {
            "id": row[0],
            "strategy_key": row[1],
            "strategy_name": row[2],
            "symbol": row[3],
            "interval": row[4],
            "ai_enabled": bool(row[5]),
            "ai_model": row[6] or "",
            "telegram_notify": bool(row[7]),
            "auto_trade_follow_global": bool(row[8]),
            "status": row[9],
            "config_json": row[10] or "",
            "created_at": row[11],
            "updated_at": row[12],
        }


if __name__ == "__main__":
    """
    手动测试：
    在项目根目录执行：
    python -m trading_core.strategy_config_repository
    """
    repo = StrategyConfigRepository()

    print("==== 初始化默认策略 ====")
    print(repo.seed_default_strategy_if_missing(
        strategy_key="MA99_MTF",
        strategy_name="MA99_MTF",
        symbol="BTCUSDT",
        interval="5m",
        ai_enabled=True,
        ai_model="gpt",
        telegram_notify=True,
        auto_trade_follow_global=True,
        status="stopped",
        config_json='{"risk_level":"medium"}',
    ))

    print("\n==== 当前策略列表 ====")
    print(repo.list_strategy_configs())

    print("\n==== 更新策略状态 ====")
    print(repo.update_status("MA99_MTF", "running"))

    print("\n==== 当前运行中的策略数量 ====")
    print(repo.get_enabled_strategy_count())