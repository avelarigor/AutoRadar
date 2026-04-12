import asyncio
import random
from typing import Dict, Any
from extractor_olx import extract_olx_listing
from normalizer_olx import normalize_olx_listing
from fipe_updater_olx import update_fipe_from_olx


async def scan_olx_listing(page, url: str) -> Dict[str, Any]:

    """
    Realiza o scan de um anúncio da OLX.
    Inclui comportamento humano para evitar bloqueio Cloudflare/bot-detection.
    """

    print(f"[SCAN_OLX] Iniciando processamento: {url}")

    try:

        # Pausa pré-navegação: imita tempo de "decidir clicar" no link
        await asyncio.sleep(random.uniform(1.5, 3.5))

        await page.goto(url, wait_until="domcontentloaded", timeout=45000)

        # Verifica bloqueio Cloudflare/OLX antes de extrair
        page_title = await page.title()
        if any(kw in page_title.lower() for kw in ("attention required", "just a moment", "cloudflare", "acesso negado", "bloqueado")):
            print(f"[SCAN_OLX] Bloqueio detectado (título: {page_title!r}) — abortando")
            return None

        # Pausa pós-carregamento: permite que dataLayer (GTM) seja preenchido pelo JS
        await asyncio.sleep(random.uniform(2.0, 4.0))

        # Scroll gradual: simula leitura humana da página
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.35)")
            await asyncio.sleep(random.uniform(0.6, 1.2))
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.70)")
            await asyncio.sleep(random.uniform(0.5, 1.0))
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(random.uniform(0.5, 1.0))
        except Exception:
            pass

        # --------------------------------------------
        # EXTRAÇÃO
        # --------------------------------------------

        raw_data = await extract_olx_listing(page)

        # --------------------------------------------
        # NORMALIZAÇÃO
        # --------------------------------------------

        normalized_data = normalize_olx_listing(raw_data)

        # --------------------------------------------
        # ATUALIZA BASE FIPE
        # --------------------------------------------

        update_fipe_from_olx(normalized_data)

        # --------------------------------------------
        # CAMPOS PRINCIPAIS
        # --------------------------------------------

        title = normalized_data.get("title")
        price = normalized_data.get("price")
        brand = normalized_data.get("brand")
        model = normalized_data.get("model")
        year = normalized_data.get("year")
        km = normalized_data.get("km")

        city = normalized_data.get("city")
        state = normalized_data.get("state")

        description = normalized_data.get("description")

        images = normalized_data.get("images") or []

        main_photo_url = None
        if images:
            main_photo_url = images[0]

        published_at = normalized_data.get("published_at")

        cambio = normalized_data.get("cambio")
        combustivel = normalized_data.get("combustivel")

        cor_externa = normalized_data.get("cor_externa")
        cor_interna = normalized_data.get("cor_interna")

        # --------------------------------------------
        # CAMPOS OLX (AUXILIARES)
        # --------------------------------------------

        fipe_olx = normalized_data.get("fipe_olx")
        avg_price_olx = normalized_data.get("avg_price_olx")

        margin = None

        if fipe_olx and price:

            try:

                margin = round((price - fipe_olx) / fipe_olx, 2)

            except Exception:

                pass

        print("[SCAN_OLX] Extração finalizada")

        # --------------------------------------------
        # RETORNO COMPATÍVEL COM O PIPELINE
        # --------------------------------------------

        return {

            "url": url,
            "source": "olx",

            "title": title,
            "brand": brand,
            "model": model,
            "year": year,

            "price": price,
            "price_display": f"R$ {price:,.0f}".replace(",", ".") if isinstance(price, (int, float)) and price else price,
            "currency": "BRL",

            "km": km,

            "city": city,
            "state": state,

            "description": description,

            "main_photo_url": main_photo_url,
            "main_photo_path": None,

            "cambio": cambio,
            "cor_externa": cor_externa,
            "cor_interna": cor_interna,
            "combustivel": combustivel,

            "published_at": published_at,

            "fipe_price": fipe_olx,
            "fipe_model": model,
            "margin_value": margin,

            "details": normalized_data.get("details"),
            "features": normalized_data.get("features"),
            "images": images,
            "avg_price_olx": avg_price_olx

        }

    except Exception as e:

        print("[SCAN_OLX] Erro detectado")

        return {
            "error": str(e),
            "url": url
        }