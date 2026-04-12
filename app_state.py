#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Estado persistente e eventos simples em SQLite (mesmo DB do Telegram).
"""

import sqlite3
from pathlib import Path
from typing import List, Dict
from datetime import datetime
from telegram_cache import _connect

BASE_DIR = Path(__file__).resolve().parent
# DB_PATH = BASE_DIR / "telegram_cache.db"


def _get_conn():
    return _connect()


def set_state(key: str, value: str):
    conn = _get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO app_state (key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET
            value=excluded.value,
            updated_at=CURRENT_TIMESTAMP
    """, (key, value))

    conn.commit()
    conn.close()


def get_state(key: str):
    conn = _get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT value FROM app_state WHERE key = ?", (key,))
    row = cursor.fetchone()

    conn.close()
    return row[0] if row else None


def get_state_int(key: str, default: int = 0) -> int:
    val = get_state(key)
    try:
        return int(val) if val is not None and str(val).strip() != "" else default
    except Exception:
        return default


def get_state_float(key: str, default: float = 0.0) -> float:
    val = get_state(key)
    try:
        return float(val) if val is not None and str(val).strip() != "" else default
    except Exception:
        return default


def _now_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def append_event(tag: str, msg: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO app_events (event_type, message, created_at) VALUES (?, ?, ?)",
            ( (tag or "").strip()[:20], (msg or "").strip()[:300], _now_str()),
        )
        conn.commit()
    finally:
        conn.close()


def get_last_events(limit: int = 5) -> List[Dict[str, str]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT created_at, event_type, message FROM app_events ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def heartbeat(worker: str) -> None:
    set_state(f"{worker}.last_heartbeat", _now_str())
