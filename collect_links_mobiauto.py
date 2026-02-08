#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coleta de Links da Mobiauto
Extrai links de anúncios da página de busca da Mobiauto.
Created by Igor Avelar - avelar.igor@gmail.com
"""

import sys
import json
import re
import time
import subprocess
import os
from pathlib import Path
from typing import List, Callable, Optional, Any
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent

# Link padrão para Montes Claros/MG
DEFAULT_MOBIAUTO_URL = "https://www.mobiauto.com.br/comprar/carros-usados/mg-montes-claros"

# Chrome existente (igual ao Facebook) — quando disponível usa a mesma sessão
CDP_URL = "http://127.0.0.1:9222"

# User-Agent e viewport mobile (evitar bloqueio / layout desktop)
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)
MOBILE_VIEWPORT = {"width": 375, "height": 667}


def _speed_routes(page, block_images=True):
    """Bloqueia image/media/font para acelerar coleta."""
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
        print(f"[Mobiauto] {msg}")


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
    # Desativado: este método estava encerrando instâncias do Chrome usadas por outros módulos.
    return


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


def _minimize_browser_window_win():
    """No Windows: tenta minimizar a janela do navegador."""
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
                    if "chrome" in title or "chromium" in title:
                        found.append(hwnd)

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(EnumWindowsProc(enum_cb), 0)
        for hwnd in found:
            try:
                user32.ShowWindow(hwnd, SW_MINIMIZE)
            except Exception:
                pass
    except Exception:
        pass


def parse_mobiauto_url(search_url: str) -> dict:
    """
    Parseia o link da Mobiauto e extrai componentes para construir URLs de busca.
    Retorna dict com: base_url, path, query_params, page_param_name
    """
    if not search_url or not search_url.strip():
        search_url = DEFAULT_MOBIAUTO_URL
        _log("Coleta: usando URL padrão (Montes Claros/MG)")
    
    try:
        parsed = urlparse(search_url)
        query_params = parse_qs(parsed.query)
        
        # Remover page=1 do link original (vamos variar isso)
        if 'page' in query_params:
            del query_params['page']
        
        # Construir base URL sem page
        base_query = urlencode(query_params, doseq=True)
        base_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            base_query,
            parsed.fragment
        ))
        
        # Mobiauto usa ?page=X no final
        return {
            "base_url": base_url,
            "path": parsed.path,
            "query_params": query_params,
            "full_url_template": base_url + ("&" if base_query else "?") + "page={page}"
        }
    except Exception as e:
        _log("Erro ao parsear URL da Mobiauto: %s" % e)
        # Fallback para URL padrão
        return parse_mobiauto_url(DEFAULT_MOBIAUTO_URL)


def collect_links(
    search_url: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    status_message_callback: Optional[Callable[[str], None]] = None,
    is_aborted_callback: Optional[Callable[[], bool]] = None,
    max_pages: int = 10,
    browser: Optional[Any] = None,
) -> List[str]:
    """
    Coleta links de anúncios da Mobiauto.
    browser: se informado, reutiliza (não fecha). Caso contrário abre/fecha Playwright.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        _log("Coleta: Playwright não instalado - %s" % e)
        print("❌ Playwright não instalado. Instale com: pip install playwright")
        return []

    url_info = parse_mobiauto_url(search_url)
    links = []
    seen_links = set()
    _log("Coleta: iniciando Mobiauto (URL base: %s)" % url_info["base_url"])
    if status_message_callback:
        status_message_callback("Coletando links da Mobiauto...")

    def _run_with_browser(browser_instance, close_browser_when_done: bool):
        context = browser_instance.new_context(
            viewport=MOBILE_VIEWPORT,
            user_agent=MOBILE_USER_AGENT,
            locale="pt_BR",
            device_scale_factor=1,
            is_mobile=True,
            has_touch=True,
        )
        page = context.new_page()
        _speed_routes(page, block_images=True)
        _log("Coleta Mobiauto: usando versão mobile (viewport %s)" % MOBILE_VIEWPORT)
        try:
            for page_num in range(1, max_pages + 1):
                if is_aborted_callback and is_aborted_callback():
                    _log("Coleta: cancelado pelo usuário")
                    break
                url = url_info["full_url_template"].format(page=page_num)
                _log("Coleta: página %d - %s" % (page_num, url))
                if status_message_callback:
                    status_message_callback("Coletando página %d/%d..." % (page_num, max_pages))
                try:
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    except Exception as goto_error:
                        error_str = str(goto_error).lower()
                        if "timeout" in error_str or "504" in error_str or "502" in error_str:
                            _log("Coleta Mobiauto: erro (%s). Tentando load..." % error_str[:80])
                            page.goto(url, wait_until="load", timeout=30000)
                        else:
                            raise
                    time.sleep(6)
                    try:
                        page.wait_for_selector('a[href*="/detalhes/"]', timeout=10000)
                    except Exception:
                        pass
                    time.sleep(2)
                    page_links = page.evaluate("""
                            () => {
                                const links = [];
                                const seen = new Set();
                                
                                // Buscar por cards de anúncios (deal-card)
                                const cards = document.querySelectorAll('.deal-card, [class*="deal-card"], [class*="css-nwi4ld"]');
                                
                                for (const card of cards) {
                                    // Procurar link dentro do card
                                    const linkEl = card.querySelector('a[href*="/comprar/carros/"][href*="/detalhes/"]') ||
                                                   card.querySelector('a[href*="/detalhes/"]');
                                    
                                    if (linkEl) {
                                        let href = linkEl.getAttribute('href');
                                        if (href) {
                                            // Normalizar URL
                                            if (!href.startsWith('http')) {
                                                href = 'https://www.mobiauto.com.br' + (href.startsWith('/') ? href : '/' + href);
                                            }
                                            
                                            // Garantir que é um link de anúncio válido
                                            if (href.includes('/comprar/carros/') && href.includes('/detalhes/') && !seen.has(href)) {
                                                seen.add(href);
                                                links.push(href);
                                            }
                                        }
                                    }
                                }
                                
                                // Fallback: buscar diretamente por links com padrão de anúncio
                                if (links.length === 0) {
                                    const allLinks = document.querySelectorAll('a[href*="/comprar/carros/"][href*="/detalhes/"]');
                                    for (const el of allLinks) {
                                        let href = el.getAttribute('href');
                                        if (href && !href.startsWith('http')) {
                                            href = 'https://www.mobiauto.com.br' + (href.startsWith('/') ? href : '/' + href);
                                        }
                                        if (href && !seen.has(href)) {
                                            seen.add(href);
                                            links.push(href);
                                        }
                                    }
                                }
                                
                                return links;
                            }
                    """)
                    if not page_links or len(page_links) == 0:
                        _log("Coleta: nenhum link encontrado na página %d. Parando." % page_num)
                        break
                    new_links = [link for link in page_links if link not in seen_links]
                    links.extend(new_links)
                    seen_links.update(new_links)
                    _log("Coleta: página %d - %d links novos (total: %d)" % (page_num, len(new_links), len(links)))
                    if progress_callback:
                        progress_callback(len(links), len(links))
                    if len(new_links) == 0:
                        _log("Coleta: nenhum link novo. Parando.")
                        break
                    time.sleep(2)
                except Exception as e:
                    error_str = str(e).lower()
                    _log("❌ Coleta Mobiauto: erro na página %d - %s" % (page_num, str(e)[:200]))
                    if "504" in error_str or "cloudfront" in error_str:
                        _log("⚠️ Erro 504 CloudFront: servidor sobrecarregado ou indisponível. Continuando pipeline sem Mobiauto.")
                    elif "502" in error_str or "503" in error_str:
                        _log("⚠️ Erro %s: servidor temporariamente indisponível. Continuando pipeline sem Mobiauto." % error_str[:10])
                    elif "timeout" in error_str or "timed_out" in error_str:
                        _log("⚠️ Timeout: conexão lenta ou servidor não respondeu. Continuando pipeline sem Mobiauto.")
                    elif "net::" in error_str or "network" in error_str:
                        _log("⚠️ Erro de rede: problema de conexão. Continuando pipeline sem Mobiauto.")
                    else:
                        _log("⚠️ Erro desconhecido. Continuando pipeline sem Mobiauto.")
                    break
            _minimize_browser_window_win()
                
        finally:
            try:
                context.close()
            except Exception:
                pass
            if close_browser_when_done:
                try:
                    browser_instance.close()
                except Exception:
                    pass

    try:
        if browser is not None:
            _run_with_browser(browser, False)
        else:
            with sync_playwright() as p:
                use_cdp = False
                browser = None
                try:
                    browser = p.chromium.connect_over_cdp(CDP_URL)
                    use_cdp = True
                    _log("Coleta: usando Chrome existente (porta 9222)")
                    print("📌 Usando Chrome existente (porta 9222)")
                except Exception:
                    try:
                        if _launch_chrome_with_debug_port():
                            time.sleep(5)
                            browser = p.chromium.connect_over_cdp(CDP_URL)
                            use_cdp = True
                            _log("Coleta: conectado ao Chrome (porta 9222)")
                            print("📌 Conectado ao Chrome (porta 9222)")
                    except Exception:
                        pass
                    if browser is None:
                        raise RuntimeError("collect_links_mobiauto.py: CDP indisponível e fallback Chromium desativado.")
                _run_with_browser(browser, True)
    except Exception as e:
        _log("Coleta: erro geral - %s" % e)
        import traceback
        traceback.print_exc()
    _log("Coleta: total de %d links coletados" % len(links))
    return links
