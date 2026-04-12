#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path
from typing import Dict, Any
import telebot
from telegram_cache import get_pending, mark_sent, mark_failed, reset_inflight
from core.telegram_formatter import format_telegram_message

CONFIG_PATH = Path(__file__).parent / "telegram_config.json"
BATCH_SIZE = 5


def load_telegram_config() -> Dict[str, str]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    token = config.get("TOKEN")
    default_chat_id = config.get("DEFAULT_CHAT_ID")

    if not token or not default_chat_id:
        raise RuntimeError("TOKEN ou DEFAULT_CHAT_ID ausente no telegram_config.json")

    return {
        "TOKEN": token,
        "DEFAULT_CHAT_ID": default_chat_id,
        "TELEGRAM_CHANNELS": config.get("TELEGRAM_CHANNELS", {}),
    }


def safe_format_message(entry: Dict[str, Any]) -> str:
    try:
        return format_telegram_message(entry)
    except Exception as e:
        print(f"[TG FORMAT ERROR] {e}")
        return f"{entry.get('title', 'Veículo')}\nPreço: {entry.get('price_display','')}"


def send_pending_photos_once(max_items: int = 5) -> tuple:
    try:
        config = load_telegram_config()
        bot = telebot.TeleBot(config["TOKEN"])

        pending = get_pending(limit=max_items)
        if not pending:
            return (0, 0)

        sent = 0

        for entry in pending:
            try:
                message = safe_format_message(entry)
                photo_url = entry.get("main_photo_url")

                # Log de diagnóstico por envio
                print(
                    f"[TG DISPATCH] ID={entry.get('id')} | "
                    f"title='{entry.get('title')}' | "
                    f"source={entry.get('source')} | "
                    f"region={entry.get('region') or '—'} | "
                    f"city={entry.get('city') or '—'} | "
                    f"price={entry.get('price_display') or entry.get('price')} | "
                    f"fipe_model='{entry.get('fipe_model')}' | "
                    f"margin={entry.get('margin_value')} | "
                    f"url={entry.get('url')}"
                )

                # Roteamento por região
                channels = config.get("TELEGRAM_CHANNELS", {})
                default_chat = config.get("DEFAULT_CHAT_ID", "")
                region = (entry.get("region") or "").strip().lower()
                chat_id = channels.get(region, default_chat)

                if photo_url and isinstance(photo_url, str) and photo_url.startswith("http"):
                    print(f"[TG DEBUG] Enviando com foto: {photo_url} → canal {region or 'default'} ({chat_id})")
                    try:
                        bot.send_photo(
                            chat_id=chat_id,
                            photo=photo_url,
                            caption=message,
                            parse_mode="HTML"
                        )
                    except Exception as photo_err:
                        print(f"[TG] Foto falhou (ID={entry.get('id')}): {photo_err} — enviando sem foto")
                        bot.send_message(
                            chat_id=chat_id,
                            text=message,
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )

                else:
                    print(f"[TG DEBUG] Sem foto para ID={entry.get('id')} → canal {region or 'default'} ({chat_id})")

                    bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )

                mark_sent(entry["id"])
                sent += 1
                print(f"[TG] Enviado ID={entry['id']}")

            except Exception as e:
                print(f"[TG] Falha ID={entry.get('id')} Erro: {e}")
                mark_failed(entry["id"])

        return (sent, len(pending) - sent)

    except Exception as e:
        print(f"[TG] Erro crítico ao enviar mensagens: {e}")
        return (0, 0)