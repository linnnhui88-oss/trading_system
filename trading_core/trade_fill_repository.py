# -*- coding: utf-8 -*-
"""
Trade fill repository

作用：
1. 专门记录每一次实际成交/执行事件
2. 支持开仓、加仓、部分平仓、全平、止盈、止损、手动平仓等动作
3. 为交易记录页面提供完整可追溯的数据来源

为什么必须有这个文件：
- 订单(order)是“下单意图”
- 成交(fill)是“实际执行结果”
- 你要展示“部分平仓”，必须单独记录 fill，不能只看 positions/orders

注意：
- 当前文件只负责数据库读写
- 当前文件不会自动接入现有交易执行流程
- 后续我们会在 order_executor.py 里把真实执行结果写进这里
"""

import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional


class TradeFillRepository:
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
                CREATE TABLE IF NOT EXISTS trade_fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    position_side TEXT,
                    action_type TEXT NOT NULL,
                    order_id TEXT,
                    exchange_trade_id TEXT,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    realized_pnl REAL DEFAULT 0,
                    fee REAL DEFAULT 0,
                    fee_asset TEXT,
                    ai_model TEXT,
                    ai_decision TEXT,
                    signal_source TEXT,
                    signal_reason TEXT,
                    executed_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trade_fills_symbol
                ON trade_fills(symbol)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trade_fills_strategy_name
                ON trade_fills(strategy_name)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trade_fills_action_type
                ON trade_fills(action_type)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trade_fills_executed_at
                ON trade_fills(executed_at)
            """)

            conn.commit()
            conn.close()

    def create_fill(self, fill_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        新增一条成交明细记录
        fill_data 建议包含：
        - strategy_name
        - symbol
        - side
        - position_side
        - action_type
        - order_id
        - exchange_trade_id
        - quantity
        - price
        - realized_pnl
        - fee
        - fee_asset
        - ai_model
        - ai_decision
        - signal_source
        - signal_reason
        - executed_at
        """
        now = datetime.utcnow().isoformat()
        executed_at = (fill_data.get("executed_at") or now).strip()

        record = {
            "strategy_name": (fill_data.get("strategy_name") or "").strip(),
            "symbol": (fill_data.get("symbol") or "").strip(),
            "side": (fill_data.get("side") or "").strip().upper(),
            "position_side": (fill_data.get("position_side") or "").strip().upper(),
            "action_type": (fill_data.get("action_type") or "").strip().lower(),
            "order_id": str(fill_data.get("order_id") or "").strip(),
            "exchange_trade_id": str(fill_data.get("exchange_trade_id") or "").strip(),
            "quantity": self._safe_float(fill_data.get("quantity"), default=0.0),
            "price": self._safe_float(fill_data.get("price"), default=0.0),
            "realized_pnl": self._safe_float(fill_data.get("realized_pnl"), default=0.0),
            "fee": self._safe_float(fill_data.get("fee"), default=0.0),
            "fee_asset": (fill_data.get("fee_asset") or "").strip(),
            "ai_model": (fill_data.get("ai_model") or "").strip(),
            "ai_decision": (fill_data.get("ai_decision") or "").strip().upper(),
            "signal_source": (fill_data.get("signal_source") or "").strip(),
            "signal_reason": (fill_data.get("signal_reason") or "").strip(),
            "executed_at": executed_at,
            "created_at": now,
        }

        self._validate_fill_record(record)

        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO trade_fills (
                    strategy_name,
                    symbol,
                    side,
                    position_side,
                    action_type,
                    order_id,
                    exchange_trade_id,
                    quantity,
                    price,
                    realized_pnl,
                    fee,
                    fee_asset,
                    ai_model,
                    ai_decision,
                    signal_source,
                    signal_reason,
                    executed_at,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record["strategy_name"],
                record["symbol"],
                record["side"],
                record["position_side"],
                record["action_type"],
                record["order_id"],
                record["exchange_trade_id"],
                record["quantity"],
                record["price"],
                record["realized_pnl"],
                record["fee"],
                record["fee_asset"],
                record["ai_model"],
                record["ai_decision"],
                record["signal_source"],
                record["signal_reason"],
                record["executed_at"],
                record["created_at"],
            ))

            row_id = cursor.lastrowid
            conn.commit()
            conn.close()

        return self.get_fill_by_id(row_id)

    def get_fill_by_id(self, fill_id: int) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                id,
                strategy_name,
                symbol,
                side,
                position_side,
                action_type,
                order_id,
                exchange_trade_id,
                quantity,
                price,
                realized_pnl,
                fee,
                fee_asset,
                ai_model,
                ai_decision,
                signal_source,
                signal_reason,
                executed_at,
                created_at
            FROM trade_fills
            WHERE id = ?
        """, (fill_id,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return self._row_to_dict(row)

    def list_fills(
        self,
        symbol: str = "",
        strategy_name: str = "",
        action_type: str = "",
        start_time: str = "",
        end_time: str = "",
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT
                id,
                strategy_name,
                symbol,
                side,
                position_side,
                action_type,
                order_id,
                exchange_trade_id,
                quantity,
                price,
                realized_pnl,
                fee,
                fee_asset,
                ai_model,
                ai_decision,
                signal_source,
                signal_reason,
                executed_at,
                created_at
            FROM trade_fills
            WHERE 1 = 1
        """
        params = []

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.strip())

        if strategy_name:
            query += " AND strategy_name = ?"
            params.append(strategy_name.strip())

        if action_type:
            query += " AND action_type = ?"
            params.append(action_type.strip().lower())

        if start_time:
            query += " AND executed_at >= ?"
            params.append(start_time.strip())

        if end_time:
            query += " AND executed_at <= ?"
            params.append(end_time.strip())

        query += " ORDER BY executed_at DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([max(1, int(limit)), max(0, int(offset))])

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def count_fills(
        self,
        symbol: str = "",
        strategy_name: str = "",
        action_type: str = "",
        start_time: str = "",
        end_time: str = ""
    ) -> int:
        query = "SELECT COUNT(*) FROM trade_fills WHERE 1 = 1"
        params = []

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.strip())

        if strategy_name:
            query += " AND strategy_name = ?"
            params.append(strategy_name.strip())

        if action_type:
            query += " AND action_type = ?"
            params.append(action_type.strip().lower())

        if start_time:
            query += " AND executed_at >= ?"
            params.append(start_time.strip())

        if end_time:
            query += " AND executed_at <= ?"
            params.append(end_time.strip())

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(query, params)
        count = cursor.fetchone()[0]
        conn.close()

        return int(count)

    def get_summary(self) -> Dict[str, Any]:
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*), COALESCE(SUM(realized_pnl), 0), COALESCE(SUM(fee), 0)
            FROM trade_fills
        """)
        row = cursor.fetchone()

        cursor.execute("""
            SELECT action_type, COUNT(*)
            FROM trade_fills
            GROUP BY action_type
            ORDER BY COUNT(*) DESC
        """)
        action_rows = cursor.fetchall()

        conn.close()

        action_counts = {}
        for action_type, cnt in action_rows:
            action_counts[action_type] = cnt

        return {
            "total_fills": int(row[0] or 0),
            "total_realized_pnl": float(row[1] or 0.0),
            "total_fee": float(row[2] or 0.0),
            "action_counts": action_counts,
        }

    def _validate_fill_record(self, record: Dict[str, Any]):
        if not record["symbol"]:
            raise ValueError("symbol 不能为空")

        if not record["side"]:
            raise ValueError("side 不能为空")

        if record["side"] not in {"BUY", "SELL"}:
            raise ValueError("side 只能是 BUY 或 SELL")

        if not record["action_type"]:
            raise ValueError("action_type 不能为空")

        allowed_action_types = {
            "open",
            "add",
            "partial_close",
            "close",
            "take_profit",
            "stop_loss",
            "manual_close",
        }
        if record["action_type"] not in allowed_action_types:
            raise ValueError(
                f"action_type 不合法，必须是 {sorted(list(allowed_action_types))}"
            )

        if record["quantity"] <= 0:
            raise ValueError("quantity 必须大于 0")

        if record["price"] <= 0:
            raise ValueError("price 必须大于 0")

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        return {
            "id": row[0],
            "strategy_name": row[1],
            "symbol": row[2],
            "side": row[3],
            "position_side": row[4],
            "action_type": row[5],
            "order_id": row[6],
            "exchange_trade_id": row[7],
            "quantity": float(row[8] or 0.0),
            "price": float(row[9] or 0.0),
            "realized_pnl": float(row[10] or 0.0),
            "fee": float(row[11] or 0.0),
            "fee_asset": row[12] or "",
            "ai_model": row[13] or "",
            "ai_decision": row[14] or "",
            "signal_source": row[15] or "",
            "signal_reason": row[16] or "",
            "executed_at": row[17],
            "created_at": row[18],
        }


if __name__ == "__main__":
    """
    手动测试：
    在项目根目录执行：
    python -m trading_core.trade_fill_repository
    """
    repo = TradeFillRepository()

    demo = repo.create_fill({
        "strategy_name": "MA99_MTF",
        "symbol": "BTCUSDT",
        "side": "SELL",
        "position_side": "LONG",
        "action_type": "partial_close",
        "order_id": "demo-order-001",
        "exchange_trade_id": "demo-trade-001",
        "quantity": 0.01,
        "price": 68500.5,
        "realized_pnl": 12.6,
        "fee": 0.25,
        "fee_asset": "USDT",
        "ai_model": "gpt",
        "ai_decision": "EXECUTE",
        "signal_source": "strategy_signal",
        "signal_reason": "达到部分止盈条件",
    })

    print("==== 新增成交 ====")
    print(demo)

    print("\n==== 最近成交 ====")
    print(repo.list_fills(limit=10))

    print("\n==== 汇总 ====")
    print(repo.get_summary())