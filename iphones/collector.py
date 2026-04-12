"""
Coleta links de iPhones no Facebook Marketplace e OLX.
Usa o browser compartilhado (Facebook) e um browser efêmero (OLX),
igual ao padrão já adotado no módulo de carros.
"""

import asyncio
import random
import re
from playwright.async_api import async_playwright
from shared_browser import get_collector_page

# ─────────────────────────────────────────────────────────────
# URLs de coleta — Facebook Marketplace
# ─────────────────────────────────────────────────────────────
FACEBOOK_IPHONE_URLS = [
    "https://www.facebook.com/marketplace/103996099635518/search?minPrice=1000&query=iphone&exact=false",
    "https://www.facebook.com/marketplace/103996099635518/search?minPrice=1000&sortBy=creation_time_descend&query=iphone&exact=false",
    "https://www.facebook.com/marketplace/103996099635518/search?minPrice=1000&sortBy=price_descend&query=iphone&exact=false",
    "https://www.facebook.com/marketplace/103996099635518/search?minPrice=1000&sortBy=price_ascend&query=iphone&exact=false",
]

# URLs de coleta — OLX
OLX_IPHONE_URLS = [
    "https://www.olx.com.br/celulares/estado-mg/regiao-de-montes-claros-e-diamantina/montes-claros?ps=1000&q=iphone",
    "https://www.olx.com.br/celulares/estado-mg/regiao-de-montes-claros-e-diamantina/montes-claros?ps=1000&q=iphone&sf=1",
    "https://www.olx.com.br/celulares/estado-mg/regiao-de-montes-claros-e-diamantina/montes-claros?ps=1000&q=iphone&sp=5",
    "https://www.olx.com.br/celulares/estado-mg/regiao-de-montes-claros-e-diamantina/montes-claros?ps=1000&q=iphone&sp=1",
]

MARKETPLACE_ITEM_RE = re.compile(r"marketplace/item/(\d+)")
OLX_ITEM_RE = re.compile(r"olx\.com\.br/.+-(\d{7,})")

_fb_rotation_index = 0
_olx_rotation_index = 0


async def collect_facebook_iphone_links() -> list[str]:
    """Coleta links de iPhone no Facebook usando a página compartilhada do coletor."""
    global _fb_rotation_index

    url = FACEBOOK_IPHONE_URLS[_fb_rotation_index % len(FACEBOOK_IPHONE_URLS)]
    _fb_rotation_index += 1

    print(f"[IPHONE FB] Coletando: {url}")

    try:
        page = await get_collector_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        seen_ids: set[str] = set()
        links: list[str] = []

        for _ in range(6):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(random.uniform(2.0, 3.5))

            anchors = await page.query_selector_all("a[href*='/marketplace/item/']")
            for a in anchors:
                href = await a.get_attribute("href")
                if not href:
                    continue
                m = MARKETPLACE_ITEM_RE.search(href)
                if m and m.group(1) not in seen_ids:
                    seen_ids.add(m.group(1))
                    links.append(f"https://www.facebook.com/marketplace/item/{m.group(1)}/")

        print(f"[IPHONE FB] {len(links)} links coletados")
        return links

    except Exception as e:
        print(f"[IPHONE FB] Erro na coleta: {e}")
        return []


async def collect_olx_iphone_links() -> list[str]:
    """Coleta links de iPhone no OLX com browser efêmero."""
    global _olx_rotation_index

    url = OLX_IPHONE_URLS[_olx_rotation_index % len(OLX_IPHONE_URLS)]
    _olx_rotation_index += 1

    print(f"[IPHONE OLX] Coletando: {url}")

    links: list[str] = set()

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-gpu",
            "--disable-extensions",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--js-flags=--max-old-space-size=128",
        ],
    )
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = await context.new_page()

    try:
        for page_num in range(1, 4):
            sep = "&" if "?" in url else "?"
            paged_url = f"{url}{sep}o={page_num}"
            print(f"[IPHONE OLX] Página {page_num}: {paged_url}")

            await page.goto(paged_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(random.uniform(2.5, 4.0))

            anchors = await page.query_selector_all("a[href*='olx.com.br'], a[href*='/celulares/']")
            for a in anchors:
                href = await a.get_attribute("href")
                if not href:
                    continue
                # Normaliza URL relativa
                if href.startswith("/"):
                    href = "https://www.olx.com.br" + href
                if OLX_ITEM_RE.search(href) and "iphone" in href.lower():
                    links.add(href.split("?")[0])

        result = list(links)
        print(f"[IPHONE OLX] {len(result)} links coletados")
        return result

    except Exception as e:
        print(f"[IPHONE OLX] Erro na coleta: {e}")
        return []

    finally:
        await context.close()
        await browser.close()
        await playwright.stop()
