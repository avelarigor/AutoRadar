"""
Monitor 8 horas - AutoRadar
Verifica a cada 10 minutos:
  - Se o processo Python está vivo
  - Se o log está sendo atualizado (app escrevendo)
  - Chamadas FIPE API no log
  - Oportunidades novas salvas no DB
  - Alertas de anomalia
"""

import sqlite3
import os
import sys
import time
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOG_PATH   = Path("logs") / f"autoradar_{datetime.now().strftime('%Y%m%d')}.log"
ERR_PATH   = Path("logs/monitor_err.log")
DB_PATH    = Path("data/autoradar.db")
OUT_PATH   = Path("logs/monitor_8h_report.log")
INTERVAL   = 10 * 60        # 10 minutos
DURATION   = 8 * 60 * 60    # 8 horas

APP_PID_FILE = Path("logs/app_pid.txt")

def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log(msg):
    line = f"[{ts()}] {msg}"
    print(line, flush=True)
    with open(OUT_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def get_app_pid():
    """Lê PID salvo se existir."""
    if APP_PID_FILE.exists():
        try:
            return int(APP_PID_FILE.read_text().strip())
        except Exception:
            return None
    return None

def is_pid_running(pid):
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, timeout=5
        )
        return str(pid) in result.stdout
    except Exception:
        return False

def find_python_pid():
    """Encontra o processo python rodando run_app.py."""
    try:
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "processid,commandline", "/format:csv"],
            capture_output=True, text=True, timeout=8
        )
        for line in result.stdout.splitlines():
            if "run_app" in line.lower():
                parts = line.strip().split(",")
                if len(parts) >= 3:
                    try:
                        return int(parts[-1].strip())
                    except Exception:
                        pass
    except Exception:
        pass
    return None

def check_log_activity(last_size):
    """Retorna (novo_size, linhas_novas, está_ativo)."""
    if not LOG_PATH.exists():
        return last_size, [], False
    curr_size = LOG_PATH.stat().st_size
    new_lines = []
    if curr_size > last_size:
        try:
            with open(LOG_PATH, "rb") as f:
                f.seek(last_size)
                chunk = f.read(curr_size - last_size)
            text = chunk.decode("utf-8", errors="replace")
            new_lines = text.splitlines()
        except Exception:
            pass
    return curr_size, new_lines, curr_size != last_size

def count_fipe_calls(lines):
    """Conta resoluções FIPE (local DB + API) nas linhas."""
    # [FIPE API] = chamada à API externa
    # [MARGIN_DEBUG] = resolução bem-sucedida (preço FIPE + margem calculada)
    # [FIPE NÃO ENCONTRADA] = buscou mas não achou no DB local
    # [FIPE_UPDATER] = updater de OLX
    keywords = ["[FIPE API]", "[MARGIN_DEBUG]", "[FIPE NÃO", "[FIPE_UPDATER]",
                "parallelum", "fipe_price"]
    count = 0
    for l in lines:
        if any(kw.lower() in l.lower() for kw in keywords):
            count += 1
    return count

def count_saves(lines):
    """Conta salvamentos de oportunidades."""
    keywords = ["[SAVE]", "oportunidade salva", "opportunity saved",
                "salvando oportunidade", "nova oportunidade"]
    count = 0
    for l in lines:
        if any(kw.lower() in l.lower() for kw in keywords):
            count += 1
    return count

def count_scans(lines):
    keywords_fb  = ["[SCAN_FB]", "scan_fb"]
    keywords_olx = ["[SCAN_OLX]", "scan_olx", "scan debug"]
    fb = sum(1 for l in lines if any(k.lower() in l.lower() for k in keywords_fb))
    olx = sum(1 for l in lines if any(k.lower() in l.lower() for k in keywords_olx))
    return fb, olx

def count_telegram(lines):
    keywords = ["[TG]", "telegram_sent", "mensagem enviada", "sending telegram"]
    return sum(1 for l in lines if any(k.lower() in l.lower() for k in keywords))

def db_snapshot():
    """Retorna totais do banco."""
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        total    = cur.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        sent     = cur.execute("SELECT COUNT(*) FROM opportunities WHERE telegram_sent=1").fetchone()[0]
        pending  = cur.execute("SELECT COUNT(*) FROM opportunities WHERE telegram_sent=0").fetchone()[0]
        # FIPE preenchido
        with_fipe = cur.execute("SELECT COUNT(*) FROM opportunities WHERE fipe_price > 0").fetchone()[0]
        # Última oportunidade
        last = cur.execute(
            "SELECT id, title, price, fipe_price, margin_value, source FROM opportunities ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return {
            "total": total, "sent": sent, "pending": pending,
            "with_fipe": with_fipe, "last": last
        }
    except Exception as e:
        return {"error": str(e)}

def count_errors(lines):
    """Coleta linhas de erro recentes."""
    err_keywords = ["error", "traceback", "exception", "critical", "fatal", "crashed"]
    errors = []
    for l in lines:
        if any(k in l.lower() for k in err_keywords):
            errors.append(l[:200])
    return errors[:10]  # máximo 10


def check_errors(lines):
    """Coleta linhas de erro recentes."""
    err_keywords = ["error", "traceback", "exception", "critical", "fatal", "crashed"]
    errors = []
    for l in lines:
        if any(k in l.lower() for k in err_keywords):
            errors.append(l[:200])
    return errors[:10]  # máximo 10

def count_olx_blocks(lines):
    """Conta ocorrências de bloqueio Cloudflare/OLX nas linhas de log."""
    keywords = ["bloqueio detectado", "cloudflare detectado", "attention required",
                "just a moment", "acesso negado", "bloqueado"]
    return sum(1 for l in lines if any(k.lower() in l.lower() for k in keywords))


def count_fb_no_desc(lines):
    """Conta anúncios FB sem descrição."""
    return sum(1 for l in lines if "nenhuma descri" in l.lower() and "description" in l.lower())


def count_fb_desc_sources(lines):
    """Conta fontes de descrição FB encontradas."""
    sources = {"data-testid DOM": 0, "redacted_description JSON": 0,
               "description JSON": 0, "span DOM": 0}
    for l in lines:
        if "[DESCRIPTION] Fonte:" in l:
            for src in sources:
                if src in l:
                    sources[src] += 1
    return {k: v for k, v in sources.items() if v > 0}


def kill_orphan_chromes():
    """Mata apenas Chromes do app (profiles/facebook e profiles/olx)."""
    try:
        import psutil
        _base = Path(__file__).resolve().parent
        markers = (
            str(_base / "profiles" / "facebook").lower(),
            str(_base / "profiles" / "olx").lower(),
        )
        killed = 0
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if "chrome" not in (proc.info["name"] or "").lower():
                    continue
                cmd = " ".join(proc.info["cmdline"] or []).lower()
                if any(m in cmd for m in markers):
                    proc.kill()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        log(f"[CHROME KILL] {killed} Chrome(s) do app encerrado(s)")
    except Exception as e:
        log(f"[CHROME KILL] Erro: {e}")


def get_chrome_info():
    """Retorna contagem e MB de processos chrome."""
    try:
        import psutil as _ps
        procs = [p for p in _ps.process_iter(["name", "memory_info"])
                 if (p.info["name"] or "").lower() == "chrome.exe"]
        mb = sum(p.info["memory_info"].rss for p in procs) / 1048576
        return len(procs), round(mb)
    except Exception:
        return 0, 0


def run_monitor():
    log("=" * 60)
    log("MONITOR 8H — AutoRadar iniciado")
    log(f"Duração: {DURATION//3600}h | Intervalo: {INTERVAL//60}min")
    log("=" * 60)

    start_time = time.time()
    end_time   = start_time + DURATION

    # Snapshot inicial do DB
    snap0 = db_snapshot()
    if snap0 and "error" not in snap0:
        log(f"[BASELINE] DB: total={snap0['total']} | enviados={snap0['sent']} | com_fipe={snap0['with_fipe']}")
        if snap0["last"]:
            last = snap0["last"]
            log(f"[BASELINE] Última oportunidade ID={last[0]}: {last[1]} | R${last[2]:,} | FIPE=R${last[3]:,} | {last[5]}")

    last_log_size = LOG_PATH.stat().st_size if LOG_PATH.exists() else 0
    cycle = 0
    total_fipe_calls  = 0
    total_saves       = 0
    total_tg          = 0
    total_fb_scans    = 0
    total_olx_scans   = 0
    last_db_total     = snap0["total"] if snap0 and "error" not in snap0 else 0

    # Intervalo curto na primeira checagem (2 min) para confirmar arranque
    sleep_first = min(120, INTERVAL)

    while time.time() < end_time:
        sleep_secs = sleep_first if cycle == 0 else INTERVAL
        sleep_first = INTERVAL  # depois do primeiro sempre usa INTERVAL

        elapsed = time.time() - start_time
        remaining = end_time - time.time()
        log(f"\n[CICLO {cycle+1}] Aguardando {sleep_secs//60}min... "
            f"(decorrido: {int(elapsed//3600)}h{int((elapsed%3600)//60)}m | "
            f"restante: {int(remaining//3600)}h{int((remaining%3600)//60)}m)")

        time.sleep(sleep_secs)
        cycle += 1

        # ── 1. Processo vivo? ──────────────────────────────
        pid = find_python_pid()
        if pid:
            log(f"[PROC] Python run_app.py rodando — PID={pid}")
        else:
            log("[PROC] ⚠️  PROCESSO NÃO ENCONTRADO. App pode ter travado!")

        # ── 2. Atividade no log ────────────────────────────
        curr_size, new_lines, is_active = check_log_activity(last_log_size)
        delta_bytes = curr_size - last_log_size
        log(f"[LOG] Δbytes={delta_bytes:+,} | {len(new_lines)} novas linhas | ativo={'SIM' if is_active else 'NÃO ⚠️'}")
        last_log_size = curr_size

        if not is_active and pid:
            log("[LOG] ⚠️  App rodando mas sem escrita no log — possível travamento!")

        # ── 3. Métricas das novas linhas ───────────────────
        fipe_calls = count_fipe_calls(new_lines)
        saves      = count_saves(new_lines)
        fb_s, olx_s = count_scans(new_lines)
        tg_msgs    = count_telegram(new_lines)

        total_fipe_calls += fipe_calls
        total_saves      += saves
        total_fb_scans   += fb_s
        total_olx_scans  += olx_s
        total_tg         += tg_msgs

        log(f"[SCAN] FB={fb_s} | OLX={olx_s} — FIPE_calls={fipe_calls} — saves={saves} — TG={tg_msgs}")

        # ── 4. DB snapshot ─────────────────────────────────
        snap = db_snapshot()
        if snap and "error" not in snap:
            new_opps = snap["total"] - last_db_total
            last_db_total = snap["total"]
            log(f"[DB] total={snap['total']} (+{new_opps} novas) | enviados={snap['sent']} | pendentes={snap['pending']} | com_fipe={snap['with_fipe']}")
            if snap["last"]:
                last = snap["last"]
                fipe_str = f"FIPE=R${last[3]:,}" if last[3] else "FIPE=N/A"
                log(f"[DB] Última opp: ID={last[0]} [{last[5]}] {last[1]} | R${last[2]:,} | {fipe_str} | margem=R${last[4]:,}" if last[4] else
                    f"[DB] Última opp: ID={last[0]} [{last[5]}] {last[1]} | R${last[2]:,} | {fipe_str}")
        else:
            log(f"[DB] Erro ao ler: {snap}")

        # ── 5. Erros recentes ──────────────────────────────
        errors = check_errors(new_lines)
        if errors:
            log(f"[ERROS] {len(errors)} linha(s) de erro encontradas:")
            for e in errors[:5]:
                log(f"  > {e}")

        # ── 5b. Bloqueios OLX ──────────────────────────────
        olx_blocks = count_olx_blocks(new_lines)
        if olx_blocks:
            log(f"[OLX ALERT] ⚠️  {olx_blocks} bloqueio(s) Cloudflare/OLX detectado(s) neste ciclo!")

        # ── 5c. Descrição FB ───────────────────────────────
        no_desc = count_fb_no_desc(new_lines)
        desc_sources = count_fb_desc_sources(new_lines)
        if no_desc:
            log(f"[FB DESC] ⚠️  {no_desc} anúncio(s) sem descrição neste ciclo")
        if desc_sources:
            log(f"[FB DESC] Fontes: {desc_sources}")

        # ── 5d. Chrome órfãos ──────────────────────────────
        cr_n, cr_mb = get_chrome_info()
        log(f"[CHROME] {cr_n} processo(s) = {cr_mb} MB")
        if cr_n > 15:
            log(f"[CHROME ALERT] ⚠️  {cr_n} Chromes — matando órfãos...")
            kill_orphan_chromes()

        # ── 6. FIPE sem chamadas ─aviso ────────────────────
        if cycle >= 3 and total_fipe_calls == 0:
            log("[ALERTA] ⚠️  Nenhuma chamada FIPE registrada ainda nos logs!")

    # ── RESUMO FINAL ──────────────────────────────────────
    log("\n" + "=" * 60)
    log("RESUMO FINAL — 8 HORAS DE MONITORAMENTO")
    log("=" * 60)
    snap_final = db_snapshot()
    if snap_final and "error" not in snap_final:
        total_new = snap_final["total"] - (snap0["total"] if snap0 and "error" not in snap0 else 0)
        log(f"Oportunidades novas registradas: {total_new}")
        log(f"Total no DB: {snap_final['total']} | Enviados: {snap_final['sent']}")
        log(f"Com FIPE preenchido: {snap_final['with_fipe']}")
    log(f"Scans FB: {total_fb_scans} | Scans OLX: {total_olx_scans}")
    log(f"Chamadas FIPE API (log): {total_fipe_calls}")
    log(f"Saves detectados (log): {total_saves}")
    log(f"Mensagens Telegram: {total_tg}")
    log(f"Relatório salvo em: {OUT_PATH}")
    log("=" * 60)

if __name__ == "__main__":
    run_monitor()
