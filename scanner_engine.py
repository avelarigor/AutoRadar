import asyncio
import random
import sqlite3
from typing import List, Dict

from playwright.async_api import async_playwright
from scanners.scan_facebook import scan_facebook_listing
from scanners.scan_olx import scan_olx_listing

from fipe.engine_v2 import FipeEngineV2
from shared_browser import get_shared_page, get_olx_cars_page
import autoradar_config

# IMPORT CORRETO
from filters import is_valid_listing

DB_PATH = "data/autoradar.db"

fipe_engine = FipeEngineV2()


def save_opportunity(listing: Dict):

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO opportunities (

            url,
            source,

            title,
            brand,
            model,
            year,

            price,
            price_display,
            currency,

            km,

            city,
            state,

            description,

            main_photo_url,
            main_photo_path,

            cambio,
            cor_externa,
            cor_interna,
            combustivel,

            published_at,

            fipe_price,
            fipe_model,
            margin_value,
            region

        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (

        listing.get("url"),
        listing.get("source"),

        listing.get("title"),
        listing.get("brand"),
        listing.get("model"),
        listing.get("year"),

        listing.get("price"),
        listing.get("price_display"),
        listing.get("currency"),

        listing.get("km"),

        listing.get("city"),
        listing.get("state"),

        listing.get("description"),

        listing.get("main_photo_url"),
        listing.get("main_photo_path"),

        listing.get("cambio"),
        listing.get("cor_externa"),
        listing.get("cor_interna"),
        listing.get("combustivel"),

        listing.get("published_at"),

        listing.get("fipe_price"),
        listing.get("fipe_model"),
        listing.get("margin_value"),
        listing.get("region", ""),
    ))

    conn.commit()
    conn.close()

    print(f"[SAVE] Oportunidade salva: {listing.get('title')}")


async def scan_listings(links: List[str]):

    fb_page = await get_shared_page()

    listings = []
    errors = 0

    try:
        for url in links:

            try:

                # --------------------------------------------------------
                # SELEÇÃO DO SCANNER (FACEBOOK / OLX)
                # --------------------------------------------------------

                if "olx.com.br" in url:
                    # Reutiliza página OLX persistente — evita subir novo Chromium por link
                    olx_page = await get_olx_cars_page()
                    listing = await scan_olx_listing(olx_page, url)
                    # Delay inter-scan: imita usuário navegando entre anúncios
                    await asyncio.sleep(random.uniform(6.0, 12.0))
                else:
                    listing = await scan_facebook_listing(fb_page, url)

                # --------------------------------------------------------

                if not listing:
                    continue

                # --------------------------------------------------------
                # APLICA FILTRO EM TITLE + DESCRIPTION
                # --------------------------------------------------------

                title = listing.get("title", "")
                description = listing.get("description", "")

                merged_text = f"{title} {description}"

                filter_listing = {
                    "title": merged_text
                }

                if not is_valid_listing(filter_listing):
                    print(f"[FILTER BLOCK] Anúncio bloqueado: {title}")
                    continue

                # --------------------------------------------------------

                title = listing.get("title")
                year = listing.get("year")
                price = listing.get("price")
                brand = listing.get("brand")
                km = listing.get("km")

                if not title or not year or not price or not brand:
                    print(
                        f"[SCAN DROP] dados insuficientes | "
                        f"title={title} brand={brand} year={year} price={price}"
                    )
                    continue

                print(
                    f"[SCAN DEBUG] {title} | brand={brand} | "
                    f"year={year} | km={km} | price={price}"
                )

                from datetime import datetime

                current_year = datetime.now().year

                if year < 1980 or year > current_year:
                    continue

                loop = asyncio.get_event_loop()
                try:
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, fipe_engine.get_price, brand, title, year),
                        timeout=60,  # máx 60s por consulta FIPE (inclui chamadas à API)
                    )
                except asyncio.TimeoutError:
                    print(f"[FIPE TIMEOUT] Consulta FIPE excedeu 60s para: {title} — ignorado")
                    result = None

                if not result:
                    continue

                fipe_price = result.get("fipe_price")
                fipe_model = result.get("fipe_model")

                if not fipe_price:
                    continue

                margin = fipe_price - price

                margin_threshold = autoradar_config.get_margin_for_url(
                    url, listing.get("region", "")
                )
                if margin < margin_threshold:
                    continue

                if price > fipe_price:
                    continue

                listing["fipe_price"] = fipe_price
                listing["margin_value"] = margin
                listing["fipe_model"] = fipe_model

                print(
                    f"[MARGIN_DEBUG] {title} | "
                    f"Preço={price} | FIPE={fipe_price} | "
                    f"Margem={margin} | modelo_fipe={fipe_model}"
                )

                listings.append(listing)

            except Exception as e:

                print(f"[SCANNER] Erro interno: {e}")
                errors += 1

    finally:
        pass  # Páginas OLX e Facebook são reutilizadas — não fechar aqui

    return listings, errors