# -*- coding: utf-8 -*-
"""
AI provider config manager

作用：
1. 管理 AI 大模型配置（API Key / Base URL / Model Name / 启用状态）
2. 使用 SQLite 持久化保存配置
3. 给设置页和策略页提供“哪些模型可用、哪些模型灰色禁用”的状态数据

注意：
- 当前文件只负责“配置管理”，不负责实际调用大模型 API
- 当前文件不会直接影响现有交易逻辑
"""

import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Dict, List, Optional

from trading_core.ai_model_registry import (
    build_default_provider_config,
    get_all_ai_models,
    get_ai_model,
    is_supported_ai_model,
)


class AIProviderConfigManager:
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
                CREATE TABLE IF NOT EXISTS ai_provider_configs (
                    provider_key TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    provider_name TEXT,
                    api_key TEXT,
                    base_url TEXT,
                    model_name TEXT,
                    is_enabled INTEGER DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)

            conn.commit()
            conn.close()

        # 注意：这里必须放到锁外面，避免 _seed_default_records() 二次获取同一把锁造成死锁
        self._seed_default_records()

    def _seed_default_records(self):
        now = datetime.utcnow().isoformat()

        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()

            for model in get_all_ai_models():
                provider_key = model["provider_key"]
                label = model["label"]
                provider_name = model["provider_name"]
                default_model_name = model["default_model_name"]

                cursor.execute("""
                    SELECT provider_key
                    FROM ai_provider_configs
                    WHERE provider_key = ?
                """, (provider_key,))
                exists = cursor.fetchone()

                if not exists:
                    cursor.execute("""
                        INSERT INTO ai_provider_configs (
                            provider_key,
                            label,
                            provider_name,
                            api_key,
                            base_url,
                            model_name,
                            is_enabled,
                            created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        provider_key,
                        label,
                        provider_name,
                        "",
                        "",
                        default_model_name,
                        0,
                        now,
                        now
                    ))

            conn.commit()
            conn.close()

    def save_provider_config(
        self,
        provider_key: str,
        api_key: str = "",
        base_url: str = "",
        model_name: str = "",
        is_enabled: bool = False
    ) -> Dict:
        if not is_supported_ai_model(provider_key):
            raise ValueError(f"Unsupported AI provider: {provider_key}")

        meta = get_ai_model(provider_key)
        now = datetime.utcnow().isoformat()

        api_key = (api_key or "").strip()
        base_url = (base_url or "").strip()
        model_name = (model_name or meta["default_model_name"]).strip()

        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO ai_provider_configs (
                    provider_key,
                    label,
                    provider_name,
                    api_key,
                    base_url,
                    model_name,
                    is_enabled,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_key) DO UPDATE SET
                    label = excluded.label,
                    provider_name = excluded.provider_name,
                    api_key = excluded.api_key,
                    base_url = excluded.base_url,
                    model_name = excluded.model_name,
                    is_enabled = excluded.is_enabled,
                    updated_at = excluded.updated_at
            """, (
                provider_key,
                meta["label"],
                meta["provider_name"],
                api_key,
                base_url,
                model_name,
                1 if is_enabled else 0,
                now,
                now
            ))

            conn.commit()
            conn.close()

        return self.get_provider_config(provider_key)

    def get_provider_config(self, provider_key: str) -> Optional[Dict]:
        if not is_supported_ai_model(provider_key):
            return None

        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                provider_key,
                label,
                provider_name,
                api_key,
                base_url,
                model_name,
                is_enabled,
                created_at,
                updated_at
            FROM ai_provider_configs
            WHERE provider_key = ?
        """, (provider_key,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        api_key = row[3] or ""
        configured = bool(api_key.strip())
        enabled = bool(row[6])

        result = {
            "provider_key": row[0],
            "label": row[1],
            "provider_name": row[2],
            "api_key": api_key,
            "masked_api_key": self._mask_api_key(api_key),
            "base_url": row[4] or "",
            "model_name": row[5] or "",
            "is_enabled": enabled,
            "configured": configured,
            "selectable": configured and enabled,
            "created_at": row[7],
            "updated_at": row[8],
        }
        return result

    def list_provider_configs(self) -> List[Dict]:
        results = []
        for model in get_all_ai_models():
            provider_key = model["provider_key"]
            config = self.get_provider_config(provider_key)
            if config:
                results.append(config)
            else:
                default_item = build_default_provider_config(provider_key)
                results.append(default_item)

        results.sort(key=lambda x: get_ai_model(x["provider_key"]).get("sort_order", 999))
        return results

    def list_models_with_status(self) -> List[Dict]:
        """
        返回给前端策略页/设置页使用的标准数据
        """
        items = []
        for item in self.list_provider_configs():
            items.append({
                "provider_key": item["provider_key"],
                "label": item["label"],
                "provider_name": item["provider_name"],
                "model_name": item["model_name"],
                "configured": item["configured"],
                "is_enabled": item["is_enabled"],
                "selectable": item["selectable"],
                "masked_api_key": item["masked_api_key"],
                "base_url": item["base_url"],
                "updated_at": item["updated_at"],
            })
        return items

    def enable_provider(self, provider_key: str) -> Dict:
        current = self.get_provider_config(provider_key)
        if not current:
            raise ValueError(f"Provider not found: {provider_key}")

        if not current["configured"]:
            raise ValueError(f"Provider API key not configured: {provider_key}")

        return self.save_provider_config(
            provider_key=provider_key,
            api_key=current["api_key"],
            base_url=current["base_url"],
            model_name=current["model_name"],
            is_enabled=True
        )

    def disable_provider(self, provider_key: str) -> Dict:
        current = self.get_provider_config(provider_key)
        if not current:
            raise ValueError(f"Provider not found: {provider_key}")

        return self.save_provider_config(
            provider_key=provider_key,
            api_key=current["api_key"],
            base_url=current["base_url"],
            model_name=current["model_name"],
            is_enabled=False
        )

    def delete_provider_api_key(self, provider_key: str) -> Dict:
        """
        清空 API Key，但保留记录。用于前端“清除配置”。
        """
        current = self.get_provider_config(provider_key)
        if not current:
            raise ValueError(f"Provider not found: {provider_key}")

        return self.save_provider_config(
            provider_key=provider_key,
            api_key="",
            base_url=current["base_url"],
            model_name=current["model_name"],
            is_enabled=False
        )

    def export_safe_configs(self) -> str:
        """
        导出安全配置（不包含明文 api_key）
        """
        safe_items = []
        for item in self.list_provider_configs():
            safe_items.append({
                "provider_key": item["provider_key"],
                "label": item["label"],
                "provider_name": item["provider_name"],
                "masked_api_key": item["masked_api_key"],
                "base_url": item["base_url"],
                "model_name": item["model_name"],
                "is_enabled": item["is_enabled"],
                "configured": item["configured"],
                "selectable": item["selectable"],
                "updated_at": item["updated_at"],
            })
        return json.dumps(safe_items, ensure_ascii=False, indent=2)

    @staticmethod
    def _mask_api_key(api_key: str) -> str:
        if not api_key:
            return ""

        key = api_key.strip()
        if len(key) <= 8:
            return "*" * len(key)

        return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"


if __name__ == "__main__":
    """
    允许手动测试本文件是否正常
    执行方式（在项目根目录）：
    python -m trading_core.ai_provider_config_manager
    """
    manager = AIProviderConfigManager()

    print("==== 当前模型状态 ====")
    print(manager.export_safe_configs())

    print("\n==== 示例：保存 GPT 配置 ====")
    manager.save_provider_config(
        provider_key="gpt",
        api_key="sk-demo-test-1234567890",
        base_url="",
        model_name="gpt-4o-mini",
        is_enabled=True
    )

    print(manager.export_safe_configs())