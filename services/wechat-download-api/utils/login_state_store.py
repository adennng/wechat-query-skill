#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2026 tmwgsicp
# Licensed under the GNU Affero General Public License v3.0
# See LICENSE file in the project root for full license text.
# SPDX-License-Identifier: AGPL-3.0-only
"""
登录状态持久化
记录最近登录时间、失效状态和待提醒标记。
"""

import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

_default_db = Path(__file__).parent.parent / "data" / "rss.db"
DB_PATH = Path(os.getenv("RSS_DB_PATH", str(_default_db)))


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_login_state_db() -> None:
    """创建登录状态表（幂等）。"""
    now_ms = int(time.time() * 1000)
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS auth_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_login_time INTEGER NOT NULL DEFAULT 0,
                login_state TEXT NOT NULL DEFAULT 'unknown',
                last_invalid_time INTEGER NOT NULL DEFAULT 0,
                last_invalid_reason TEXT NOT NULL DEFAULT '',
                invalid_alert_pending INTEGER NOT NULL DEFAULT 0,
                invalid_alert_sent_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0
            );
        """)
        conn.execute(
            "INSERT OR IGNORE INTO auth_state (id, updated_at) VALUES (1, ?)",
            (now_ms,),
        )
        conn.commit()
    finally:
        conn.close()


def get_login_state() -> Dict[str, Any]:
    """获取当前登录状态行。"""
    init_login_state_db()
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM auth_state WHERE id=1").fetchone()
        return dict(row) if row else {
            "id": 1,
            "last_login_time": 0,
            "login_state": "unknown",
            "last_invalid_time": 0,
            "last_invalid_reason": "",
            "invalid_alert_pending": 0,
            "invalid_alert_sent_at": 0,
            "updated_at": 0,
        }
    finally:
        conn.close()


def mark_login_valid(login_time_ms: Optional[int] = None) -> None:
    """标记凭证当前有效，并重置失效提醒。"""
    init_login_state_db()
    now_ms = login_time_ms or int(time.time() * 1000)
    conn = _get_conn()
    try:
        conn.execute(
            """
            UPDATE auth_state
               SET last_login_time=?,
                   login_state='valid',
                   last_invalid_time=0,
                   last_invalid_reason='',
                   invalid_alert_pending=0,
                   invalid_alert_sent_at=0,
                   updated_at=?
             WHERE id=1
            """,
            (now_ms, now_ms),
        )
        conn.commit()
    finally:
        conn.close()


def mark_login_invalid(source: str, reason: str) -> bool:
    """
    标记登录失效。
    返回值表示本次是否首次进入失效状态，可用于触发一次性提醒。
    """
    init_login_state_db()
    now_ms = int(time.time() * 1000)
    reason_text = f"{source}: {reason}".strip(": ")
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT login_state, invalid_alert_pending FROM auth_state WHERE id=1"
        ).fetchone()
        current_state = row["login_state"] if row else "unknown"
        should_raise_alert = current_state != "invalid"
        conn.execute(
            """
            UPDATE auth_state
               SET login_state='invalid',
                   last_invalid_time=?,
                   last_invalid_reason=?,
                   invalid_alert_pending=CASE
                       WHEN login_state='invalid' THEN invalid_alert_pending
                       ELSE 1
                   END,
                   updated_at=?
             WHERE id=1
            """,
            (now_ms, reason_text, now_ms),
        )
        conn.commit()
        return should_raise_alert
    finally:
        conn.close()


def ack_invalid_alert() -> None:
    """确认失效提醒已由上层发送。"""
    init_login_state_db()
    now_ms = int(time.time() * 1000)
    conn = _get_conn()
    try:
        conn.execute(
            """
            UPDATE auth_state
               SET invalid_alert_pending=0,
                   invalid_alert_sent_at=?,
                   updated_at=?
             WHERE id=1
            """,
            (now_ms, now_ms),
        )
        conn.commit()
    finally:
        conn.close()


def clear_login_state() -> None:
    """清空当前登录有效性标记，但保留最近登录时间用于展示。"""
    init_login_state_db()
    now_ms = int(time.time() * 1000)
    conn = _get_conn()
    try:
        conn.execute(
            """
            UPDATE auth_state
               SET login_state='unknown',
                   last_invalid_time=0,
                   last_invalid_reason='',
                   invalid_alert_pending=0,
                   invalid_alert_sent_at=0,
                   updated_at=?
             WHERE id=1
            """,
            (now_ms,),
        )
        conn.commit()
    finally:
        conn.close()
