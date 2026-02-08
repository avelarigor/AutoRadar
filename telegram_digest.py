# -*- coding: utf-8 -*-
"""
Telegram Daily Tracker + Digests 🧾📲

Objetivo:
- Registrar somente o essencial de cada envio (modelo/ano/valor/fipe/margem)
- Enviar "digest" automático às 12:00 e 19:00 (uma vez por dia)
- Enviar resumo do dia anterior às 08:00 do dia seguinte

⚠️ Não depende de scheduler externo.
Funciona assim:
- Cada execução do pipeline chama maybe_send_digests(...) depois de enviar oportunidades.
- O módulo olha o horário atual e decide se já está na hora e se ainda não foi enviado.

Arquivos gerados (em out/):
- telegram_daily/AAAA-MM-DD.jsonl         (log bruto do dia)
- telegram_daily/state.json              (controle de digests enviados)

Você precisa passar uma função `send_text(texto)` que envia mensagem no Telegram
(ou adaptar para usar o seu send_telegram.py).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


# --------------------
# Helpers
# --------------------

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _today_str(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")

def _yesterday_str(now: datetime) -> str:
    return (now - timedelta(days=1)).strftime("%Y-%m-%d")

def _load_json(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default

def _save_json(p: Path, obj) -> None:
    try:
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


@dataclass
class SentRow:
    ts: str
    modelo: str
    ano: int
    valor: float
    fipe: float
    margem: float
    origem: str = ""

    @staticmethod
    def from_dict(d: Dict) -> "SentRow":
        return SentRow(
            ts=str(d.get("ts") or ""),
            modelo=str(d.get("modelo") or ""),
            ano=int(d.get("ano") or 0),
            valor=float(d.get("valor") or 0),
            fipe=float(d.get("fipe") or 0),
            margem=float(d.get("margem") or 0),
            origem=str(d.get("origem") or ""),
        )


# --------------------
# Storage
# --------------------

def get_base_dir() -> Path:
    try:
        from path_utils import get_out_dir  # type: ignore
        out = get_out_dir()
    except Exception:
        out = Path("out")
    base = Path(out) / "telegram_daily"
    _ensure_dir(base)
    return base

def day_log_path(day: str) -> Path:
    return get_base_dir() / f"{day}.jsonl"

def state_path() -> Path:
    return get_base_dir() / "state.json"


# --------------------
# Public API
# --------------------

def log_sent(item: Dict, now: Optional[datetime] = None) -> None:
    """
    item esperado (mínimo):
    {
      "modelo_short": "Gol City",
      "ano": 2014,
      "preco": 29900,
      "valor_fipe": 36000,
      "margem": 6100,
      "source": "FB|WM|OLX|MA"
    }
    """
    now = now or datetime.now()
    day = _today_str(now)
    p = day_log_path(day)

    row = SentRow(
        ts=now.isoformat(timespec="seconds"),
        modelo=str(item.get("modelo_short") or item.get("modelo") or "").strip(),
        ano=int(item.get("ano") or 0),
        valor=float(item.get("preco") or item.get("valor") or 0),
        fipe=float(item.get("valor_fipe") or item.get("fipe") or 0),
        margem=float(item.get("margem") or 0),
        origem=str(item.get("source") or item.get("origem") or "")
    )

    # só registra se tiver o essencial
    if not row.modelo or row.ano <= 0 or row.valor <= 0 or row.fipe <= 0:
        return

    try:
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_day(day: str) -> List[SentRow]:
    p = day_log_path(day)
    if not p.exists():
        return []
    rows: List[SentRow] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(SentRow.from_dict(json.loads(line)))
            except Exception:
                continue
    except Exception:
        return []
    return rows


def top_by_margin(rows: List[SentRow], n: int = 10) -> List[SentRow]:
    return sorted(rows, key=lambda r: r.margem, reverse=True)[:n]


def _fmt_money(v: float) -> str:
    # formato pt-BR simples
    s = f"{v:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def build_midday_message(rows: List[SentRow]) -> str:
    total = len(rows)
    top = top_by_margin(rows, 10)
    lines = []
    lines.append("🕛 12:00")
    lines.append(f"🚀 Até agora já enviamos *{total}* oportunidades hoje! 😄")
    if top:
        lines.append("🏆 Algumas das melhores até o momento:")
        for r in top:
            lines.append(f"• {r.modelo} {r.ano} | {_fmt_money(r.valor)} | FIPE {_fmt_money(r.fipe)} | Margem {_fmt_money(r.margem)}")
    lines.append("⏳ E ainda tem mais por vir… aguenta aí! 🔥")
    return "\n".join(lines)


def build_evening_message(rows: List[SentRow]) -> str:
    total = len(rows)
    top = top_by_margin(rows, 10)
    lines = []
    lines.append("🌙 19:00")
    lines.append(f"😎 Já mandamos *{total}* oportunidades hoje… e pensa que acabou? 👀")
    if top:
        lines.append("💎 Se liga em algumas:")
        for r in top:
            lines.append(f"• {r.modelo} {r.ano} | {_fmt_money(r.valor)} | FIPE {_fmt_money(r.fipe)} | Margem {_fmt_money(r.margem)}")
    lines.append("🔥 Daqui a pouco tem mais!!!")
    return "\n".join(lines)


def build_morning_yesterday_message(rows_yesterday: List[SentRow], day_yesterday: str) -> str:
    total = len(rows_yesterday)
    top = top_by_margin(rows_yesterday, 1)
    lines = []
    lines.append("🌅 08:00")
    lines.append(f"📌 Ontem ({day_yesterday}) enviamos *{total}* oportunidades. Será que hoje supera? Bora pra cima!!! 💪🚗")
    if top:
        r = top[0]
        lines.append("🥇 A campeã de ontem:")
        lines.append(f"👉 {r.modelo} {r.ano} | {_fmt_money(r.valor)} | FIPE {_fmt_money(r.fipe)} | Margem {_fmt_money(r.margem)}")
    return "\n".join(lines)


def maybe_send_digests(send_text: Callable[[str], None], now: Optional[datetime] = None) -> None:
    """
    Regras:
    - Se agora >= 12:00 e digest_12 ainda não foi enviado hoje → envia
    - Se agora >= 19:00 e digest_19 ainda não foi enviado hoje → envia
    - Se agora >= 08:00 e digest_yesterday ainda não foi enviado hoje → envia resumo de ontem

    Estado fica em out/telegram_daily/state.json
    """
    now = now or datetime.now()
    day = _today_str(now)
    yday = _yesterday_str(now)

    st_path = state_path()
    state = _load_json(st_path, default={})
    state.setdefault("last_day", day)
    state.setdefault("sent", {})  # day -> {midday: bool, evening: bool, morning_yday: bool}

    sent_today = state["sent"].setdefault(day, {"midday": False, "evening": False, "morning_yday": False})

    # Morning yesterday (08:00)
    if now.hour >= 8 and not sent_today.get("morning_yday", False):
        rows_y = read_day(yday)
        if rows_y:
            send_text(build_morning_yesterday_message(rows_y, yday))
        sent_today["morning_yday"] = True

    # Midday (12:00)
    if now.hour >= 12 and not sent_today.get("midday", False):
        rows = read_day(day)
        if rows:
            send_text(build_midday_message(rows))
        sent_today["midday"] = True

    # Evening (19:00)
    if now.hour >= 19 and not sent_today.get("evening", False):
        rows = read_day(day)
        if rows:
            send_text(build_evening_message(rows))
        sent_today["evening"] = True

    _save_json(st_path, state)
