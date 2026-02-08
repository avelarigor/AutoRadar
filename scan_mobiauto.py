#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scan de Anúncios da Mobiauto
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
from typing import List, Dict, Any, Callable, Optional

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent

# Chrome existente (igual ao Facebook)
CDP_URL = "http://127.0.0.1:9222"

# Versão mobile (igual à coleta) — anti-bots costumam ser menos acionados em mobile
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)
MOBILE_VIEWPORT = {"width": 375, "height": 667}


def _speed_routes(page, block_images=True):
    """Bloqueia image/media/font para acelerar."""
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


def _apply_mobile_emulation(context, page):
    """Em modo CDP, aplica UA/viewport mobile na page atual (sem abrir nova aba)."""
    try:
        cdp = context.new_cdp_session(page)
        cdp.send("Emulation.setUserAgentOverride", {"userAgent": MOBILE_USER_AGENT})
        cdp.send("Emulation.setDeviceMetricsOverride", {
            "width": MOBILE_VIEWPORT["width"],
            "height": MOBILE_VIEWPORT["height"],
            "deviceScaleFactor": 1,
            "mobile": True,
        })
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True})
    except Exception:
        pass


def _log(msg):
    """Log simples para debug."""
    try:
        from log_config import get_logger
        get_logger().info(msg)
    except Exception:
        print(f"[Mobiauto Scan] {msg}")


def _find_chrome():
    """Encontra o executável do Chrome no Windows."""
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
    """(SAFE) Evita matar chrome.exe do pipeline.
    Mantém somente uma tentativa de encerrar chromium.exe (quando existir).
    """
    if sys.platform != "win32":
        return
    try:
        import time
        time.sleep(1)
        # IMPORTANTE: não matar chrome.exe por ParentProcessId (isso derruba o Chrome usado via CDP)
        # Se algum dia você voltar a usar Chromium do Playwright, esse kill ajuda a limpar processos órfãos.
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "chromium.exe"],
                capture_output=True,
                timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            )
        except Exception:
            pass
    except Exception:
        pass


def _city_from_url(link: str) -> str:
    """Extrai cidade da URL Mobiauto (ex.: .../mg-montes-claros/... → 'Montes Claros - MG')."""
    if not link or "mobiauto" not in link.lower():
        return ""
    m = re.search(r'/comprar/[^/]+/([a-z]{2})-([a-z0-9-]+)(?:/|$)', link)
    if not m:
        m = re.search(r'/([a-z]{2})-([a-z0-9-]+)(?:/|$)', link)
    if m:
        uf, slug = m.group(1).upper(), m.group(2).replace("-", " ").title()
        if slug and uf and len(slug) < 50:
            return f"{slug} - {uf}"
    return ""


def _scan_cache_days() -> int:
    """Dias para considerar cache de scan válido (0 = sempre re-escanar)."""
    try:
        prefs_file = BASE_DIR / "user_preferences.json"
        if prefs_file.exists():
            with open(prefs_file, "r", encoding="utf-8") as f:
                prefs = json.load(f)
            return max(0, int(prefs.get("scan_cache_days", 7)))
    except Exception:
        pass
    return 7


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


def _launch_chrome_with_debug_port():
    """Tenta abrir Chrome na porta 9222 para CDP."""
    chrome_path = _find_chrome()
    if not chrome_path:
        return False
    try:
        import subprocess
        subprocess.Popen(
            [
                chrome_path,
                f"--remote-debugging-port=9222",
                "--user-data-dir=" + str(BASE_DIR / "chrome_login_profile"),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        )
        return True
    except Exception:
        return False


def extract_price(text: str) -> Optional[float]:
    """Extrai preço do texto (formato R$ X.XXX,XX ou R$ XXXX)."""
    if not text:
        return None
    # Padrões: R$ seguido de número (pode ter ponto de milhar e vírgula decimal)
    patterns = [
        r'R\$\s*(\d[\d.]*,\d{2})',
        r'R\$\s*(\d[\d.]*)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text.replace(' ', ''))
        if match:
            try:
                price_str = match.group(1).replace('.', '').replace(',', '.')
                return float(price_str)
            except Exception:
                pass
    return None


def extract_year(text: str) -> Optional[int]:
    """Extrai ano do veículo (4 dígitos entre 1950 e ano atual + 1)."""
    if not text:
        return None
    import datetime
    current_year = datetime.datetime.now().year + 1
    matches = re.findall(r'\b(19[5-9]\d|20[0-3]\d)\b', text)
    for match in matches:
        try:
            year = int(match)
            if 1950 <= year <= current_year:
                return year
        except Exception:
            pass
    return None


def extract_km(text: str) -> Optional[int]:
    """
    Extrai quilometragem do veículo (odômetro).
    Suporta: "43.169 km", "114.000 quilômetros", "KM 43.169", "KM\\n43.169" (Webmotors/Mobiauto).
    Ignora "X km de distância".
    """
    if not text:
        return None
    t = text.replace("\r", "\n")
    # 1) Padrão de tabela: "KM" como rótulo e o número separado (Webmotors/Mobiauto)
    m = re.search(r"\bKM\b\s*[:\-]?\s*([\d.]{3,})\b", t, re.IGNORECASE)
    if m:
        raw = m.group(1).replace(".", "").strip()
        if raw.isdigit():
            val = int(raw)
            if val >= 0:
                return val
    # 2) Padrões clássicos: número + km / quilômetros
    patterns = [
        r'(\d[\d.]*)\s*k?m\b',
        r'(\d[\d.]*)\s*quil[ôo]metros?',
    ]
    candidates = []
    for pattern in patterns:
        for match in re.finditer(pattern, t, re.IGNORECASE):
            try:
                start = max(0, match.start() - 30)
                context = t[start:match.end() + 30].lower()
                if "distância" in context or "distancia" in context:
                    continue
                raw = match.group(1).replace('.', '').strip()
                if not raw.isdigit():
                    continue
                value = int(raw)
                if value >= 1000:
                    candidates.append(value)
            except Exception:
                pass
    return candidates[0] if candidates else None


def _looks_like_css_title(t: Optional[str]) -> bool:
    """Retorna True se o título parece lixo de CSS (styled-components/emotion)."""
    if not t:
        return False
    s = str(t).strip()
    if s.startswith(".css-"):
        return True
    if "{" in s or "}" in s:
        return True
    if "text-transform" in s or "font-weight" in s:
        return True
    return False


def normalize_km(km_text: Optional[str], fallback_text: Optional[str] = None) -> Optional[int]:
    """Se km_text já for número puro (ex: do __NEXT_DATA__), usa direto; senão extrai com extract_km."""
    t = (km_text or "").strip()
    t_digits = t.replace(".", "").replace(" ", "")
    if t_digits.isdigit():
        return int(t_digits)
    return extract_km((t + " " + (fallback_text or "")).strip())


def scan_listings(
    links: List[str],
    progress_callback: Optional[Callable[[int, int], None]] = None,
    listing_queue: Optional[Any] = None,
    browser: Optional[Any] = None,
) -> tuple:
    """
    Escaneia anúncios da Mobiauto. Retorna (listings, erros_count).
    browser: se informado, reutiliza (não fecha).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        _log("Scan: Playwright não instalado - %s" % e)
        print("❌ Playwright não instalado. Instale com: pip install playwright")
        return ([], 0)

    from path_utils import get_out_dir, get_cache_listing_dir

    listings = []
    errors_count = 0
    cache_dir = get_cache_listing_dir()
    out_dir = get_out_dir()
    print(f"📊 Escaneando {len(links)} anúncios da Mobiauto...")
    _log("Scan: iniciando %s anúncios" % len(links))

    reuse_browser = browser is not None
    p_ctx = None
    if reuse_browser:
        context = browser.contexts[0] if browser.contexts else browser.new_context(locale="pt_BR")
        page = context.pages[0] if context.pages else context.new_page()
        use_cdp = True
    else:
        p_ctx = sync_playwright()
        p = p_ctx.__enter__()
        use_cdp = False
        browser = None
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
            use_cdp = True
            print("📌 Usando Chrome existente (porta 9222)")
        except Exception:
            try:
                if _launch_chrome_with_debug_port():
                    time.sleep(5)
                    browser = p.chromium.connect_over_cdp(CDP_URL)
                    use_cdp = True
                    print("📌 Conectado ao Chrome (porta 9222)")
            except Exception:
                pass
            if browser is None:
                print("📌 Usando janela minimizada")
                browser = p.chromium.launch(
                    headless=False,
                    args=["--start-minimized", "--window-size=1280,800"]
                )
        if use_cdp:
            context = browser.contexts[0] if browser.contexts else browser.new_context(locale="pt_BR")
            page = context.pages[0] if context.pages else context.new_page()
            _apply_mobile_emulation(context, page)
            _speed_routes(page, block_images=True)
        else:
            context = browser.new_context(
                viewport=MOBILE_VIEWPORT,
                user_agent=MOBILE_USER_AGENT,
                locale="pt_BR",
                is_mobile=True,
                device_scale_factor=1,
            )
            page = context.new_page()
            _speed_routes(page, block_images=True)

    try:
                for idx, link in enumerate(links, 1):
                    if progress_callback:
                        progress_callback(idx, len(links))
                    
                    cache_key = hashlib.md5(link.encode()).hexdigest()
                    cache_file = cache_dir / f"mobiauto_{cache_key}.json"
                    cache_days = _scan_cache_days()
                    
                    # Verificar cache (só válido se último scan dentro de scan_cache_days)
                    if cache_file.exists():
                        try:
                            with open(cache_file, 'r', encoding='utf-8') as f:
                                cached = json.load(f)
                                if _is_cache_valid(cache_file, cached, cache_days):
                                    if cached.get("source") in ("webmotors", "mobiauto"):
                                        kmc = (cached.get("km") or "")
                                        kmc = str(kmc).strip() if kmc is not None else ""
                                        if not kmc or kmc in ("—", "-"):
                                            _log("Cache sem KM: forçando rescan - %s" % link[:50])
                                            raise Exception("cache sem KM: forçando rescan")
                                    if cached.get("source") == "mobiauto":
                                        t = (cached.get("title") or "").strip()
                                        if _looks_like_css_title(t) or len(t) < 6:
                                            _log("Cache com título inválido: forçando rescan - %s" % link[:50])
                                            raise Exception("cache com título inválido: forçando rescan")
                                    # Garantir cidade: cache antigo pode ter city vazia ou JSON
                                    if cached.get("source") == "mobiauto":
                                        c = (cached.get("city") or "").strip()
                                        if not c or c.startswith("{") or '"props"' in c or '"pageProps"' in c:
                                            from_url = _city_from_url(cached.get("url") or link)
                                            if from_url:
                                                cached["city"] = from_url
                                    listings.append(cached)
                                    _log("Scan: cache hit - %s" % link[:50])
                                    continue
                        except Exception:
                            pass
                    
                    try:
                        page.goto(link, wait_until="domcontentloaded", timeout=60000)
                        try:
                            page.wait_for_selector("#__NEXT_DATA__", state="attached", timeout=5000)
                        except Exception:
                            pass
                        
                        # Extrair dados da página usando JavaScript
                        # Mobiauto: preço em css-1rb9omp ou data-analytic-id="details-vehicle-price"
                        # Ano e KM em divs com label seguido de css-fwo2te
                        data = page.evaluate("""
                            () => {
                                const result = {
                                    title: '',
                                    price: '',
                                    year: '',
                                    km: '',
                                    description: '',
                                    city: '',
                                    image_url: ''
                                };
                                
                                // TÍTULO: ler do script #__NEXT_DATA__ -> deal (vários caminhos no mobile)
                                let nextDataTitle = '';
                                try {
                                    const el = document.getElementById('__NEXT_DATA__');
                                    if (el && el.textContent) {
                                        const next = JSON.parse(el.textContent);
                                        const pp = next && next.props && next.props.pageProps;
                                        const deal = (pp && pp.deal) || (pp && pp.initialState && pp.initialState.deal) ||
                                                    (pp && pp.dealDetails && pp.dealDetails.deal) || (pp && pp.props && pp.props.deal) || null;
                                        if (deal) {
                                            const parts = [deal.makeName, deal.modelName, deal.trimName].filter(Boolean).map(s => (s + '').trim());
                                            nextDataTitle = parts.join(' ').trim();
                                        }
                                    }
                                } catch (e) {}
                                if (nextDataTitle && nextDataTitle.length > 5) result.title = nextDataTitle;
                                if (!result.title || result.title.length < 5) {
                                    const h1 = document.querySelector('h1');
                                    if (h1) {
                                        const h2 = h1.nextElementSibling && h1.nextElementSibling.tagName === 'H2' ? h1.nextElementSibling.textContent.trim() : '';
                                        result.title = (h1.textContent.trim() + (h2 ? ' ' + h2 : '')).trim();
                                    }
                                }
                                if (!result.title || result.title.length < 5) {
                                    const metaTitle = document.querySelector('meta[property="og:title"]');
                                    const ogTitle = metaTitle ? (metaTitle.getAttribute('content') || '').trim() : '';
                                    if (ogTitle && ogTitle.length > 10) {
                                        result.title = ogTitle.replace(/\\s*-\\s*Mobiauto\\s*-\\s*\\d+.*$/i, '').trim();
                                    }
                                }
                                if (!result.title) {
                                    const titleTag = document.querySelector('title');
                                    if (titleTag) result.title = titleTag.textContent.trim().replace(/\\s*-\\s*Mobiauto.*$/i, '').trim();
                                }
                                function looksLikeCssGarbage(s) {
                                    if (!s) return false;
                                    const t = (s + '').trim();
                                    if (t.startsWith('.css-') || t.indexOf('{') >= 0 || t.indexOf('}') >= 0) return true;
                                    if (t.indexOf('text-transform') >= 0 || t.indexOf('font-weight') >= 0) return true;
                                    return false;
                                }
                                if (looksLikeCssGarbage(result.title)) result.title = '';
                                
                                // Preço (data-analytic-id="details-vehicle-price" ou css-1rb9omp)
                                const priceEl = document.querySelector('[data-analytic-id="details-vehicle-price"]') ||
                                                document.querySelector('.css-1rb9omp') ||
                                                document.querySelector('[class*="price"]');
                                if (priceEl) result.price = priceEl.textContent.trim();
                                
                                // Ano (procurar div com label "Ano" seguido de valor)
                                const anoSection = Array.from(document.querySelectorAll('p, div')).find(el => {
                                    const text = el.textContent || '';
                                    return text.includes('Ano') && el.nextElementSibling;
                                });
                                if (anoSection) {
                                    const anoValue = anoSection.nextElementSibling || 
                                                    anoSection.parentElement?.querySelector('.css-fwo2te');
                                    if (anoValue) result.year = anoValue.textContent.trim();
                                }
                                
                                // KM: 1) __NEXT_DATA__ -> deal (vários caminhos), 2) deal.comments, 3) DOM
                                try {
                                    const el = document.getElementById('__NEXT_DATA__');
                                    if (el && el.textContent) {
                                        const next = JSON.parse(el.textContent);
                                        const pp = next && next.props && next.props.pageProps;
                                        const deal = (pp && pp.deal) || (pp && pp.initialState && pp.initialState.deal) ||
                                                    (pp && pp.dealDetails && pp.dealDetails.deal) || (pp && pp.props && pp.props.deal) || null;
                                        if (deal && deal.km != null && deal.km !== '') {
                                            result.km = String(deal.km);
                                        }
                                        if (!result.km && deal && deal.comments) {
                                            const c = String(deal.comments);
                                            const m = c.match(/\\bKM\\s*[:\\-]?\\s*([\\d.]{3,})\\b/i);
                                            if (m) result.km = m[1];
                                        }
                                    }
                                } catch (e) {}
                                if (!result.km) {
                                    const kmSection = Array.from(document.querySelectorAll('p')).find(el => {
                                        const text = (el.textContent || '').trim();
                                        return text === 'KM' && el.nextElementSibling;
                                    });
                                    if (kmSection) {
                                        const kmValue = kmSection.nextElementSibling || kmSection.parentElement?.querySelector('.css-fwo2te');
                                        if (kmValue) result.km = kmValue.textContent.trim();
                                    }
                                }
                                
                                // Cidade: 1) JSON-LD (estável), 2) window.__INITIAL_STATE__/__NEXT_DATA__, 3) DOM
                                function isValidCity(s) {
                                    if (!s || typeof s !== 'string' || s.length < 1 || s.length > 150) return false;
                                    const t = s.trim();
                                    if (t.startsWith('{') || t.indexOf('pageProps') >= 0 || t.indexOf('"props"') >= 0) return false;
                                    if (t.indexOf('vtp') >= 0 && t.indexOf('CAR') >= 0) return false;
                                    return true;
                                }
                                // 1) JSON-LD: <script type="application/ld+json"> → Vehicle.offers.availableAtOrFrom.address
                                const ldScripts = document.querySelectorAll('script[type="application/ld+json"]');
                                for (const script of ldScripts) {
                                    try {
                                        const content = (script.textContent || '').trim();
                                        if (content.indexOf('addressLocality') === -1) continue;
                                        const data = JSON.parse(content);
                                        const items = Array.isArray(data) ? data : [data];
                                        for (const item of items) {
                                            const offers = item.offers;
                                            const atOrFrom = offers && (offers.availableAtOrFrom || (Array.isArray(offers) ? offers[0] : null));
                                            const addr = atOrFrom && (atOrFrom.address || (atOrFrom.addressLocality ? atOrFrom : null));
                                            if (!addr) continue;
                                            const loc = (addr.addressLocality || '').trim();
                                            const reg = (addr.addressRegion || '').trim();
                                            if (loc && isValidCity(loc)) {
                                                result.city = reg ? (loc + ' - ' + reg) : loc;
                                                break;
                                            }
                                        }
                                        if (result.city) break;
                                    } catch (e) {}
                                }
                                // 2) Estado global JS (Mobiauto: __INITIAL_STATE__ ou __NEXT_DATA__)
                                if (!result.city) {
                                    try {
                                        const state = window.__INITIAL_STATE__ || (window.__NEXT_DATA__ && window.__NEXT_DATA__.props && window.__NEXT_DATA__.props.pageProps);
                                        const addr = state && (state.listing && state.listing.seller && state.listing.seller.address) ||
                                                     (state && state.seller && state.seller.address) ||
                                                     (state && state.address);
                                        if (addr && addr.city) {
                                            const loc = (addr.city || '').trim();
                                            const reg = (addr.state || addr.region || addr.addressRegion || '').trim();
                                            if (loc && isValidCity(loc)) result.city = reg ? (loc + ' - ' + reg) : loc;
                                        }
                                    } catch (e) {}
                                }
                                // 3) Fallback DOM (label "Cidade" ou .location-text)
                                if (!result.city) {
                                    const citySection = Array.from(document.querySelectorAll('p')).find(el => {
                                        const text = (el.textContent || '').trim();
                                        return text === 'Cidade' && el.nextElementSibling;
                                    });
                                    if (citySection) {
                                        const cityValue = citySection.nextElementSibling || citySection.parentElement?.querySelector('.css-fwo2te');
                                        if (cityValue) {
                                            const raw = (cityValue.innerText || cityValue.textContent || '').trim();
                                            if (isValidCity(raw)) result.city = raw;
                                        }
                                    }
                                }
                                if (!result.city) {
                                    const locationEl = document.querySelector('.location-text span');
                                    if (locationEl) {
                                        const raw = (locationEl.innerText || locationEl.textContent || '').trim();
                                        if (isValidCity(raw)) result.city = raw;
                                    }
                                }
                                
                                // Descrição (pode estar em várias tags)
                                const descEl = document.querySelector('[class*="description"]') ||
                                               document.querySelector('p');
                                if (descEl) result.description = descEl.textContent.trim();
                                
                                // Imagem principal
                                const imgEl = document.querySelector('[class*="carousel"] img') ||
                                            document.querySelector('.deal-card img') ||
                                            document.querySelector('img[alt*="carro"]');
                                if (imgEl) result.image_url = imgEl.src || imgEl.getAttribute('data-src') || '';
                                
                                return result;
                            }
                        """)
                        
                        # KM: ler do DOM <script id="__NEXT_DATA__"> (window.__NEXT_DATA__ pode não existir)
                        km = None
                        try:
                            km_text = page.evaluate("""
                            () => {
                                try {
                                    const el = document.getElementById("__NEXT_DATA__");
                                    if (!el || !el.textContent) return "";
                                    const json = JSON.parse(el.textContent);
                                    const deal = json && json.props && json.props.pageProps && json.props.pageProps.deal;
                                    const km = deal && deal.km;
                                    return (km === undefined || km === null) ? "" : String(km);
                                } catch (e) { return ""; }
                            }
                            """)
                            if km_text:
                                km_text = (km_text or "").strip()
                                if km_text.isdigit():
                                    km = int(km_text)
                                else:
                                    digits = "".join(c for c in km_text if c.isdigit())
                                    if digits.isdigit():
                                        km = int(digits)
                        except Exception:
                            pass
                        # Processar dados extraídos
                        title = data.get('title', '').strip()
                        price_text = data.get('price', '').strip()
                        year_text = data.get('year', '').strip()
                        description = data.get('description', '').strip()
                        city = data.get('city', '').strip()
                        image_url = data.get('image_url', '').strip()
                        
                        # Não usar título/descrição/cidade que sejam JSON (ex.: pageProps/__NEXT_DATA__)
                        def _is_json_like(s):
                            if not s:
                                return False
                            s = (s or "").strip()
                            if len(s) >= 10 and (s.startswith('{') or '"pageProps"' in s or '"props"' in s):
                                return True
                            return False
                        if _is_json_like(title):
                            title = ""
                        if _is_json_like(description):
                            description = ""
                        if _is_json_like(city):
                            city = ""
                        # Fallback cidade: extrair da URL (ex.: .../mg-montes-claros/... → "Montes Claros - MG")
                        if not city or _is_json_like(city):
                            from_url = _city_from_url(link)
                            if from_url:
                                city = from_url
                        
                        # Extrair valores numéricos
                        price = extract_price(price_text or title or description)
                        year = extract_year(year_text or title or description)
                        
                        if not title:
                            page_title = (page.title() or "").strip()
                            if page_title and not _is_json_like(page_title):
                                title = page_title[:200]
                            if not title:
                                title = "Anúncio Mobiauto"
                        _log("[DEBUG-MA] title=%s km=%s url=%s" % ((title or "")[:60], km, link[:70]))
                        
                        if not title:
                            # Tentar extrair do título da página
                            title = page.title() or ""
                        
                        if not price:
                            _log("Scan: aviso - sem preço em %s" % link[:50])
                        
                        listing = {
                            "url": link,
                            "title": title,
                            "price": price,
                            "year": year,
                            "km": km,
                            "description": description,
                            "city": city,
                            "image_url": image_url,
                            "source": "mobiauto",
                            "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                        
                        # Salvar em cache
                        try:
                            cache_dir.mkdir(parents=True, exist_ok=True)
                            with open(cache_file, 'w', encoding='utf-8') as f:
                                json.dump(listing, f, indent=2, ensure_ascii=False)
                        except Exception:
                            pass
                        
                        listings.append(listing)
                        
                        if listing_queue:
                            listing_queue.put(listing)
                        
                        _log("Scan: OK - %s" % link[:50])
                        
                        time.sleep(1)  # Delay entre requisições
                        
                    except Exception as e:
                        errors_count += 1
                        error_str = str(e).lower()
                        
                        # Log detalhado do tipo de erro
                        if "504" in error_str or "cloudfront" in error_str:
                            _log("❌ Scan Mobiauto: erro 504 CloudFront em %s - servidor sobrecarregado" % link[:50])
                        elif "502" in error_str or "503" in error_str:
                            _log("❌ Scan Mobiauto: erro %s em %s - servidor temporariamente indisponível" % (error_str[:10], link[:50]))
                        elif "timeout" in error_str or "timed_out" in error_str:
                            _log("❌ Scan Mobiauto: timeout em %s - conexão lenta ou servidor não respondeu" % link[:50])
                        elif "net::" in error_str or "network" in error_str:
                            _log("❌ Scan Mobiauto: erro de rede em %s - problema de conexão" % link[:50])
                        else:
                            _log("❌ Scan Mobiauto: erro em %s - %s" % (link[:50], str(e)[:200]))
                        
                        continue  # Continuar com próximo anúncio
                
    except Exception as e:
        _log("Scan: erro geral - %s" % e)
        import traceback
        traceback.print_exc()
    finally:
        if not reuse_browser:
            if not use_cdp and browser:
                try:
                    browser.close()
                    _kill_chrome_processes_orphaned()
                except Exception:
                    pass
            if p_ctx is not None:
                try:
                    p_ctx.__exit__(None, None, None)
                except Exception:
                    pass
    
    # Salvar lista completa
    try:
        out_file = out_dir / "listings_mobiauto.json"
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(listings, f, indent=2, ensure_ascii=False)
        _log("Scan: %s anúncios salvos em %s" % (len(listings), out_file))
    except Exception as e:
        _log("Scan: erro ao salvar lista - %s" % e)
    
    _log("Scan: concluído (OK=%s, erros=%s)" % (len(listings), errors_count))
    return (listings, errors_count)
