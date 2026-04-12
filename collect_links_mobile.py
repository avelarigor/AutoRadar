import re
import random
import asyncio
from typing import List, Tuple, Optional, Callable

from filters import is_blocked_title
from shared_browser import get_collector_page

MARKETPLACE_ITEM_RE = re.compile(r"marketplace/item/(\d+)")

# bloqueio adicional para motos direto no collect
MOTO_KEYWORDS = [
    "cg",
    "fan",
    "titan",
    "bros",
    "xre",
    "cb",
    "fazer",
    "lander",
    "tenere",
    "xtz",
    "factor",
    "intruder",
    "yes",
    "nx",
    "crf",
    "dt",
]

print(">>> ARQUIVO EXECUTADO:", __file__)


async def collect_links(
    city: str,
    state: str,
    price_min: int,
    price_max: int,
    max_links: int = 120,
    progress_callback: Optional[Callable] = None,
    is_aborted_callback: Optional[Callable] = None,
    wait_for_login_callback: Optional[Callable] = None,
    browser=None,
    marketplace_region_id: Optional[str] = None,
    search_url: str = "",
    status_message_callback: Optional[Callable] = None
) -> Tuple[List[str], Optional[str]]:

    print("[FACEBOOK] Coleta iniciada")

    if not search_url:
        return [], None

    page = await get_collector_page()

    await page.goto(search_url, wait_until="domcontentloaded")

    await asyncio.sleep(random.uniform(5.0, 9.0))

    seen_ids = set()

    scroll_round = 0
    MAX_SCROLLS = 7

    while scroll_round < MAX_SCROLLS:

        scroll_round += 1

        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            await asyncio.sleep(2)
            continue

        await asyncio.sleep(random.uniform(4.0, 7.0))

        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

        try:
            anchors = await page.query_selector_all("a[href*='/marketplace/item/']")
        except Exception:
            await asyncio.sleep(2)
            continue

        for a in anchors:

            try:
                href = await a.get_attribute("href")
            except Exception:
                continue

            if not href:
                continue

            match = MARKETPLACE_ITEM_RE.search(href)

            if not match:
                continue

            item_id = match.group(1)

            if item_id in seen_ids:
                continue

            try:
                card = await a.evaluate_handle("el => el.closest('div')")
                text = (await card.inner_text() or "").lower()
            except Exception:
                text = (await a.inner_text() or "").lower()

            # filtro motos direto no card
            if any(k in text for k in MOTO_KEYWORDS):
                print(f"[COLLECT FILTER] Ignorado: {text[:40]}")
                continue

            # filtro geral
            if is_blocked_title(text):
                print(f"[COLLECT FILTER] Ignorado: {text[:40]}")
                continue

            # só adiciona depois de passar nos filtros
            seen_ids.add(item_id)

        print(f"[SCROLL {scroll_round}] válidos: {len(seen_ids)}")

    links = [
        f"https://www.facebook.com/marketplace/item/{item_id}/"
        for item_id in seen_ids
    ]

    print(f"[FACEBOOK TOTAL] {len(links)} links válidos")

    return links[:max_links], None