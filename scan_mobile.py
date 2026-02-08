#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scan de Anúncios (versão estável mesclada)
Visita cada link coletado e extrai informações (preço, modelo, ano, km, etc.).
Created by Igor Avelar - avelar.igor@gmail.com
"""

import sys
import json
import re
import time
import hashlib
import subprocess
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from queue import Queue

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
# Mesma sessão do Facebook usada na coleta (evita logar a cada anúncio)
BROWSER_STATE_FILE = BASE_DIR / "browser_state.json"
# Chrome existente (igual ao Debug) — mesmo perfil que a coleta
CDP_URL = "http://127.0.0.1:9222"
CHROME_DEBUG_PROFILE = BASE_DIR / "chrome_login_profile"

# Versão mobile — anti-bots costumam ser menos acionados; Marketplace é usado em mobile
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)
MOBILE_VIEWPORT = {"width": 390, "height": 844}


def _speed_routes(page, block_images=False):
    """Facebook: bloqueia só font+media (manter imagens)."""
    try:
        blocked = ("image", "media", "font") if block_images else ("media", "font")
        def handler(route):
            if route.request.resource_type in blocked:
                route.abort()
            else:
                route.continue_()
        page.route("**/*", handler)
    except Exception:
        pass


def _find_chrome():
    paths = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
    ]
    for p in paths:
        if p.exists():
            return str(p)
    return None


def _kill_chrome_processes_orphaned():
    """Mata processos órfãos do Chrome criados pelo Playwright (apenas quando não usa CDP)."""
    if sys.platform != "win32":
        return
    try:
        import time
        import os
        # Aguardar um pouco para o browser.close() terminar
        time.sleep(2)
        # Matar apenas processos chromium.exe (Playwright) - não afeta Chrome do usuário
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "chromium.exe"],
                capture_output=True,
                timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            )
        except Exception:
            pass
        # Tentar matar processos chrome.exe que são filhos do processo Python atual
        try:
            current_pid = os.getpid()
            ps_cmd = f'Get-WmiObject Win32_Process | Where-Object {{$_.ParentProcessId -eq {current_pid} -and $_.Name -eq "chrome.exe"}} | ForEach-Object {{Stop-Process -Id $_.ProcessId -Force}}'
            subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            )
        except Exception:
            pass
        _log("Scan: tentativa de encerrar processos órfãos do Chrome.")
    except Exception as e:
        _log("Scan: aviso ao encerrar processos Chrome - %s" % e)


def _minimize_browser_window_win():
    """No Windows: tenta minimizar a janela do navegador (Chrome ignora --start-minimized em alguns casos)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        SW_MINIMIZE = 6
        found = []

        def enum_cb(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd) + 1
                buf = ctypes.create_unicode_buffer(length)
                if user32.GetWindowTextW(hwnd, buf, length):
                    title = buf.value.lower()
                    if "marketplace" in title or "facebook" in title:
                        found.append(hwnd)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        if found:
            user32.ShowWindow(found[0], SW_MINIMIZE)
    except Exception:
        pass


def _launch_chrome_with_debug_port():
    """Igual ao Debug: abre Chrome com porta 9222 para CDP."""
    chrome_exe = _find_chrome()
    if not chrome_exe:
        return False
    CHROME_DEBUG_PROFILE.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            chrome_exe,
            "--remote-debugging-port=9222",
            f"--user-data-dir={CHROME_DEBUG_PROFILE}",
            "--start-minimized",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True


def _log(msg):
    try:
        from log_config import get_logger
        get_logger().info(msg)
    except Exception:
        print(msg)


def _inject_saved_session_into_context(context):
    """Injeta cookies de browser_state.json no context (para CDP usar login persistente)."""
    if not BROWSER_STATE_FILE.exists():
        return
    try:
        with open(BROWSER_STATE_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)
        cookies = state.get("cookies")
        if cookies:
            context.add_cookies(cookies)
            _log("Scan: sessão do Facebook (cookies) aplicada ao navegador (login persistente)")
            print("📌 Sessão do Facebook aplicada (login persistente).")
    except Exception as e:
        _log("Scan: aviso ao aplicar sessão ao CDP - %s" % e)


# Ordem: R$ e reais primeiro (Brasil); US$/ $ por último (só se não achar em R$)
_PRICE_PATTERNS = [
    (r'(R\$\s*[\d.,]+)', 'BRL'),
    (r'([\d.,]+\s*reais?)', 'BRL'),
    (r'(pre[çc]o[:\s]*[\d.,]+)', 'BRL'),
    (r'(US\$\s*[\d.,]+)', 'USD'),
    (r'(\$\s*[\d.,]+)', 'USD'),
]


def extract_price(text: str) -> Optional[float]:
    """Extrai valor numérico do preço (prioriza R$)."""
    result = extract_price_as_shown(text)
    return result[0] if result else None


def extract_price_as_shown(text: str) -> Optional[tuple]:
    """
    Extrai preço exatamente como no anúncio.
    Retorna (valor_numérico, texto_exibido, moeda) ou None.
    Prioriza R$ para anúncios no Brasil.
    """
    if not text:
        return None
    for pattern, currency in _PRICE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            display = match.group(1).strip()
            num_str = re.search(r'[\d.,]+', display)
            if num_str:
                try:
                    raw = num_str.group(0).replace('.', '').replace(',', '.')
                    value = float(raw)
                    return (value, display, currency)
                except Exception:
                    pass
    return None


def extract_year(text: str) -> Optional[int]:
    match = re.search(r'\b(19[89]\d|20[0-3]\d)\b', text)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            pass
    return None


def extract_km(text: str) -> Optional[int]:
    """
    Extrai quilometragem do veículo (odômetro). Ignora valores baixos que são
    tipicamente distância do anúncio (ex: "70 km de distância" no Facebook).
    """
    # Padrões: número (pode ter ponto de milhar BR: 50.000) + km ou quilômetros
    patterns = [
        r'(\d[\d.]*)\s*k?m\b',
        r'(\d[\d.]*)\s*quil[ôo]metros?',
    ]
    candidates = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            try:
                raw = match.group(1).replace('.', '').strip()
                if not raw.isdigit():
                    continue
                value = int(raw)
                # Valores < 1000 são quase sempre "X km de distância", não odômetro
                if value >= 1000:
                    candidates.append(value)
            except Exception:
                pass
    if candidates:
        # Retorna o primeiro valor plausível de odômetro (ex: 50000, 120000)
        return candidates[0]
    return None


def extract_km_dom(page: Any) -> Optional[int]:
    """Tenta extrair KM pelo DOM (labels com 'km'/'quilometr') antes de depender do inner_text."""
    try:
        return page.evaluate("""
        () => {
          const labels = Array.from(document.querySelectorAll('span, div'))
            .map(e => e.innerText)
            .filter(t => t && /km|quilometr/i.test(t));
          for (const t of labels) {
            const m = t.replace(/\\./g,'').match(/(\\d{3,})/);
            if (m) return parseInt(m[1], 10);
          }
          return null;
        }
        """)
    except Exception:
        return None


def _extract_title_from_fallback_text(text: str) -> Optional[str]:
    """Quando a página é 'Este navegador não é compatível', tenta extrair título do corpo (ex.: '2003 Honda CMX' antes de US$)."""
    if not text:
        return None
    # Padrão: linha com ano 4 dígitos + nome do modelo, seguida de US$ preço
    m = re.search(r"\n(\d{4}\s+[^\n]+?)\s*\nUS\$\s*[\d.,]+", text)
    if m:
        return m.group(1).strip()
    # Alternativa: texto entre "Veículos" (ou "›") e "US$"
    m = re.search(r"(?:Veículos|›)\s*\+?\d*\s*\n([^\n]+)\nUS\$\s*[\d.,]+", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


# Títulos do menu/header do Facebook que NÃO são o título do anúncio (mesmo lógica do Debug)
MENU_TITLE_BLACKLIST = frozenset({
    "notificações", "marketplace", "explorar tudo", "caixa de entrada",
    "acesso ao marketplace", "compra", "venda", "criar novo classificado",
    "localização", "categorias", "veículos", "locação de imóveis",
    "artigos domésticos", "artigos esportivos", "número de notificações não lidas",
})


def extract_vehicle_details(text: str) -> dict:
    """
    Extrai detalhes do bloco 'Sobre esse veículo': câmbio, cor externa, cor interna, combustível.
    Retorna dict com chaves cambio, cor_externa, cor_interna, combustivel (valor None se não encontrado).
    """
    out = {"cambio": None, "cor_externa": None, "cor_interna": None, "combustivel": None}
    if not text or not text.strip():
        return out
    t = text.replace("\r", "\n")
    # Câmbio: "Câmbio automático" / "Câmbio manual" / "automático" / "manual" após "câmbio"
    m = re.search(r"c[âa]mbio[:\s]*(\w+)", t, re.IGNORECASE)
    if m:
        val = m.group(1).strip().lower()
        if "automat" in val or val == "automático" or val == "automatico":
            out["cambio"] = "Automático"
        elif "manual" in val or val == "mec":
            out["cambio"] = "Manual"
    if not out["cambio"]:
        if re.search(r"\bautom[áa]tico\b", t, re.IGNORECASE) and re.search(r"c[âa]mbio", t, re.IGNORECASE):
            out["cambio"] = "Automático"
        elif re.search(r"\bmanual\b", t, re.IGNORECASE) and re.search(r"c[âa]mbio", t, re.IGNORECASE):
            out["cambio"] = "Manual"
    # Cor externa: "Cor externa: White" / "Exterior color: White" / "Cor externa · White"
    for pattern in [
        r"cor\s+externa[:\s·]+([^\n·|]+)",
        r"exterior\s*color[:\s·]+([^\n·|]+)",
        r"cor\s+externa[:\s·]*\s*([A-Za-zÀ-ÿ0-9\s]+?)(?:\s·|\n|$)",
    ]:
        m = re.search(pattern, t, re.IGNORECASE)
        if m:
            out["cor_externa"] = m.group(1).strip().strip(".").strip()[:40]
            break
    # Cor interna
    for pattern in [
        r"cor\s+interna[:\s·]+([^\n·|]+)",
        r"interior\s*color[:\s·]+([^\n·|]+)",
        r"cor\s+interna[:\s·]*\s*([A-Za-zÀ-ÿ0-9\s]+?)(?:\s·|\n|$)",
    ]:
        m = re.search(pattern, t, re.IGNORECASE)
        if m:
            out["cor_interna"] = m.group(1).strip().strip(".").strip()[:40]
            break
    # Combustível: "Tipo de combustível: Diesel" / "Combustível: Flex" / "Fuel type: Flex"
    for pattern in [
        r"tipo\s*de\s*combust[íií]vel\s*[:\s·\-]*\s*([^\n·|]+)",
        r"combust[íií]vel\s*[:\s·\-]*\s*([^\n·|]+)",
        r"fuel\s*type\s*[:\s·\-]*\s*([^\n·|]+)",
        r"(?:tipo\s*de\s*)?combust[íií]vel[^\n]*?[:\s·]\s*(\w+)",
    ]:
        m = re.search(pattern, t, re.IGNORECASE)
        if m:
            val = m.group(1).strip().strip(".").strip()[:30]
            if val and val.lower() not in ("patrocinado", "sponsored", "ver", "see"):
                out["combustivel"] = val
                break
    return out


def extract_city(text: str, default_city: str = "") -> str:
    """Extrai cidade do anúncio. Prioriza padrão real do Facebook ('Anunciado... em Cidade, UF')."""
    if not text:
        return default_city
    # 1) Padrão do Facebook: "Anunciado Há X em Franca, SP" (evita "em bom estado, SP" etc.)
    m = re.search(r'anunciado.*?em\s+([A-Za-zÀ-ÿ\s]+,\s*[A-Z]{2})', text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    # 2) Rótulos "localização:", "cidade:"
    m = re.search(r'(?:localização|location|cidade|city)[:\s]+([^\n|,]+)', text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # 3) Fallback amplo (último recurso)
    m = re.search(r'\bem\s+([^,\n]+,\s*[A-Za-z]{2})\b', text)
    if m:
        return m.group(1).strip()
    return default_city


def _cache_key(link: str) -> str:
    """Chave estável para cache (evita hash() aleatório entre execuções)."""
    return hashlib.md5(link.encode()).hexdigest()


def _scan_cache_days() -> int:
    """Dias para considerar cache de scan válido (0 = sempre re-escanar)."""
    try:
        prefs_file = BASE_DIR / "user_preferences.json"
        if prefs_file.exists():
            with open(prefs_file, "r", encoding="utf-8") as f:
                prefs = json.load(f)
            return max(0, int(prefs.get("scan_cache_days", 30)))
    except Exception:
        pass
    return 30


def _is_cache_valid(cache_file: Path, listing: Dict[str, Any], cache_days: int) -> bool:
    """True se o cache ainda está dentro do prazo (scan_cache_days)."""
    if cache_days <= 0:
        return False
    scanned_at = listing.get("scanned_at") or ""
    if not scanned_at:
        try:
            mtime = cache_file.stat().st_mtime
            scanned_at = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return False
    try:
        scanned_dt = datetime.strptime(scanned_at[:19], "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - scanned_dt) <= timedelta(days=cache_days)
    except Exception:
        return False


def scan_listings(
    links: List[str],
    progress_callback: Optional[Callable[[int, int], None]] = None,
    listing_queue: Optional["Queue"] = None,
    browser: Optional[Any] = None,
) -> tuple:
    """Retorna (listings, erros_count). browser: se informado, reutiliza (não fecha)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        _log("Scan: Playwright não instalado - %s" % e)
        print("❌ Playwright não instalado. Instale com: pip install playwright")
        return ([], 0)

    from path_utils import get_out_dir, get_cache_listing_dir

    listings = []
    errors_count = 0
    # Micro-otimização: carregar preferências 1x (evita abrir JSON a cada anúncio)
    _pref_price_min = None
    _pref_price_max = None
    try:
        _prefs_file = BASE_DIR / "user_preferences.json"
        if _prefs_file.exists():
            with open(_prefs_file, "r", encoding="utf-8") as _f:
                _prefs = json.load(_f)
            _pref_price_min = _prefs.get("price_min")
            _pref_price_max = _prefs.get("price_max")
    except Exception:
        pass
    cache_dir = get_cache_listing_dir()
    out_dir = get_out_dir()

    print(f"📊 Escaneando {len(links)} anúncios...")
    _log("Scan: iniciando %s anúncios" % len(links))

    reuse_browser = browser is not None
    if reuse_browser:
        use_cdp = True
        context = browser.contexts[0] if browser.contexts else browser.new_context(locale="pt_BR")
        _inject_saved_session_into_context(context)
        page = context.pages[0] if context.pages else context.new_page()
        _speed_routes(page, block_images=False)
        # Loop de scan (mesmo código que no bloco use_cdp abaixo)
        for i, link in enumerate(links, 1):
            if progress_callback:
                progress_callback(i, len(links))
            cache_file = cache_dir / f"{_cache_key(link)}.json"
            cache_days = _scan_cache_days()
            if cache_file.exists():
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        listing = json.load(f)
                        if _is_cache_valid(cache_file, listing, cache_days):
                            listings.append(listing)
                            if listing_queue is not None:
                                listing_queue.put(listing)
                            print(f"[{i}/{len(links)}] ✅ Cache | {link[:50]}...")
                            continue
                except Exception:
                    pass
            try:
                print(f"[{i}/{len(links)}] 🔍 Escaneando {link[:50]}...")
                try:
                    response = page.goto(link, wait_until="domcontentloaded", timeout=30000)
                    # Verificar status HTTP
                    if response and response.status >= 400:
                        _log("⚠️ Scan: erro HTTP %d em %s" % (response.status, link[:50]))
                        if response.status == 403:
                            _log("❌ Scan: acesso negado (403) - página bloqueada pelo Facebook")
                            # Tentar usar cache se disponível (mesmo que expirado)
                            if cache_file.exists():
                                try:
                                    with open(cache_file, 'r', encoding='utf-8') as f:
                                        cached_listing = json.load(f)
                                        if cached_listing.get("title") and cached_listing.get("year"):
                                            _log("✅ Scan: usando cache expirado para página bloqueada")
                                            listings.append(cached_listing)
                                            if listing_queue is not None:
                                                listing_queue.put(cached_listing)
                                            continue
                                except Exception:
                                    pass
                            errors_count += 1
                            continue
                except Exception as goto_error:
                    error_str = str(goto_error).lower()
                    if "403" in error_str or "access denied" in error_str or "forbidden" in error_str:
                        _log("❌ Scan: acesso negado ao acessar %s" % link[:50])
                        # Tentar usar cache se disponível
                        if cache_file.exists():
                            try:
                                with open(cache_file, 'r', encoding='utf-8') as f:
                                    cached_listing = json.load(f)
                                    if cached_listing.get("title") and cached_listing.get("year"):
                                        _log("✅ Scan: usando cache para página bloqueada")
                                        listings.append(cached_listing)
                                        if listing_queue is not None:
                                            listing_queue.put(cached_listing)
                                        continue
                            except Exception:
                                pass
                        errors_count += 1
                        continue
                    else:
                        raise
                try:
                    page.wait_for_selector('h1, [data-testid="marketplace-pdp-title"]', timeout=4000)
                except Exception:
                    pass
                if i == 1:
                    _minimize_browser_window_win()
                try:
                    ver_mais = page.get_by_text("Ver mais", exact=False).first
                    if ver_mais.is_visible(timeout=500):
                        ver_mais.click()
                        time.sleep(0.8)
                except Exception:
                    try:
                        page.click("text=See more", timeout=500)
                        time.sleep(0.8)
                    except Exception:
                        pass
                page_text = page.inner_text('body') or ""
                
                # Verificar se a página está bloqueada pelo conteúdo
                page_text_lower = page_text.lower()
                if "access to this page has been denied" in page_text_lower or "acesso negado" in page_text_lower or "forbidden" in page_text_lower or "403" in page_text:
                    _log("❌ Scan: página bloqueada detectada no conteúdo: %s" % link[:50])
                    # Tentar usar cache se disponível
                    if cache_file.exists():
                        try:
                            with open(cache_file, 'r', encoding='utf-8') as f:
                                cached_listing = json.load(f)
                                if cached_listing.get("title") and cached_listing.get("year"):
                                    _log("✅ Scan: usando cache para página bloqueada (detectada no conteúdo)")
                                    listings.append(cached_listing)
                                    if listing_queue is not None:
                                        listing_queue.put(cached_listing)
                                    continue
                        except Exception:
                            pass
                    errors_count += 1
                    continue
                if "não está mais disponível" in page_text_lower or "listing unavailable" in page_text_lower or "no longer available" in page_text_lower:
                    _log("⛔ Anúncio removido: %s" % link[:50])
                    continue
                price_result = extract_price_as_shown(page_text)
                if price_result:
                    price, price_display, currency = price_result
                else:
                    price, price_display, currency = None, "", ""
                year = extract_year(page_text)
                km = extract_km_dom(page) or extract_km(page_text)
                city = extract_city(page_text)
                vehicle_details = extract_vehicle_details(page_text)
                title = ""
                try:
                    candidates = page.query_selector_all('h1, [data-testid="marketplace-pdp-title"], [data-testid="marketplace_pdp_title"], [role="heading"]')
                    for elem in candidates:
                        t = (elem.inner_text() or "").strip()
                        if not t or len(t) < 6: continue
                        if t.lower() in MENU_TITLE_BLACKLIST: continue
                        if any(menu in t.lower() for menu in MENU_TITLE_BLACKLIST): continue
                        title = t
                        break
                except Exception:
                    pass
                if not title:
                    for line in (page_text or "").split("\n"):
                        line = line.strip()
                        if 10 <= len(line) <= 120 and line.lower() not in MENU_TITLE_BLACKLIST:
                            if not any(menu in line.lower() for menu in MENU_TITLE_BLACKLIST):
                                title = line
                                break
                if not title and page_text:
                    title_match = re.search(r'^(.{10,100})', page_text)
                    if title_match:
                        title = title_match.group(1).strip()
                if title and "não é compatível" in title.lower():
                    title_from_desc = _extract_title_from_fallback_text(page_text)
                    if title_from_desc:
                        title = title_from_desc
                if title and not re.search(r'\b(19[89]\d|20[0-3]\d)\b', title):
                    title = ""
                main_photo_path = ""
                main_photo_url = ""
                try:
                    img = page.query_selector('img[src*="scontent"], img[src*="fbcdn"], img[src*="marketplace"]')
                    if not img:
                        for im in page.query_selector_all("img[src]"):
                            s = im.get_attribute("src") or ""
                            if ("scontent" in s or "fbcdn" in s or "marketplace" in s) and "emoji" not in s.lower() and "avatar" not in s.lower():
                                img = im
                                break
                    if img:
                        src = img.get_attribute("src")
                        if src and src.startswith("http"):
                            main_photo_url = src
                except Exception:
                    pass
                price_min_cfg = _pref_price_min
                price_max_cfg = _pref_price_max
                if price is not None and price <= 0:
                    continue
                if price is not None:
                    if price_min_cfg is not None and price_min_cfg > 0 and price < price_min_cfg:
                        continue
                    if price_max_cfg is not None and price_max_cfg > 0 and price > price_max_cfg:
                        continue
                listing = {
                    "url": link,
                    "title": title or "Sem título",
                    "price": price,
                    "price_display": price_display,
                    "currency": currency,
                    "year": year,
                    "km": km,
                    "city": city,
                    "main_photo_path": main_photo_path,
                    "main_photo_url": main_photo_url,
                    "description": (page_text[:500] if page_text else ""),
                    "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "source": "facebook",
                    "cambio": vehicle_details.get("cambio"),
                    "cor_externa": vehicle_details.get("cor_externa"),
                    "cor_interna": vehicle_details.get("cor_interna"),
                    "combustivel": vehicle_details.get("combustivel"),
                }
                listings.append(listing)
                if listing_queue is not None:
                    listing_queue.put(listing)
                try:
                    with open(cache_dir / f"{_cache_key(link)}.json", 'w', encoding='utf-8') as f:
                        json.dump(listing, f, indent=2, ensure_ascii=False)
                except Exception:
                    pass
                # Validar se conseguiu extrair dados mínimos antes de salvar
                if not title or not year:
                    _log("⚠️ Scan: dados incompletos (sem título ou ano) em %s - título='%s', ano=%s" % (link[:50], title[:50] if title else "None", year))
                    # Tentar usar cache se disponível (mesmo que expirado)
                    if cache_file.exists():
                        try:
                            with open(cache_file, 'r', encoding='utf-8') as f:
                                cached_listing = json.load(f)
                                if cached_listing.get("title") and cached_listing.get("year"):
                                    _log("✅ Scan: usando cache para anúncio com dados incompletos")
                                    listings.append(cached_listing)
                                    if listing_queue is not None:
                                        listing_queue.put(cached_listing)
                                    continue
                        except Exception:
                            pass
                    # Não salvar anúncio sem título ou ano
                    errors_count += 1
                    continue
                
                time.sleep(1)
            except Exception as e:
                errors_count += 1
                error_str = str(e).lower()
                if "403" in error_str or "access denied" in error_str or "forbidden" in error_str:
                    _log("❌ Scan: acesso negado ao acessar %s - %s" % (link[:50], str(e)[:100]))
                    # Tentar usar cache se disponível
                    if cache_file.exists():
                        try:
                            with open(cache_file, 'r', encoding='utf-8') as f:
                                cached_listing = json.load(f)
                                if cached_listing.get("title") and cached_listing.get("year"):
                                    _log("✅ Scan: usando cache após erro de acesso negado")
                                    listings.append(cached_listing)
                                    if listing_queue is not None:
                                        listing_queue.put(cached_listing)
                                    continue
                        except Exception:
                            pass
                else:
                    print(f"[{i}/{len(links)}] ❌ Erro: {e}")
                continue
        try:
            with open(out_dir / "listings_facebook.json", 'w', encoding='utf-8') as f:
                json.dump(listings, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return (listings, errors_count)

    try:
        with sync_playwright() as p:
            # Primeiro tentar Chrome na porta 9222 (CDP): conteúdo completo
            use_cdp = False
            try:
                browser = p.chromium.connect_over_cdp(CDP_URL)
                use_cdp = True
                print("📌 Usando Chrome existente (porta 9222) — conteúdo completo.")
            except Exception as e1:
                try:
                    if _launch_chrome_with_debug_port():
                        time.sleep(5)
                        browser = p.chromium.connect_over_cdp(CDP_URL)
                        use_cdp = True
                        print("📌 Conectado ao Chrome (porta 9222).")
                except Exception:
                    pass
                if not use_cdp:
                    print("📌 Nenhum Chrome na porta 9222. Usando janela minimizada.")
                    browser = p.chromium.launch(channel="chrome", 
                        headless=False,
                        args=["--start-minimized", "--window-size=1280,800"]
                    )
            if use_cdp:
                context = browser.contexts[0] if browser.contexts else browser.new_context(locale="pt_BR")
                _inject_saved_session_into_context(context)
                page = context.pages[0] if context.pages else context.new_page()
                _speed_routes(page, block_images=False)
            else:
                context_opts = {
                    "viewport": MOBILE_VIEWPORT,
                    "user_agent": MOBILE_USER_AGENT,
                    "locale": "pt_BR",
                    "is_mobile": True,
                    "device_scale_factor": 1,
                }
                if BROWSER_STATE_FILE.exists():
                    context_opts["storage_state"] = str(BROWSER_STATE_FILE)
                    print("📌 Usando sessão do Facebook salva (login persistente)")
                context = browser.new_context(**context_opts)
                page = context.new_page()
                _speed_routes(page, block_images=False)

            for i, link in enumerate(links, 1):
                if progress_callback:
                    progress_callback(i, len(links))

                cache_file = cache_dir / f"{_cache_key(link)}.json"
                cache_days = _scan_cache_days()
                if cache_file.exists():
                    try:
                        with open(cache_file, 'r', encoding='utf-8') as f:
                            listing = json.load(f)
                            if _is_cache_valid(cache_file, listing, cache_days):
                                listings.append(listing)
                                if listing_queue is not None:
                                    listing_queue.put(listing)
                                print(f"[{i}/{len(links)}] ✅ Cache | {link[:50]}...")
                                continue
                    except Exception:
                        pass

                try:
                    print(f"[{i}/{len(links)}] 🔍 Escaneando {link[:50]}...")
                    try:
                        response = page.goto(link, wait_until="domcontentloaded", timeout=30000)
                        # Verificar status HTTP
                        if response and response.status >= 400:
                            _log("⚠️ Scan: erro HTTP %d em %s" % (response.status, link[:50]))
                            if response.status == 403:
                                _log("❌ Scan: acesso negado (403) - página bloqueada pelo Facebook")
                                # Tentar usar cache se disponível (mesmo que expirado)
                                if cache_file.exists():
                                    try:
                                        with open(cache_file, 'r', encoding='utf-8') as f:
                                            cached_listing = json.load(f)
                                            if cached_listing.get("title") and cached_listing.get("year"):
                                                _log("✅ Scan: usando cache expirado para página bloqueada")
                                                listings.append(cached_listing)
                                                if listing_queue is not None:
                                                    listing_queue.put(cached_listing)
                                                continue
                                    except Exception:
                                        pass
                                errors_count += 1
                                continue
                    except Exception as goto_error:
                        error_str = str(goto_error).lower()
                        if "403" in error_str or "access denied" in error_str or "forbidden" in error_str:
                            _log("❌ Scan: acesso negado ao acessar %s" % link[:50])
                            # Tentar usar cache se disponível
                            if cache_file.exists():
                                try:
                                    with open(cache_file, 'r', encoding='utf-8') as f:
                                        cached_listing = json.load(f)
                                        if cached_listing.get("title") and cached_listing.get("year"):
                                            _log("✅ Scan: usando cache para página bloqueada")
                                            listings.append(cached_listing)
                                            if listing_queue is not None:
                                                listing_queue.put(cached_listing)
                                            continue
                                except Exception:
                                    pass
                            errors_count += 1
                            continue
                        else:
                            raise
                    try:
                        page.wait_for_selector('h1, [data-testid="marketplace-pdp-title"]', timeout=4000)
                    except Exception:
                        pass
                    if i == 1:
                        _minimize_browser_window_win()
                    # Expandir "Ver mais" para que "Sobre esse veículo" (combustível, etc.) entre no texto
                    try:
                        ver_mais = page.get_by_text("Ver mais", exact=False).first
                        if ver_mais.is_visible(timeout=500):
                            ver_mais.click()
                            time.sleep(0.8)
                    except Exception:
                        try:
                            page.click("text=See more", timeout=500)
                            time.sleep(0.8)
                        except Exception:
                            pass

                    page_text = page.inner_text('body') or ""
                    
                    # Verificar se a página está bloqueada pelo conteúdo
                    page_text_lower = page_text.lower()
                    if "access to this page has been denied" in page_text_lower or "acesso negado" in page_text_lower or "forbidden" in page_text_lower or "403" in page_text:
                        _log("❌ Scan: página bloqueada detectada no conteúdo: %s" % link[:50])
                        # Tentar usar cache se disponível
                        if cache_file.exists():
                            try:
                                with open(cache_file, 'r', encoding='utf-8') as f:
                                    cached_listing = json.load(f)
                                    if cached_listing.get("title") and cached_listing.get("year"):
                                        _log("✅ Scan: usando cache para página bloqueada (detectada no conteúdo)")
                                        listings.append(cached_listing)
                                        if listing_queue is not None:
                                            listing_queue.put(cached_listing)
                                        continue
                            except Exception:
                                pass
                        errors_count += 1
                        continue
                    if "não está mais disponível" in page_text_lower or "listing unavailable" in page_text_lower or "no longer available" in page_text_lower:
                        _log("⛔ Anúncio removido: %s" % link[:50])
                        continue
                    price_result = extract_price_as_shown(page_text)
                    if price_result:
                        price, price_display, currency = price_result
                    else:
                        price, price_display, currency = None, "", ""
                    year = extract_year(page_text)
                    km = extract_km_dom(page) or extract_km(page_text)
                    city = extract_city(page_text)
                    vehicle_details = extract_vehicle_details(page_text)

                    title = ""
                    try:
                        # Facebook: o primeiro h1 pode ser do menu ("Notificações"). Pegar o do anúncio (lógica do Debug).
                        candidates = page.query_selector_all(
                            'h1, [data-testid="marketplace-pdp-title"], [data-testid="marketplace_pdp_title"], [role="heading"]'
                        )
                        for elem in candidates:
                            t = (elem.inner_text() or "").strip()
                            t_lower = t.lower()
                            if not t or len(t) < 6:
                                continue
                            if t_lower in MENU_TITLE_BLACKLIST:
                                continue
                            if any(menu in t_lower for menu in MENU_TITLE_BLACKLIST):
                                continue
                            title = t
                            break
                    except Exception:
                        pass
                    if not title:
                        for line in (page_text or "").split("\n"):
                            line = line.strip()
                            if 10 <= len(line) <= 120 and line.lower() not in MENU_TITLE_BLACKLIST:
                                if not any(menu in line.lower() for menu in MENU_TITLE_BLACKLIST):
                                    title = line
                                    break
                    if not title:
                        title_match = re.search(r'^(.{10,100})', page_text)
                        if title_match:
                            title = title_match.group(1).strip()
                    # Se a página é "Este navegador não é compatível", extrair título do texto
                    if title and "não é compatível" in title.lower():
                        title_from_desc = _extract_title_from_fallback_text(page_text)
                        if title_from_desc:
                            title = title_from_desc
                    if title and not re.search(r'\b(19[89]\d|20[0-3]\d)\b', title):
                        title = ""

                    # Foto principal: só guardar URL; download sob demanda ao enviar no Telegram
                    main_photo_path = ""
                    main_photo_url = ""
                    try:
                        img = page.query_selector('img[src*="scontent"], img[src*="fbcdn"], img[src*="marketplace"]')
                        if not img:
                            for im in page.query_selector_all("img[src]"):
                                s = im.get_attribute("src") or ""
                                if ("scontent" in s or "fbcdn" in s or "marketplace" in s) and "emoji" not in s.lower() and "avatar" not in s.lower():
                                    img = im
                                    break
                        if img:
                            src = img.get_attribute("src")
                            if src and src.startswith("http"):
                                main_photo_url = src
                    except Exception:
                        pass

                    # Revalidar preço no DOM: fora da faixa configurada → descarta (anti-bug R$ 2.502.008, etc.)
                    price_min_cfg = _pref_price_min
                    price_max_cfg = _pref_price_max
                    # Preço inválido: R$ 0 ou negativo é inaceitável
                    if price is not None and price <= 0:
                        print(f"[{i}/{len(links)}] ⏭️ Preço inválido (R$ 0 ou negativo) — ignorando")
                        continue
                    # Filtro de preço: 0 = sem limite (só aplica se mínimo/máximo > 0)
                    if price is not None:
                        if price_min_cfg is not None and price_min_cfg > 0 and price < price_min_cfg:
                            print(f"[{i}/{len(links)}] ⏭️ Fora da faixa (preço R$ {price:,.0f} < mínimo)")
                            continue
                        if price_max_cfg is not None and price_max_cfg > 0 and price > price_max_cfg:
                            print(f"[{i}/{len(links)}] ⏭️ Fora da faixa (preço R$ {price:,.0f} > máximo)")
                            continue

                    listing = {
                        "url": link,
                        "title": title or "Sem título",
                        "price": price,
                        "price_display": price_display,
                        "currency": currency,
                        "year": year,
                        "km": km,
                        "city": city,
                        "main_photo_path": main_photo_path,
                        "main_photo_url": main_photo_url,
                        "description": page_text[:500] if page_text else "",
                        "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "source": "facebook",
                        "cambio": vehicle_details.get("cambio"),
                        "cor_externa": vehicle_details.get("cor_externa"),
                        "cor_interna": vehicle_details.get("cor_interna"),
                        "combustivel": vehicle_details.get("combustivel"),
                    }
                    listings.append(listing)
                    if listing_queue is not None:
                        listing_queue.put(listing)

                    try:
                        with open(cache_file, 'w', encoding='utf-8') as f:
                            json.dump(listing, f, indent=2, ensure_ascii=False)
                    except Exception:
                        pass

                    fipe_valor = None
                    try:
                        from ranking_mvp import _extract_model_tokens, _normalize_text
                        from fipe_api import get_fipe_from_cache_or_api
                        if title and year:
                            modelo_tokens = _extract_model_tokens(title)
                            title_lower = _normalize_text(title)
                            marcas = ['honda', 'toyota', 'ford', 'chevrolet', 'volkswagen', 'fiat', 'hyundai', 'jeep', 'nissan', 'renault']
                            marca = next((m for m in marcas if m in title_lower), None)
                            if marca and modelo_tokens:
                                fipe_valor = get_fipe_from_cache_or_api(marca, " ".join(modelo_tokens), year)
                    except Exception:
                        pass

                    fipe_str = f" | 💲 FIPE Aprox R$ {fipe_valor:,.0f}" if fipe_valor else ""
                    price_str = price_display if price_display else (f"R$ {price:,.0f}" if price is not None else "N/A")
                    km_str = f"{km:,}" if km is not None else "N/A"
                    year_str = str(year) if year is not None else "N/A"
                    title_short = (title or "Sem título").strip()[:50] + ("…" if len((title or "").strip()) > 50 else "")
                    print(f"[{i}/{len(links)}] Processado | {title_short} | 💰 {price_str} | 🚗 {km_str} km | 📅 {year_str}{fipe_str}")

                except Exception as e:
                    errors_count += 1
                    error_str = str(e).lower()
                    if "403" in error_str or "access denied" in error_str or "forbidden" in error_str:
                        _log("❌ Scan: acesso negado ao acessar %s - %s" % (link[:50], str(e)[:100]))
                        # Tentar usar cache se disponível
                        if cache_file.exists():
                            try:
                                with open(cache_file, 'r', encoding='utf-8') as f:
                                    cached_listing = json.load(f)
                                    if cached_listing.get("title") and cached_listing.get("year"):
                                        _log("✅ Scan: usando cache após erro de acesso negado")
                                        listings.append(cached_listing)
                                        if listing_queue is not None:
                                            listing_queue.put(cached_listing)
                                        continue
                            except Exception:
                                pass
                    else:
                        print(f"[{i}/{len(links)}] ❌ Erro: {e}")
                        _log("Scan: erro em link %s/%s - %s" % (i, len(links), e))
                    continue

                time.sleep(1)

            # Não fechar o Chrome quando usamos CDP (é o navegador do usuário)
            if not use_cdp and browser:
                browser.close()

    except Exception as e:
        print(f"❌ Erro durante scan: {e}")
        _log("Scan: erro geral - %s" % e)
        import traceback
        traceback.print_exc()

    output_file = out_dir / "listings_facebook.json"
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(listings, f, indent=2, ensure_ascii=False)
        print(f"✅ {len(listings)} anúncios salvos em {output_file}")
        _log("Scan: concluído. OK=%s, erros=%s" % (len(listings), errors_count))
    except Exception as e:
        print(f"❌ Erro ao salvar: {e}")

    return (listings, errors_count)
