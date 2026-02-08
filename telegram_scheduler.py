#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scheduler para parciais (12h/19h) e recap (08h do dia seguinte).
Pode rodar dentro do app (tick() a cada 30–60s) ou via Task Scheduler (noon/evening/recap).
"""

from datetime import datetime
from typing import Optional

from telegram_log import get_flag, set_flag
from telegram_reports import build_partial_message, build_recap_message, yesterday_str


def send_html_message(text: str) -> bool:
    """Envia mensagem HTML ao chat configurado (reutiliza config do send_telegram)."""
    from send_telegram import load_config
    cfg = load_config()
    if not cfg:
        print("⚠️ Telegram: sem config (telegram_config.json)")
        return False

    try:
        import requests
    except ImportError:
        print("⚠️ Telegram: requests não instalado. Instale com: pip install requests")
        return False

    token = cfg["bot_token"]
    chat_id = cfg["chat_id"]
    base_url = f"https://api.telegram.org/bot{token}"

    try:
        data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        r = requests.post(f"{base_url}/sendMessage", data=data, timeout=30)
        if not r.ok:
            print(f"⚠️ Telegram: falha ao enviar mensagem - {r.status_code} {r.text[:150]}")
            return False
        return True
    except Exception as e:
        print(f"⚠️ Telegram: erro ao enviar mensagem: {e}")
        return False


def tick(now: Optional[datetime] = None) -> None:
    """
    Chame a cada 30–60s no app. Garante 1 envio por janela (12h, 19h, 8h) por dia.
    """
    now = now or datetime.now()
    day = now.strftime("%Y-%m-%d")
    hour = now.hour
    minute = now.minute

    noon_sent, evening_sent, recap_sent = get_flag(day)

    # 12:00 — parcial
    if hour == 12 and 0 <= minute <= 10 and noon_sent == 0:
        msg = build_partial_message(day, when_label="12:00", top_n=10)
        if send_html_message(msg):
            set_flag(day, noon=1)
            print("✅ Parcial 12:00 enviada 😄")

    # 19:00 — parcial
    if hour == 19 and 0 <= minute <= 10 and evening_sent == 0:
        msg = build_partial_message(day, when_label="19:00", top_n=10)
        if send_html_message(msg):
            set_flag(day, evening=1)
            print("✅ Parcial 19:00 enviada 😄")

    # 08:00 — recap de ontem (flag do dia atual)
    if hour == 8 and 0 <= minute <= 20 and recap_sent == 0:
        yday = yesterday_str()
        msg = build_recap_message(yday)
        if send_html_message(msg):
            set_flag(day, recap=1)
            print("✅ Recap 08:00 enviada 🚀")


if __name__ == "__main__":
    import sys
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()

    if cmd == "noon":
        d = datetime.now().strftime("%Y-%m-%d")
        send_html_message(build_partial_message(d, "12:00", top_n=10))
    elif cmd == "evening":
        d = datetime.now().strftime("%Y-%m-%d")
        send_html_message(build_partial_message(d, "19:00", top_n=10))
    elif cmd == "recap":
        y = yesterday_str()
        send_html_message(build_recap_message(y))
    else:
        tick()
