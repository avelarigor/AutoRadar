import json
import asyncio
import traceback
import time
from typing import Optional, Dict
import autoradar_config as config
from app_state import set_state, heartbeat, append_event
from link_queue import enqueue_links, claim_next_batch, mark_done, unstuck_claims
import shared_browser
from collect_links_mobile import collect_links
from send_telegram import send_pending_photos_once
from telegram_dispatcher import telegram_dispatcher_loop
from filters import get_all_blocked_words
from collect_links_olx import collect_links_olx
from scanner_engine import scan_listings, save_opportunity
from shared_browser import get_shared_page
from autoradar_config import MARGIN_MIN_REAIS

# ===============================
# FILTRO DE MOTOS E CAMINHÕES
# ===============================
EXCLUSION_KEYWORDS = get_all_blocked_words()

def is_excluded_vehicle(title: str) -> bool:
    title_lower = title.lower()
    for word in EXCLUSION_KEYWORDS:
        if word in title_lower:
            print(f"[FILTER] Ignorado por palavra: {word} | {title}")
            return True
    return False


# ===============================
# ROTATIVIDADE FACEBOOK
# ===============================

FACEBOOK_ROTATION_URLS = [

    # Montes Claros — /vehicles inclui carros, motos, caminhões
    # Motos são filtradas em collect_links_mobile.py via MOTO_KEYWORDS + filters.py
    "https://www.facebook.com/marketplace/montesclaros/vehicles?minPrice=12000&sortBy=creation_time_descend",
    "https://www.facebook.com/marketplace/montesclaros/vehicles?minPrice=12000&sortBy=price_ascend",
    "https://www.facebook.com/marketplace/montesclaros/vehicles?minPrice=12000&sortBy=price_descend",

    # Belo Horizonte — DESABILITADO até segunda ordem
    # "https://www.facebook.com/marketplace/belohorizonte/vehicles?minPrice=12000&sortBy=creation_time_descend",
    # "https://www.facebook.com/marketplace/belohorizonte/vehicles?minPrice=12000&sortBy=price_ascend",
    # "https://www.facebook.com/marketplace/belohorizonte/vehicles?minPrice=12000&sortBy=price_descend",
]

rotation_index = 0


# ===============================
# COLETA DE LINKS
# ===============================
async def collector_loop(stop_event=None):
    print("[COLLECTOR] Loop iniciado")

    global rotation_index

    # Primeira coleta ocorre imediatamente ao iniciar — sem delay artificial.
    last_olx_run = 0
    last_fb_run  = 0

    while not stop_event.is_set():
        try:

            current_time = time.time()

            # =================================
            # OLX — intervalo controlado pelo config
            # =================================
            if current_time - last_olx_run >= config.OLX_INTERVAL_SECONDS:
                last_olx_run = current_time
                try:
                    print("[OLX] Iniciando coleta OLX...")
                    olx_links = await collect_links_olx(max_pages=config.OLX_MAX_PAGES)
                    if olx_links:
                        enqueue_links("olx", olx_links)
                        print(f"[OLX] {len(olx_links)} links enfileirados")
                    else:
                        print("[OLX] Nenhum link coletado neste ciclo")
                except Exception as e:
                    print(f"[COLLECTOR] Erro OLX: {e}")
                    traceback.print_exc()

            # =================================
            # FACEBOOK — a cada 20 minutos
            # =================================
            if current_time - last_fb_run >= 1200:
                last_fb_run = current_time

                city = config.CITY
                state = config.STATE
                price_min = config.PRICE_MIN
                price_max = config.PRICE_MAX

                # =================================
                # ROTACIONAR URL
                # =================================

                search_url = FACEBOOK_ROTATION_URLS[rotation_index]

                print(f"[COLLECT ROTATION] índice={rotation_index}")
                print(f"[COLLECT ROTATION] URL={search_url}")

                rotation_index += 1

                if rotation_index >= len(FACEBOOK_ROTATION_URLS):
                    rotation_index = 0

                # =================================
                # COLETAR LINKS
                # =================================

                links, _ = await collect_links(
                    city=city,
                    state=state,
                    price_min=price_min,
                    price_max=price_max,
                    search_url=search_url,
                    marketplace_region_id=config.FACEBOOK_REGION_ID
                )

                print(f"[COLLECT] Links coletados: {len(links)}")

                # Detectar região pelo slug da URL de busca usada neste ciclo
                _su_lower = search_url.lower()
                _fb_region = "bh" if ("belohorizonte" in _su_lower or "belo-horizonte" in _su_lower) else "mc"
                enqueue_links("facebook", links, region=_fb_region)

        except Exception as e:
            print(f"[COLLECTOR] Erro no loop: {e}")
            traceback.print_exc()

        # ── Contagem regressiva para próximas coletas ──────────────────────
        elapsed_olx = time.time() - last_olx_run
        elapsed_fb  = time.time() - last_fb_run
        wait_olx = max(0, int(config.OLX_INTERVAL_SECONDS - elapsed_olx))
        wait_fb  = max(0, int(1200 - elapsed_fb))
        print(
            f"[STANDBY] Próxima coleta → "
            f"Facebook em {wait_fb//60:02d}m{wait_fb%60:02d}s | "
            f"OLX em {wait_olx//60:02d}m{wait_olx%60:02d}s"
        )

        # ── Fecha browsers quando ambos os ciclos têm > 15 min de espera ─────
        # Margem generosa: evita fechar browser logo antes de uma coleta OLX
        if wait_fb > 900 and wait_olx > 900:
            try:
                await shared_browser.close_all_browsers()
            except Exception as _ce:
                print(f"[STANDBY] Aviso ao fechar browsers: {_ce}")
        # ──────────────────────────────────────────────────────────────────

        await asyncio.sleep(60)


# ===============================
# SCANNER LOOP
# ===============================
async def scanner_loop(stop_event):
    print(f"[DEBUG CONFIG] MARGIN_MIN_REAIS = {MARGIN_MIN_REAIS} | type={type(MARGIN_MIN_REAIS)}")
    print("[SCANNER] Loop iniciado")
    _unstuck_counter = 0

    while not stop_event.is_set():
        try:
            # Liberar itens CLAIMED presos a cada ~5 min (300 ciclos de 1s)
            _unstuck_counter += 1
            if _unstuck_counter >= 300:
                _unstuck_counter = 0
                n = unstuck_claims(max_age_minutes=20)
                if n:
                    print(f"[SCANNER] {n} item(s) CLAIMED liberados para retry")

            batch = claim_next_batch(limit=1)

            if not batch:
                await asyncio.sleep(1)
                continue

            print(f"[SCANNER] Processando {len(batch)} item(s)")

            links = [item["url"] for item in batch]

            # Mapeia url → region para enriquecer listing após o scan
            _url_region_map = {item["url"]: (item.get("region") or "") for item in batch}

            listings, errors = await scan_listings(links)

            print(f"[SCANNER] Listings retornados: {len(listings)} | Erros: {errors}")

            for listing in listings:
                try:
                    # Propaga region tag: url do listing pode diferir da enfileirada
                    # (normalizações), tenta match direto e fallback por conteúdo de URL
                    if not listing.get("region"):
                        url_key = listing.get("url", "")
                        listing["region"] = _url_region_map.get(url_key, "")
                        if not listing["region"]:
                            # fallback por slug na URL do item (funciona para OLX)
                            ul = url_key.lower()
                            if "belo-horizonte" in ul or "belohorizonte" in ul:
                                listing["region"] = "bh"
                            elif "montes-claros" in ul or "montesclaros" in ul or "regiao-de-montes-claros" in ul:
                                listing["region"] = "mc"

                    if not _is_valid_opportunity(listing):
                        continue

                    save_opportunity(listing)

                    print(f"[SCANNER] Oportunidade salva: {listing.get('title')}")

                except Exception as e:
                    print(f"[SCANNER] Erro ao salvar oportunidade: {e}")

            for item in batch:
                mark_done(item["id"])

        except Exception as e:
            print(f"[SCANNER] erro: {e}")

        await asyncio.sleep(2)


def _is_valid_opportunity(listing: dict):

    if not listing:
        return False

    title = listing.get("title")

    if not title:
        print("[VALIDATION] Sem título → descartado")
        return False

    from filters import is_valid_listing

    if not is_valid_listing(listing):
        print(f"[VALIDATION] Bloqueado por filtro: {title}")
        return False

    if listing.get("fipe_price") is None:
        print(f"[VALIDATION] Sem FIPE → {title}")
        return False

    margin = listing.get("margin_value")

    if margin is None:
        print(f"[VALIDATION] Sem margem → {title}")
        return False

    if margin <= 0:
        print(f"[VALIDATION] Margem negativa → {title}")
        return False

    effective_margin = config.get_margin_for_url(listing.get("url", ""), region=listing.get("region", ""))
    if margin < effective_margin:
        print(f"[VALIDATION] Abaixo da margem mínima ({effective_margin:.0f}) [{listing.get('region','?')}] → {title}")
        return False

    # Sanidade: FIPE não pode ser mais de 2.5x o preço anunciado — indica mismatch de modelo
    price = listing.get("price") or listing.get("fipe_price")
    fipe_price = listing.get("fipe_price")
    if price and fipe_price and fipe_price > price * 2.5:
        print(f"[VALIDATION] FIPE suspeita ({fipe_price} > 2.5x preço {price}) → descartado: {title}")
        return False

    return True


def get_unsent_opportunities(limit=5):
    return []


def mark_as_sent(opportunity_id):
    pass