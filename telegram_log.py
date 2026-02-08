#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Registro leve de envios do Telegram (SQLite).
Salva só o essencial por oportunidade enviada (sem guardar mensagens).
Usado para parciais (12h/19h) e recap (08h do dia seguinte).
"""

import hashlib
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent


def _out_dir() -> Path:
    try:
        from path_utils import get_out_dir
        return get_out_dir()
    except Exception:
        return BASE_DIR / "out"


DB_PATH = _out_dir() / "telegram_sends.db"


def infer_source(url: str) -> str:
    u = (url or "").lower()
    if "facebook.com" in u:
        return "Facebook"
    if "olx.com.br" in u:
        return "OLX"
    if "webmotors.com.br" in u:
        return "Webmotors"
    if "mobiauto.com.br" in u:
        return "Mobiauto"
    return "Outros"


def _local_day_and_ts() -> Tuple[str, str]:
    now = datetime.now()
    return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d %H:%M:%S")


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if not s:
            return None
        s = s.replace("R$", "").replace(".", "").replace(",", ".")
        return float(s)
    except Exception:
        return None


def _safe_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        if isinstance(x, int):
            return x
        s = str(x).strip()
        if not s:
            return None
        return int(re.sub(r"[^\d]+", "", s))
    except Exception:
        return None


def model_short_from_item(item: Dict[str, Any]) -> str:
    """
    Modelo curto para relatórios (ex.: "Gol City").
    Remove ruído, limita 2-3 palavras.
    """
    title = (item.get("modelo") or item.get("title_original") or item.get("title") or "Anúncio")
    title = str(title)
    if "{" in title or '"pageProps"' in title or '"props"' in title:
        title = "Anúncio"

    t = title.lower()
    marcas = [
        "volkswagen", "vw", "chevrolet", "gm", "fiat", "ford", "toyota", "honda",
        "hyundai", "renault", "nissan", "peugeot", "citroen", "jeep", "mitsubishi",
        "bmw", "mercedes", "audi", "kia", "chery", "byd"
    ]
    for m in marcas:
        t = re.sub(rf"\b{re.escape(m)}\b", "", t)

    noise = [
        "flex", "gasolina", "diesel", "etanol", "aut", "automático", "automatico",
        "manual", "cv", "16v", "8v", "turbo", "completo", "top", "novo", "único dono",
        "unico dono", "revisado", "blindado"
    ]
    for n in noise:
        t = re.sub(rf"\b{re.escape(n)}\b", "", t)

    t = re.sub(r"[^a-z0-9\s]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    parts = t.split()
    if not parts:
        return "Anúncio"
    short = " ".join(parts[:3]).strip()
    return short.title()[:40]


def build_listing_id(item: Dict[str, Any]) -> str:
    """ID estável para deduplicar envios."""
    url = (item.get("url") or "").strip()
    if url:
        m = re.search(r"facebook\.com/marketplace/item/(\d+)", url, re.I)
        if m:
            return f"fb_{m.group(1)}"
        return "u_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]

    title = str(item.get("modelo") or item.get("title_original") or item.get("title") or "")
    ano = str(item.get("ano") or item.get("year") or "")
    preco = str(item.get("preco") or item.get("price") or "")
    raw = f"{title}|{ano}|{preco}"
    return "h_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS telegram_sends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            source TEXT,
            model_short TEXT,
            year INTEGER,
            price REAL,
            fipe REAL,
            margin_value REAL,
            margin_pct REAL,
            link TEXT,
            listing_id TEXT NOT NULL UNIQUE
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_telegram_sends_day ON telegram_sends(day);")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_flags (
            day TEXT PRIMARY KEY,
            noon_sent INTEGER DEFAULT 0,
            evening_sent INTEGER DEFAULT 0,
            recap_sent INTEGER DEFAULT 0
        );
        """)
        conn.commit()
    finally:
        conn.close()


def log_send(item: Dict[str, Any], sent_ok: bool = True) -> bool:
    """
    Registra o envio (se ok). Retorna True se inseriu, False se ignorou (duplicado).
    """
    if not sent_ok:
        return False

    init_db()
    day, ts = _local_day_and_ts()

    url = (item.get("url") or "").strip()
    source = infer_source(url)
    model_short = model_short_from_item(item)

    year = _safe_int(item.get("ano") or item.get("year"))
    price = _safe_float(item.get("preco") or item.get("price"))
    fipe = _safe_float(item.get("fipe"))
    margin_value = _safe_float(item.get("margem_reais"))
    margin_pct = _safe_float(item.get("margem"))
    listing_id = build_listing_id(item)
    link = url

    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO telegram_sends
            (day, sent_at, source, model_short, year, price, fipe, margin_value, margin_pct, link, listing_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (day, ts, source, model_short, year, price, fipe, margin_value, margin_pct, link, listing_id)
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def get_flag(day: str) -> Tuple[int, int, int]:
    init_db()
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT noon_sent, evening_sent, recap_sent FROM daily_flags WHERE day = ?", (day,))
        row = cur.fetchone()
        if not row:
            cur.execute("INSERT OR IGNORE INTO daily_flags(day, noon_sent, evening_sent, recap_sent) VALUES (?,0,0,0)", (day,))
            conn.commit()
            return (0, 0, 0)
        return (int(row[0]), int(row[1]), int(row[2]))
    finally:
        conn.close()


def set_flag(day: str, *, noon: Optional[int] = None, evening: Optional[int] = None, recap: Optional[int] = None) -> None:
    init_db()
    conn = _connect()
    try:
        conn.execute("INSERT OR IGNORE INTO daily_flags(day, noon_sent, evening_sent, recap_sent) VALUES (?,0,0,0)", (day,))
        if noon is not None:
            conn.execute("UPDATE daily_flags SET noon_sent = ? WHERE day = ?", (int(noon), day))
        if evening is not None:
            conn.execute("UPDATE daily_flags SET evening_sent = ? WHERE day = ?", (int(evening), day))
        if recap is not None:
            conn.execute("UPDATE daily_flags SET recap_sent = ? WHERE day = ?", (int(recap), day))
        conn.commit()
    finally:
        conn.close()
