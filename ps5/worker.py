"""
Loops assíncronos do módulo PS5.
Chamados por run_app.py quando PS5_ENABLED = True.
"""

import asyncio
import time
import traceback

import sqlite3
import telebot
import json
from pathlib import Path

from link_queue import enqueue_links, claim_next_batch, mark_done, unstuck_claims
from ps5.collector import collect_facebook_ps5_links, collect_olx_ps5_links
from ps5.scanner import scan_ps5_link, save_ps5_opportunity
from ps5.formatter import format_ps5_message
from config_db import DB_PATH

_TG_CONFIG_PATH = Path(__file__).parent.parent / "telegram_config.json"

MODULE = "ps5"


def _load_tg():
    with open(_TG_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg["TOKEN"], cfg["GADGETS_CHAT_ID"]


# ─────────────────────────────────────────────────────────────
# Collector loop — coleta links a cada 5 min (Facebook) e 7 min (OLX)
# ─────────────────────────────────────────────────────────────

async def ps5_collector_loop(stop_event):
    print("[PS5 COLLECTOR] Loop iniciado")

    last_fb  = time.time() - 570   # 1ª coleta em ~30s
    last_olx = time.time() - 360   # 1ª coleta em ~60s

    while not stop_event.is_set():
        try:
            now = time.time()

            if now - last_fb >= 600:   # 10 min
                last_fb = now
                links = await collect_facebook_ps5_links()
                if links:
                    enqueue_links("facebook", links, module=MODULE)

            if now - last_olx >= 420:  # 7 min
                last_olx = now
                links = await collect_olx_ps5_links()
                if links:
                    enqueue_links("olx", links, module=MODULE)

        except Exception as e:
            print(f"[PS5 COLLECTOR] Erro: {e}")
            traceback.print_exc()

        await asyncio.sleep(15)


# ─────────────────────────────────────────────────────────────
# Scanner loop — processa fila de links ps5 um a um
# ─────────────────────────────────────────────────────────────

async def ps5_scanner_loop(stop_event):
    print("[PS5 SCANNER] Loop iniciado")
    _unstuck_counter = 0

    while not stop_event.is_set():
        try:
            # Liberar itens CLAIMED presos a cada ~5 min
            _unstuck_counter += 1
            if _unstuck_counter >= 150:
                _unstuck_counter = 0
                n = unstuck_claims(max_age_minutes=20)
                if n:
                    print(f"[PS5 SCANNER] {n} item(s) CLAIMED liberados para retry")

            batch = claim_next_batch(limit=1, module=MODULE)
            if not batch:
                await asyncio.sleep(2)
                continue

            item = batch[0]
            url  = item["url"]
            print(f"[PS5 SCANNER] Processando: {url}")

            opp = await scan_ps5_link(url)
            if opp:
                save_ps5_opportunity(opp)

            mark_done(item["id"])

        except Exception as e:
            print(f"[PS5 SCANNER] Erro: {e}")
            traceback.print_exc()

        await asyncio.sleep(1)


# ─────────────────────────────────────────────────────────────
# Dispatcher loop — envia oportunidades não enviadas ao Telegram
# ─────────────────────────────────────────────────────────────

async def ps5_dispatcher_loop(stop_event):
    print("[PS5 DISPATCHER] Loop iniciado")

    # Ao iniciar, libera itens presos em estado in_flight (3) de runs anteriores
    try:
        conn0 = sqlite3.connect(str(DB_PATH))
        n = conn0.execute(
            "UPDATE ps5_opportunities SET telegram_sent = 0 WHERE telegram_sent = 3"
        ).rowcount
        conn0.commit()
        conn0.close()
        if n:
            print(f"[PS5 DISPATCHER] {n} item(s) 'in_flight' resetados para 0 no startup")
    except Exception:
        pass

    while not stop_event.is_set():
        try:
            # Claim atômico: marca telegram_sent=3 (in_flight) antes de ler
            conn = sqlite3.connect(str(DB_PATH))
            conn.execute("""
                UPDATE ps5_opportunities SET telegram_sent = 3
                WHERE id IN (
                    SELECT id FROM ps5_opportunities
                    WHERE telegram_sent = 0
                    ORDER BY created_at DESC
                    LIMIT 5
                )
            """)
            conn.commit()

            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM ps5_opportunities
                WHERE telegram_sent = 3
                ORDER BY created_at DESC
                LIMIT 5
            """).fetchall()
            conn.close()

            if not rows:
                await asyncio.sleep(5)
                continue

            token, chat_id = _load_tg()
            bot = telebot.TeleBot(token)

            for row in rows:
                opp = dict(row)
                try:
                    msg = format_ps5_message(opp)
                    photo_url = opp.get("photo_url")

                    if photo_url and photo_url.startswith("http"):
                        bot.send_photo(chat_id=chat_id, photo=photo_url, caption=msg, parse_mode="HTML")
                    else:
                        bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")

                    conn2 = sqlite3.connect(str(DB_PATH))
                    conn2.execute("UPDATE ps5_opportunities SET telegram_sent = 1 WHERE id = ?", (opp["id"],))
                    conn2.commit()
                    conn2.close()

                    print(f"[PS5 DISPATCHER] Enviado: {opp.get('title')}")

                except Exception as e:
                    print(f"[PS5 DISPATCHER] Erro ao enviar: {e}")
                    conn3 = sqlite3.connect(str(DB_PATH))
                    cur_attempts = (conn3.execute(
                        "SELECT send_attempts FROM ps5_opportunities WHERE id = ?", (opp["id"],)
                    ).fetchone() or [0])[0] or 0
                    cur_attempts += 1
                    if cur_attempts >= 3:
                        conn3.execute(
                            "UPDATE ps5_opportunities SET telegram_sent = 2, send_attempts = ? WHERE id = ?",
                            (cur_attempts, opp["id"])
                        )
                        print(f"[PS5 DISPATCHER] Descartado após {cur_attempts} tentativas: {opp.get('title')}")
                    else:
                        conn3.execute(
                            "UPDATE ps5_opportunities SET telegram_sent = 0, send_attempts = ? WHERE id = ?",
                            (cur_attempts, opp["id"])
                        )
                    conn3.commit()
                    conn3.close()

        except Exception as e:
            print(f"[PS5 DISPATCHER] Erro no loop: {e}")
            traceback.print_exc()

        await asyncio.sleep(5)
