#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scan de Anúncios da Webmotors
Visita cada link coletado e extrai informações (preço, modelo, ano, km, etc.).

Anti-bot (Estratégia 1 — sessão humana):
- Se existir out/webmotors_session.json, o scan usa essa sessão (cookies + localStorage) e pode
  não ver o desafio "Pressione e segure".
- Na primeira vez que o desafio aparecer na execução: pausa até 90s para você resolver na janela;
  ao resolver, salva a sessão em out/webmotors_session.json e continua. Próximas runs carregam essa sessão.
- Se já tiver oferecido a pausa ou após 3 falhas consecutivas: pula o link/restante sem esperar.
- Logs distinguem: "bloqueio anti-bot (desafio)" vs "timeout (pode ser bloqueio WAF)" vs "servidor indisponível".
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

# Versão mobile (igual à coleta de links) — reduz bloqueio WAF nas páginas de detalhe
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)
MOBILE_VIEWPORT = {"width": 390, "height": 844}


def _speed_routes(page, block_images=True):
    """Bloqueia image/media/font para acelerar (WM/MA/OLX: tudo; FB: só font+media)."""
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
        print(f"[Webmotors Scan] {msg}")


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
    """Extrai preço do texto (R$ X.XXX,XX / R$ X.XXX ou só número com ponto/vírgula)."""
    if not text:
        return None
    text_clean = text.replace(' ', '').strip()
    # Padrões: R$ seguido de número (pode ter ponto de milhar e vírgula decimal)
    patterns = [
        r'R\$\s*(\d[\d.]*,\d{2})',
        r'R\$\s*(\d[\d.]*)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text_clean)
        if match:
            try:
                price_str = match.group(1).replace('.', '').replace(',', '.')
                return float(price_str)
            except Exception:
                pass
    # Número só (ex.: "115.990" ou "115990" do card FIPE sem "R$")
    m = re.search(r'^(\d[\d\.\,]*)$', text_clean)
    if m:
        try:
            s = m.group(1).replace('.', '').replace(',', '.')
            return float(s)
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


def normalize_km(km_text: Optional[str], fallback_text: Optional[str] = None) -> Optional[int]:
    """Se km_text já for número puro (ex: do JSON-LD / __INITIAL_STATE__), usa direto; senão extrai com extract_km."""
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
    Escaneia anúncios da Webmotors. Retorna (listings, erros_count).
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
    # Arquivo opcional: se existir, pula todo o scan da Webmotors (crie antes de rodar ou durante a execução para pular o restante)
    skip_file = out_dir / "skip_webmotors"
    webmotors_session_file = out_dir / "webmotors_session.json"
    if skip_file.exists():
        _log("⏭️ Webmotors: arquivo skip_webmotors encontrado — pulando scan (apague out/skip_webmotors para habilitar de novo).")
        print("⏭️ Webmotors: pulando (existe out/skip_webmotors).")
        return ([], len(links))
    print(f"📊 Escaneando {len(links)} anúncios da Webmotors...")
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
            context_opts = {
                "viewport": MOBILE_VIEWPORT,
                "user_agent": MOBILE_USER_AGENT,
                "locale": "pt_BR",
                "is_mobile": True,
                "device_scale_factor": 1,
            }
            if webmotors_session_file.exists():
                try:
                    context_opts["storage_state"] = str(webmotors_session_file)
                    _log("📂 Webmotors: usando sessão salva (out/webmotors_session.json) — desafio já resolvido antes.")
                    print("📂 Webmotors: sessão anterior carregada; se o desafio aparecer, resolva uma vez para re-salvar.")
                except Exception:
                    pass
            context = browser.new_context(**context_opts)
            page = context.new_page()
            _speed_routes(page, block_images=True)
            _log("Scan Webmotors: usando viewport mobile (390x844) para reduzir bloqueio nas páginas de detalhe.")

    # Sessão humana (Estratégia 1): na 1ª vez que o desafio aparecer, pausar até 90s para resolver e salvar sessão
    session_wait_offered = False

    # Após N bloqueios/timeouts consecutivos, pular o restante dos links da Webmotors para não atrasar o pipeline
    CONSECUTIVE_SKIP_THRESHOLD = 3
    consecutive_failures = 0

    try:
                for idx, link in enumerate(links, 1):
                    # Pular se o usuário criou out/skip_webmotors durante a execução
                    if skip_file.exists():
                        remaining = len(links) - idx + 1
                        _log("⏭️ Webmotors: skip_webmotors detectado durante o scan — pulando os %d links restantes." % remaining)
                        print("⏭️ Webmotors: pulando restante (out/skip_webmotors criado).")
                        errors_count += remaining
                        break
                    if progress_callback:
                        progress_callback(idx, len(links))
                    
                    # Se já acumulamos muitos erros consecutivos, pular o restante da Webmotors
                    if consecutive_failures >= CONSECUTIVE_SKIP_THRESHOLD:
                        remaining = len(links) - idx
                        if remaining > 0:
                            _log("⏭️ Webmotors: %d bloqueios/timeouts seguidos — pulando os %d links restantes para não atrasar o pipeline." % (CONSECUTIVE_SKIP_THRESHOLD, remaining))
                            print("⏭️ Webmotors: pulando %d links restantes (bloqueio anti-bot)." % remaining)
                            errors_count += remaining
                        break
                    
                    cache_key = hashlib.md5(link.encode()).hexdigest()
                    cache_file = cache_dir / f"webmotors_{cache_key}.json"
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
                                    if cached.get("source") == "webmotors":
                                        price_cached = cached.get("price")
                                        if price_cached is None or (isinstance(price_cached, (int, float)) and price_cached <= 0):
                                            _log("Cache Webmotors sem preço: forçando rescan - %s" % link[:50])
                                            raise Exception("cache Webmotors sem preço: forçando rescan")
                                    listings.append(cached)
                                    if listing_queue is not None:
                                        listing_queue.put(cached)
                                    _log("Scan: cache hit - %s" % link[:50])
                                    consecutive_failures = 0  # reset ao ter sucesso (cache hit)
                                    continue
                        except Exception:
                            pass
                    
                    def _is_challenge_page():
                        try:
                            return page.evaluate("""() => {
                                const t = (document.body && document.body.innerText || '').toLowerCase();
                                if (t.includes('pressione e segure') || t.includes('você é um humano') || t.includes('access denied')) return true;
                                if (document.querySelector('iframe[src*="challenge"], iframe[src*="captcha"], iframe[title*="challenge" i]')) return true;
                                if (document.querySelector('[id*="cf-challenge" i], [class*="cf-challenge" i]')) return true;
                                if (document.querySelector('[id*="px-captcha" i], [class*="px-captcha" i], script[src*="perimeterx" i]')) return true;
                                return false;
                            }""")
                        except Exception:
                            return False
                    
                    def _log_block_and_skip():
                        _log("⏭️ Webmotors: bloqueio anti-bot em %s — pulando (seguindo com o que já temos)." % link[:55])
                        print("⏭️ Webmotors: bloqueio detectado, pulando link.")
                    
                    try:
                        page.goto(link, wait_until="domcontentloaded", timeout=25000)
                    except Exception as goto_err:
                        error_str = str(goto_err).lower()
                        try:
                            if _is_challenge_page():
                                # Bloqueio WAF/desafio (não é timeout de rede)
                                if reuse_browser or session_wait_offered:
                                    _log("⏭️ Webmotors: bloqueio anti-bot (desafio) em %s — pulando." % link[:50])
                                    _log_block_and_skip()
                                    errors_count += 1
                                    consecutive_failures += 1
                                    continue
                                session_wait_offered = True
                                _log("⚠️ Webmotors: desafio detectado (página carregou). Resolva 'Pressione e segure' na janela; aguardando até 90s para salvar sessão.")
                                print("⚠️ Resolva o 'Pressione e segure' na janela do navegador. Aguardando até 90s…")
                                for _ in range(45):
                                    time.sleep(2)
                                    if not _is_challenge_page():
                                        break
                                if not _is_challenge_page():
                                    try:
                                        context.storage_state(path=str(webmotors_session_file))
                                        _log("✅ Webmotors: sessão salva em out/webmotors_session.json (próximas runs podem não ver o desafio).")
                                        print("✅ Sessão salva. Continuando a coleta.")
                                    except Exception:
                                        pass
                                    consecutive_failures = 0
                                    # cair no fluxo normal: extrair desta página (não dar continue)
                                else:
                                    _log_block_and_skip()
                                    errors_count += 1
                                    consecutive_failures += 1
                                    continue
                        except Exception:
                            pass
                        # Timeout/erro de rede (não é desafio)
                        errors_count += 1
                        consecutive_failures += 1
                        if "timeout" in error_str or "timed_out" in error_str:
                            _log("❌ Scan Webmotors: timeout em %s (pode ser bloqueio WAF) — pulando." % link[:50])
                        elif "502" in error_str or "503" in error_str:
                            _log("❌ Scan Webmotors: servidor indisponível em %s — pulando." % link[:50])
                        else:
                            _log("❌ Scan Webmotors: erro em %s — %s" % (link[:50], str(goto_err)[:80]))
                        continue
                    
                    # Página carregou: se for desafio, dar uma chance de resolver (1x por run) e salvar sessão
                    if _is_challenge_page():
                        if reuse_browser or session_wait_offered:
                            _log("⏭️ Webmotors: bloqueio anti-bot (desafio) em %s — pulando." % link[:50])
                            _log_block_and_skip()
                            errors_count += 1
                            consecutive_failures += 1
                            continue
                        session_wait_offered = True
                        _log("⚠️ Webmotors: desafio 'Pressione e segure' detectado. Resolva na janela; aguardando até 90s para salvar sessão.")
                        print("⚠️ Resolva o 'Pressione e segure' na janela do navegador. Aguardando até 90s…")
                        for _ in range(45):
                            time.sleep(2)
                            if not _is_challenge_page():
                                break
                        if not _is_challenge_page():
                            try:
                                context.storage_state(path=str(webmotors_session_file))
                                _log("✅ Webmotors: sessão salva em out/webmotors_session.json.")
                                print("✅ Sessão salva. Continuando a coleta.")
                            except Exception:
                                pass
                            consecutive_failures = 0
                            time.sleep(1)
                        else:
                            _log_block_and_skip()
                            errors_count += 1
                            consecutive_failures += 1
                            continue
                    
                    try:
                        # Scroll rápido para disparar lazy-load do bloco de preço (mobile)
                        try:
                            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                            time.sleep(0.35)
                            page.evaluate("() => window.scrollTo(0, 0)")
                            time.sleep(0.15)
                        except Exception:
                            pass
                        # Esperar elemento de KM (desktop: ID; mobile: pode ser bloco com "KM")
                        try:
                            page.wait_for_selector("#VehiclePrincipalInformatiOnodometer", timeout=4000)
                        except Exception:
                            try:
                                page.wait_for_selector("text=KM", timeout=2000)
                            except Exception:
                                pass
                        # Esperar bloco de preço (mobile: #vehicleSendProposalPrice) para hidratação React
                        try:
                            page.wait_for_selector("#vehicleSendProposalPrice, [id*='SendProposalPrice']", timeout=4000)
                        except Exception:
                            pass
                        # Extrair dados da página usando JavaScript
                        # Webmotors página de detalhes: usa IDs específicos e classes
                        data = page.evaluate("""
                            () => {
                                const result = {
                                    title: '',
                                    price: '',
                                    fipe_webmotors: '',
                                    year: '',
                                    km: '',
                                    description: '',
                                    city: '',
                                    image_url: ''
                                };
                                function getText(sel) {
                                    const el = document.querySelector(sel);
                                    return el ? (el.textContent || '').trim() : '';
                                }
                                
                                // Título (VehicleDetails__header__title - h1)
                                const titleEl = document.querySelector('#VehicleBasicInformationTitle') ||
                                                document.querySelector('.VehicleDetails__header__title') ||
                                                document.querySelector('h1');
                                if (titleEl) {
                                    // Combinar título e descrição se houver
                                    const descEl = titleEl.querySelector('#VehicleBasicInformationDescription') ||
                                                  titleEl.querySelector('.VehicleDetails__header__description');
                                    result.title = titleEl.textContent.trim();
                                    if (descEl && descEl.textContent.trim()) {
                                        result.title = result.title + ' ' + descEl.textContent.trim();
                                    }
                                }
                                
                                // Preço (mobile): 1) formulário (#vehicleSendProposalPrice) já com "R$"
                                // 2) bloco "Valor anunciado" onde o <strong> às vezes tem só "115.990" (sem "R$")
                                // 3) outros fallbacks
                                let priceText = '';
                                const proposalPrice = document.querySelector('#vehicleSendProposalPrice');
                                if (proposalPrice && proposalPrice.textContent) {
                                    priceText = proposalPrice.textContent.trim();
                                }
                                if (!priceText) {
                                    const announcedBox = document.querySelector('.VehicleDetailsFipe__price--announced');
                                    if (announcedBox) {
                                        const t = (announcedBox.innerText || announcedBox.textContent || '').replace(/\\s+/g, ' ').trim();
                                        const m1 = t.match(/R\\$\\s*[\\d\\.]+(?:,\\d{2})?/);
                                        if (m1) {
                                            priceText = m1[0];
                                        } else {
                                            const m2 = t.match(/\\b\\d{1,3}(?:\\.\\d{3})+\\b/);
                                            if (m2) priceText = m2[0];
                                        }
                                    }
                                }
                                if (!priceText) {
                                    const priceEl = document.querySelector('.VehicleDetailsFipe__price--announced .VehicleDetailsFipe__price__value') ||
                                                    document.querySelector('.VehicleDetailsFipe__price__value') ||
                                                    document.querySelector('[class*="price"] strong');
                                    if (priceEl) priceText = (priceEl.textContent || '').trim();
                                }
                                if (priceText) result.price = priceText;
                                // FIPE WEBMOTORS (bônus)
                                const fipeRaw = getText('.VehicleDetailsFipe__price-fipe .VehicleDetailsFipe__price__value') ||
                                    getText('.VehicleDetailsFipe__price-fipe strong.VehicleDetailsFipe__price__value');
                                if (fipeRaw) result.fipe_webmotors = fipeRaw;
                                // PREÇO (fallback): JSON-LD + meta tags
                                if (!result.price) {
                                    const ld = document.querySelectorAll('script[type="application/ld+json"]');
                                    for (const s of ld) {
                                        try {
                                            const txt = (s.textContent || '').trim();
                                            if (!txt) continue;
                                            const j = JSON.parse(txt);
                                            const items = Array.isArray(j) ? j : [j];
                                            for (const it of items) {
                                                const offers = it && it.offers;
                                                const off = Array.isArray(offers) ? offers[0] : offers;
                                                const p = off && (off.price != null ? off.price : (off.priceSpecification && off.priceSpecification.price));
                                                if (p != null && String(p).trim()) {
                                                    const v = String(p).trim().replace(/\\D/g, '');
                                                    if (v && v.length >= 4) {
                                                        result.price = 'R$ ' + v.replace(/\\B(?=(\\d{3})+(?!\\d))/g, '.');
                                                        break;
                                                    }
                                                }
                                            }
                                            if (result.price) break;
                                        } catch (e) {}
                                    }
                                }
                                if (!result.price) {
                                    const meta = document.querySelector('meta[property="product:price:amount"]') ||
                                                 document.querySelector('meta[property="og:price:amount"]') ||
                                                 document.querySelector('meta[name="price"]');
                                    const v = meta ? (meta.getAttribute('content') || '').trim() : '';
                                    if (v) {
                                        const digits = v.replace(/\\D/g, '');
                                        if (digits && digits.length >= 4) {
                                            result.price = 'R$ ' + digits.replace(/\\B(?=(\\d{3})+(?!\\d))/g, '.');
                                        }
                                    }
                                }
                                
                                // Ano (VehiclePrincipalInformationYear - ID)
                                const yearEl = document.querySelector('#VehiclePrincipalInformationYear') ||
                                               document.querySelector('[id*="Year"]');
                                if (yearEl) result.year = yearEl.textContent.trim();
                                
                                // KM: 1) JSON-LD mileageFromOdometer.value, 2) __INITIAL_STATE__.ad.vehicle.odometer, 3) DOM
                                const ldKm = document.querySelectorAll('script[type="application/ld+json"]');
                                for (const script of ldKm) {
                                    try {
                                        const content = (script.textContent || '').trim();
                                        if (content.indexOf('mileageFromOdometer') === -1) continue;
                                        const data = JSON.parse(content);
                                        const items = Array.isArray(data) ? data : [data];
                                        for (const item of items) {
                                            const m = item.mileageFromOdometer;
                                            const val = m && (m.value != null ? m.value : m);
                                            if (typeof val === 'number' && !isNaN(val) && val >= 0) {
                                                result.km = String(val);
                                                break;
                                            }
                                            if (typeof val === 'string' && val.trim()) result.km = val.trim();
                                        }
                                        if (result.km) break;
                                    } catch (e) {}
                                }
                                if (!result.km) {
                                    try {
                                        const state = window.__INITIAL_STATE__;
                                        const odometer = state && state.ad && state.ad.vehicle && state.ad.vehicle.odometer;
                                        if (odometer != null && odometer !== '') {
                                            const num = typeof odometer === 'number' ? odometer : parseInt(odometer, 10);
                                            if (!isNaN(num) && num >= 0) result.km = String(num);
                                        }
                                    } catch (e) {}
                                }
                                if (!result.km) {
                                    const kmEl = document.querySelector('#VehiclePrincipalInformatiOnodometer') ||
                                                 document.querySelector('#VehiclePrincipalInformationOdometer');
                                    if (kmEl) result.km = kmEl.textContent.trim();
                                    if (!result.km) {
                                        const kmEl2 = document.querySelector('[id*="odometer"]');
                                        if (kmEl2) result.km = kmEl2.textContent.trim();
                                    }
                                }
                                if (!result.km) {
                                    const listItems = document.querySelectorAll('.VehicleDetails__list__item, li');
                                    for (const li of listItems) {
                                        const titleEl = li.querySelector('.VehicleDetails__list__item__title, h2');
                                        if (titleEl && titleEl.textContent.trim() === 'KM') {
                                            const val = li.querySelector('.VehicleDetails__list__item__value, strong');
                                            if (val && val.textContent.trim()) { result.km = val.textContent.trim(); break; }
                                        }
                                    }
                                }
                                if (!result.km) {
                                    const nodes = Array.from(document.querySelectorAll('*')).filter(e => e && (e.textContent || '').trim() === 'KM');
                                    for (const n of nodes) {
                                        let v = n.nextElementSibling && n.nextElementSibling.textContent ? n.nextElementSibling.textContent.trim() : '';
                                        if (!v) {
                                            const card = n.closest('li, div, section');
                                            const cardText = card ? (card.textContent || '') : '';
                                            const m = cardText.match(/\\b(\\d{1,3}(?:\\.\\d{3})+)\\b/);
                                            if (m) { result.km = m[1]; break; }
                                        } else {
                                            result.km = v;
                                            break;
                                        }
                                    }
                                }
                                
                                // Cidade (VehiclePrincipalInformationLocation - ID)
                                const cityEl = document.querySelector('#VehiclePrincipalInformationLocation') ||
                                              document.querySelector('[id*="Location"]');
                                if (cityEl) result.city = cityEl.textContent.trim();
                                
                                // Descrição (pode estar em várias tags)
                                const descEl = document.querySelector('[class*="description"]') ||
                                               document.querySelector('.VehicleDetails__header__description') ||
                                               document.querySelector('p');
                                if (descEl) result.description = descEl.textContent.trim();
                                
                                // Imagem principal (carousel)
                                const imgEl = document.querySelector('[data-testid="carousel-item-0"] img') ||
                                            document.querySelector('.DetailCarousel__container__items__photo') ||
                                            document.querySelector('img[alt*="carro"]');
                                if (imgEl) result.image_url = imgEl.src || imgEl.getAttribute('data-src') || '';
                                
                                return result;
                            }
                        """)
                        
                        # KM: 1) DOM por ID (desktop e mobile quando existir), 2) estado JS
                        km = None
                        try:
                            odometer = page.locator("#VehiclePrincipalInformatiOnodometer")
                            if odometer.count() > 0:
                                raw = (odometer.inner_text() or "").strip()
                                raw_digits = raw.replace(".", "").replace(",", "")
                                if raw_digits.isdigit():
                                    km = int(raw_digits)
                        except Exception:
                            pass
                        if km is None:
                            try:
                                km_text = page.evaluate("""
                                () => {
                                    try {
                                        const s = window.__INITIAL_STATE__;
                                        const v = s && s.ad && s.ad.vehicle && s.ad.vehicle.odometer;
                                        return (v === undefined || v === null) ? "" : String(v);
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
                        _log("[DEBUG-WM] km=%s url=%s" % (km, link[:70]))
                        
                        # Processar dados extraídos
                        title = data.get('title', '').strip()
                        price_text = (data.get("price") or "").strip()
                        # Normaliza quando o DOM entrega só o número (ex.: "115.990") sem "R$"; extract_price() só entende "R$"
                        if price_text and ("R$" not in price_text and "r$" not in price_text):
                            digits = re.sub(r"\D", "", price_text)
                            if digits and len(digits) >= 4:
                                try:
                                    n = int(digits)
                                    price_text = "R$ " + f"{n:,}".replace(",", ".")
                                except Exception:
                                    pass
                        data["price"] = price_text
                        fipe_text = (data.get("fipe_webmotors") or "").strip()
                        if fipe_text and "R$" not in fipe_text:
                            digits = "".join(ch for ch in fipe_text if ch.isdigit())
                            if len(digits) >= 4:
                                fipe_text = "R$ " + f"{int(digits):,}".replace(",", ".")
                        data["fipe_webmotors"] = fipe_text
                        # --- Fallbacks quando preço ainda vazio (locator DOM, page.content) ---
                        if not price_text:
                            try:
                                price_loc = page.locator("#vehicleSendProposalPrice, [id*='SendProposalPrice']")
                                if price_loc.count() > 0:
                                    price_loc.first.scroll_into_view_if_needed()
                                    page.wait_for_timeout(350)
                                    price_text = (price_loc.first.inner_text() or "").strip()
                            except Exception:
                                pass
                        if price_text:
                            m = re.search(r"R\$\s*[\d\.\,]+", price_text)
                            if m:
                                price_text = m.group(0)
                        if not price_text:
                            try:
                                html = page.content()
                                m = re.search(r'id="vehicleSendProposalPrice"[^>]*>\s*(R\$\s*[\d\.\,]+)', html, re.I)
                                if m:
                                    price_text = m.group(1).strip()
                            except Exception:
                                pass
                        if not price_text:
                            try:
                                html_content = page.content()
                                m = re.search(
                                    r'VehicleDetailsFipe__price--announced.*?VehicleDetailsFipe__price__value[^>]*>\s*(R\$\s*[\d\.\,]+)',
                                    html_content,
                                    re.IGNORECASE | re.DOTALL,
                                )
                                if m:
                                    price_text = m.group(1).strip()
                                if not price_text:
                                    m = re.search(
                                        r'VehicleDetailsFipe__price--announced.*?VehicleDetailsFipe__price__value[^>]*>\s*([\d\.\,]+)',
                                        html_content,
                                        re.IGNORECASE | re.DOTALL,
                                    )
                                    if m:
                                        price_text = m.group(1).strip()
                            except Exception:
                                pass
                        if not price_text:
                            try:
                                html_content = page.content()
                                candidates = []
                                for m in re.finditer(r'R\$\s*\d{1,3}(?:\.\d{3})+|R\$\s*\d{4,}', html_content):
                                    s = m.group(0)
                                    start = max(0, m.start() - 40)
                                    end = min(len(html_content), m.end() + 40)
                                    around = html_content[start:end].lower()
                                    if "parcela" in around or "parcelas" in around or "mês" in around or "mes" in around:
                                        continue
                                    candidates.append(s)
                                if candidates:
                                    def _to_num(x):
                                        return int(re.sub(r'\D', '', x) or "0")
                                    price_text = max(candidates, key=_to_num).strip()
                            except Exception:
                                pass
                        data["price"] = price_text
                        # --- FIM FIX PREÇO ---
                        year_text = data.get('year', '').strip()
                        description = data.get('description', '').strip()
                        city = data.get('city', '').strip()
                        image_url = data.get('image_url', '').strip()
                        
                        # Não usar título/descrição que sejam JSON (ex.: pageProps do Next.js)
                        def _is_json_like(s):
                            if not s or len(s) < 20:
                                return False
                            s = s.strip()
                            if s.startswith('{') or '"pageProps"' in s or '"props"' in s:
                                return True
                            return False
                        if _is_json_like(title):
                            title = ""
                        if _is_json_like(description):
                            description = ""
                        
                        # Extrair valores numéricos
                        price = extract_price(price_text or title or description)
                        year = extract_year(year_text or title or description)
                        _log("[DEBUG-WM] price_text='%s' price=%s url=%s" % ((price_text or "")[:40], price, link[:70]))
                        
                        if not title:
                            # Tentar extrair do título da página (não é JSON)
                            page_title = (page.title() or "").strip()
                            if page_title and not _is_json_like(page_title):
                                title = page_title[:200]
                            if not title:
                                title = "Anúncio Webmotors"
                        
                        if not price:
                            _log("Scan: aviso - sem preço em %s" % link[:50])
                        fipe_webmotors = extract_price(data.get("fipe_webmotors") or "") if data.get("fipe_webmotors") else None
                        listing = {
                            "url": link,
                            "title": title,
                            "price": price,
                            "year": year,
                            "km": km,
                            "description": description,
                            "city": city,
                            "image_url": image_url,
                            "source": "webmotors",
                            "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "fipe_webmotors": fipe_webmotors,
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
                        consecutive_failures = 0  # sucesso: reset para não pular o restante
                    
                        time.sleep(1)  # Delay entre requisições
                        
                    except Exception as e:
                        errors_count += 1
                        consecutive_failures += 1
                        error_str = str(e).lower()
                        
                        # Log detalhado do tipo de erro
                        if "504" in error_str or "cloudfront" in error_str:
                            _log("❌ Scan Webmotors: erro 504 CloudFront em %s - servidor sobrecarregado" % link[:50])
                        elif "502" in error_str or "503" in error_str:
                            _log("❌ Scan Webmotors: erro %s em %s - servidor temporariamente indisponível" % (error_str[:10], link[:50]))
                        elif "timeout" in error_str or "timed_out" in error_str:
                            _log("❌ Scan Webmotors: timeout em %s - conexão lenta ou servidor não respondeu" % link[:50])
                        elif "net::" in error_str or "network" in error_str:
                            _log("❌ Scan Webmotors: erro de rede em %s - problema de conexão" % link[:50])
                        else:
                            _log("❌ Scan Webmotors: erro em %s - %s" % (link[:50], str(e)[:200]))
                        
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
        out_file = out_dir / "listings_webmotors.json"
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(listings, f, indent=2, ensure_ascii=False)
        _log("Scan: %s anúncios salvos em %s" % (len(listings), out_file))
    except Exception as e:
        _log("Scan: erro ao salvar lista - %s" % e)
    
    _log("Scan: concluído (OK=%s, erros=%s)" % (len(listings), errors_count))
    return (listings, errors_count)
