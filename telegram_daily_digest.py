#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Resumo diário de oportunidades enviado ao Telegram.
Expede o compilado às 12:00 e às 18:00, por canal (mc e bh).
"""

import asyncio
from datetime import datetime, date
from typing import List, Dict, Any, Optional

import telebot

from send_telegram import load_telegram_config
from telegram_cache import _connect
import autoradar_config as config


# Horários de envio (hora UTC-3 local)
DIGEST_HOURS = {12, 18}


def _fetch_opportunities_since(since_dt: datetime, region: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retorna oportunidades salvas/enviadas após since_dt, opcionalmente filtradas por região."""
    conn = _connect()
    try:
        cur = conn.cursor()
        query = """
            SELECT id, title, source, url, price_display, margin_value, region, city
            FROM opportunities
            WHERE created_at >= ?
              AND telegram_sent IN (1, 3)
        """
        params: list = [since_dt.strftime("%Y-%m-%d %H:%M:%S")]
        if region:
            query += " AND region = ?"
            params.append(region)
        query += " ORDER BY margin_value DESC"
        cur.execute(query, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _format_source(source: str) -> str:
    return "OLX" if source == "olx" else "FB"


def _format_margin(margin_value) -> str:
    try:
        v = int(float(margin_value))
        return f"R$ {v:,.0f}".replace(",", ".")
    except Exception:
        return str(margin_value)


def _build_digest_message(opps: List[Dict[str, Any]], region: str, since_dt: datetime, now: datetime) -> str:
    """Monta a mensagem HTML do digest para um canal."""
    period_label = f"{since_dt.strftime('%H:%M')}–{now.strftime('%H:%M')}"
    date_label = now.strftime("%d/%m/%Y")
    region_label = "Montes Claros" if region == "mc" else "Belo Horizonte"

    header = (
        f"📋 <b>Resumo AutoRadar — {region_label}</b>\n"
        f"🗓 {date_label}  |  ⏱ {period_label}\n"
    )

    if not opps:
        return header + "\n⚠️ Nenhuma oportunidade encontrada neste período."

    lines: List[str] = []
    for opp in opps:
        title = opp.get("title") or "Veículo"
        source = _format_source(opp.get("source") or "")
        margin = _format_margin(opp.get("margin_value") or 0)
        price = opp.get("price_display") or ""
        url = opp.get("url") or ""

        if url:
            item = f'• <a href="{url}">{title}</a> [{source}] — margem {margin} ✅'
        else:
            item = f'• {title} [{source}] — margem {margin} ✅'

        if price:
            item += f'  <i>({price})</i>'

        lines.append(item)

    total = len(opps)
    best = opps[0]  # já ordenado por maior margem
    best_margin = _format_margin(best.get("margin_value") or 0)
    best_title = best.get("title") or ""
    best_url = best.get("url") or ""

    footer = (
        f"\n🏆 Melhor: <a href=\"{best_url}\">{best_title}</a> — {best_margin}"
        if best_url else
        f"\n🏆 Melhor: {best_title} — {best_margin}"
    )

    body = "\n".join(lines)
    count_line = f"\n\n<b>{total} oportunidade{'s' if total != 1 else ''} encontrada{'s' if total != 1 else ''}</b>"

    return header + "\n" + body + count_line + footer


def send_digest_for_region(region: str, since_dt: datetime, now: datetime) -> bool:
    """Envia o digest de uma região. Retorna True se enviou."""
    try:
        cfg = load_telegram_config()
        bot = telebot.TeleBot(cfg["TOKEN"])
        channels = cfg.get("TELEGRAM_CHANNELS", {})
        chat_id = channels.get(region, cfg.get("DEFAULT_CHAT_ID", ""))
        if not chat_id:
            print(f"[DIGEST] Sem chat_id para região '{region}'")
            return False

        opps = _fetch_opportunities_since(since_dt, region=region)
        msg = _build_digest_message(opps, region, since_dt, now)

        bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        print(f"[DIGEST] Enviado para '{region}' ({len(opps)} oportunidades) → chat {chat_id}")
        return True

    except Exception as e:
        print(f"[DIGEST] Erro ao enviar para '{region}': {e}")
        return False


def send_daily_digest(since_dt: Optional[datetime] = None) -> None:
    """
    Envia o digest apenas para regiões ativas (REGION_MC_ENABLED / REGION_BH_ENABLED).
    since_dt: janela de início (padrão: 6h atrás).
    """
    now = datetime.now()
    if since_dt is None:
        from datetime import timedelta
        since_dt = now.replace(minute=0, second=0, microsecond=0)
        since_dt = since_dt.replace(hour=max(0, since_dt.hour - 6))

    region_flags = {
        "mc": config.REGION_MC_ENABLED,
        "bh": config.REGION_BH_ENABLED,
    }

    for region, enabled in region_flags.items():
        if not enabled:
            print(f"[DIGEST] Região '{region}' desativada — digest ignorado")
            continue
        send_digest_for_region(region, since_dt, now)


# ================================================================
# Loop assíncrono — integrado ao autoradar_workers
# ================================================================

async def digest_scheduler_loop(stop_event=None) -> None:
    """
    Aguarda os horários de envio (12:00 e 18:00) e dispara o digest.
    Mantém rastreio do último horário disparado para não duplicar no mesmo dia.
    """
    print("[DIGEST] Scheduler iniciado — disparando às 12:00 e 18:00")
    last_fired: Dict[int, date] = {}   # hora → data do último disparo

    while stop_event is None or not stop_event.is_set():
        now = datetime.now()
        hour = now.hour
        today = now.date()

        if hour in DIGEST_HOURS:
            # Só dispara uma vez por horário por dia
            if last_fired.get(hour) != today:
                last_fired[hour] = today

                # Janela = desde o último horário de disparo
                prev_hours = sorted(h for h in DIGEST_HOURS if h < hour)
                if prev_hours:
                    since_hour = prev_hours[-1]
                else:
                    since_hour = 0   # desde meia-noite

                since_dt = now.replace(hour=since_hour, minute=0, second=0, microsecond=0)
                print(f"[DIGEST] Disparando compilado das {hour:02d}:00 (desde {since_dt.strftime('%H:%M')})")

                try:
                    send_daily_digest(since_dt=since_dt)
                except Exception as e:
                    print(f"[DIGEST] Erro no disparo: {e}")

        await asyncio.sleep(60)
