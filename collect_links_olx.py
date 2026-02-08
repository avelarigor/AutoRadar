#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coleta de Links da OLX
Extrai links de anúncios da página de busca da OLX (versão mobile forçada).
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

# URL padrão para Montes Claros/MG - mais recentes
DEFAULT_OLX_URL = "https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/estado-mg/regiao-de-montes-claros-e-diamantina/montes-claros?sf=1"

# Chrome existente (igual ao Facebook) — quando disponível usa a mesma sessão
CDP_URL = "http://127.0.0.1:9222"
# Segundo Chrome, só para coleta OLX em thread (evita Cloudflare vs Chromium; usa Chrome real via CDP)
CDP_PORT_OLX = 9223
CDP_URL_OLX = "http://127.0.0.1:%d" % CDP_PORT_OLX
OLX_CHROME_PROFILE = BASE_DIR / "chrome_login_profile_olx"

# User-Agent mobile para forçar versão mobile mesmo na URL desktop
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
        print(f"[OLX] {msg}")


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


def _launch_chrome_olx_cdp():
    """Abre Chrome real na porta 9223 para coleta OLX (thread isolada). Evita Chromium/Cloudflare."""
    chrome_path = _find_chrome()
    if not chrome_path:
        return False
    try:
        OLX_CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            [
                chrome_path,
                "--remote-debugging-port=%d" % CDP_PORT_OLX,
                "--user-data-dir=" + str(OLX_CHROME_PROFILE),
                "--start-minimized",
                "--window-size=1280,800",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        )
        return True
    except Exception:
        return False


def _kill_chrome_olx():
    """Encerra processos Chrome que usam o perfil OLX (porta 9223)."""
    if sys.platform != "win32":
        return
    try:
        profile_path = str(OLX_CHROME_PROFILE.resolve())
        ps_script = (
            "param($ProfilePath); "
            "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" -ErrorAction SilentlyContinue | "
            "Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($ProfilePath) -ge 0 } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script, "-ProfilePath", profile_path],
            capture_output=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        )
    except Exception:
        pass


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


def parse_olx_url(search_url: str) -> dict:
    """
    Parseia o link da OLX e extrai componentes para construir URLs de busca.
    Retorna dict com: base_url, page_param_name
    """
    if not search_url or not search_url.strip():
        search_url = DEFAULT_OLX_URL
        _log("Coleta: usando URL padrão (Montes Claros/MG)")
    
    try:
        parsed = urlparse(search_url)
        query_params = parse_qs(parsed.query)
        
        # OLX usa ?o=2 para segunda página, ?o=3 para terceira, etc.
        # Remover ?o= se existir
        if 'o' in query_params:
            del query_params['o']
        
        # Construir base URL sem parâmetro de página
        base_query = urlencode(query_params, doseq=True)
        base_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            base_query,
            parsed.fragment
        ))
        
        return {
            "base_url": base_url,
            "path": parsed.path,
            "query_params": query_params,
            "full_url_template": base_url + ("&" if base_query else "?") + "o={page}"
        }
    except Exception as e:
        _log("Erro ao parsear URL da OLX: %s" % e)
        # Fallback para URL padrão
        return parse_olx_url(DEFAULT_OLX_URL)


def _normalize_olx_url(url: str) -> Optional[str]:
    """
    Normaliza URL da OLX:
    - Remove query params (mantém host original: mg.olx.com.br ou www.olx.com.br).
      Preservar mg.olx.com.br evita redirecionamento para a página principal ao clicar no anúncio.
    - Retorna apenas URLs de anúncios individuais (com ID numérico no final do path).
    """
    if not url or not isinstance(url, str):
        return None
    
    # Não alterar o host (mg.olx.com.br deve ser mantido para o link abrir o anúncio correto)
    
    # Remover query params (manter apenas estrutura base)
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    
    # Verificar se é link de anúncio individual (tem ID numérico no final do path)
    # Padrão: /.../[modelo]-[ano]-[ID] onde ID é numérico
    path_parts = [p for p in parsed.path.split('/') if p]
    if len(path_parts) >= 3:
        # Último segmento deve terminar com número (ID do anúncio)
        last_part = path_parts[-1]
        # Verificar se termina com número (ex: fiat-punto-2014-1475512233)
        if re.search(r'-\d+$', last_part):
            return base_url
    
    return None


def collect_links(
    search_url: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    status_message_callback: Optional[Callable[[str], None]] = None,
    is_aborted_callback: Optional[Callable[[], bool]] = None,
    max_pages: int = 1,  # Apenas primeira página (padrão: ~105 anúncios)
    browser: Optional[Any] = None,
    own_browser_only: bool = False,
) -> List[str]:
    """
    Coleta links de anúncios da OLX.
    browser: se informado, reutiliza (não fecha). Caso contrário abre/fecha Playwright.
    own_browser_only: se True e browser for None, não tenta conectar ao CDP (porta 9222);
        abre sempre um Chromium próprio. Use True quando rodar em thread separada para evitar
        "Cannot switch to a different thread" e isolar bloqueios da OLX do resto do pipeline.
    
    Returns:
        Lista de URLs dos anúncios normalizadas (www.olx.com.br)
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        _log("Coleta: Playwright não instalado - %s" % e)
        print("❌ Playwright não instalado. Instale com: pip install playwright")
        return []

    url_info = parse_olx_url(search_url)
    links = []
    seen_links = set()
    
    _log("Coleta OLX: iniciando (URL base: %s, max_pages: %d)" % (url_info["base_url"], max_pages))
    
    if status_message_callback:
        status_message_callback("Coletando links da OLX...")
    
    def _run_with_browser(browser_instance, close_browser_when_done: bool):
        # Contexto MOBILE para forçar versão mobile mesmo na URL desktop
        context = browser_instance.new_context(
            viewport=MOBILE_VIEWPORT,
            user_agent=MOBILE_USER_AGENT,
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
        _log("Coleta OLX: usando User-Agent mobile para forçar versão mobile")
        try:
            # Coletar links de cada página
            for page_num in range(1, max_pages + 1):
                if is_aborted_callback and is_aborted_callback():
                    _log("Coleta: cancelado pelo usuário")
                    break
                
                url = url_info["full_url_template"].format(page=page_num)
                _log("Coleta: página %d - %s" % (page_num, url))
                if status_message_callback:
                    status_message_callback("Coletando página %d/%d da OLX..." % (page_num, max_pages))
                
                try:
                    # Acessar página
                    try:
                        response = page.goto(url, wait_until="domcontentloaded", timeout=90000)
                        if response:
                            status = response.status
                            _log("Coleta: status HTTP %d" % status)
                            if status >= 400:
                                _log("⚠️ Erro HTTP %d na página %d" % (status, page_num))
                                if status == 502 or status == 503:
                                    _log("Servidor temporariamente indisponível. Parando coleta.")
                                    break
                    except Exception as goto_error:
                        error_str = str(goto_error).lower()
                        if "504" in error_str or "502" in error_str or "503" in error_str or "timeout" in error_str:
                            _log("Coleta OLX: erro (%s). Tentando novamente..." % error_str[:80])
                            time.sleep(5)
                            try:
                                page.goto(url, wait_until="load", timeout=60000)
                            except Exception:
                                _log("Erro persistente. Parando coleta.")
                                break
                        else:
                            raise
                    
                    # Aguardar JavaScript carregar
                    time.sleep(5)
                    
                    # Scroll para carregar mais conteúdo (se necessário)
                    for i in range(3):
                        page.evaluate("window.scrollBy(0, 500)")
                        time.sleep(2)
                    
                    # Buscar links de anúncios individuais
                    # Padrão: links que terminam com ID numérico (ex: fiat-punto-2014-1475512233)
                    page_links = page.evaluate("""
                        () => {
                            const links = [];
                            const seen = new Set();
                            const allLinks = document.querySelectorAll('a[href]');
                            
                            for (const link of allLinks) {
                                let href = link.getAttribute('href');
                                if (!href) continue;
                                
                                // Normalizar URL relativa
                                if (href.startsWith('/')) {
                                    href = 'https://www.olx.com.br' + href;
                                } else if (!href.startsWith('http')) {
                                    continue;
                                }
                                
                                // Filtrar apenas links de anúncios individuais
                                // Padrão: /.../[modelo]-[ano]-[ID] onde ID é numérico
                                // Manter host original (mg.olx.com.br) para o link abrir o anúncio correto
                                try {
                                    const urlObj = new URL(href);
                                    const pathParts = urlObj.pathname.split('/').filter(p => p);
                                    
                                    if (pathParts.length >= 3) {
                                        const lastPart = pathParts[pathParts.length - 1];
                                        // Verificar se termina com número (ID do anúncio)
                                        if (/\\d+$/.test(lastPart) && /-\\d+$/.test(lastPart)) {
                                            // Remover apenas query params; manter host (mg.olx.com.br ou www.olx.com.br)
                                            const cleanUrl = urlObj.origin + urlObj.pathname;
                                            if (!seen.has(cleanUrl)) {
                                                seen.add(cleanUrl);
                                                links.push(cleanUrl);
                                            }
                                        }
                                    }
                                } catch (e) {
                                    // URL inválida, ignorar
                                }
                            }
                            
                            return links;
                        }
                    """)
                    
                    if not page_links or len(page_links) == 0:
                        _log("Coleta: nenhum link encontrado na página %d. Parando." % page_num)
                        break
                    
                    # Normalizar e filtrar links
                    normalized_links = []
                    for link in page_links:
                        normalized = _normalize_olx_url(link)
                        if normalized and normalized not in seen_links:
                            normalized_links.append(normalized)
                            seen_links.add(normalized)
                    
                    links.extend(normalized_links)
                    _log("Coleta: página %d - %d links novos (total: %d)" % (page_num, len(normalized_links), len(links)))
                    
                    if progress_callback:
                        progress_callback(len(links), len(links))
                    
                    if len(normalized_links) == 0:
                        _log("Coleta: nenhum link novo. Parando.")
                        break
                    
                    # Delay conservador entre páginas (5-10s)
                    delay = 10
                    _log("Coleta: aguardando %ds antes da próxima página..." % delay)
                    time.sleep(delay)
                    
                except Exception as e:
                    error_str = str(e).lower()
                    _log("❌ Coleta OLX: erro na página %d - %s" % (page_num, str(e)[:200]))
                    if "504" in error_str or "502" in error_str or "503" in error_str:
                        _log("⚠️ Erro HTTP: servidor temporariamente indisponível. Parando coleta.")
                    elif "timeout" in error_str or "timed_out" in error_str:
                        _log("⚠️ Timeout: conexão lenta. Parando coleta.")
                    elif "net::" in error_str or "network" in error_str:
                        _log("⚠️ Erro de rede. Parando coleta.")
                    else:
                        _log("⚠️ Erro desconhecido. Parando coleta.")
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
                    _kill_chrome_processes_orphaned()
                except Exception:
                    pass

    try:
        if browser is not None:
            _run_with_browser(browser, False)
        else:
            with sync_playwright() as p:
                use_cdp = False
                browser_instance = None
                if own_browser_only:
                    # Thread separada: segundo Chrome real via CDP (porta 9223), não Chromium — reduz bloqueio Cloudflare.
                    _log("Coleta OLX: usando segundo Chrome via CDP (porta %d)" % CDP_PORT_OLX)
                    print("📌 OLX: segundo Chrome (CDP %d) para coleta em paralelo" % CDP_PORT_OLX)
                    try:
                        browser_instance = p.chromium.connect_over_cdp(CDP_URL_OLX)
                    except Exception:
                        if _launch_chrome_olx_cdp():
                            time.sleep(5)
                            browser_instance = p.chromium.connect_over_cdp(CDP_URL_OLX)
                        else:
                            raise RuntimeError("Não foi possível iniciar Chrome para OLX (porta %d)" % CDP_PORT_OLX)
                else:
                    try:
                        browser_instance = p.chromium.connect_over_cdp(CDP_URL)
                        use_cdp = True
                        _log("Coleta: usando Chrome existente (porta 9222)")
                        print("📌 OLX: usando Chrome existente (porta 9222)")
                    except Exception:
                        try:
                            if _launch_chrome_with_debug_port():
                                time.sleep(5)
                                browser_instance = p.chromium.connect_over_cdp(CDP_URL)
                                use_cdp = True
                                _log("Coleta: conectado ao Chrome (porta 9222)")
                                print("📌 OLX: conectado ao Chrome (porta 9222)")
                        except Exception:
                            pass
                        if browser_instance is None:
                            _log("Coleta: usando janela minimizada (sem CDP)")
                            print("📌 OLX: usando janela minimizada")
                            browser_instance = p.chromium.launch(
                                headless=False,
                                args=[
                                    f"--user-data-dir={BASE_DIR / 'chrome_login_profile'}",
                                    "--start-minimized",
                                    "--window-size=1280,800",
                                ]
                            )
                _run_with_browser(browser_instance, True)
                if own_browser_only:
                    _kill_chrome_olx()
    except Exception as e:
        _log("Coleta: erro geral - %s" % e)
        import traceback
        traceback.print_exc()
    
    _log("Coleta OLX: total de %d links coletados" % len(links))
    return links
