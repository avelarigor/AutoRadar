from playwright.async_api import Page
from typing import Dict
import json
import re


async def extract_olx_listing(page: Page) -> Dict:
    """
    Extrai dados de anúncio OLX via window.dataLayer (GTM) e schema.org JSON-LD.
    OLX não usa __NEXT_DATA__; os dados estruturados estão no dataLayer.
    """

    # -------------------------------------------------------
    # 1. window.dataLayer → adDetail (fonte principal)
    # -------------------------------------------------------
    ad_detail = {}
    price_ref = {}
    detail_ad_date = None
    try:
        raw = await page.evaluate("() => JSON.stringify(window.dataLayer || [])")
        datalayer = json.loads(raw) if raw else []
        for entry in datalayer:
            page_data = entry.get("page", {})
            if page_data.get("pageType") == "ad_detail":
                ad_detail = page_data.get("adDetail", {})
                detail_data = page_data.get("detail", {})
                price_ref = detail_data.get("abuyPriceRef", {})
                detail_ad_date = detail_data.get("adDate")  # unix timestamp correto
                break
    except Exception:
        pass

    # -------------------------------------------------------
    # 2. schema.org JSON-LD → description + images
    # -------------------------------------------------------
    jsonld_item = {}
    jsonld_offer = {}
    try:
        scripts = await page.evaluate("""
            () => Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
                       .map(s => s.textContent)
        """)
        for s in scripts:
            try:
                d = json.loads(s)
                if "makesOffer" in d:
                    jsonld_offer = d.get("makesOffer", {})
                    jsonld_item = jsonld_offer.get("itemOffered", {})
                    break
            except Exception:
                pass
    except Exception:
        pass

    if not ad_detail and not jsonld_item:
        # Página vazia ou expirada — retornar fallback
        title = ""
        try:
            title = re.sub(r"\s*\|\s*OLX\s*$", "", await page.title()).strip()
        except Exception:
            pass
        print("[EXTRACTOR_OLX] Página sem dados estruturados — listagem possivelmente expirada")
        return _empty_result(title)

    # -------------------------------------------------------
    # 3. Montar resultado a partir das fontes disponíveis
    # -------------------------------------------------------
    title = (
        ad_detail.get("subject")
        or jsonld_item.get("name", "")
        or ""
    )
    if not title:
        try:
            title = re.sub(r"\s*\|\s*OLX\s*$", "", await page.title()).strip()
        except Exception:
            pass

    price_raw = (
        ad_detail.get("price")
        or jsonld_offer.get("priceSpecification", {}).get("price", "")
        or ""
    )

    brand = ad_detail.get("brand") or jsonld_item.get("brand", "") or None
    model = ad_detail.get("model") or jsonld_item.get("model", "") or None
    year_raw = ad_detail.get("regdate") or jsonld_item.get("modelDate", "") or None
    km_raw = ad_detail.get("mileage") or jsonld_item.get("mileageFromOdometer", "") or None
    city = ad_detail.get("municipality", "")
    state = ad_detail.get("state", "")
    cambio = ad_detail.get("gearbox") or jsonld_item.get("vehicleTransmission", "") or None
    combustivel = ad_detail.get("fuel") or jsonld_item.get("fuelType", "") or None
    cor_externa = ad_detail.get("carcolor") or None

    description = ""
    raw_desc = jsonld_item.get("description", "")
    if raw_desc:
        description = re.sub(r"<br\s*/?>", "\n", raw_desc).strip()

    images = []
    for img in jsonld_item.get("image", []):
        url = img.get("contentUrl", "") if isinstance(img, dict) else str(img)
        if url:
            images.append(url)

    # Preferir o unix timestamp de page.detail (correto) sobre adDetail.adDate (incorreto)
    published_at_raw = str(detail_ad_date) if detail_ad_date else (ad_detail.get("adDate") or None)

    # Preço de referência de mercado OLX (abuyPriceRef.price_p50 = mediana)
    avg_price_olx_raw = str(price_ref.get("price_p50", "")) if price_ref else None

    return {
        "title": title,
        "price_raw": str(price_raw) if price_raw else None,
        "brand": brand,
        "model": model,
        "year_raw": str(year_raw) if year_raw else None,
        "km_raw": str(km_raw) if km_raw else None,
        "city": city or None,
        "state": state or None,
        "description": description,
        "images": images,
        "published_at_raw": str(published_at_raw) if published_at_raw else None,
        "fipe_olx_raw": None,
        "avg_price_olx_raw": avg_price_olx_raw,
        "cambio": cambio,
        "combustivel": combustivel,
        "cor_externa": cor_externa,
        "raw_details": ad_detail,
    }


def _empty_result(title: str = "") -> dict:
    return {
        "title": title,
        "price_raw": None,
        "brand": None,
        "model": None,
        "year_raw": None,
        "km_raw": None,
        "city": None,
        "state": None,
        "description": "",
        "images": [],
        "published_at_raw": None,
        "fipe_olx_raw": None,
        "avg_price_olx_raw": None,
        "cambio": None,
        "combustivel": None,
        "cor_externa": None,
        "raw_details": {},
    }

