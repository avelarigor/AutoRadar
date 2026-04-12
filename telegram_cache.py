#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from config_db import DB_PATH


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column_exists(conn, table, column, definition):
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    if column not in columns:
        print(f"[DB MIGRATION] Adicionando coluna {column}")
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = _connect()
    try:
        ensure_column_exists(conn, "opportunities", "telegram_sent", "INTEGER DEFAULT 0")
        conn.commit()
    finally:
        conn.close()


def get_pending(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Retorna e marca atomicamente itens a enviar (telegram_sent=0→3 in_flight)."""
    init_db()
    conn = _connect()
    try:
        # Claim atômico: evita envio duplo em múltiplas instâncias
        if limit:
            conn.execute("""
                UPDATE opportunities SET telegram_sent = 3
                WHERE id IN (
                    SELECT id FROM opportunities
                    WHERE telegram_sent = 0
                    ORDER BY created_at DESC
                    LIMIT ?
                )
            """, (limit,))
        else:
            conn.execute("""
                UPDATE opportunities SET telegram_sent = 3
                WHERE telegram_sent = 0
            """)
        conn.commit()

        sql = "SELECT * FROM opportunities WHERE telegram_sent = 3 ORDER BY created_at DESC"
        if limit:
            sql += " LIMIT ?"
            rows = conn.execute(sql, (limit,)).fetchall()
        else:
            rows = conn.execute(sql).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_sent(item_id: int):
    conn = _connect()
    try:
        conn.execute("""
            UPDATE opportunities
            SET telegram_sent = 1
            WHERE id = ?
        """, (item_id,))
        conn.commit()
    finally:
        conn.close()


def mark_failed(item_id: int):
    """Incrementa send_attempts. Reverte para retry (0) ou abandona (2) após 5 falhas."""
    conn = _connect()
    try:
        ensure_column_exists(conn, "opportunities", "send_attempts", "INTEGER DEFAULT 0")
        conn.commit()
        conn.execute("""
            UPDATE opportunities
            SET send_attempts = send_attempts + 1,
                telegram_sent = CASE WHEN send_attempts + 1 >= 5 THEN 2 ELSE 0 END
            WHERE id = ? AND telegram_sent = 3
        """, (item_id,))
        conn.commit()
        row = conn.execute("SELECT send_attempts, telegram_sent FROM opportunities WHERE id=?", (item_id,)).fetchone()
        if row and row[1] == 2:
            print(f"[TG] ID={item_id} abandonado após {row[0]} tentativas (telegram_sent=2)")
        elif row:
            print(f"[TG] ID={item_id} tentativa {row[0]}/5 — volta para retry")
    finally:
        conn.close()


def reset_inflight():
    """Reseta itens in_flight (3→0) — chamar no startup."""
    conn = _connect()
    try:
        n = conn.execute(
            "UPDATE opportunities SET telegram_sent = 0 WHERE telegram_sent = 3"
        ).rowcount
        conn.commit()
        if n:
            print(f"[DISPATCHER] {n} item(s) 'in_flight' resetados no startup")
    finally:
        conn.close()