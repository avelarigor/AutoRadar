import asyncio
import json
import time
import sqlite3
from pathlib import Path
import signal
import sys
import os
import psutil

# ─── Guarda de instância única ────────────────────────────────────────────────
# Bloqueia execução se não for o .venv Python (ex: C:\Python311 não pode rodar).
_BASE = Path(__file__).resolve().parent
_VENV_PYTHON = os.path.normcase(str(_BASE / ".venv" / "Scripts" / "python.exe"))
if os.path.normcase(sys.executable) != _VENV_PYTHON:
    sys.exit(0)
# ─────────────────────────────────────────────────────────────────────────────

# Garantir que stdout/stderr suportem emojis ao redirecionar para arquivo
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from production_logger import setup_logging
setup_logging()

import db_schema

from autoradar_workers import (
    collector_loop,
    scanner_loop,
)
from telegram_dispatcher import telegram_dispatcher_loop
from telegram_daily_digest import digest_scheduler_loop
import autoradar_config as config

# Forçar Facebook Only
WEBMOTORS_AVAILABLE = False
MOBIAUTO_AVAILABLE = False
OLX_AVAILABLE = True

# Garantir schema do banco (silencioso)
db_schema.ensure_schema()

# ─── Health check de inicialização ───────────────────────────────────────────
DB_PATH = Path("data/autoradar.db").resolve()
_conn = sqlite3.connect(DB_PATH)
_cur  = _conn.cursor()
_cur.execute("SELECT COUNT(*) FROM link_queue")
_queue_count = _cur.fetchone()[0]
_cur.execute("SELECT COUNT(*) FROM opportunities")
_opp_count = _cur.fetchone()[0]
_conn.close()

_db_size_kb = round(DB_PATH.stat().st_size / 1024)
_fb_interval_min  = 1200 // 60
_olx_interval_min = config.OLX_INTERVAL_SECONDS // 60
_olx_first_min    = 600 // 60

_W = 52
print("=" * _W)
print(f"{'AUTORADAR  — INICIADO COM SUCESSO':^{_W}}")
print("=" * _W)
print(f"  {'Módulo':<22} {'Status'}")
print(f"  {'-'*22} {'-'*20}")
print(f"  {'Facebook':<22} {'ATIVO'}")
print(f"  {'OLX':<22} {'ATIVO'}")
print(f"  {'iPhone':<22} {'desativado' if not config.IPHONES_ENABLED else 'ATIVO'}")
print(f"  {'PS5':<22} {'desativado' if not config.PS5_ENABLED else 'ATIVO'}")
print(f"  {'Região MC':<22} {'ATIVA' if config.REGION_MC_ENABLED else 'desativada'}")
print(f"  {'Região BH':<22} {'ATIVA' if config.REGION_BH_ENABLED else 'desativada'}")
print("-" * _W)
print(f"  {'FIPE':<22} carregada")
print(f"  {'Banco de dados':<22} {_db_size_kb} KB")
print(f"  {'Fila (link_queue)':<22} {_queue_count} itens")
print(f"  {'Oportunidades salvas':<22} {_opp_count}")
print("-" * _W)
print(f"  {'Intervalo Facebook':<22} a cada {_fb_interval_min} min")
print(f"  {'Intervalo OLX':<22} a cada {_olx_interval_min} min (1ª em {_olx_first_min} min)")
print(f"  {'Páginas OLX/rodada':<22} {config.OLX_MAX_PAGES}")
print("=" * _W)
print()

async def main():
    print("[APP] Iniciando loops principais...")

    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    def shutdown():
        print("[APP] Encerrando loops...")
        stop_event.set()

    # Signal handlers funcionam apenas em Unix
    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGINT, shutdown)
        loop.add_signal_handler(signal.SIGTERM, shutdown)

    coroutines = [
        collector_loop(stop_event),
        scanner_loop(stop_event),
        telegram_dispatcher_loop(stop_event),
        digest_scheduler_loop(stop_event),
    ]

    if config.IPHONES_ENABLED:
        from iphones.worker import (
            iphone_collector_loop,
            iphone_scanner_loop,
            iphone_dispatcher_loop,
        )
        print("[IPHONES] Módulo iPhone ATIVADO")
        coroutines += [
            iphone_collector_loop(stop_event),
            iphone_scanner_loop(stop_event),
            iphone_dispatcher_loop(stop_event),
        ]
    else:
        print("[IPHONES] Módulo iPhone desativado (IPHONES_ENABLED = False)")

    if config.PS5_ENABLED:
        from ps5.worker import (
            ps5_collector_loop,
            ps5_scanner_loop,
            ps5_dispatcher_loop,
        )
        print("[PS5] Módulo PS5 ATIVADO")
        coroutines += [
            ps5_collector_loop(stop_event),
            ps5_scanner_loop(stop_event),
            ps5_dispatcher_loop(stop_event),
        ]
    else:
        print("[PS5] Módulo PS5 desativado (PS5_ENABLED = False)")

    coroutines.append(watchdog_loop(stop_event))

    await asyncio.gather(*coroutines)

    # ── Shutdown: fecha browsers e mata Chromes órfãos ─────────────────────────────
    print("[APP] Encerrando browsers antes de sair...")
    try:
        from shared_browser import close_all_browsers
        await close_all_browsers()
    except Exception as _e:
        print(f"[APP] Aviso ao fechar browsers: {_e}")
    # Mata apenas os Chromes do app (perfis profiles/facebook e profiles/olx)
    # Não usa taskkill /IM chrome.exe para não matar o Chrome pessoal do usuário
    try:
        import psutil as _ps
        from pathlib import Path as _Path
        _base = _Path(__file__).resolve().parent
        _markers = (
            str(_base / "profiles" / "facebook").lower(),
            str(_base / "profiles" / "olx").lower(),
        )
        _killed = 0
        for _p in _ps.process_iter(["pid", "name", "cmdline"]):
            try:
                if "chrome" not in (_p.info["name"] or "").lower():
                    continue
                _cmd = " ".join(_p.info["cmdline"] or []).lower()
                if any(_m in _cmd for _m in _markers):
                    _p.kill()
                    _killed += 1
            except (_ps.NoSuchProcess, _ps.AccessDenied):
                pass
        if _killed:
            print(f"[APP] {_killed} Chrome(s) do app encerrado(s)")
    except Exception as _e:
        print(f"[APP] Aviso ao matar Chromes: {_e}")


async def watchdog_loop(stop_event: asyncio.Event):
    """Monitora RAM e uptime — aciona restart limpo se necessário."""
    MAX_UPTIME_H  = 8          # horas antes de restart programado
    MAX_RAM_MB    = 1200       # MB — se ultrapassar, reinicia
    CHECK_EVERY   = 300        # segundos entre verificações (5 min)

    start_time = time.time()
    proc = psutil.Process()

    print(f"[WATCHDOG] Monitoramento ativo — RAM max={MAX_RAM_MB} MB, uptime max={MAX_UPTIME_H}h")

    while not stop_event.is_set():
        await asyncio.sleep(CHECK_EVERY)
        if stop_event.is_set():
            break

        uptime_h = (time.time() - start_time) / 3600
        try:
            ram_mb = proc.memory_info().rss / 1024 / 1024
        except Exception:
            ram_mb = 0

        print(f"[WATCHDOG] RAM={ram_mb:.0f} MB | Uptime={uptime_h:.1f}h")

        if uptime_h >= MAX_UPTIME_H:
            print(f"[WATCHDOG] Uptime {uptime_h:.1f}h atingiu o limite de {MAX_UPTIME_H}h — reiniciando...")
            stop_event.set()
            return

        if ram_mb > MAX_RAM_MB:
            print(f"[WATCHDOG] RAM {ram_mb:.0f} MB excede limite de {MAX_RAM_MB} MB — reiniciando...")
            stop_event.set()
            return


if __name__ == "__main__":
    asyncio.run(main())
