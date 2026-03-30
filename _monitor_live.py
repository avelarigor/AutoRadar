"""
_monitor_live.py — Monitor em tempo real do AutoRadar
Lê o log linha a linha conforme cresce, detecta padrões de problema
e imprime alertas com timestamps.

Uso: python _monitor_live.py
"""

import sys
import time
import os
from pathlib import Path
from datetime import datetime, timedelta
from collections import deque

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"

# ─── Padrões de problema ─────────────────────────────────────────────────────

ERRORS = [
    "traceback",
    "exception",
    "unhandled",
    "crash",
    "fatal",
]

WARNINGS = [
    "fipe api erro",
    "fipe timeout",
    "timeout",
    "connection timed out",
    "err_connection",
    "connection closed",
    "socket.send() raised",
    "max retries exceeded",
    "connection aborted",
    "read timed out",
]

# Silencia mensagens repetitivas de baixo nível
MUTE_PATTERNS = [
    "queue debug] ignorado",
    "collect filter] ignorado",
    "filter debug] rejeitado",
    "filter block",
    "fipe_updater] nenhum valor",
]

SILENCE_AFTER = 5   # silencia padrão repetitivo após N ocorrências em 2 min

# ─── Estado ──────────────────────────────────────────────────────────────────

recent_warnings = deque(maxlen=200)   # (timestamp, line)
mute_counts: dict[str, list] = {}     # pattern → [timestamps]
last_activity = time.time()
stall_warned = False
STALL_THRESHOLD = 300  # 5 minutos sem log = alerta de stalll

# ─── Helpers ─────────────────────────────────────────────────────────────────

def ts():
    return datetime.now().strftime("%H:%M:%S")

def alert(tag, msg, color=""):
    colors = {"RED": "\033[91m", "YELLOW": "\033[93m", "GREEN": "\033[92m", "CYAN": "\033[96m", "": ""}
    reset = "\033[0m"
    print(f"{colors.get(color, '')}[{ts()}] {tag}: {msg}{reset}", flush=True)

def log_today():
    name = f"autoradar_{datetime.now().strftime('%Y%m%d')}.log"
    return LOGS_DIR / name

def is_muted(line_lower):
    for pat in MUTE_PATTERNS:
        if pat in line_lower:
            now = time.time()
            bucket = mute_counts.setdefault(pat, [])
            bucket[:] = [t for t in bucket if now - t < 120]
            count = len(bucket)
            bucket.append(now)
            return count >= SILENCE_AFTER
    return False

def classify(line):
    ll = line.lower()
    for p in ERRORS:
        if p in ll:
            return "ERROR"
    for p in WARNINGS:
        if p in ll:
            return "WARN"
    return "INFO"

def print_line(line):
    global last_activity, stall_warned
    last_activity = time.time()
    stall_warned = False

    ll = line.lower()
    if is_muted(ll):
        return

    kind = classify(line)

    if kind == "ERROR":
        alert("!! ERRO", line, "RED")
    elif kind == "WARN":
        alert("⚠  WARN", line, "YELLOW")
    else:
        # Linhas informativas relevantes — imprime sem cor
        keywords = [
            "margin_debug",
            "oportunidade salva",
            "telegram",
            "dispatcher",
            "enviado",
            "scanner] listings retornados",
            "iphone scan",
            "ps5 scan",
            "fipe api] atualizando",
            "collect rotation",
            "facebook] coleta",
            "olx][page",
            "scanner] processando",
            "queue] enfileirar",
            "app] iniciando",
            "loop iniciado",
        ]
        if any(k in ll for k in keywords):
            print(f"[{ts()}] {line}", flush=True)

# ─── Loop principal ───────────────────────────────────────────────────────────

def run():
    global stall_warned

    print(f"\n{'='*60}")
    print(f"  AutoRadar Live Monitor — iniciado {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Ctrl+C para sair")
    print(f"{'='*60}\n", flush=True)

    current_log = None
    f = None
    pos = 0

    while True:
        today_log = log_today()

        # Troca de arquivo de log (virada de dia)
        if today_log != current_log:
            if f:
                f.close()
            current_log = today_log
            if current_log.exists():
                f = open(current_log, "r", encoding="utf-8", errors="replace")
                f.seek(0, 2)  # vai para o fim
                pos = f.tell()
                alert(">>", f"Monitorando: {current_log.name}", "CYAN")
            else:
                f = None

        # Lê novas linhas
        if f:
            try:
                f.seek(pos)
                chunk = f.read()
                if chunk:
                    pos = f.tell()
                    for line in chunk.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        # Remove prefixo de timestamp do production_logger
                        if " | OUT | " in line:
                            line = line.split(" | OUT | ", 1)[1]
                        elif " | ERR | " in line:
                            line = "[STDERR] " + line.split(" | ERR | ", 1)[1]
                        elif " | WARNING | " in line:
                            line = "[WARNING] " + line.split(" | WARNING | ", 1)[1]
                        print_line(line)
            except Exception as e:
                alert("MON ERR", str(e), "RED")
                try:
                    f.close()
                except Exception:
                    pass
                f = None

        # Alerta de stall (sem atividade por N minutos)
        idle = time.time() - last_activity
        if idle > STALL_THRESHOLD and not stall_warned:
            stall_warned = True
            alert("!! STALL", f"Sem atividade no log há {int(idle//60)}min — app pode ter travado!", "RED")

        # Sumário a cada 10 minutos
        now = datetime.now()
        if now.second < 2 and now.minute % 10 == 0:
            wcount = sum(1 for t, _ in recent_warnings if time.time() - t < 600)
            alert("PULSE", f"App vivo | warnings últimos 10min: {wcount}", "CYAN")

        time.sleep(1)

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n[Monitor encerrado]", flush=True)
