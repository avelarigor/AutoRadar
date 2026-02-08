#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scan de Anúncios da OLX
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
from urllib.parse import urlparse
from typing import List, Dict, Any, Callable, Optional

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent

# Chrome existente (igual ao Facebook)
CDP_URL = "http://127.0.0.1:9222"

# User-Agent mobile para forçar versão mobile
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


def _log(msg):
    """Log simples para debug."""
    try:
        from log_config import get_logger
        get_logger().info(msg)
    except Exception:
        print(f"[OLX Scan] {msg}")


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
    """Extrai preço do texto (formato R$ X.XXX ou R$ XXXX)."""
    if not text:
        return None
    # Padrão: R$ seguido de número (pode ter ponto de milhar)
    patterns = [
        r'R\$\s*(\d[\d.]*)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text.replace(' ', ''))
        if match:
            try:
                price_str = match.group(1).replace('.', '')
                return float(price_str)
            except (ValueError, AttributeError):
                continue
    return None


def extract_year(text: str) -> Optional[int]:
    """Extrai ano do texto (4 dígitos entre 1900-2099)."""
    if not text:
        return None
    match = re.search(r'\b(19|20)\d{2}\b', text)
    if match:
        try:
            year = int(match.group())
            if 1900 <= year <= 2099:
                return year
        except (ValueError, AttributeError):
            pass
    return None


def extract_km(text: str) -> Optional[int]:
    """Extrai quilometragem do texto (número seguido opcionalmente de 'km')."""
    if not text:
        return None
    # Padrão: número (pode ter ponto de milhar) seguido opcionalmente de 'km'
    patterns = [
        r'(\d[\d.]*)\s*km',
        r'(\d[\d.]*)\s*Km',
        r'(\d[\d.]*)\s*KM',
        r'(\d[\d.]*)',  # Apenas número (OLX pode não ter "km")
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                km_str = match.group(1).replace('.', '')
                km_val = int(km_str)
                if 0 <= km_val <= 10000000:  # Valores razoáveis
                    return km_val
            except (ValueError, AttributeError):
                continue
    return None


def scan_listings(
    links: List[str],
    progress_callback: Optional[Callable[[int, int], None]] = None,
    listing_queue: Optional[Any] = None,
    browser: Optional[Any] = None,
) -> tuple:
    """
    Escaneia anúncios da OLX. Retorna (listings, erros_count).
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
    print(f"📊 Escaneando {len(links)} anúncios da OLX...")
    _log("Scan OLX: iniciando %s anúncios" % len(links))

    reuse_browser = browser is not None
    p_ctx = None
    if reuse_browser:
        # Usar contexto existente ou criar novo com User-Agent mobile
        if browser.contexts:
            context = browser.contexts[0]
        else:
            context = browser.new_context(
                user_agent=MOBILE_USER_AGENT,
                viewport=MOBILE_VIEWPORT,
                locale="pt_BR",
                extra_http_headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                }
            )
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
            print("📌 OLX: usando Chrome existente (porta 9222)")
        except Exception:
            try:
                if _launch_chrome_with_debug_port():
                    time.sleep(5)
                    browser = p.chromium.connect_over_cdp(CDP_URL)
                    use_cdp = True
                    print("📌 OLX: conectado ao Chrome (porta 9222)")
            except Exception:
                pass
            if browser is None:
                print("📌 OLX: usando janela minimizada")
                browser = p.chromium.launch(
                    headless=False,
                    args=[
                        f"--user-data-dir={BASE_DIR / 'chrome_login_profile'}",
                        "--start-minimized",
                        "--window-size=1280,800",
                    ]
                )
        if use_cdp:
            if browser.contexts:
                context = browser.contexts[0]
            else:
                context = browser.new_context(
                    user_agent=MOBILE_USER_AGENT,
                    viewport=MOBILE_VIEWPORT,
                    locale="pt_BR",
                    extra_http_headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                        "Accept-Encoding": "gzip, deflate, br",
                        "DNT": "1",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1",
                    }
                )
            page = context.pages[0] if context.pages else context.new_page()
            _speed_routes(page, block_images=True)
        else:
            context = browser.new_context(
                user_agent=MOBILE_USER_AGENT,
                viewport=MOBILE_VIEWPORT,
                locale="pt_BR",
                extra_http_headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                }
            )
            page = context.new_page()
            _speed_routes(page, block_images=True)

    try:
        for idx, link in enumerate(links, 1):
            if progress_callback:
                progress_callback(idx, len(links))
            
            cache_key = hashlib.md5(link.encode()).hexdigest()
            cache_file = cache_dir / f"olx_{cache_key}.json"
            cache_days = _scan_cache_days()
            # Verificar cache (só válido se último scan dentro de scan_cache_days)
            if cache_file.exists():
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        cached = json.load(f)
                        if _is_cache_valid(cache_file, cached, cache_days):
                            listings.append(cached)
                            if listing_queue is not None:
                                listing_queue.put(cached)
                            _log("Scan: cache hit - %s" % link[:50])
                            continue
                except Exception:
                    pass
            
            try:
                # Acessar página com timeout maior
                try:
                    response = page.goto(link, wait_until="domcontentloaded", timeout=90000)
                    if response and response.status >= 400:
                        _log("Scan: erro HTTP %d em %s" % (response.status, link[:50]))
                        errors_count += 1
                        continue
                except Exception as goto_error:
                    error_str = str(goto_error).lower()
                    if "timeout" in error_str:
                        _log("Scan: timeout em %s - tentando load..." % link[:50])
                        try:
                            page.goto(link, wait_until="load", timeout=60000)
                        except Exception:
                            errors_count += 1
                            continue
                    else:
                        errors_count += 1
                        continue
                
                # Aguardar JavaScript carregar
                time.sleep(3)
                
                # URL final (após possíveis redirects); usar só se for ainda página de anúncio
                try:
                    final_url = page.url()
                    if final_url and re.search(r'-\d+$', urlparse(final_url).path.rstrip('/').split('/')[-1] if urlparse(final_url).path else ''):
                        link = final_url.split('?')[0].strip()
                    # senão mantém o link solicitado (evita salvar URL da página principal)
                except Exception:
                    pass
                
                # Extrair dados da página usando JavaScript
                # Prioridade: seção "Detalhes" (Modelo = melhor para FIPE; todos os opcionais para Telegram)
                data = page.evaluate("""
                    () => {
                        const result = {
                            title: '',
                            price: '',
                            year: '',
                            km: '',
                            description: '',
                            city: '',
                            state: '',
                            image_url: '',
                            detalhes: {}
                        };
                        
                        // 0. SEÇÃO DETALHES — todos os pares label/valor (Modelo, Marca, Ano, Quilometragem, Câmbio, etc.)
                        const detailsSection = document.querySelector('#details') || 
                            Array.from(document.querySelectorAll('[class*="ad__sc-1l883pa"]')).find(el => 
                                el.textContent.indexOf('Detalhes') >= 0 && el.querySelector('[class*="ad__sc-2h9gkk"]')
                            );
                        const container = detailsSection ? (detailsSection.querySelector && detailsSection.querySelector('[class*="ad__sc-wuor06"]') || detailsSection) : null;
                        const items = container ? Array.from(container.querySelectorAll('div[class*="ad__sc-2h9gkk-0"]')) : [];
                        for (const item of items) {
                            const labelEl = item.querySelector('span.typo-overline');
                            const valueEl = item.querySelector('a[class*="ad__sc-2h9gkk-3"]') || 
                                             Array.from(item.querySelectorAll('span')).find(s => !s.classList.contains('typo-overline') && (s.textContent || '').trim().length > 0);
                            if (labelEl && valueEl) {
                                const label = (labelEl.textContent || '').trim();
                                const value = (valueEl.textContent || '').trim();
                                if (label && value) result.detalhes[label] = value;
                            }
                        }
                        
                        // 1. TÍTULO — 1) JSON-LD Product.name/model (estável), 2) Detalhes.Modelo, 3) h1, 4) og:title/document.title
                        const genericTitles = ['Carros Usados e Novos', 'Compre e venda', 'O Maior Site', 'OLX - O Maior Site'];
                        function isValidTitle(s) {
                            if (!s || typeof s !== 'string') return false;
                            const t = s.trim();
                            if (t.length <= 2) return false;
                            return !genericTitles.some(g => t.indexOf(g) >= 0);
                        }
                        // 1) JSON-LD: <script type="application/ld+json"> → @type Product → name ou model
                        const ldScripts = document.querySelectorAll('script[type="application/ld+json"]');
                        for (const script of ldScripts) {
                            try {
                                const content = (script.textContent || '').trim();
                                if (content.indexOf('"@type"') === -1 || (content.indexOf('Product') === -1 && content.indexOf('product') === -1)) continue;
                                const data = JSON.parse(content);
                                const items = Array.isArray(data) ? data : [data];
                                for (const item of items) {
                                    if ((item['@type'] || '').toLowerCase() !== 'product') continue;
                                    const name = (item.name || item.model || '').trim();
                                    if (name && isValidTitle(name)) {
                                        result.title = name;
                                        break;
                                    }
                                }
                                if (result.title) break;
                            } catch (e) {}
                        }
                        // 2) Seção Detalhes — Modelo
                        if (!result.title && result.detalhes['Modelo'] && result.detalhes['Modelo'].length > 2 && isValidTitle(result.detalhes['Modelo'])) {
                            result.title = result.detalhes['Modelo'];
                        }
                        // 3) Fallback h1 (título visual da página)
                        if (!result.title) {
                            const h1 = document.querySelector('h1[data-testid="ad-title"]') || document.querySelector('h1');
                            if (h1) {
                                const h1Text = (h1.textContent || '').trim();
                                if (h1Text && isValidTitle(h1Text)) result.title = h1Text;
                            }
                        }
                        // 4) og:title / document.title
                        if (!result.title) {
                            const metaTitle = document.querySelector('meta[property="og:title"]');
                            const ogTitle = metaTitle ? (metaTitle.getAttribute('content') || '').trim() : '';
                            const pageTitle = (document.title || '').replace(/\\s*-\\s*\\d+\\s*\\|\\s*OLX.*$/i, '').trim();
                            if (ogTitle && isValidTitle(ogTitle)) result.title = ogTitle;
                            else if (pageTitle && isValidTitle(pageTitle)) result.title = pageTitle;
                        }
                        // Nunca deixar título como "Descrição" (label de seção)
                        if (!result.title || (result.title.trim() === 'Descrição') || result.title.trim().length <= 2) {
                            const og = document.querySelector('meta[property="og:title"]');
                            const ogVal = og ? (og.getAttribute('content') || '').trim() : '';
                            if (ogVal && ogVal.length > 5) result.title = ogVal;
                            else result.title = (document.title || '').replace(/\\s*-\\s*\\d+\\s*\\|\\s*OLX.*$/i, '').trim() || result.title;
                        }
                        
                        // 2. PREÇO
                        let priceEl = document.querySelector('#price-box-container span.typo-title-large') ||
                                     document.querySelector('span.typo-title-large');
                        if (priceEl) result.price = priceEl.textContent.trim();
                        else {
                            const bodyText = document.body.textContent || '';
                            const priceMatch = bodyText.match(/R\\$\\s*([\\d\\.]+)/);
                            if (priceMatch) result.price = 'R$ ' + priceMatch[1];
                        }
                        
                        // 3. ANO — Detalhes primeiro
                        result.year = result.detalhes['Ano'] || '';
                        if (!result.year) {
                            const anoLabel = Array.from(document.querySelectorAll('span')).find(el => 
                                el.textContent.trim() === 'Ano' && el.classList.contains('typo-overline'));
                            if (anoLabel) {
                                const anoContainer = anoLabel.closest('div[class*="ad__sc-2h9gkk"]');
                                if (anoContainer) {
                                    const anoLink = anoContainer.querySelector('a');
                                    if (anoLink) result.year = anoLink.textContent.trim();
                                }
                            }
                        }
                        if (!result.year && result.title) {
                            const yearMatch = result.title.match(/\\b(19|20)\\d{2}\\b/);
                            if (yearMatch) result.year = yearMatch[0];
                        }
                        
                        // 4. QUILOMETRAGEM — Detalhes primeiro
                        result.km = result.detalhes['Quilometragem'] || '';
                        if (!result.km) {
                            const kmLabel = Array.from(document.querySelectorAll('span')).find(el => 
                                el.textContent.trim() === 'Quilometragem' && el.classList.contains('typo-overline'));
                            if (kmLabel) {
                                const kmContainer = kmLabel.closest('div[class*="ad__sc-2h9gkk"]');
                                if (kmContainer) {
                                    const kmSpan = kmContainer.querySelector('span:not(.typo-overline)');
                                    if (kmSpan) result.km = kmSpan.textContent.trim();
                                }
                            }
                        }
                        if (!result.km) {
                            const bodyText = document.body.textContent || '';
                            const kmMatch = bodyText.match(/(\\d[\\.\\d]*)\\s*km/i);
                            if (kmMatch) result.km = kmMatch[1];
                        }
                        
                        // 5. CIDADE/ESTADO
                        const cityEl = Array.from(document.querySelectorAll('span.typo-body-small.font-semibold.text-neutral-110')).find(el => {
                            const text = el.textContent.trim();
                            return text.includes(',') && (text.includes('MG') || text.includes('Minas'));
                        });
                        if (cityEl) {
                            const locationText = cityEl.textContent.trim();
                            const parts = locationText.split(',').map(p => p.trim());
                            if (parts.length >= 2) {
                                result.city = parts[0];
                                result.state = parts[1].split(' ')[0];
                            }
                        }
                        
                        // 6. FOTO PRINCIPAL
                        const ogImage = document.querySelector('meta[property="og:image"]');
                        if (ogImage) result.image_url = ogImage.getAttribute('content') || '';
                        else {
                            const imgEl = document.querySelector('img[src*="img.olx.com.br/images"]') ||
                                         document.querySelector('img[fetchpriority="high"]') ||
                                         document.querySelector('img[data-display="single"]');
                            if (imgEl) result.image_url = imgEl.src || imgEl.getAttribute('data-src') || '';
                        }
                        
                        // 7. DESCRIÇÃO
                        let descEl = document.querySelector('div[data-section="description"] span.typo-body-medium') ||
                                     document.querySelector('div.ad__sc-2mjlki-0.iAOKgI span.typo-body-medium');
                        if (descEl) {
                            result.description = descEl.textContent.trim().replace(/\\(\\d+\\)\\.\\.\\.\\s*ver\\s*n[úu]mero/gi, '').trim();
                        } else {
                            const metaDesc = document.querySelector('meta[property="og:description"]');
                            if (metaDesc) result.description = metaDesc.getAttribute('content') || '';
                        }
                        
                        return result;
                    }
                """)
                
                # Processar dados extraídos
                detalhes = data.get('detalhes') or {}
                title = data.get('title', '').strip()
                price_text = data.get('price', '').strip()
                year_text = data.get('year', '').strip() or detalhes.get('Ano', '')
                km_text = data.get('km', '').strip() or detalhes.get('Quilometragem', '')
                description = data.get('description', '').strip()
                city = data.get('city', '').strip()
                state = data.get('state', '').strip()
                image_url = data.get('image_url', '').strip()
                
                # Extrair valores numéricos
                price = extract_price(price_text or title or description)
                year = extract_year(year_text or title or description or link)
                km = extract_km(km_text or description)
                
                # Se não conseguiu ano do seletor, tentar extrair da URL
                if not year:
                    url_match = re.search(r'-(\d{4})-\d+$', link)
                    if url_match:
                        try:
                            year = int(url_match.group(1))
                        except (ValueError, AttributeError):
                            pass
                
                # Detectar se caímos na página de listagem (título genérico) — não cachear
                _is_list_page = any(
                    x in (title or "")
                    for x in (
                        "Carros Usados e Novos",
                        "Compre e venda perto",
                        "O Maior Site de Compra e Venda do Brasil",
                        "OLX - O Maior Site",
                    )
                )
                if _is_list_page:
                    title = title or "Anúncio OLX"
                    _log("Scan: página de listagem detectada (título genérico) - %s" % link[:50])
                
                if not title:
                    title = "Anúncio OLX"
                # Se o título veio como "Descrição" (label da seção), usar Detalhes ou slug da URL
                if (title or "").strip().lower() == "descrição" or (len((title or "").strip()) <= 2):
                    _marca = (detalhes.get("Marca") or "").strip()
                    _modelo = (detalhes.get("Modelo") or "").strip()
                    if _marca or _modelo:
                        title = ("%s %s" % (_marca, _modelo)).strip() or title
                    if (title or "").strip().lower() == "descrição" or not (title or "").strip():
                        # Fallback: slug da URL (ex.: fiat-punto-attractive-...)
                        slug = (link.rstrip("/").split("/")[-1] or "").split("?")[0]
                        if slug and "-" in slug:
                            title = slug.replace("-", " ").rsplit(" ", 1)[0][:80] if slug.replace("-", " ").rsplit(" ", 1) else slug.replace("-", " ")[:80]
                        if not (title or "").strip():
                            title = "Anúncio OLX"
                
                if not price:
                    _log("Scan: aviso - sem preço em %s" % link[:50])
                
                # Mapear campos da seção Detalhes para o listing (opcionais para Telegram)
                def _d(key):
                    return (detalhes.get(key) or '').strip()
                listing = {
                    "url": link,
                    "title": title,
                    "price": price,
                    "price_display": price_text if price_text else (f"R$ {price:,.0f}" if price else ""),
                    "year": year,
                    "km": km,
                    "city": city,
                    "state": state,
                    "description": description[:500] if description else "",
                    "main_photo_url": image_url,
                    "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "currency": "BRL",
                    "source": "olx",
                    # Opcionais da seção Detalhes (Telegram + FIPE)
                    "categoria": _d("Categoria") or None,
                    "marca": _d("Marca") or None,
                    "tipo_veiculo": _d("Tipo de veículo") or None,
                    "cambio": _d("Câmbio") or None,
                    "combustivel": _d("Combustível") or None,
                    "cor_externa": _d("Cor") or None,
                    "potencia_motor": _d("Potência do motor") or None,
                    "detalhes": {k: v for k, v in detalhes.items() if v} if detalhes else None,
                }
                
                listings.append(listing)
                
                if listing_queue is not None:
                    listing_queue.put(listing)
                
                # Salvar cache apenas se for página de anúncio (não listagem)
                if not _is_list_page:
                    try:
                        with open(cache_file, 'w', encoding='utf-8') as f:
                            json.dump(listing, f, indent=2, ensure_ascii=False)
                    except Exception:
                        pass
                
                _log("Scan: OK - %s" % link[:50])
                
                # Delay conservador entre requisições (5-10s)
                delay = 7
                time.sleep(delay)
                
            except Exception as e:
                errors_count += 1
                error_str = str(e).lower()
                
                # Log detalhado do tipo de erro
                if "504" in error_str or "502" in error_str or "503" in error_str:
                    _log("❌ Scan OLX: erro HTTP em %s - servidor temporariamente indisponível" % link[:50])
                elif "timeout" in error_str or "timed_out" in error_str:
                    _log("❌ Scan OLX: timeout em %s - conexão lenta ou servidor não respondeu" % link[:50])
                elif "net::" in error_str or "network" in error_str:
                    _log("❌ Scan OLX: erro de rede em %s - problema de conexão" % link[:50])
                else:
                    _log("❌ Scan OLX: erro em %s - %s" % (link[:50], str(e)[:200]))
                
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
        out_file = out_dir / "listings_olx.json"
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(listings, f, indent=2, ensure_ascii=False)
        print(f"✅ {len(listings)} anúncios salvos em {out_file}")
        _log("Scan OLX: concluído. OK=%s, erros=%s" % (len(listings), errors_count))
    except Exception as e:
        print(f"❌ Erro ao salvar: {e}")
        _log("Scan OLX: erro ao salvar - %s" % e)
    
    return (listings, errors_count)
