#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AutoRadar - Marketplace Bot (versão estável mesclada)
Ponto de entrada principal que orquestra todo o pipeline.
Created by Igor Avelar - avelar.igor@gmail.com
"""

import sys
import os
import json
import time
from pathlib import Path

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
CHROME_PROFILE_DIR = BASE_DIR / "chrome_login_profile"

# Log em arquivo desde o início (para debug)
try:
    from log_config import setup_logging, get_logger
    setup_logging()
except Exception:
    pass

def _log(msg, level="info"):
    try:
        get_logger().info(msg)
    except Exception:
        print(msg)


def _close_chrome_opened_by_app():
    """Encerra APENAS processos do Chrome que usam o perfil do app (caminho completo).
    Não toca no Chrome principal do usuário (outro perfil)."""
    if sys.platform != "win32":
        return
    try:
        profile_path = str(CHROME_PROFILE_DIR.resolve())
        import subprocess
        # Passar o caminho como argumento para evitar escape; só matar Chrome com esse perfil exato
        ps_script = (
            "param($ProfilePath); "
            "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" -ErrorAction SilentlyContinue | "
            "Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($ProfilePath) -ge 0 } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        cmd = ["powershell", "-NoProfile", "-Command", ps_script, "-ProfilePath", profile_path]
        subprocess.run(cmd, capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW if getattr(subprocess, "CREATE_NO_WINDOW", 0) else 0)
        _log("Chrome: processos do perfil do app encerrados (se houver).")
    except Exception as e:
        _log("Chrome: aviso ao encerrar processos - %s" % e)

try:
    from progress_ui import ProgressWindow
    from collect_links_mobile import collect_links, get_shared_browser
    from scan_mobile import scan_listings
    from consolidate_listings import consolidate_all_listings
    from ranking_mvp import main as ranking_main, write_ranking_report, evaluate_one_listing, build_ranking_with_batch_ia, build_ranking_with_rejected, _get_fipe_api_func
    from path_utils import get_ui_dir, get_out_dir
except ImportError as e:
    print(f"❌ Erro ao importar módulos principais: {e}")
    print("Certifique-se de que todos os arquivos .py estão na pasta do projeto.")
    sys.exit(1)

# Webmotors (opcional - não bloqueia o pipeline se falhar)
WEBMOTORS_AVAILABLE = False
try:
    from collect_links_webmotors import collect_links as collect_links_webmotors
    from scan_webmotors import scan_listings as scan_listings_webmotors
    WEBMOTORS_AVAILABLE = True
    _log("Módulo Webmotors carregado com sucesso")
except ImportError as e:
    _log("⚠️ Webmotors não disponível (módulo não encontrado): %s" % e)
    WEBMOTORS_AVAILABLE = False
except Exception as e:
    _log("⚠️ Erro ao carregar módulo Webmotors: %s" % e)
    WEBMOTORS_AVAILABLE = False

# Mobiauto (opcional - não bloqueia o pipeline se falhar)
MOBIAUTO_AVAILABLE = False
try:
    from collect_links_mobiauto import collect_links as collect_links_mobiauto
    from scan_mobiauto import scan_listings as scan_listings_mobiauto
    MOBIAUTO_AVAILABLE = True
    _log("Módulo Mobiauto carregado com sucesso")
except ImportError as e:
    _log("⚠️ Mobiauto não disponível (módulo não encontrado): %s" % e)
    MOBIAUTO_AVAILABLE = False
except Exception as e:
    _log("⚠️ Erro ao carregar módulo Mobiauto: %s" % e)
    MOBIAUTO_AVAILABLE = False

# OLX (opcional - não bloqueia o pipeline se falhar)
OLX_AVAILABLE = False
try:
    from collect_links_olx import collect_links as collect_links_olx
    from scan_olx import scan_listings as scan_listings_olx
    OLX_AVAILABLE = True
    _log("Módulo OLX carregado com sucesso")
except ImportError as e:
    _log("⚠️ OLX não disponível (módulo não encontrado): %s" % e)
    OLX_AVAILABLE = False
except Exception as e:
    _log("⚠️ Erro ao carregar módulo OLX: %s" % e)
    OLX_AVAILABLE = False


PREFS_FILE = BASE_DIR / "user_preferences.json"

# Valores padrão: Montes Claros MG, sem limite de preço, margem mínima R$ 5.000, rodar a cada 60 min.
# scan_cache_days: re-escanar URL só se último scan tiver mais de X dias (0 = sempre re-escanar).
# Edite user_preferences.json para alterar (ex.: margin_min_reais, city, state, run_every_minutes).
DEFAULT_PREFS = {
    "city": "Montes Claros",
    "state": "MG",
    "price_min": 0,
    "price_max": 0,
    "margin_min_reais": 5000,
    "vehicle_types": {"car": True, "motorcycle": True, "truck": True},
    "run_every_minutes": 30,
    "scan_cache_days": 30,
    "dev_reload_modules": False,  # true = recarrega módulos a cada pipeline (útil em dev; produção deixa false)
    "telegram_daily_reports": {"enabled": False},  # true = log de envios (parciais 12h/19h, recap 08h)
}


def ensure_default_preferences():
    """Cria user_preferences.json com valores padrão se não existir. Não sobrescreve arquivo existente."""
    if PREFS_FILE.exists():
        return
    try:
        PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PREFS_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_PREFS, f, indent=2, ensure_ascii=False)
        _log("Criado %s com valores padrão (Montes Claros, MG; sem limite de preço; margem mín. R$ 5.000)" % PREFS_FILE.name)
    except Exception as e:
        _log("Erro ao criar preferências padrão: %s" % e)


def load_preferences():
    ensure_default_preferences()
    if PREFS_FILE.exists():
        try:
            with open(PREFS_FILE, 'r', encoding='utf-8') as f:
                prefs = json.load(f)
            # Garantir chaves essenciais com padrão (e preencher vazios para localização)
            for k, v in DEFAULT_PREFS.items():
                if k not in prefs:
                    prefs[k] = v
                elif k in ("city", "state") and not (prefs.get(k) or "").strip():
                    prefs[k] = v
            return prefs
        except Exception as e:
            _log("Erro ao carregar preferências: %s" % e)
    return dict(DEFAULT_PREFS)


def _fipe_update_background():
    """Thread em segundo plano: se passaram 30 dias desde a última atualização da FIPE, roda o download."""
    try:
        from fipe_update_if_due import run_update_if_due
        if run_update_if_due(in_process=True):
            _log("Tabela FIPE atualizada em segundo plano (a cada 30 dias).")
    except Exception as e:
        _log("FIPE atualização em segundo plano: %s" % e)


def _get_interval_seconds(preferences):
    """Intervalo em segundos para próxima execução (run_every_minutes em user_preferences.json)."""
    minutes = int(preferences.get("run_every_minutes", 60))
    return max(1, min(1440, minutes)) * 60  # entre 1 min e 24 h


def _load_ranking_config():
    """Carrega FIPE, keywords e preferências para o worker de ranking. Retorna (fipe_db, keywords_avoid, margin_min_reais, vehicle_types)."""
    out_dir = get_out_dir()
    fipe_file = out_dir / "fipe_db_norm.json"
    fipe_db = {}
    if fipe_file.exists():
        try:
            with open(fipe_file, 'r', encoding='utf-8') as f:
                fipe_db = json.load(f)
        except Exception:
            pass
    # Termos de golpe sempre bloqueados (financiamento isca)
    keywords_avoid = [
        "ACEITAMOS FINANCIAMENTO",
        "ENTRADA: R$",
        "PARCELAS: R$",
    ]
    keywords_file = BASE_DIR / "keywords_golpe.txt"
    if keywords_file.exists():
        try:
            with open(keywords_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and line not in keywords_avoid:
                        keywords_avoid.append(line)
        except Exception:
            pass
    margin_min_reais = float(DEFAULT_PREFS.get("margin_min_reais", 5000))
    vehicle_types = dict(DEFAULT_PREFS.get("vehicle_types", {"car": True, "motorcycle": True, "truck": True}))
    if PREFS_FILE.exists():
        try:
            with open(PREFS_FILE, 'r', encoding='utf-8') as f:
                prefs = json.load(f)
                margin_min_reais = float(prefs.get("margin_min_reais", margin_min_reais))
                vehicle_types = prefs.get("vehicle_types", vehicle_types)
        except Exception:
            pass
    return fipe_db, keywords_avoid, margin_min_reais, vehicle_types


def _ranking_worker(listing_queue, results_list, results_lock, fipe_db, keywords_avoid, margin_min_reais, vehicle_types, progress_callback=None, total=0, drop_reasons=None):
    """Consome anúncios da fila, avalia com FIPE/IA e adiciona oportunidades à results_list."""
    get_fipe = _get_fipe_api_func()
    processed = 0
    while True:
        item = listing_queue.get()
        try:
            if item is None:
                return
            r = evaluate_one_listing(
                item, fipe_db, keywords_avoid, margin_min_reais, vehicle_types, get_fipe,
                drop_reasons=drop_reasons
            )
            if r is not None:
                with results_lock:
                    results_list.append(r)
        finally:
            listing_queue.task_done()
            if item is not None:
                processed += 1
                if progress_callback and total > 0:
                    try:
                        progress_callback(processed, total)
                    except Exception:
                        pass


def _load_saved_listings():
    """Carrega listings salvos dos arquivos JSON (checkpoint recovery)"""
    out_dir = get_out_dir()
    all_listings = []
    
    # Carregar Facebook
    fb_file = out_dir / "listings_facebook.json"
    if fb_file.exists():
        try:
            with open(fb_file, 'r', encoding='utf-8') as f:
                fb_list = json.load(f)
                if isinstance(fb_list, list):
                    all_listings.extend(fb_list)
                    _log("✅ Checkpoint: carregados %d anúncios do Facebook" % len(fb_list))
        except Exception as e:
            _log("⚠️ Erro ao carregar checkpoint Facebook: %s" % e)
    
    # Carregar Webmotors
    wm_file = out_dir / "listings_webmotors.json"
    if wm_file.exists():
        try:
            with open(wm_file, 'r', encoding='utf-8') as f:
                wm_list = json.load(f)
                if isinstance(wm_list, list):
                    all_listings.extend(wm_list)
                    _log("✅ Checkpoint: carregados %d anúncios da Webmotors" % len(wm_list))
        except Exception as e:
            _log("⚠️ Erro ao carregar checkpoint Webmotors: %s" % e)
    
    # Carregar Mobiauto
    ma_file = out_dir / "listings_mobiauto.json"
    if ma_file.exists():
        try:
            with open(ma_file, 'r', encoding='utf-8') as f:
                ma_list = json.load(f)
                if isinstance(ma_list, list):
                    all_listings.extend(ma_list)
                    _log("✅ Checkpoint: carregados %d anúncios da Mobiauto" % len(ma_list))
        except Exception as e:
            _log("⚠️ Erro ao carregar checkpoint Mobiauto: %s" % e)
    
    # Carregar OLX
    olx_file = out_dir / "listings_olx.json"
    if olx_file.exists():
        try:
            with open(olx_file, 'r', encoding='utf-8') as f:
                olx_list = json.load(f)
                if isinstance(olx_list, list):
                    all_listings.extend(olx_list)
                    _log("✅ Checkpoint: carregados %d anúncios da OLX" % len(olx_list))
        except Exception as e:
            _log("⚠️ Erro ao carregar checkpoint OLX: %s" % e)
    
    # Carregar checkpoint geral (se existir)
    checkpoint_file = out_dir / "checkpoint_listings.json"
    if checkpoint_file.exists():
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                checkpoint_list = json.load(f)
                if isinstance(checkpoint_list, list):
                    # Adicionar apenas se não estiverem duplicados
                    existing_urls = {l.get('url') for l in all_listings if l.get('url')}
                    new_items = [l for l in checkpoint_list if l.get('url') not in existing_urls]
                    all_listings.extend(new_items)
                    if new_items:
                        _log("✅ Checkpoint: carregados %d anúncios adicionais do checkpoint geral" % len(new_items))
        except Exception as e:
            _log("⚠️ Erro ao carregar checkpoint geral: %s" % e)
    
    return all_listings


def _reload_modules():
    """Recarrega módulos Python para aplicar mudanças sem reiniciar o app."""
    try:
        import importlib
        import sys
        
        # Módulos que podem ser modificados durante desenvolvimento
        modules_to_reload = [
            'ranking_mvp',
            'send_telegram',
            'collect_links_olx',
            'scan_olx',
            'collect_links_webmotors',
            'scan_webmotors',
            'collect_links_mobiauto',
            'scan_mobiauto',
        ]
        
        reloaded = []
        for module_name in modules_to_reload:
            if module_name in sys.modules:
                try:
                    importlib.reload(sys.modules[module_name])
                    reloaded.append(module_name)
                except Exception as e:
                    _log("⚠️ Não foi possível recarregar %s: %s" % (module_name, e))
        
        if reloaded:
            _log("🔄 Módulos recarregados: %s" % ", ".join(reloaded))
        
        # Reimportar funções principais após reload
        global build_ranking_with_rejected, write_ranking_report
        from ranking_mvp import build_ranking_with_rejected, write_ranking_report
    except Exception as e:
        _log("⚠️ Erro ao recarregar módulos: %s" % e)


def _run_pipeline_once(progress_window, preferences):
    """
    Executa uma vez: coleta, scan (em paralelo com avaliação FIPE/IA), consolidação, relatório.
    Retorna (links, scan_count, scan_errors, ranking_count) ou None se falhar antes do scan.
    Se existir checkpoint_listings.json com dados (pipeline anterior não finalizou), retoma
    de onde parou: carrega os anúncios já escaneados e executa apenas o ranking.
    """
    # Recarregar módulos só se dev_reload_modules=true (produção: default false, evita custo)
    if preferences.get("dev_reload_modules", False):
        _reload_modules()

    from path_utils import get_out_dir
    checkpoint_file = get_out_dir() / "checkpoint_listings.json"
    # SEMPRE retomar do checkpoint quando existir (pipeline anterior falhou antes do ranking)
    if checkpoint_file.exists():
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                all_listings = json.load(f)
            if not isinstance(all_listings, list):
                all_listings = []
        except Exception as e:
            _log("Erro ao carregar checkpoint: %s" % e)
            all_listings = []
        if all_listings:
            _log("Modo: apenas ranking a partir do checkpoint (%d anúncios)" % len(all_listings))
            progress_window.update_status("Carregando checkpoint e executando apenas ranking...")
            progress_window.update_progress(15, 100)
            fipe_db, keywords_avoid, margin_min_reais, vehicle_types = _load_ranking_config()
            get_fipe = _get_fipe_api_func()
            drop_reasons = {}
            _last_progress_time = [0.0]
            def _avaliacao_progress(c, t):
                import time as _time
                now = _time.time()
                if t and (c == 1 or c == t or c % 5 == 0 or (now - _last_progress_time[0]) >= 0.3):
                    _last_progress_time[0] = now
                    pct = 70 + (25 * c / t) if t else 70
                    progress_window.update_progress(pct, 100)
                    progress_window.update_status("Avaliando oportunidades (FIPE/IA)... %d/%d" % (c, t) if t else "Avaliando oportunidades (FIPE/IA)...")
            progress_window.update_status("Avaliando oportunidades (FIPE/IA)... 0/%d" % len(all_listings))
            progress_window.update_progress(70, 100)
            ranking, rejected = [], []
            try:
                ranking, rejected = build_ranking_with_rejected(
                    all_listings, fipe_db, keywords_avoid, margin_min_reais, vehicle_types,
                    get_fipe, drop_reasons, progress_callback=_avaliacao_progress,
                )
            except Exception as e:
                _log("Erro no ranking (modo checkpoint): %s" % e)
                import traceback
                _log(traceback.format_exc())
                raise
            ranking_count = len(ranking)
            progress_window.update_status("Consolidando listas...")
            progress_window.update_progress(95, 100)
            consolidate_all_listings()
            progress_window.update_status("Gerando relatório...")
            progress_window.update_progress(98, 100)
            write_ranking_report(ranking, get_out_dir(), get_ui_dir(), rejected=rejected)
            progress_window.update_progress(100, 100)
            _log("Ranking gerado (checkpoint): %s oportunidades" % ranking_count)
            try:
                progress_window._refresh_telegram_info()
            except Exception:
                pass
            progress_window.update_status("Concluído. %s oportunidades encontradas." % ranking_count)
            # Remover checkpoint para a próxima execução fazer coleta+scan completa
            try:
                checkpoint_file.unlink(missing_ok=True)
                _log("Checkpoint removido; próxima execução fará coleta e scan completos.")
            except Exception:
                pass
            return ([], len(all_listings), 0, ranking_count)
        # checkpoint vazio ou inválido; segue o fluxo normal
        _log("Checkpoint vazio ou inválido; executando pipeline completo.")
    
    import queue
    import threading
    from collect_links_mobile import collect_links, BROWSER_STATE_FILE
    
    # Inicializar variável olx_links no escopo correto
    olx_links = []

    # Log de status dos módulos disponíveis
    _log("=" * 70)
    _log("📋 Status dos módulos: Facebook=✅, Webmotors=%s, Mobiauto=%s, OLX=%s" % (
        "✅" if WEBMOTORS_AVAILABLE else "❌",
        "✅" if MOBIAUTO_AVAILABLE else "❌",
        "✅" if OLX_AVAILABLE else "❌"
    ))
    _log("=" * 70)

    def _coleta_progress(c, t):
        progress_window.update_progress(c, t)
        progress_window.update_status("Coletando links... %d/%d" % (c, t) if t else "Coletando links...")

    links = []
    shared_browser = None
    use_cdp = False
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sync_playwright = None
    city = (preferences.get('city') or "").strip() or DEFAULT_PREFS.get("city", "Montes Claros")
    state = (preferences.get('state') or "").strip() or DEFAULT_PREFS.get("state", "MG")

    if sync_playwright is not None:
        with sync_playwright() as p:
            shared_browser, use_cdp = get_shared_browser(p)
            links = collect_links(
                city=city,
                state=state,
                price_min=preferences.get('price_min', 0),
                price_max=preferences.get('price_max', 0),
                progress_callback=_coleta_progress,
                wait_for_login_callback=progress_window.wait_for_login,
                marketplace_region_id=preferences.get('marketplace_region_id', ''),
                status_message_callback=lambda msg: progress_window.update_status(msg),
                is_aborted_callback=lambda: getattr(progress_window, '_closing', False),
                browser=shared_browser,
            )
            _log("Facebook: %s links coletados" % len(links))
            webmotors_links = []
            if WEBMOTORS_AVAILABLE and preferences.get('webmotors', {}).get('enabled', False):
                _log("Webmotors: coletando links...")
                progress_window.update_status("Coletando links da Webmotors...")
                try:
                    webmotors_links = collect_links_webmotors(
                        search_url=(preferences.get('webmotors', {}).get('search_url') or '').strip(),
                        progress_callback=_coleta_progress,
                        status_message_callback=lambda msg: progress_window.update_status(msg),
                        is_aborted_callback=lambda: getattr(progress_window, '_closing', False),
                        browser=shared_browser,
                    )
                    _log("Webmotors: %s links coletados" % len(webmotors_links))
                except Exception as e:
                    _log("Webmotors: erro ao coletar links - %s" % e)
            mobiauto_links = []
            mobiauto_enabled = preferences.get('mobiauto', {}).get('enabled', False)
            _log("Mobiauto: disponível=%s, habilitado=%s" % (MOBIAUTO_AVAILABLE, mobiauto_enabled))
            if MOBIAUTO_AVAILABLE and mobiauto_enabled:
                _log("Mobiauto: iniciando coleta de links (habilitado nas preferências)")
                progress_window.update_status("Coletando links da Mobiauto...")
                try:
                    mobiauto_search_url = (preferences.get('mobiauto', {}).get('search_url') or '').strip()
                    _log("Mobiauto: URL de busca: %s" % (mobiauto_search_url if mobiauto_search_url else "(padrão)"))
                    mobiauto_links = collect_links_mobiauto(
                        search_url=mobiauto_search_url,
                        progress_callback=_coleta_progress,
                        status_message_callback=lambda msg: progress_window.update_status(msg),
                        is_aborted_callback=lambda: getattr(progress_window, '_closing', False),
                        browser=shared_browser,
                    )
                    _log("✅ Mobiauto: coleta concluída com sucesso - %s links coletados" % len(mobiauto_links))
                except Exception as e:
                    _log("❌ Mobiauto: ERRO ao coletar links - %s" % e)
                    import traceback
                    _log("Mobiauto: traceback completo:\n%s" % traceback.format_exc())
                    mobiauto_links = []
            elif MOBIAUTO_AVAILABLE and not mobiauto_enabled:
                _log("⚠️ Mobiauto: módulo disponível mas DESABILITADO nas preferências")
            elif not MOBIAUTO_AVAILABLE:
                _log("⚠️ Mobiauto: módulo NÃO DISPONÍVEL")
            # OLX: coleta em thread paralela com navegador próprio (own_browser_only=True).
            # Assim: (1) não bloqueia o pipeline se a OLX travar/bloquear; (2) evita "Cannot switch to a different thread"
            # ao não compartilhar o shared_browser; (3) maior probabilidade de bloqueio na OLX fica isolada.
            olx_links = []
            olx_thread = None
            olx_result = [None, None]  # [links, error]
            olx_enabled = preferences.get('olx', {}).get('enabled', True)
            _log("OLX: disponível=%s, habilitado=%s" % (OLX_AVAILABLE, olx_enabled))
            if OLX_AVAILABLE and olx_enabled:
                _log("OLX: iniciando coleta em paralelo (navegador próprio, isolado)...")
                progress_window.update_status("Coletando links da OLX (em paralelo)...")
                def _olx_collect_worker():
                    try:
                        olx_search_url = (preferences.get('olx', {}).get('search_url') or '').strip()
                        if not olx_search_url:
                            olx_search_url = "https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/estado-mg/regiao-de-montes-claros-e-diamantina/montes-claros?sf=1"
                        _log("OLX: URL de busca: %s" % olx_search_url)
                        olx_result[0] = collect_links_olx(
                            search_url=olx_search_url,
                            progress_callback=None,
                            status_message_callback=None,
                            is_aborted_callback=lambda: getattr(progress_window, '_closing', False),
                            max_pages=2,
                            browser=None,
                            own_browser_only=True,
                        )
                        _log("✅ OLX: coleta concluída - %s links coletados" % len(olx_result[0] or []))
                    except Exception as e:
                        _log("❌ OLX: ERRO ao coletar links - %s" % e)
                        import traceback
                        _log("OLX: traceback completo:\n%s" % traceback.format_exc())
                        olx_result[1] = e
                olx_thread = threading.Thread(target=_olx_collect_worker, daemon=True)
                olx_thread.start()
                _log("OLX: thread de coleta iniciada (navegador próprio)")
            elif OLX_AVAILABLE and not olx_enabled:
                _log("⚠️ OLX: módulo disponível mas DESABILITADO nas preferências")
            elif not OLX_AVAILABLE:
                _log("⚠️ OLX: módulo NÃO DISPONÍVEL")
            total_links = len(links) + len(webmotors_links) + len(mobiauto_links)
            progress_window.update_progress(10, 100)
            progress_window.update_status("%d links coletados (FB: %d, WM: %d, MA: %d, OLX: coletando...)" % (total_links, len(links), len(webmotors_links), len(mobiauto_links)))
            if not total_links:
                _log("Nenhum link coletado.")
                progress_window.update_status("Nenhum link encontrado")
                _close_chrome_opened_by_app()
                return None
            fipe_db, keywords_avoid, margin_min_reais, vehicle_types = _load_ranking_config()
            get_fipe = _get_fipe_api_func()
            drop_reasons = {}
            _last_progress = [0]
            _last_progress_time = [0.0]
            def _avaliacao_progress(c, t):
                import time as _time
                now = _time.time()
                if t and (c == 1 or c == t or c % 5 == 0 or (now - _last_progress_time[0]) >= 0.3):
                    _last_progress[0] = c
                    _last_progress_time[0] = now
                    pct = 70 + (25 * c / t) if t else 70
                    progress_window.update_progress(pct, 100)
                    progress_window.update_status("Avaliando oportunidades (FIPE/IA)... %d/%d" % (c, t) if t else "Avaliando oportunidades (FIPE/IA)...")
            def _scan_progress(c, t):
                progress_window.update_progress(c, t)
                progress_window.update_status("Processando anúncios... %d/%d" % (c, t) if t else "Escaneando anúncios...")
            scan_listings_count = 0
            scan_errors = 0
            all_listings = []
            if links:
                progress_window.update_status("Processando anúncios do Facebook... 0/%d" % len(links))
                progress_window.update_progress(0, total_links)
                scan_listings_result = scan_listings(links=links, progress_callback=_scan_progress, listing_queue=None, browser=shared_browser)
                fb_list = scan_listings_result[0] if isinstance(scan_listings_result, tuple) else scan_listings_result
                fb_errors = scan_listings_result[1] if isinstance(scan_listings_result, tuple) and len(scan_listings_result) > 1 else 0
                scan_listings_count += len(fb_list)
                scan_errors += fb_errors
                all_listings.extend(fb_list or [])
                _log("Facebook scan concluído (OK=%s, erros=%s)" % (len(fb_list or []), fb_errors))
            if webmotors_links and WEBMOTORS_AVAILABLE:
                _log("Webmotors: iniciando scan de %s anúncios" % len(webmotors_links))
                progress_window.update_status("Processando anúncios da Webmotors... 0/%d" % len(webmotors_links))
                try:
                    scan_listings_result = scan_listings_webmotors(links=webmotors_links, progress_callback=_scan_progress, listing_queue=None, browser=shared_browser)
                    wm_list = scan_listings_result[0] if isinstance(scan_listings_result, tuple) else scan_listings_result
                    wm_errors = scan_listings_result[1] if isinstance(scan_listings_result, tuple) and len(scan_listings_result) > 1 else 0
                    scan_listings_count += len(wm_list or [])
                    scan_errors += wm_errors
                    all_listings.extend(wm_list or [])
                    _log("✅ Webmotors: scan concluído com sucesso (OK=%s, erros=%s)" % (len(wm_list or []), wm_errors))
                except Exception as e:
                    _log("❌ Webmotors: ERRO durante scan - %s" % e)
                    scan_errors += len(webmotors_links)
            if mobiauto_links and MOBIAUTO_AVAILABLE:
                _log("Mobiauto: iniciando scan de %s anúncios" % len(mobiauto_links))
                progress_window.update_status("Processando anúncios da Mobiauto... 0/%d" % len(mobiauto_links))
                try:
                    scan_listings_result = scan_listings_mobiauto(links=mobiauto_links, progress_callback=_scan_progress, listing_queue=None, browser=shared_browser)
                    ma_list = scan_listings_result[0] if isinstance(scan_listings_result, tuple) else scan_listings_result
                    ma_errors = scan_listings_result[1] if isinstance(scan_listings_result, tuple) and len(scan_listings_result) > 1 else 0
                    scan_listings_count += len(ma_list or [])
                    scan_errors += ma_errors
                    all_listings.extend(ma_list or [])
                    _log("✅ Mobiauto: scan concluído com sucesso (OK=%s, erros=%s)" % (len(ma_list or []), ma_errors))
                except Exception as e:
                    _log("❌ Mobiauto: ERRO durante scan - %s" % e)
                    scan_errors += len(mobiauto_links)
            # OLX: aguardar coleta em paralelo (navegador próprio da thread)
            if OLX_AVAILABLE and olx_thread:
                _log("OLX: aguardando término da coleta (timeout 5min)...")
                olx_thread.join(timeout=300)
                if olx_result[0] is not None:
                    olx_links = olx_result[0]
                    _log("✅ OLX: %s links coletados com sucesso" % len(olx_links))
                elif olx_result[1] is not None:
                    _log("❌ OLX: erro na coleta - %s" % olx_result[1])
                else:
                    _log("⚠️ OLX: timeout ou ainda processando (pipeline segue com FB+WM+MA)")
                    if olx_thread.is_alive():
                        _log("⚠️ OLX: thread ainda rodando; continuando sem links OLX desta execução.")
            if olx_links and OLX_AVAILABLE:
                _log("OLX: iniciando scan de %s anúncios" % len(olx_links))
                progress_window.update_status("Processando anúncios da OLX... 0/%d" % len(olx_links))
                try:
                    scan_listings_result = scan_listings_olx(links=olx_links, progress_callback=_scan_progress, listing_queue=None, browser=shared_browser)
                    olx_list = scan_listings_result[0] if isinstance(scan_listings_result, tuple) else scan_listings_result
                    olx_errors = scan_listings_result[1] if isinstance(scan_listings_result, tuple) and len(scan_listings_result) > 1 else 0
                    scan_listings_count += len(olx_list or [])
                    scan_errors += olx_errors
                    all_listings.extend(olx_list or [])
                    _log("✅ OLX: scan concluído com sucesso (OK=%s, erros=%s)" % (len(olx_list or []), olx_errors))
                except Exception as e:
                    _log("❌ OLX: ERRO durante scan - %s" % e)
                    scan_errors += len(olx_links)
    else:
        links = collect_links(
            city=city,
            state=state,
            price_min=preferences.get('price_min', 0),
            price_max=preferences.get('price_max', 0),
            progress_callback=_coleta_progress,
            wait_for_login_callback=progress_window.wait_for_login,
            marketplace_region_id=preferences.get('marketplace_region_id', ''),
            status_message_callback=lambda msg: progress_window.update_status(msg),
            is_aborted_callback=lambda: getattr(progress_window, '_closing', False),
            browser=None,
        )
        _log("Facebook: %s links coletados" % len(links))
        webmotors_links = []
        if WEBMOTORS_AVAILABLE and preferences.get('webmotors', {}).get('enabled', False):
            _log("Webmotors: coletando links...")
            progress_window.update_status("Coletando links da Webmotors...")
            try:
                webmotors_links = collect_links_webmotors(
                    search_url=(preferences.get('webmotors', {}).get('search_url') or '').strip(),
                    progress_callback=_coleta_progress,
                    status_message_callback=lambda msg: progress_window.update_status(msg),
                    is_aborted_callback=lambda: getattr(progress_window, '_closing', False),
                )
                _log("Webmotors: %s links coletados" % len(webmotors_links))
            except Exception as e:
                _log("Webmotors: erro ao coletar links - %s" % e)
        mobiauto_links = []
        mobiauto_enabled_2 = preferences.get('mobiauto', {}).get('enabled', False)
        _log("Mobiauto (bloco 2): disponível=%s, habilitado=%s" % (MOBIAUTO_AVAILABLE, mobiauto_enabled_2))
        if MOBIAUTO_AVAILABLE and mobiauto_enabled_2:
            _log("Mobiauto: iniciando coleta de links (habilitado nas preferências)")
            progress_window.update_status("Coletando links da Mobiauto...")
            try:
                mobiauto_search_url = (preferences.get('mobiauto', {}).get('search_url') or '').strip()
                _log("Mobiauto: URL de busca: %s" % (mobiauto_search_url if mobiauto_search_url else "(padrão)"))
                mobiauto_links = collect_links_mobiauto(
                    search_url=mobiauto_search_url,
                    progress_callback=_coleta_progress,
                    status_message_callback=lambda msg: progress_window.update_status(msg),
                    is_aborted_callback=lambda: getattr(progress_window, '_closing', False),
                )
                _log("✅ Mobiauto: coleta concluída com sucesso - %s links coletados" % len(mobiauto_links))
            except Exception as e:
                _log("❌ Mobiauto: ERRO ao coletar links - %s" % e)
                import traceback
                _log("Mobiauto: traceback completo:\n%s" % traceback.format_exc())
                mobiauto_links = []
        elif MOBIAUTO_AVAILABLE and not mobiauto_enabled_2:
            _log("⚠️ Mobiauto (bloco 2): módulo disponível mas DESABILITADO nas preferências")
        elif not MOBIAUTO_AVAILABLE:
            _log("⚠️ Mobiauto (bloco 2): módulo NÃO DISPONÍVEL")
        # OLX: coleta em thread paralela com navegador próprio (isolado)
        olx_links = []
        olx_thread_2 = None
        olx_result_2 = [None, None]
        olx_enabled_2 = preferences.get('olx', {}).get('enabled', True)
        if OLX_AVAILABLE and olx_enabled_2:
            _log("OLX: iniciando coleta em paralelo (navegador próprio)...")
            progress_window.update_status("Coletando links da OLX (em paralelo)...")
            def _olx_collect_worker_2():
                try:
                    olx_search_url = (preferences.get('olx', {}).get('search_url') or '').strip()
                    if not olx_search_url:
                        olx_search_url = "https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/estado-mg/regiao-de-montes-claros-e-diamantina/montes-claros?sf=1"
                    olx_result_2[0] = collect_links_olx(
                        search_url=olx_search_url,
                        progress_callback=None,
                        status_message_callback=None,
                        is_aborted_callback=lambda: getattr(progress_window, '_closing', False),
                        max_pages=2,
                        browser=None,
                        own_browser_only=True,
                    )
                    _log("✅ OLX: coleta concluída - %s links coletados" % len(olx_result_2[0] or []))
                except Exception as e:
                    _log("❌ OLX: ERRO ao coletar links - %s" % e)
                    import traceback
                    _log("OLX: traceback completo:\n%s" % traceback.format_exc())
                    olx_result_2[1] = e
            olx_thread_2 = threading.Thread(target=_olx_collect_worker_2, daemon=True)
            olx_thread_2.start()
        total_links = len(links) + len(webmotors_links) + len(mobiauto_links)
        progress_window.update_progress(10, 100)
        progress_window.update_status("%d links coletados (FB: %d, WM: %d, MA: %d, OLX: coletando...)" % (total_links, len(links), len(webmotors_links), len(mobiauto_links)))
        if not total_links:
            _log("Nenhum link coletado.")
            progress_window.update_status("Nenhum link encontrado")
            _close_chrome_opened_by_app()
            return None
        fipe_db, keywords_avoid, margin_min_reais, vehicle_types = _load_ranking_config()
        get_fipe = _get_fipe_api_func()
        drop_reasons = {}
        _last_progress = [0]
        _last_progress_time = [0.0]
        def _avaliacao_progress(c, t):
            import time as _time
            now = _time.time()
            if t and (c == 1 or c == t or c % 5 == 0 or (now - _last_progress_time[0]) >= 0.3):
                _last_progress[0] = c
                _last_progress_time[0] = now
                pct = 70 + (25 * c / t) if t else 70
                progress_window.update_progress(pct, 100)
                progress_window.update_status("Avaliando oportunidades (FIPE/IA)... %d/%d" % (c, t) if t else "Avaliando oportunidades (FIPE/IA)...")
        def _scan_progress(c, t):
            progress_window.update_progress(c, t)
            progress_window.update_status("Processando anúncios... %d/%d" % (c, t) if t else "Escaneando anúncios...")
        scan_listings_count = 0
        scan_errors = 0
        all_listings = []
        if links:
            progress_window.update_status("Processando anúncios do Facebook... 0/%d" % len(links))
            progress_window.update_progress(0, total_links)
            scan_listings_result = scan_listings(links=links, progress_callback=_scan_progress, listing_queue=None, browser=None)
            fb_list = scan_listings_result[0] if isinstance(scan_listings_result, tuple) else scan_listings_result
            fb_errors = scan_listings_result[1] if isinstance(scan_listings_result, tuple) and len(scan_listings_result) > 1 else 0
            scan_listings_count += len(fb_list)
            scan_errors += fb_errors
            all_listings.extend(fb_list or [])
            _log("Facebook scan concluído (OK=%s, erros=%s)" % (len(fb_list or []), fb_errors))
        if webmotors_links and WEBMOTORS_AVAILABLE:
            _log("Webmotors: iniciando scan de %s anúncios" % len(webmotors_links))
            progress_window.update_status("Processando anúncios da Webmotors... 0/%d" % len(webmotors_links))
            try:
                scan_listings_result = scan_listings_webmotors(links=webmotors_links, progress_callback=_scan_progress, listing_queue=None, browser=None)
                wm_list = scan_listings_result[0] if isinstance(scan_listings_result, tuple) else scan_listings_result
                wm_errors = scan_listings_result[1] if isinstance(scan_listings_result, tuple) and len(scan_listings_result) > 1 else 0
                scan_listings_count += len(wm_list or [])
                scan_errors += wm_errors
                all_listings.extend(wm_list or [])
                _log("✅ Webmotors: scan concluído com sucesso (OK=%s, erros=%s)" % (len(wm_list or []), wm_errors))
            except Exception as e:
                _log("❌ Webmotors: ERRO durante scan - %s" % e)
                scan_errors += len(webmotors_links)
        if mobiauto_links and MOBIAUTO_AVAILABLE:
            _log("Mobiauto: iniciando scan de %s anúncios" % len(mobiauto_links))
            progress_window.update_status("Processando anúncios da Mobiauto... 0/%d" % len(mobiauto_links))
            try:
                scan_listings_result = scan_listings_mobiauto(links=mobiauto_links, progress_callback=_scan_progress, listing_queue=None, browser=None)
                ma_list = scan_listings_result[0] if isinstance(scan_listings_result, tuple) else scan_listings_result
                ma_errors = scan_listings_result[1] if isinstance(scan_listings_result, tuple) and len(scan_listings_result) > 1 else 0
                scan_listings_count += len(ma_list or [])
                scan_errors += ma_errors
                all_listings.extend(ma_list or [])
                _log("✅ Mobiauto: scan concluído com sucesso (OK=%s, erros=%s)" % (len(ma_list or []), ma_errors))
            except Exception as e:
                _log("❌ Mobiauto: ERRO durante scan - %s" % e)
                scan_errors += len(mobiauto_links)
        # OLX (bloco 2): aguardar coleta em paralelo (navegador próprio) — fora do if Mobiauto para sempre rodar
        if OLX_AVAILABLE and olx_thread_2:
            _log("OLX (bloco 2): aguardando término da coleta (timeout 5min)...")
            olx_thread_2.join(timeout=300)
            if olx_result_2[0] is not None:
                olx_links = olx_result_2[0]
                _log("✅ OLX (bloco 2): %s links coletados" % len(olx_links))
            elif olx_result_2[1] is not None:
                _log("❌ OLX (bloco 2): erro na coleta - %s" % olx_result_2[1])
            else:
                _log("⚠️ OLX (bloco 2): timeout ou ainda processando")
        if olx_links and OLX_AVAILABLE:
            _log("OLX: iniciando scan de %s anúncios" % len(olx_links))
            progress_window.update_status("Processando anúncios da OLX... 0/%d" % len(olx_links))
            try:
                scan_listings_result = scan_listings_olx(links=olx_links, progress_callback=_scan_progress, listing_queue=None, browser=None)
                olx_list = scan_listings_result[0] if isinstance(scan_listings_result, tuple) else scan_listings_result
                olx_errors = scan_listings_result[1] if isinstance(scan_listings_result, tuple) and len(scan_listings_result) > 1 else 0
                scan_listings_count += len(olx_list or [])
                scan_errors += olx_errors
                all_listings.extend(olx_list or [])
                _log("✅ OLX: scan concluído com sucesso (OK=%s, erros=%s)" % (len(olx_list or []), olx_errors))
            except Exception as e:
                _log("❌ OLX: ERRO durante scan - %s" % e)
                scan_errors += len(olx_links)

    if mobiauto_links and not MOBIAUTO_AVAILABLE:
        _log("⚠️ Mobiauto: %s links coletados mas módulo não disponível para scan" % len(mobiauto_links))
    if webmotors_links and not WEBMOTORS_AVAILABLE:
        _log("⚠️ Webmotors: %s links coletados mas módulo não disponível para scan" % len(webmotors_links))

    _log("📊 Scan total concluído: OK=%s, erros=%s (FB: %s, WM: %s, MA: %s, OLX: %s)" % (
        scan_listings_count, scan_errors,
        len(links), len(webmotors_links), len(mobiauto_links), len(olx_links) if 'olx_links' in locals() else 0
    ))
    _log("📋 Anúncios na memória antes do ranking: %d (FB: %d, WM: %d, MA: %d, OLX: %d)" % (
        len(all_listings),
        len([l for l in all_listings if 'facebook.com' in l.get('url', '')]),
        len([l for l in all_listings if 'webmotors.com.br' in l.get('url', '')]),
        len([l for l in all_listings if 'mobiauto.com.br' in l.get('url', '')]),
        len([l for l in all_listings if 'olx.com.br' in l.get('url', '')]),
    ))

    # Se não houver listings na memória, tentar carregar dos arquivos salvos (checkpoint)
    if not all_listings:
        _log("⚠️ Nenhum listing na memória. Tentando carregar dados salvos (checkpoint)...")
        all_listings = _load_saved_listings()
        if all_listings:
            _log("✅ Carregados %d anúncios dos arquivos salvos" % len(all_listings))
            scan_listings_count = len(all_listings)
        else:
            _log("❌ Nenhum dado salvo encontrado. Nada para processar.")
            progress_window.update_status("Nenhum anúncio para processar")
            _close_chrome_opened_by_app()
            return None

    progress_window.update_status("Avaliando oportunidades (FIPE/IA)... 0/%d" % len(all_listings))
    progress_window.update_progress(70, 100)
    
    # Tentar fazer ranking, com fallback para dados salvos se houver erro
    ranking = []
    rejected = []
    try:
        ranking, rejected = build_ranking_with_rejected(
            all_listings, fipe_db, keywords_avoid, margin_min_reais, vehicle_types,
            get_fipe, drop_reasons, progress_callback=_avaliacao_progress,
        )
    except Exception as e:
        _log("❌ ERRO durante avaliação/ranking: %s" % e)
        import traceback
        _log("Traceback completo:\n%s" % traceback.format_exc())
        
        # Tentar salvar os dados coletados antes de falhar
        _log("💾 Tentando salvar dados coletados antes de falhar...")
        try:
            checkpoint_file = get_out_dir() / "checkpoint_listings.json"
            with open(checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(all_listings, f, indent=2, ensure_ascii=False)
            _log("✅ Dados salvos em checkpoint: %s" % checkpoint_file)
            progress_window.update_status("Erro no ranking. Dados salvos em checkpoint.")
        except Exception as save_err:
            _log("❌ Erro ao salvar checkpoint: %s" % save_err)
        
        # Mostrar erro na UI mas não abortar completamente
        progress_window.update_status("Erro no ranking. Verifique os logs.")
        raise  # Re-raise para que o erro seja tratado no nível superior
    ranking_count = len(ranking)
    if ranking_count == 0 and drop_reasons:
        total_drop = sum(drop_reasons.values())
        if total_drop > 0:
            _log("📋 Motivos de exclusão (0 oportunidades):")
            for reason, count in sorted(drop_reasons.items(), key=lambda x: -x[1]):
                label = {
                    "palavra_chave": "palavra-chave evitada (ex.: quitado, sinistro)",
                    "sem_fipe": "sem valor FIPE na base",
                    "margem_insuficiente": "margem abaixo do mínimo",
                    "tipo_veículo": "tipo desativado (moto/caminhão)",
                    "sem_marca": "marca não reconhecida",
                    "risco_ia": "risco de golpe (IA)",
                    "preço_suspeito": "preço muito abaixo da FIPE",
                    "sem_modelo": "não foi possível extrair modelo",
                    "sem_título_ou_ano": "sem título ou ano",
                    "sem_preço": "sem preço válido",
                    "moeda": "moeda diferente de BRL",
                }.get(reason, reason)
                _log("   • %s: %d" % (label, count))
            _log("   💡 Dica: 'quitado' e 'permuta' em keywords_golpe.txt excluem anúncios legítimos. Use Atualizar FIPE para base mais recente.")
    progress_window.update_status("Consolidando listas...")
    progress_window.update_progress(95, 100)
    consolidate_all_listings()
    progress_window.update_status("Gerando relatório...")
    progress_window.update_progress(98, 100)
    write_ranking_report(ranking, get_out_dir(), get_ui_dir(), rejected=rejected)
    progress_window.update_progress(100, 100)
    _log("Ranking gerado: %s oportunidades" % ranking_count)
    if sync_playwright is not None and shared_browser is not None and not use_cdp:
        try:
            shared_browser.close()
        except Exception:
            pass
    # Atualizar informações do Telegram na UI
    try:
        progress_window._refresh_telegram_info()
    except Exception:
        pass
    # Atualizar status para "Concluído" antes de retornar (para que o countdown apareça)
    progress_window.update_status("Concluído. %s oportunidades encontradas." % ranking_count)
    return (links, scan_listings_count, scan_errors, ranking_count)


def _schedule_next_run(progress_window, preferences):
    """
    Agenda próxima execução em X minutos (user_preferences.run_every_minutes), com contagem regressiva na tela.
    Não abre outra instância do app.
    """
    interval_seconds = _get_interval_seconds(preferences)
    progress_window._recurring_30 = True
    progress_window.update_status("Concluído. Aguardando próxima execução.")
    remaining = [interval_seconds]

    def tick():
        if getattr(progress_window, "_closing", False):
            return
        if not getattr(progress_window, "root", None) or not progress_window.root.winfo_exists():
            return
        # Parciais 12h/19h e recap 08h (se telegram_daily_reports.enabled)
        if preferences.get("telegram_daily_reports", {}).get("enabled", False):
            try:
                from telegram_scheduler import tick as telegram_tick
                telegram_tick()
            except Exception:
                pass
        remaining[0] -= 1
        if remaining[0] <= 0:
            progress_window.update_countdown("")
            progress_window.update_status("Iniciando nova execução...")
            try:
                progress_window.root.update()
                progress_window.root.update_idletasks()
            except Exception:
                pass
            # Rodar o pipeline em thread (igual à primeira execução); senão a UI trava na segunda
            def run_next():
                result, err = None, None
                try:
                    result = _run_pipeline_once(progress_window, preferences)
                except Exception as e:
                    err = e
                    _log("Erro na execução agendada: %s" % e)
                try:
                    progress_window.safe_after(0, lambda: _on_pipeline_done(result, err, preferences))
                except Exception:
                    pass
            import threading
            threading.Thread(target=run_next, daemon=True).start()
            return
        m, s = divmod(remaining[0], 60)
        progress_window.update_countdown("Tempo para a próxima execução: %02d:%02d" % (m, s))
        progress_window.safe_after(1000, tick)

    m0, s0 = divmod(interval_seconds, 60)
    progress_window.update_countdown("Tempo para a próxima execução: %02d:%02d" % (m0, s0))
    # Uma verificação imediata (parciais 12h/19h, recap 08h) ao entrar na espera
    if preferences.get("telegram_daily_reports", {}).get("enabled", False):
        try:
            from telegram_scheduler import tick as telegram_tick
            telegram_tick()
        except Exception:
            pass
    progress_window.safe_after(1000, tick)


def main():
    _log("=" * 70)
    _log("🚀 AUTORADAR - MARKETPLACE BOT")
    _log("=" * 70)
    
    # Log de status dos módulos no início
    _log("📋 Módulos disponíveis: Facebook=✅, Webmotors=%s, Mobiauto=%s, OLX=%s" % (
        "✅" if WEBMOTORS_AVAILABLE else "❌",
        "✅" if MOBIAUTO_AVAILABLE else "❌",
        "✅" if OLX_AVAILABLE else "❌"
    ))

    # FIPE: atualização apenas pelo botão "Atualizar FIPE" na interface (não em background ao iniciar)

    # Se IA com Ollama estiver ativa: inicia o Ollama se necessário e aquece o modelo em background
    try:
        from ai_fipe_helper import start_ollama_if_needed, warm_up_ollama
        import threading
        # Iniciar Ollama se necessário (bloqueia por até 5s, mas só se use_ollama estiver ativo)
        ollama_started = start_ollama_if_needed()
        if ollama_started:
            _log("Ollama iniciado pelo app (será fechado ao sair)")
        # Aquecer o modelo em background (não bloqueia)
        _t2 = threading.Thread(target=warm_up_ollama, daemon=True)
        _t2.start()
    except Exception:
        pass

    preferences = load_preferences()
    _log("Preferências: %s/%s | margem mín. R$ %s | preço: %s" % (
        preferences.get('city', ''), preferences.get('state', ''),
        preferences.get('margin_min_reais', 0),
        "sem limite" if (preferences.get('price_min', 0) == 0 and preferences.get('price_max', 0) == 0) else "R$ %s - R$ %s" % (preferences.get('price_min', 0), preferences.get('price_max', 0))))
    # #region agent log
    try:
        import json as _json
        with open(r"c:\Projects\.cursor\debug.log", "a", encoding="utf-8") as _f:
            _f.write(_json.dumps({"location": "run_app:main", "message": "preferences_loaded", "data": {"city": preferences.get("city"), "state": preferences.get("state"), "has_city_state": bool(preferences.get("city") and preferences.get("state"))}, "hypothesisId": "H2", "timestamp": time.time() * 1000}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion

    _log("[2/5] Interface de Progresso...")

    def _on_pipeline_done(result, err, prefs):
        """Chamado na thread principal após o pipeline terminar (evita travar a GUI)."""
        try:
            if err is not None:
                _log("Erro ao reiniciar fluxo: %s" % err)
                progress_window.update_status("Erro: %s" % err)
                try:
                    from tkinter import messagebox
                    messagebox.showerror("AutoRadar", "Erro ao reiniciar fluxo: %s" % err)
                except Exception:
                    pass
                return
            if result is None:
                progress_window.update_status("Nenhum link coletado.")
                return
            links, scan_count, scan_errors, ranking_count = result
            progress_window.update_status("Concluído. %s oportunidades." % ranking_count)
            # Sempre agenda próxima execução (intervalo em user_preferences.json, padrão 60 min)
            _schedule_next_run(progress_window, prefs)
        except Exception as e:
            _log("Erro ao processar resultado: %s" % e)
            progress_window.update_status("Erro: %s" % e)

    def restart_flow():
        """Reinicia o fluxo: coleta → scan → consolidação → ranking (em thread para não travar a GUI)."""
        prefs = load_preferences()
        progress_window.update_status("Reiniciando fluxo...")
        progress_window.update_progress(0, 100)
        try:
            progress_window.root.update()
            progress_window.root.update_idletasks()
        except Exception:
            pass

        def run_in_thread():
            result, err = None, None
            try:
                result = _run_pipeline_once(progress_window, prefs)
            except Exception as e:
                err = e
                _log("Erro no pipeline: %s" % e)
            finally:
                _close_chrome_opened_by_app()
            try:
                progress_window.safe_after(0, lambda: _on_pipeline_done(result, err, prefs))
            except Exception:
                pass

        import threading
        threading.Thread(target=run_in_thread, daemon=True).start()

    progress_window = ProgressWindow(on_config_clicked=None, on_restart_flow=restart_flow)
    progress_window.show()

    try:
        _log("[3/5] Coleta de Links do Facebook Marketplace...")
        # Verificar Playwright antes da coleta (sempre usamos Chrome local na porta 9222 quando possível)
        try:
            import playwright
        except ImportError:
            _log("Playwright não instalado. Coleta e scan requerem: pip install playwright")
            try:
                from tkinter import messagebox
                messagebox.showwarning(
                    "AutoRadar - Playwright necessário",
                    "O módulo Playwright não está instalado.\n\n"
                    "Instale com:\n  pip install playwright\n\n"
                    "O app usa sempre o Chrome local (porta 9222) quando disponível;\n"
                    "não é necessário 'playwright install chromium' se você usar o Chrome."
                )
            except Exception:
                pass
        progress_window.update_status("Coletando links...")
        progress_window.update_progress(0, 100)
        try:
            progress_window.root.update()
            progress_window.root.update_idletasks()
        except Exception:
            pass

        # Checando informações de login (só abre janela se não houver sessão)
        from collect_links_mobile import BROWSER_STATE_FILE
        _log("[3a/5] Checando informações de login...")
        progress_window.update_status("Checando informações de login...")
        try:
            progress_window.root.update()
            progress_window.root.update_idletasks()
        except Exception:
            pass
        if not BROWSER_STATE_FILE.exists():
            _log("Coleta: login não encontrado. Abrindo navegador para efetuar login.")
            progress_window.prompt_before_browser()
        else:
            _log("Coleta: informações de login salvas. Iniciando coleta (Chrome porta 9222 se disponível, senão janela minimizada).")
            # #region agent log
            try:
                import json as _json
                with open(r"c:\Projects\.cursor\debug.log", "a", encoding="utf-8") as _f:
                    _f.write(_json.dumps({"location": "run_app:login_check", "message": "session_detected_skip_blank", "data": {"has_session": True, "will_open_direct_to_marketplace": True}, "hypothesisId": "H1", "timestamp": time.time() * 1000}, ensure_ascii=False) + "\n")
            except Exception:
                pass
            # #endregion

        _log("[3/5] Coleta de Links...")
        progress_window.update_status("Coletando links...")
        progress_window.update_progress(0, 100)

        def _first_pipeline_done(result, err, start_time=None):
            """Chamado na thread principal após o primeiro pipeline terminar."""
            try:
                if err is not None:
                    _log("Erro no pipeline: %s" % err)
                    progress_window.update_status("Erro: %s" % err)
                    try:
                        from tkinter import messagebox
                        messagebox.showerror("AutoRadar", "Erro no pipeline: %s" % err)
                    except Exception:
                        pass
                    return
                if result is None:
                    progress_window.update_status("Nenhum link coletado. Verifique internet e tente novamente.")
                    # Fechar após 2s sem bloquear a thread principal (evita TclError em after())
                    def _close_later():
                        try:
                            progress_window.close()
                        except Exception:
                            pass
                    progress_window.safe_after(2000, _close_later)
                    return
                links, scan_listings_count, scan_errors, ranking_count = result
                report_path = get_ui_dir() / "index.html"
                if report_path.exists():
                    _log("Relatório HTML gerado: %s" % report_path)
                else:
                    _log("Relatório HTML não encontrado: %s" % report_path)
                _log("PIPELINE CONCLUÍDO COM SUCESSO")
                if start_time is not None:
                    elapsed = time.time() - start_time
                    h, r = divmod(int(elapsed), 3600)
                    m, s = divmod(r, 60)
                    if h > 0:
                        tempo_str = "%dh %dmin %ds" % (h, m, s)
                    elif m > 0:
                        tempo_str = "%dmin %ds" % (m, s)
                    else:
                        tempo_str = "%ds" % s
                    _log("Tempo total de execução: %s" % tempo_str)
                # Atualizar status antes de iniciar countdown
                progress_window.update_status("Concluído. %s oportunidades encontradas." % ranking_count)
                # Próxima execução conforme user_preferences.json (run_every_minutes, padrão 60 min)
                _schedule_next_run(progress_window, preferences)
                try:
                    progress_window.root.mainloop()
                except Exception:
                    pass
            except Exception as _e:
                _log("Erro ao finalizar pipeline: %s" % _e)

        def run_first_pipeline():
            result, err = None, None
            start_time = time.time()
            try:
                result = _run_pipeline_once(progress_window, preferences)
            except Exception as e:
                err = e
                _log("Erro no pipeline: %s" % e)
            finally:
                _close_chrome_opened_by_app()
            try:
                progress_window.safe_after(0, lambda: _first_pipeline_done(result, err, start_time))
            except Exception:
                pass

        import threading
        threading.Thread(target=run_first_pipeline, daemon=True).start()
        try:
            progress_window.root.mainloop()
        except Exception:
            pass
        return

    except KeyboardInterrupt:
        _log("Processo interrompido pelo usuário")
        progress_window.update_status("Interrompido")
    except Exception as e:
        import traceback
        _log("Erro durante execução: %s" % e)
        try:
            from log_config import get_logger
            get_logger().debug(traceback.format_exc())
        except Exception:
            traceback.print_exc()
        progress_window.update_status(f"Erro: {e}")
    finally:
        time.sleep(2)
        # Não fechar a janela quando está em execução periódica (contagem regressiva no mesmo processo)
        if not getattr(progress_window, "_close_scheduled", False) and not getattr(progress_window, "_recurring_30", False):
            progress_window.close()


if __name__ == "__main__":
    main()
