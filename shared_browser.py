import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

_browser_context = None
_playwright_instance = None
_context_lock = asyncio.Lock()
_global_page = None

PROFILE_DIR = Path("profiles/facebook").resolve()

async def get_shared_page():
    global _browser_context, _playwright_instance, _global_page

    await _ensure_context()

    async with _context_lock:
        pages = _browser_context.pages

        if not pages:
            raise RuntimeError("Persistent context sem páginas abertas.")

        if _global_page and not _global_page.is_closed():
            return _global_page

        _global_page = pages[0]
        return _global_page


# Wrapper para compatibilidade
async def get_browser_context():
    return _browser_context


async def get_page(page_name="default"):
    return await get_shared_page()

# Define separate pages for collector and scanner
collector_page = None
scanner_page = None

# Function to get collector page
async def get_collector_page():
    global collector_page

    await _ensure_context()

    async with _context_lock:
        if collector_page is None or collector_page.is_closed():
            collector_page = await _browser_context.new_page()
        return collector_page

# Function to get scanner page
async def get_scanner_page():
    global scanner_page

    await _ensure_context()

    async with _context_lock:
        if scanner_page is None or scanner_page.is_closed():
            scanner_page = await _browser_context.new_page()
        return scanner_page

# Ensure context — tudo dentro do lock para evitar race conditions
async def _ensure_context():
    global _browser_context, _playwright_instance, _global_page, collector_page, scanner_page

    async with _context_lock:
        # Verifica se contexto existente ainda está vivo
        if _browser_context is not None:
            try:
                pages = _browser_context.pages
                if pages:
                    # Testa se o processo do browser ainda responde
                    await asyncio.wait_for(pages[0].evaluate("1"), timeout=5)
                    return _browser_context
            except Exception:
                pass
            # Contexto morto — cleanup completo antes de relançar
            print("[SHARED_BROWSER] Contexto morto detectado — reinicializando...")
            _browser_context = None
            _global_page = None
            collector_page = None
            scanner_page = None
            if _playwright_instance is not None:
                try:
                    await _playwright_instance.stop()
                except Exception:
                    pass
                _playwright_instance = None
            await asyncio.sleep(2)  # Aguarda Chrome liberar o perfil

        # Lança nova instância
        _playwright_instance = await async_playwright().start()

        _browser_context = await _playwright_instance.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        print(f"[SHARED_BROWSER] Contexto persistente (visível) iniciado em: {PROFILE_DIR}")

        return _browser_context



