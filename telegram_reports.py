#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Relatórios para Telegram (parcial do dia, recap de ontem).
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from telegram_log import DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _fmt_money(v: Optional[float]) -> str:
    if v is None:
        return "-"
    try:
        return f"R$ {v:,.0f}".replace(",", ".")
    except Exception:
        return "-"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "-"
    try:
        return f"{v:.1f}%"
    except Exception:
        return "-"


def day_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def get_count(day: str) -> int:
    if not DB_PATH.exists():
        return 0
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM telegram_sends WHERE day = ?", (day,))
        return int(cur.fetchone()["c"])
    except Exception:
        return 0
    finally:
        conn.close()


def get_top(day: str, limit: int = 10) -> List[Dict]:
    if not DB_PATH.exists():
        return []
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT model_short, year, price, fipe, margin_value, margin_pct, link, source
            FROM telegram_sends
            WHERE day = ?
            ORDER BY COALESCE(margin_value, -999999) DESC
            LIMIT ?
            """,
            (day, int(limit))
        )
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def get_champion(day: str) -> Optional[Dict]:
    rows = get_top(day, limit=1)
    return rows[0] if rows else None


def build_partial_message(day: str, when_label: str, top_n: int = 10) -> str:
    """Mensagem parcial (12h ou 19h)."""
    total = get_count(day)
    top = get_top(day, limit=top_n)

    lines = []
    lines.append(f"📡 <b>AutoRadar — Parcial {when_label}</b>")
    lines.append(f"✅ Até agora, já enviamos <b>{total}</b> oportunidades hoje! 😄")
    lines.append("")
    if top:
        lines.append("🏅 <b>Top oportunidades por margem:</b>")
        for i, it in enumerate(top, start=1):
            model = it.get("model_short") or "Anúncio"
            year = it.get("year") or "-"
            price = _fmt_money(it.get("price"))
            fipe = _fmt_money(it.get("fipe"))
            mv = _fmt_money(it.get("margin_value"))
            mp = _fmt_pct(it.get("margin_pct"))
            lines.append(f"{i}) {model} {year} — {price} | FIPE {fipe} | <b>+{mv}</b> ({mp})")
        lines.append("")
        lines.append("👀 Ainda tem mais por vir… fica ligado! 🔥")
    else:
        lines.append("😅 Ainda não tivemos envios suficientes pra montar um Top. Já já chega! 🚀")

    return "\n".join(lines).strip()


def build_recap_message(yesterday: str) -> str:
    """Mensagem de recap (08h do dia seguinte)."""
    total = get_count(yesterday)
    champ = get_champion(yesterday)

    lines = []
    lines.append("🌅 <b>Bom dia!</b>")
    lines.append(f"📊 Ontem enviamos <b>{total}</b> oportunidades. Hoje supera? Bora pra cima!!! 🚀🔥")
    lines.append("")

    if champ:
        model = champ.get("model_short") or "Anúncio"
        year = champ.get("year") or "-"
        price = _fmt_money(champ.get("price"))
        fipe = _fmt_money(champ.get("fipe"))
        mv = _fmt_money(champ.get("margin_value"))
        mp = _fmt_pct(champ.get("margin_pct"))
        link = champ.get("link") or ""
        lines.append("🏆 <b>Campeã de ontem:</b>")
        lines.append(f"{model} {year} — {price} | FIPE {fipe} | <b>+{mv}</b> ({mp}) 💰😮")
        if link:
            lines.append(f"🔗 {link}")
    else:
        lines.append("🤷‍♂️ Não encontrei envios de ontem no log (talvez o app não rodou).")

    return "\n".join(lines).strip()


def yesterday_str() -> str:
    return day_str(datetime.now() - timedelta(days=1))
