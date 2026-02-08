#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coleta de Links do Facebook Marketplace (versão estável mesclada)
Regra: sempre começar por /marketplace/category/cars; filtro só valor; coletar só marketplace/item/{ID}.
Created by Igor Avelar - avelar.igor@gmail.com
"""

import sys
import json
import re
import socket
import time
import subprocess
from pathlib import Path
from typing import List, Callable, Optional, Tuple, Any


def _check_connectivity(timeout_sec: float = 5.0) -> bool:
    """Testa se há conexão com a internet (DNS Google). Retorna True se conseguir conectar."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=timeout_sec)
        return True
    except (socket.error, OSError):
        return False


def _wait_for_connection(
    status_callback: Optional[Callable[[str], None]],
    is_aborted: Optional[Callable[[], bool]],
    interval_sec: int = 30,
) -> bool:
    """
    Fica verificando a conexão a cada interval_sec até voltar ou até ser abortado.
    Retorna True se a conexão voltou, False se foi abortado (ex.: usuário fechou o app).
    """
    if not status_callback or not is_aborted:
        return False
    while True:
        if is_aborted():
            return False
        status_callback("Sem conexão. Verificando a cada %ds..." % interval_sec)
        _log("Coleta: sem conexão. Próxima verificação em %ds." % interval_sec)
        print("📡 Sem conexão. Verificando a cada %ds... (feche o app para cancelar)" % interval_sec)
        time.sleep(interval_sec)
        if is_aborted():
            return False
        if _check_connectivity():
            status_callback("Conexão restabelecida. Retomando coleta...")
            _log("Coleta: conexão restabelecida. Retomando.")
            print("✅ Conexão restabelecida. Retomando coleta...")
            return True

# Aceitar somente URLs marketplace/item/{ID numérico} (anti-bug)
MARKETPLACE_ITEM_RE = re.compile(r"marketplace/item/(\d+)(?:/|\?|$)")

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
# Sessão do Facebook (cookies) para não precisar logar a cada execução
BROWSER_STATE_FILE = BASE_DIR / "browser_state.json"
# Perfil persistente do navegador (evita tela em branco no login)
BROWSER_PROFILE_DIR = BASE_DIR / "browser_profile"
# Chrome existente (igual ao Debug) — quando disponível usa a mesma sessão
CDP_URL = "http://127.0.0.1:9222"
CHROME_DEBUG_PROFILE = BASE_DIR / "chrome_login_profile"
# ID da região do Marketplace (igual ao Debug) — formato URL que funciona no navegador
MARKETPLACE_REGION_ID_DEFAULT = "103996099635518"
# Versão mobile — anti-bots costumam ser menos acionados
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)
MOBILE_VIEWPORT = {"width": 390, "height": 844}


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
        # Isso identifica processos criados pelo Playwright sem afetar o Chrome do usuário
        try:
            current_pid = os.getpid()
            # Usar PowerShell para encontrar e matar processos filhos
            ps_cmd = f'Get-WmiObject Win32_Process | Where-Object {{$_.ParentProcessId -eq {current_pid} -and $_.Name -eq "chrome.exe"}} | ForEach-Object {{Stop-Process -Id $_.ProcessId -Force}}'
            subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            )
        except Exception:
            pass
        _log("Coleta: tentativa de encerrar processos órfãos do Chrome.")
    except Exception as e:
        _log("Coleta: aviso ao encerrar processos Chrome - %s" % e)


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


def _log(msg, level="info"):
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
            _log("Coleta: sessão do Facebook (cookies) aplicada ao navegador (login persistente)")
            print("📌 Sessão do Facebook aplicada (login persistente).")
    except Exception as e:
        _log("Coleta: aviso ao aplicar sessão ao CDP - %s" % e)


try:
    from marketplace_urls import build_marketplace_url
except ImportError:
    def build_marketplace_url(city, state, price_min, price_max, marketplace_region_id=""):
        c = (city or "").lower().replace(" ", "")
        return f"https://www.facebook.com/marketplace/{c}/search" if c else "https://www.facebook.com/marketplace/category/cars"


def get_shared_browser(playwright) -> Tuple[Any, bool]:
    """
    Obtém um browser para reuso (CDP ou launch). Retorna (browser, use_cdp).
    use_cdp=True significa que não devemos fechar o browser ao final (é o Chrome do usuário).
    """
    use_cdp = False
    browser = None
    try:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        use_cdp = True
        _log("Coleta: usando Chrome existente (porta 9222)")
    except Exception:
        try:
            if _launch_chrome_with_debug_port():
                time.sleep(5)
                browser = playwright.chromium.connect_over_cdp(CDP_URL)
                use_cdp = True
                _log("Coleta: conectado ao Chrome (porta 9222)")
        except Exception:
            pass
        if not use_cdp:
            try:
                browser = playwright.chromium.launch(
                    headless=False,
                    args=["--start-minimized", "--window-size=390,844"]
                )
                _log("Coleta: navegador launch (minimizado)")
            except Exception:
                pass
    return (browser, use_cdp)


def collect_links(
    city: str,
    state: str,
    price_min: int,
    price_max: int,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    wait_for_login_callback: Optional[Callable[[], None]] = None,
    marketplace_region_id: str = "",
    status_message_callback: Optional[Callable[[str], None]] = None,
    is_aborted_callback: Optional[Callable[[], bool]] = None,
    browser: Any = None,
) -> Tuple[List[str], Optional[Any]]:
    """
    Coleta links do Facebook Marketplace.
    progress_callback(current, total) opcional.
    wait_for_login_callback: se informado, é chamado após abrir o navegador para você
    fazer login no Facebook; a coleta só continua depois que o callback retornar.
    marketplace_region_id: se informado, usa URL no formato do navegador (marketplace/{id}/search/...).
    status_message_callback: se informado, em caso de timeout a coleta fica aguardando a conexão
    voltar e exibe mensagens (ex.: "Sem conexão. Verificando a cada 30s...").
    is_aborted_callback: quando True (ex.: usuário fechou o app), interrompe a espera e retorna [].
    browser: se informado, reutiliza este browser (não fecha ao final).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        _log("Coleta: Playwright não instalado - %s" % e)
        print("❌ Playwright não instalado. Instale com: pip install playwright")
        print("   O app usa sempre o Chrome local (porta 9222) quando disponível; não é necessário 'playwright install chromium' se você usar o Chrome.")
        return []

    links = []
    seen_links_file = BASE_DIR / "seen_links.json"
    _log("Coleta: iniciando (URL do Marketplace será aberta no navegador)")
    seen_links = set()
    if seen_links_file.exists():
        try:
            with open(seen_links_file, 'r', encoding='utf-8') as f:
                seen_links = set(json.load(f))
        except Exception:
            pass

    # Com cidade e estado: usar URL com location= para manter filtro (ex.: Montes Claros, MG).
    # Sem cidade/estado: usar region_id no formato do navegador.
    city_stripped = (city or "").strip()
    state_stripped = (state or "").strip()
    if city_stripped and state_stripped:
        region_id = ""
        _log("Coleta: usando URL com location=%s, %s para limitar à região" % (city_stripped, state_stripped))
    else:
        region_id = (marketplace_region_id or "").strip() or MARKETPLACE_REGION_ID_DEFAULT
    marketplace_url = build_marketplace_url(city, state, price_min, price_max, region_id)
    # Com localização: mais rolagens para coletar mais links; resetar feed a cada 4 rolagens para manter região
    use_location = bool(city_stripped and state_stripped)
    max_links = 200
    max_scroll_rounds = 12  # mesmo com localização, para não parar em ~40 links
    _log("Coleta: URL = %s (max_links=%s, max_scroll=%s)" % (marketplace_url, max_links, max_scroll_rounds))

    print(f"🔍 Buscando anúncios (localização: conta do Facebook)...")
    if price_min and price_max:
        print(f"💰 Faixa de preço: R$ {price_min:,.0f} - R$ {price_max:,.0f}")
    else:
        print(f"💰 Faixa de preço: sem limite")
    if use_location:
        print(f"📍 Limitando à região: {city_stripped}, {state_stripped} (até %s links, reset do feed a cada 4 rolagens)" % max_links)
    # #region agent log
    try:
        with open(r"c:\Projects\.cursor\debug.log", "a", encoding="utf-8") as _f:
            import json as _json
            _f.write(_json.dumps({"location": "collect_links_mobile:collect_links", "message": "url_built", "data": {"city": city, "state": state, "marketplace_url": marketplace_url, "url_has_location": "location=" in marketplace_url}, "hypothesisId": "H2", "timestamp": time.time() * 1000}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion

    try:
        reuse_browser = browser is not None
        if reuse_browser:
            use_cdp = True
            context = browser.contexts[0] if browser.contexts else browser.new_context(locale="pt_BR")
            _inject_saved_session_into_context(context)
            page = context.pages[0] if context.pages else context.new_page()
            _goto_ok = False
            while not _goto_ok:
                for attempt in range(3):
                    if is_aborted_callback and is_aborted_callback():
                        _log("Coleta: cancelado pelo usuário (sem conexão).")
                        return []
                    try:
                        if attempt == 0:
                            page.goto(marketplace_url, wait_until="domcontentloaded", timeout=60000)
                        elif attempt == 1:
                            _log("Coleta: tentando novamente em 1.5s (timeout)...")
                            print("⏳ Timeout. Tentando novamente em 1.5s...")
                            time.sleep(1.5)
                            page.goto(marketplace_url, wait_until="domcontentloaded", timeout=60000)
                        else:
                            page.goto(marketplace_url, wait_until="domcontentloaded", timeout=60000)
                        _goto_ok = True
                        break
                    except Exception as e:
                        err_msg = str(e)
                        if "TIMED_OUT" in err_msg or "timeout" in err_msg.lower():
                            if attempt >= 2 and status_message_callback and is_aborted_callback:
                                if not _wait_for_connection(status_message_callback, is_aborted_callback, 30):
                                    return []
                                break
                            raise
                        raise
            time.sleep(2)
            _minimize_browser_window_win()
            time.sleep(1)
            try:
                page.wait_for_selector('a[href*="/marketplace/item/"]', timeout=15000)
            except Exception:
                pass
            _log("Coleta: iniciando rolagem e extração de links...")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            time.sleep(5)
            location_check = (city_stripped and state_stripped)
            location_in_url = ("location=" in marketplace_url and city_stripped)
            for scroll_round in range(max_scroll_rounds):
                if scroll_round > 0:
                    time.sleep(5)
                if location_check and location_in_url and scroll_round >= 4 and scroll_round % 4 == 0:
                    try:
                        page.goto(marketplace_url, wait_until="domcontentloaded", timeout=30000)
                        time.sleep(2)
                    except Exception:
                        pass
                if location_check and location_in_url:
                    try:
                        current_url = page.url or ""
                        first_word = city_stripped.split()[0].lower() if city_stripped else ""
                        if "location=" not in current_url or (first_word and first_word not in current_url.lower()):
                            page.goto(marketplace_url, wait_until="domcontentloaded", timeout=30000)
                            time.sleep(2)
                    except Exception:
                        pass
                try:
                    link_elements = page.query_selector_all('a[href*="/marketplace/item/"]')
                    for element in link_elements:
                        try:
                            href = element.get_attribute('href')
                        except Exception:
                            continue
                        if href and MARKETPLACE_ITEM_RE.search(href):
                            full_url = href if href.startswith('http') else f"https://www.facebook.com{href}"
                            if full_url not in seen_links:
                                links.append(full_url)
                                seen_links.add(full_url)
                                if progress_callback:
                                    progress_callback(len(links), max_links)
                                if len(links) >= max_links:
                                    break
                except Exception as e:
                    _log("Coleta: aviso ao extrair links - %s" % e)
                    if "target" in str(e).lower() and "closed" in str(e).lower():
                        break
                if len(links) >= max_links:
                    break
                try:
                    page.evaluate("window.scrollBy(0, 800)")
                    time.sleep(1.5)
                except Exception as e:
                    err_msg = str(e).lower()
                    if "target" in err_msg and "closed" in err_msg:
                        break
                    if "execution context" in err_msg or "destroyed" in err_msg or "navigation" in err_msg:
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=15000)
                            time.sleep(2)
                        except Exception:
                            break
                    else:
                        raise
            try:
                context.storage_state(path=str(BROWSER_STATE_FILE))
                _log("Coleta: sessão do Facebook salva")
            except Exception as e:
                _log("Coleta: aviso ao salvar sessão - %s" % e)
        else:
            _log("Coleta: iniciando Playwright...")
            with sync_playwright() as p:
                browser, use_cdp = get_shared_browser(p)
                if not browser:
                    return []
                if use_cdp:
                    context = browser.contexts[0] if browser.contexts else browser.new_context(locale="pt_BR")
                    _inject_saved_session_into_context(context)
                    page = context.pages[0] if context.pages else context.new_page()
                    _goto_ok = False
                    while not _goto_ok:
                        for attempt in range(3):
                            if is_aborted_callback and is_aborted_callback():
                                _log("Coleta: cancelado pelo usuário (sem conexão).")
                                return []
                            try:
                                if attempt == 0:
                                    page.goto(marketplace_url, wait_until="domcontentloaded", timeout=60000)
                                elif attempt == 1:
                                    _log("Coleta: tentando novamente em 1.5s (timeout)...")
                                    print("⏳ Timeout. Tentando novamente em 1.5s...")
                                    time.sleep(1.5)
                                    page.goto(marketplace_url, wait_until="domcontentloaded", timeout=60000)
                                else:
                                    _log("Coleta: usando domcontentloaded após timeout.")
                                    print("⏳ Usando carregamento parcial...")
                                    page.goto(marketplace_url, wait_until="domcontentloaded", timeout=60000)
                                _goto_ok = True
                                break
                            except Exception as e:
                                err_msg = str(e)
                                if "TIMED_OUT" in err_msg or "timeout" in err_msg.lower():
                                    _log("Coleta: tentativa %s - timeout." % (attempt + 1))
                                    if attempt >= 2:
                                        if status_message_callback and is_aborted_callback:
                                            if not _wait_for_connection(status_message_callback, is_aborted_callback, 30):
                                                return []
                                            break
                                        _log("Coleta: verifique a internet e tente novamente.")
                                        raise
                                else:
                                    raise
                    time.sleep(2)
                    _minimize_browser_window_win()
                    time.sleep(1)
                    try:
                        page.wait_for_selector('a[href*="/marketplace/item/"]', timeout=15000)
                    except Exception:
                        pass
                else:
                    context_opts = {
                        "viewport": MOBILE_VIEWPORT,
                        "user_agent": MOBILE_USER_AGENT,
                        "locale": "pt_BR",
                        "is_mobile": True,
                        "device_scale_factor": 1,
                    }
                    # Sem CDP: janela minimizada (não headless) — mobile reduz anti-bot
                    if BROWSER_STATE_FILE.exists():
                        browser = p.chromium.launch(
                            headless=False,
                            args=["--start-minimized", "--window-size=390,844"]
                        )
                        _log("Coleta: navegador minimizado, sessão salva (conteúdo completo).")
                        print("📌 Coleta em janela minimizada — conteúdo completo.")
                        context_opts["storage_state"] = str(BROWSER_STATE_FILE)
                        context = browser.new_context(**context_opts)
                    else:
                        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
                        context = p.chromium.launch_persistent_context(
                            str(BROWSER_PROFILE_DIR),
                            headless=False,
                            args=["--start-minimized", "--window-size=390,844"],
                            **context_opts
                        )
                        _log("Coleta: navegador com perfil persistente (login manual).")
                        print("📌 Abrindo janela para login (apenas esta vez).")
                    page = context.new_page()
                    if not BROWSER_STATE_FILE.exists():
                        try:
                            page.goto("https://www.facebook.com/", wait_until="load", timeout=90000)
                        except Exception as e:
                            _log("Coleta: aviso ao carregar Facebook - %s" % e)
                        time.sleep(4)
                        if wait_for_login_callback:
                            wait_for_login_callback()
                    _goto_ok = False
                    while not _goto_ok:
                        for attempt in range(3):
                            if is_aborted_callback and is_aborted_callback():
                                _log("Coleta: cancelado pelo usuário (sem conexão).")
                                return []
                            try:
                                if attempt == 0:
                                    page.goto(marketplace_url, wait_until="domcontentloaded", timeout=60000)
                                elif attempt == 1:
                                    _log("Coleta: tentando novamente (timeout)...")
                                    time.sleep(1.5)
                                    page.goto(marketplace_url, wait_until="domcontentloaded", timeout=60000)
                                else:
                                    page.goto(marketplace_url, wait_until="domcontentloaded", timeout=60000)
                                _goto_ok = True
                                break
                            except Exception as e:
                                err_msg = str(e)
                                if "TIMED_OUT" in err_msg or "timeout" in err_msg.lower():
                                    if attempt >= 2:
                                        if status_message_callback and is_aborted_callback:
                                            if not _wait_for_connection(status_message_callback, is_aborted_callback, 30):
                                                return []
                                            break
                                        _log("Coleta: timeout ao carregar o Facebook. Verifique a internet.")
                                        raise
                                else:
                                    raise
                    if _goto_ok:
                        time.sleep(2)
                        _minimize_browser_window_win()
                        time.sleep(2)
                        try:
                            page.wait_for_selector('a[href*="/marketplace/item/"]', timeout=20000)
                        except Exception:
                            pass

            _log("Coleta: iniciando rolagem e extração de links...")

            # Esperar página estável após possível navegação (login, etc.)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            # Dar tempo para o feed/localização estabilizar antes da primeira coleta de links
            time.sleep(5)

            # Com location=: Facebook costuma manter a URL mas ao rolar carrega feed "Brasil". Reabrir a URL a cada 4 rolagens.
            location_check = (city_stripped and state_stripped)
            location_in_url = ("location=" in marketplace_url and city_stripped)

            for scroll_round in range(max_scroll_rounds):
                # A cada rolagem, aguardar 5s antes de coletar os links (dar tempo de o Facebook carregar/identificar anúncios)
                if scroll_round > 0:
                    time.sleep(5)
                # A cada 4 rolagens, reabrir a URL da região para manter o filtro (evitar feed "Brasil"); assim dá para rolar mais e passar de ~40 links
                if location_check and location_in_url and scroll_round >= 4 and scroll_round % 4 == 0:
                    try:
                        _log("Coleta: resetando feed (rolagem %s) para manter %s" % (scroll_round, city_stripped))
                        page.goto(marketplace_url, wait_until="domcontentloaded", timeout=30000)
                        time.sleep(2)
                    except Exception:
                        pass

                # Se a URL perdeu o filtro de localização, reabrir
                if location_check and location_in_url:
                    try:
                        current_url = page.url or ""
                        first_word = city_stripped.split()[0].lower() if city_stripped else ""
                        if "location=" not in current_url or (first_word and first_word not in current_url.lower()):
                            _log("Coleta: URL perdeu filtro de localização, reabrindo busca em %s" % city_stripped)
                            page.goto(marketplace_url, wait_until="domcontentloaded", timeout=30000)
                            time.sleep(2)
                    except Exception:
                        pass

                try:
                    link_elements = page.query_selector_all('a[href*="/marketplace/item/"]')
                    for element in link_elements:
                        try:
                            href = element.get_attribute('href')
                        except Exception:
                            continue
                        if href and MARKETPLACE_ITEM_RE.search(href):
                            full_url = href if href.startswith('http') else f"https://www.facebook.com{href}"
                            if full_url not in seen_links:
                                links.append(full_url)
                                seen_links.add(full_url)
                                if progress_callback:
                                    progress_callback(len(links), max_links)
                                if len(links) >= max_links:
                                    break
                except Exception as e:
                    _log("Coleta: aviso ao extrair links - %s" % e)
                    if "target" in str(e).lower() and "closed" in str(e).lower():
                        break
                if len(links) >= max_links:
                    break
                # #region agent log (após primeira rodada de links)
                if scroll_round == 0 and links:
                    try:
                        with open(r"c:\Projects\.cursor\debug.log", "a", encoding="utf-8") as _f:
                            import json as _json
                            _f.write(_json.dumps({"location": "collect_links:links_collected", "message": "first_batch", "data": {"count": len(links), "first_link": links[0][:80] if links else ""}, "hypothesisId": "H4", "timestamp": time.time() * 1000}, ensure_ascii=False) + "\n")
                    except Exception:
                        pass
                # #endregion
                try:
                    page.evaluate("window.scrollBy(0, 800)")
                    time.sleep(1.5)
                except Exception as e:
                    err_msg = str(e).lower()
                    # Janela fechada pelo usuário
                    if "target" in err_msg and "closed" in err_msg:
                        _log("Coleta: janela do navegador foi fechada. Retornando links já coletados.")
                        break
                    # Navegação destruiu o contexto
                    if "execution context" in err_msg or "destroyed" in err_msg or "navigation" in err_msg:
                        _log("Coleta: página navegou, aguardando estabilizar...")
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=15000)
                            time.sleep(2)
                        except Exception:
                            break
                    else:
                        raise

            # Salvar sessão (cookies/login) para próximas execuções e para o scan
            try:
                context.storage_state(path=str(BROWSER_STATE_FILE))
                _log("Coleta: sessão do Facebook salva para próximas consultas")
            except Exception as e:
                _log("Coleta: aviso ao salvar sessão - %s" % e)

            finally:
                # Só fechar se nós abrimos o browser (não CDP/reuso)
                try:
                    if not use_cdp and browser:
                        browser.close()
                        _log("Coleta: navegador fechado ao finalizar.")
                    elif context and not use_cdp:
                        context.close()
                except Exception:
                    pass

    except Exception as e:
        import traceback
        _log("Coleta: ERRO - %s" % e)
        try:
            from log_config import get_logger
            get_logger().debug(traceback.format_exc())
        except Exception:
            traceback.print_exc()

    try:
        with open(seen_links_file, 'w', encoding='utf-8') as f:
            json.dump(list(seen_links), f, indent=2, ensure_ascii=False)
        links_file = BASE_DIR / "links.txt"
        with open(links_file, 'w', encoding='utf-8') as f:
            for link in links:
                f.write(f"{link}\n")
    except Exception as e:
        print(f"⚠️ Erro ao salvar links: {e}")

    print(f"✅ {len(links)} links coletados")
    return links
