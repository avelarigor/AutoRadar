#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Envio de oportunidades do ranking para o Telegram.
Uma mensagem por anúncio, com foto principal e texto.
Token e chat_id vêm de telegram_config.json (edite esse arquivo para alterar).
Created by Igor Avelar - avelar.igor@gmail.com

✅ Versão corrigida + dedupe por "assinatura do veículo" mantendo o MENOR preço
   (desempate por maior margem). Também mantém dedupe por URL.
"""

import html
import json
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "telegram_config.json"
SENT_TRACKING_FILE = BASE_DIR / "sent_to_telegram.json"
LAST_EXECUTION_FILE = BASE_DIR / "last_telegram_execution.json"
PREFS_FILE = BASE_DIR / "user_preferences.json"


def _telegram_daily_log_enabled() -> bool:
    """Lê user_preferences: telegram_daily_reports.enabled (default False)."""
    if not PREFS_FILE.exists():
        return False
    try:
        with open(PREFS_FILE, "r", encoding="utf-8") as f:
            prefs = json.load(f)
        return bool(prefs.get("telegram_daily_reports") or {}).get("enabled", False)
    except Exception:
        return False


def load_config() -> Optional[Dict[str, str]]:
    """Carrega token e chat_id de telegram_config.json."""
    if not CONFIG_FILE.exists():
        return None
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        token = (data.get("bot_token") or "").strip()
        chat_id = (data.get("chat_id") or "").strip()
        if token and chat_id:
            return {"bot_token": token, "chat_id": chat_id}
    except Exception:
        pass
    return None


# Formato curto: só marketplace/item/ID (sem query de rastreamento)
_MARKETPLACE_ITEM_RE = re.compile(
    r"(https?://[^/]*facebook\.com/marketplace/item/(\d+))(?:\?|/)?", re.I
)


def _shorten_marketplace_url(url: str) -> str:
    """Reduz link do Marketplace ao formato curto: https://www.facebook.com/marketplace/item/ID/"""
    if not url or not url.strip():
        return url or ""
    url = url.strip()
    m = _MARKETPLACE_ITEM_RE.search(url)
    if m:
        return f"https://www.facebook.com/marketplace/item/{m.group(2)}/"
    return url


# Valores que NÃO são cor (evitar "Cor interna: Patrocinado" etc.)
_INVALID_COLOR_VALUES = frozenset(
    {
        "patrocinado",
        "sponsored",
        "anúncio",
        "anuncio",
        "ad",
        "ads",
        "promoção",
        "promocao",
        "destaque",
        "oferta",
        "ver mais",
        "saiba mais",
    }
)


def _build_caption(item: Dict[str, Any]) -> str:
    """Monta o texto da mensagem (caption) para cada anúncio."""
    modelo = item.get("modelo") or item.get("title_original") or "Sem título"
    # Nunca enviar JSON no caption (Webmotors/Mobiauto às vezes trazem pageProps no título)
    if isinstance(modelo, str) and ("{" in modelo or '"pageProps"' in modelo or '"props"' in modelo):
        modelo = "Anúncio"
    modelo = (modelo or "Anúncio")[:200]

    preco = item.get("price_display") or (
        f"R$ {item.get('preco', 0):,.0f}" if item.get("preco") else "N/A"
    )
    ano = item.get("ano") or "-"
    km = f"{item.get('km'):,}" if item.get("km") else "-"
    fipe = f"R$ {item.get('fipe', 0):,.0f}" if item.get("fipe") else "-"
    if item.get("fipe_ia_used") and item.get("fipe"):
        fipe = f"R$ {item['fipe']:,.0f} (est. IA)"
    margem = item.get("margem")
    margem_reais = item.get("margem_reais")
    cidade = item.get("cidade") or "-"
    url = _shorten_marketplace_url(item.get("url") or "")

    # Só mostra risco de golpe quando houver risco (Alto ou Médio); não exibe linha se Baixo ou não avaliado
    risco = (item.get("risco_golpe") or "").strip()
    risco_line = f"⚠️ Risco golpe: {html.escape(risco)}" if risco and risco in ("Alto", "Médio") else None

    # Detalhes do veículo
    cambio = (item.get("cambio") or "").strip()
    cor_ext = (item.get("cor_externa") or "").strip()
    cor_int = (item.get("cor_interna") or "").strip()
    if cor_ext and cor_ext.lower() in _INVALID_COLOR_VALUES:
        cor_ext = ""
    if cor_int and cor_int.lower() in _INVALID_COLOR_VALUES:
        cor_int = ""
    combust = (item.get("combustivel") or "").strip()
    tipo_veiculo = (item.get("tipo_veiculo") or "").strip()
    potencia_motor = (item.get("potencia_motor") or "").strip()
    categoria = (item.get("categoria") or "").strip()

    # Margem suspeita (>25%)
    margem_suspeita_line = None
    if margem is not None and margem > 25.0:
        margem_suspeita_line = "<b>⚠️ Margem suspeita. Atenção</b>"

    url_line = ("🤖 " + url) if item.get("ia_checked") else url

    # Formatação com negrito usando HTML do Telegram
    modelo_bold = f"<b>{html.escape(modelo[:200])}</b>"
    preco_bold = f"<b>{html.escape(preco)}</b>"
    fipe_label_bold = "<b>FIPE Aprox:</b>"
    margem_label_bold = "<b>Margem:</b>"

    detail_parts_formatted = []
    if categoria:
        detail_parts_formatted.append(f"<b>Categoria:</b> {html.escape(categoria)}")
    if tipo_veiculo:
        detail_parts_formatted.append(f"<b>Tipo:</b> {html.escape(tipo_veiculo)}")
    if cambio:
        detail_parts_formatted.append(f"<b>Câmbio:</b> {html.escape(cambio)}")
    if combust:
        detail_parts_formatted.append(f"<b>Combustível:</b> {html.escape(combust)}")
    if potencia_motor:
        detail_parts_formatted.append(f"<b>Potência:</b> {html.escape(potencia_motor)}")
    if cor_ext:
        detail_parts_formatted.append(f"<b>Cor:</b> {html.escape(cor_ext)}")
    if cor_int:
        detail_parts_formatted.append(f"<b>Cor interna:</b> {html.escape(cor_int)}")

    detalhes_extra = item.get("detalhes") or {}
    skip_keys = {
        "Categoria",
        "Tipo de veículo",
        "Câmbio",
        "Combustível",
        "Potência do motor",
        "Cor",
        "Modelo",
        "Marca",
        "Ano",
        "Quilometragem",
    }
    if isinstance(detalhes_extra, dict):
        for k, v in detalhes_extra.items():
            if k in skip_keys or not v or not str(v).strip():
                continue
            detail_parts_formatted.append(
                f"<b>{html.escape(str(k))}:</b> {html.escape(str(v).strip()[:50])}"
            )

    details_line = "\n".join(detail_parts_formatted) if detail_parts_formatted else None

    margem_line = None
    if margem is not None and margem_reais is not None:
        margem_line = f"✅ {margem_label_bold} R$ {margem_reais:,.0f} ({margem:.1f}%)"

    lines = [
        modelo_bold,
        "",
        f"💰 {preco_bold}  |  📅 {html.escape(str(ano))}  |  🚗 {html.escape(str(km))} km",
        f"📊 {fipe_label_bold} {html.escape(fipe)}",
        margem_line,
        margem_suspeita_line,
        risco_line,
        details_line,
        f"📍 {html.escape(cidade)}",
        "",
        url_line,
    ]
    return "\n".join(l for l in lines if l is not None and str(l).strip() != "").strip()


def send_opportunities(ranking: List[Dict[str, Any]]) -> int:
    """
    Envia uma mensagem no Telegram para cada item do ranking (foto + caption).
    Deduplica por URL e por "assinatura do veículo" (pra evitar mesmo carro em URLs diferentes).
    Mantém o MENOR preço por assinatura.
    Retorna o número de mensagens enviadas com sucesso.
    """
    config = load_config()
    if not config:
        return 0

    try:
        import requests
    except ImportError:
        print("⚠️ Telegram: requests não instalado. Instale com: pip install requests")
        return 0

    token = config["bot_token"]
    chat_id = config["chat_id"]
    base_url = f"https://api.telegram.org/bot{token}"

    sent = 0
    seen_urls = set()

    # ✅ Deduplicação por "mesmo veículo" (URLs diferentes) mantendo o menor preço
    def _vehicle_sig(it: Dict[str, Any]) -> str:
        marca = (it.get("marca_norm") or it.get("marca") or "").strip().lower()
        modelo = (
            it.get("modelo_fipe")
            or it.get("modelo_abrev")
            or it.get("modelo")
            or it.get("title")
            or ""
        ).strip().lower()
        ano = str(it.get("ano") or it.get("year") or "").strip()
        km = str(it.get("km") or "").strip()

        try:
            km_i = int("".join(ch for ch in km if ch.isdigit()) or "0")
            if km_i <= 0:
                km_bucket = "km?"
            elif km_i < 20000:
                km_bucket = "km<20k"
            elif km_i < 50000:
                km_bucket = "km<50k"
            elif km_i < 100000:
                km_bucket = "km<100k"
            elif km_i < 150000:
                km_bucket = "km<150k"
            else:
                km_bucket = "km150k+"
        except Exception:
            km_bucket = "km?"

        return f"{marca}|{modelo[:40]}|{ano}|{km_bucket}"

    def _price(it: Dict[str, Any]) -> int:
        try:
            return int(it.get("preco") or it.get("price") or 0)
        except Exception:
            return 0

    def _margem_reais(it: Dict[str, Any]) -> int:
        try:
            return int(it.get("margem_reais") or 0)
        except Exception:
            return 0

    # 1) melhor por assinatura
    best_by_sig: Dict[str, Dict[str, Any]] = {}
    for it in (ranking or []):
        sig = _vehicle_sig(it)
        cur = best_by_sig.get(sig)
        if cur is None:
            best_by_sig[sig] = it
            continue

        p_new, p_cur = _price(it), _price(cur)
        if p_new and p_cur:
            if p_new < p_cur:
                best_by_sig[sig] = it
            elif p_new == p_cur and _margem_reais(it) > _margem_reais(cur):
                best_by_sig[sig] = it
        elif p_new and not p_cur:
            best_by_sig[sig] = it
        else:
            if _margem_reais(it) > _margem_reais(cur):
                best_by_sig[sig] = it

    # 2) preserva ordem original do ranking (apenas as ocorrências "best")
    filtered_ranking: List[Dict[str, Any]] = []
    used = set()
    for it in (ranking or []):
        sig = _vehicle_sig(it)
        best = best_by_sig.get(sig)
        if not best:
            continue
        best_id = id(best)
        if best_id in used:
            continue
        if it is best:
            filtered_ranking.append(it)
            used.add(best_id)

    # Log por origem (debug)
    fb_items = [r for r in filtered_ranking if "facebook.com" in r.get("url", "")]
    wm_items = [r for r in filtered_ranking if "webmotors.com.br" in r.get("url", "")]
    ma_items = [r for r in filtered_ranking if "mobiauto.com.br" in r.get("url", "")]
    olx_items = [r for r in filtered_ranking if "olx.com.br" in r.get("url", "")]
    print(
        f"📱 Telegram: processando {len(filtered_ranking)} itens "
        f"(FB: {len(fb_items)}, WM: {len(wm_items)}, MA: {len(ma_items)}, OLX: {len(olx_items)})"
    )

    for item in filtered_ranking:
        url = (item.get("url") or "").strip()
        if not url:
            continue

        # Dedup por URL (ID do marketplace quando existir)
        m = _MARKETPLACE_ITEM_RE.search(url)
        url_key = m.group(2) if m else url
        if url_key in seen_urls:
            continue
        seen_urls.add(url_key)

        caption = _build_caption(item)
        if len(caption) > 1024:
            caption = caption[:1021] + "..."

        main_photo_path = (item.get("main_photo_path") or "").strip()
        main_photo_url = (item.get("main_photo_url") or "").strip()

        try:
            if main_photo_path and Path(main_photo_path).exists():
                with open(main_photo_path, "rb") as f:
                    files = {"photo": (Path(main_photo_path).name, f)}
                    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
                    r = requests.post(f"{base_url}/sendPhoto", data=data, files=files, timeout=30)
            elif main_photo_url and main_photo_url.startswith("http"):
                data = {"chat_id": chat_id, "photo": main_photo_url, "caption": caption, "parse_mode": "HTML"}
                r = requests.post(f"{base_url}/sendPhoto", data=data, timeout=30)
            else:
                data = {"chat_id": chat_id, "text": caption, "parse_mode": "HTML"}
                r = requests.post(f"{base_url}/sendMessage", data=data, timeout=30)

            if r.ok:
                sent += 1
                if _telegram_daily_log_enabled():
                    try:
                        from telegram_log import log_send
                        log_send(item, sent_ok=True)
                    except Exception:
                        pass
            else:
                print(f"⚠️ Telegram: falha ao enviar anúncio - {r.status_code} {r.text[:100]}")
            time.sleep(0.3)
        except Exception as e:
            print(f"⚠️ Telegram: erro ao enviar anúncio: {e}")

    # Sempre salvar informações da última execução (mesmo quando sent = 0)
    try:
        from datetime import datetime
        execution_info = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "time": datetime.now().strftime("%H:%M"),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "sent_count": sent,
        }
        with open(LAST_EXECUTION_FILE, "w", encoding="utf-8") as f:
            json.dump(execution_info, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Telegram: erro ao salvar última execução - {e}")

    if sent > 0:
        print(f"📱 Telegram: {sent} mensagens enviadas para o chat configurado.")

    return sent
