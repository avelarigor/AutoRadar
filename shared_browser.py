import asyncio
import gc
import subprocess
import sys
import time
from playwright.async_api import async_playwright
from pathlib import Path

_browser_context = None
_playwright_instance = None
_context_lock = asyncio.Lock()
_global_page = None

PROFILE_DIR = Path("profiles/facebook").resolve()
OLX_PROFILE_DIR = Path("profiles/olx").resolve()

# ── Detecção do Chrome real instalado no sistema ──────────────────────────────
_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Users\{user}\AppData\Local\Google\Chrome\Application\chrome.exe",
]

def _find_chrome() -> str:
    import os
    candidates = list(_CHROME_CANDIDATES)
    # Expande variável de usuário
    user = os.environ.get("USERNAME", "")
    candidates.append(
        rf"C:\Users\{user}\AppData\Local\Google\Chrome\Application\chrome.exe"
    )
    for path in candidates:
        if Path(path).exists():
            return path
    raise FileNotFoundError(
        "Google Chrome não encontrado. Instale o Chrome ou ajuste _CHROME_CANDIDATES em shared_browser.py"
    )

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

# Página OLX reutilizável para scanner de carros — Chrome real via CDP
_olx_cars_pw = None
_olx_cars_browser = None   # BrowserContext retornado pelo CDP
_olx_cars_page = None
_olx_cars_proc = None      # subprocess do Chrome
_olx_cars_lock = asyncio.Lock()
OLX_CARS_CDP_PORT = 9222

# Página OLX reutilizável para scanner de iPhones — Chrome real via CDP
_olx_iphones_pw = None
_olx_iphones_browser = None
_olx_iphones_page = None
_olx_iphones_proc = None
_olx_iphones_lock = asyncio.Lock()
OLX_IPHONES_CDP_PORT = 9223

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


async def _get_or_create_olx_page(pw_ref, browser_ref, page_ref, proc_ref, lock, cdp_port: int):
    """
    Lança o Google Chrome real via subprocess com --remote-debugging-port e conecta
    o Playwright via CDP. Isso preserva o TLS fingerprint do Chrome real, contornando
    a detecção do Cloudflare que identifica o Chromium do Playwright pelo JA3/JA4.

    Cada worker OLX usa uma porta dedicada:
      - 9222 → carros
      - 9223 → iphones
    """
    async with lock:
        # ── Verifica se a página existente ainda responde ─────────────────────
        if page_ref[0] is not None and not page_ref[0].is_closed():
            try:
                await asyncio.wait_for(page_ref[0].evaluate("1"), timeout=3)
                return page_ref[0]
            except Exception:
                pass

        # ── Cleanup da sessão anterior ────────────────────────────────────────
        # Usa disconnect() (não close()) para não enviar Browser.close via CDP,
        # o que encerraria qualquer janela do Chrome — inclusive as do usuário.
        # O processo é encerrado exclusivamente via proc.terminate() pelo PID.
        if browser_ref[0] is not None:
            try:
                await browser_ref[0].disconnect()
            except Exception:
                pass
            browser_ref[0] = None
        if pw_ref[0] is not None:
            try:
                await pw_ref[0].stop()
            except Exception:
                pass
            pw_ref[0] = None
        if proc_ref[0] is not None:
            try:
                proc_ref[0].terminate()
                proc_ref[0].wait(timeout=5)
            except Exception:
                pass
            proc_ref[0] = None
        gc.collect()

        # ── Garante que o diretório do perfil exista ──────────────────────────
        OLX_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        chrome_exe = _find_chrome()

        # ── Lança Chrome real com debugging port ──────────────────────────────
        cmd = [
            chrome_exe,
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={OLX_PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-sync",
            "--disable-background-networking",
            "--disable-default-apps",
            "--window-size=1366,768",
        ]
        proc_ref[0] = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"[OLX BROWSER] Chrome real iniciado na porta {cdp_port} (PID {proc_ref[0].pid})")

        # ── Aguarda o DevTools ficar disponível (até 15s) ─────────────────────
        cdp_url = f"http://localhost:{cdp_port}"
        pw_ref[0] = await async_playwright().start()
        deadline = time.monotonic() + 15
        browser_ref[0] = None
        last_exc = None
        while time.monotonic() < deadline:
            try:
                browser_ref[0] = await pw_ref[0].chromium.connect_over_cdp(cdp_url)
                break
            except Exception as exc:
                last_exc = exc
                await asyncio.sleep(0.8)
        if browser_ref[0] is None:
            raise RuntimeError(
                f"Não foi possível conectar ao Chrome na porta {cdp_port}: {last_exc}"
            )

        # ── Obtém (ou cria) página ────────────────────────────────────────────
        contexts = browser_ref[0].contexts
        ctx = contexts[0] if contexts else await browser_ref[0].new_context(
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": 1366, "height": 768},
            extra_http_headers={
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )
        pages = ctx.pages
        page_ref[0] = pages[0] if pages else await ctx.new_page()

        # Script anti-detecção mínimo (complementar ao Chrome real)
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        print(f"[OLX BROWSER] Conectado via CDP na porta {cdp_port} — Chrome real")
        return page_ref[0]


async def get_olx_cars_page():
    """Página OLX via Chrome real (CDP porta 9222) para o scanner de carros."""
    global _olx_cars_pw, _olx_cars_browser, _olx_cars_page, _olx_cars_proc
    pw_ref    = [_olx_cars_pw]
    brow_ref  = [_olx_cars_browser]
    page_ref  = [_olx_cars_page]
    proc_ref  = [_olx_cars_proc]
    page = await _get_or_create_olx_page(pw_ref, brow_ref, page_ref, proc_ref, _olx_cars_lock, OLX_CARS_CDP_PORT)
    _olx_cars_pw, _olx_cars_browser, _olx_cars_page, _olx_cars_proc = pw_ref[0], brow_ref[0], page_ref[0], proc_ref[0]
    return page


async def get_olx_iphones_page():
    """Página OLX via Chrome real (CDP porta 9223) para o scanner de iPhones."""
    global _olx_iphones_pw, _olx_iphones_browser, _olx_iphones_page, _olx_iphones_proc
    pw_ref    = [_olx_iphones_pw]
    brow_ref  = [_olx_iphones_browser]
    page_ref  = [_olx_iphones_page]
    proc_ref  = [_olx_iphones_proc]
    page = await _get_or_create_olx_page(pw_ref, brow_ref, page_ref, proc_ref, _olx_iphones_lock, OLX_IPHONES_CDP_PORT)
    _olx_iphones_pw, _olx_iphones_browser, _olx_iphones_page, _olx_iphones_proc = pw_ref[0], brow_ref[0], page_ref[0], proc_ref[0]
    return page


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
            gc.collect()  # Libera objetos Python antes de subir novo processo
            await asyncio.sleep(8)  # Aguarda Chrome liberar o perfil e o OS recuperar RAM

        # Lança nova instância
        _playwright_instance = await async_playwright().start()

        _browser_context = await _playwright_instance.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--disable-default-apps",
                "--disable-sync",
                "--no-first-run",
                "--disable-background-networking",
                "--js-flags=--max-old-space-size=512",
            ],
        )

        print(f"[SHARED_BROWSER] Contexto persistente (visível) iniciado em: {PROFILE_DIR}")

        return _browser_context


async def close_all_browsers():
    """
    Fecha todos os browsers abertos pelo AutoRadar (Facebook + OLX).
    Deve ser chamado durante o período de standby para liberar RAM e evitar
    acúmulo de processos Chrome órfãos.
    Só age se houver browsers realmente abertos.
    """
    global _browser_context, _playwright_instance, _global_page, collector_page, scanner_page
    global _olx_cars_pw, _olx_cars_browser, _olx_cars_page, _olx_cars_proc
    global _olx_iphones_pw, _olx_iphones_browser, _olx_iphones_page, _olx_iphones_proc

    # Verifica se há algo aberto — evita prints desnecessários no standby
    has_open = any([
        _olx_cars_browser, _olx_iphones_browser, _browser_context, _playwright_instance,
        _olx_cars_proc, _olx_iphones_proc,
    ])
    if not has_open:
        return  # Nada a fechar

    # ── OLX Cars ─────────────────────────────────────────────────────────────
    # disconnect() apenas encerra a sessão CDP do Playwright.
    # proc.terminate() encerra exclusivamente o PID que o app abriu.
    if _olx_cars_browser is not None:
        try:
            await _olx_cars_browser.disconnect()
        except Exception:
            pass
        _olx_cars_browser = None
        _olx_cars_page = None
    if _olx_cars_pw is not None:
        try:
            await _olx_cars_pw.stop()
        except Exception:
            pass
        _olx_cars_pw = None
    if _olx_cars_proc is not None:
        try:
            _olx_cars_proc.terminate()
            _olx_cars_proc.wait(timeout=5)
        except Exception:
            pass
        _olx_cars_proc = None

    # ── OLX iPhones ──────────────────────────────────────────────────────────
    if _olx_iphones_browser is not None:
        try:
            await _olx_iphones_browser.disconnect()
        except Exception:
            pass
        _olx_iphones_browser = None
        _olx_iphones_page = None
    if _olx_iphones_pw is not None:
        try:
            await _olx_iphones_pw.stop()
        except Exception:
            pass
        _olx_iphones_pw = None
    if _olx_iphones_proc is not None:
        try:
            _olx_iphones_proc.terminate()
            _olx_iphones_proc.wait(timeout=5)
        except Exception:
            pass
        _olx_iphones_proc = None

    # ── Facebook ─────────────────────────────────────────────────────────────
    async with _context_lock:
        _global_page = None
        collector_page = None
        scanner_page = None
        if _browser_context is not None:
            try:
                await _browser_context.close()
            except Exception:
                pass
            _browser_context = None
        if _playwright_instance is not None:
            try:
                await _playwright_instance.stop()
            except Exception:
                pass
            _playwright_instance = None

    gc.collect()
    print("[BROWSER] Todos os browsers encerrados — RAM liberada")



