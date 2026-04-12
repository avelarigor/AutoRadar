#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fila persistente de links (SQLite) para scan FIFO com retry/backoff.
"""

from config_db import DB_PATH
from autoradar_config import RESCAN_COOLDOWN_DAYS

from datetime import datetime, timedelta
from typing import Iterable, List, Dict, Any, Optional, Tuple

from telegram_cache import _connect
from core.settings import DEBUG


STATUS_NEW = "NEW"
STATUS_CLAIMED = "CLAIMED"
STATUS_DONE = "DONE"
STATUS_RETRY = "RETRY"
STATUS_FAILED = "FAILED"


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    u = url.strip()
    u = u.split("#", 1)[0]
    u = u.split("?", 1)[0]
    return u


def _retry_delay_minutes(attempts: int) -> int:
    if attempts <= 1:
        return 10
    if attempts == 2:
        return 30
    if attempts == 3:
        return 120
    if attempts >= 4:
        return 720
    return 10


def enqueue_links(source: str, urls: Iterable[str], module: str = "car", region: str = "") -> Tuple[int, int]:
    now = _now_str()
    added = 0
    ignored = 0
    conn = _connect()
    try:
        cur = conn.cursor()
        for raw in urls or []:
            url = _normalize_url(raw)
            if not url:
                continue
            # Para OLX o region pode ser inferido da própria URL do item;
            # para Facebook (item/xxx) não há slug — usamos o tag passado pelo caller.
            effective_region = region
            if not effective_region:
                ul = url.lower()
                if "belo-horizonte" in ul or "belohorizonte" in ul:
                    effective_region = "bh"
                elif "montes-claros" in ul or "montesclaros" in ul or "regiao-de-montes-claros" in ul:
                    effective_region = "mc"
            cur.execute(
                """
                INSERT OR IGNORE INTO link_queue
                (source, url, status, attempts, discovered_at, updated_at, module, region)
                VALUES (?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (source, url, STATUS_NEW, now, now, module, effective_region),
            )
            if cur.rowcount == 1:
                added += 1
            else:
                # URL já existe — re-enfileira se DONE/FAILED há mais de 6h
                # (permite detectar queda de preço em anúncios já processados)
                cur.execute(
                    """
                    UPDATE link_queue
                    SET status = ?, attempts = 0, updated_at = ?
                    WHERE url = ?
                      AND status IN (?, ?)
                      AND updated_at <= datetime('now', ?)
                    """,
                    (STATUS_NEW, now, url, STATUS_DONE, STATUS_FAILED, f'-{RESCAN_COOLDOWN_DAYS} days'),
                )
                if cur.rowcount == 1:
                    added += 1
                    print(f"[QUEUE] Re-enfileirado para re-scan (possível queda de preço): {url}")
                else:
                    ignored += 1
                    print(f"[QUEUE DEBUG] Ignorado: {url} | Motivo: duplicado ou já existente")
        conn.commit()
    finally:
        conn.close()

    if added or ignored:
        print(f"[QUEUE] enfileirar fonte={source} adicionados={added} ignorados={ignored}")
    return added, ignored


def claim_next_batch(limit: int = 30, module: str = "car") -> List[Dict[str, Any]]:
    now = _now_str()
    conn = _connect()
    try:
        # Inclui itens NEW e itens RETRY cujo prazo de espera já passou
        rows = conn.execute(
            """
            SELECT id, source, url, attempts, region
            FROM link_queue
            WHERE (module = ? OR module IS NULL)
              AND (
                status = ?
                OR (status = ? AND (next_retry_at IS NULL OR next_retry_at <= ?))
              )
            ORDER BY discovered_at ASC
            LIMIT ?
            """,
            (module, STATUS_NEW, STATUS_RETRY, now, int(limit)),
        ).fetchall()

        ids = [r["id"] for r in rows]

        if ids:
            conn.execute(
                f"""
                UPDATE link_queue
                SET status = ?, updated_at = ?
                WHERE id IN ({",".join("?" for _ in ids)})
                """,
                [STATUS_CLAIMED, now] + ids,
            )

        conn.commit()

    finally:
        conn.close()

    batch = [dict(r) for r in rows]

    if batch:
        oldest = batch[0].get("id")
        if DEBUG:
            print(f"[QUEUE] reivindicar n={len(batch)} mais_antigo={oldest}")

    return batch


def mark_done(item_id: int) -> None:
    now = _now_str()
    conn = _connect()
    try:
        conn.execute(
            "UPDATE link_queue SET status = ?, updated_at = ? WHERE id = ?",
            (STATUS_DONE, now, int(item_id)),
        )
        conn.commit()
    finally:
        conn.close()


def mark_retry(item_id: int, error: str) -> Tuple[int, Optional[str], bool]:
    now = _now_str()
    conn = _connect()
    try:
        row = conn.execute("SELECT attempts, url FROM link_queue WHERE id = ?", (int(item_id),)).fetchone()
        if not row:
            return (0, None, False)
        attempts = int(row["attempts"] or 0) + 1
        url = row["url"]
        if attempts >= 6:
            conn.execute(
                """
                UPDATE link_queue
                SET status = ?, attempts = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (STATUS_FAILED, attempts, (error or "").strip()[:300], now, int(item_id)),
            )
            conn.commit()
            print(f"[QUEUE] falha url={url} tentativas={attempts} erro={str(error)[:120]}")
            return (attempts, None, True)
        delay_min = _retry_delay_minutes(attempts)
        next_retry = (datetime.now() + timedelta(minutes=delay_min)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """
            UPDATE link_queue
            SET status = ?, attempts = ?, last_error = ?, next_retry_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (STATUS_RETRY, attempts, (error or "").strip()[:300], next_retry, now, int(item_id)),
        )
        conn.commit()
        print(f"[QUEUE] tentar_novamente url={url} tentativas={attempts} proxima_tentativa_em={next_retry}")
        return (attempts, next_retry, False)
    finally:
        conn.close()


def mark_failed(item_id: int, error: str) -> None:
    now = _now_str()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE link_queue
            SET status = ?, last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (STATUS_FAILED, (error or "").strip()[:300], now, int(item_id)),
        )
        conn.commit()
    finally:
        conn.close()


def unstuck_claims(max_age_minutes: int = 20) -> int:
    now = _now_str()
    cutoff = (datetime.now() - timedelta(minutes=max_age_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    retry_at = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE link_queue
            SET status = ?, next_retry_at = ?, last_error = ?, updated_at = ?
            WHERE status = ? AND updated_at <= ?
            """,
            (STATUS_RETRY, retry_at, "timeout de CLAIM", now, STATUS_CLAIMED, cutoff),
        )
        conn.commit()
        count = cur.rowcount or 0
    finally:
        conn.close()

    if count:
        print(f"[QUEUE] tentar_novamente url=* tentativas=* proxima_tentativa_em={retry_at}")
    return count


def queue_counts() -> Dict[str, int]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(1) AS c FROM link_queue GROUP BY status"
        ).fetchall()
        counts = {r["status"]: int(r["c"] or 0) for r in rows}
        for status in (STATUS_NEW, STATUS_CLAIMED, STATUS_RETRY, STATUS_DONE, STATUS_FAILED):
            counts.setdefault(status, 0)
        return counts
    finally:
        conn.close()


def reset_queue():
    from telegram_cache import _connect
    conn = _connect()
    try:
        conn.execute("DELETE FROM link_queue;")
        conn.commit()
        print("[QUEUE] reset completo executado")
    finally:
        conn.close()


def _ensure_schema():
    conn = _connect()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS link_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            url TEXT UNIQUE,
            status TEXT,
            attempts INTEGER DEFAULT 0,
            discovered_at DATETIME,
            updated_at DATETIME,
            next_retry_at DATETIME,
            last_error TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.commit()
    finally:
        conn.close()

_ensure_schema()
