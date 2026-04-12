"""
_monitor_resources.py — Monitor de CPU/RAM do sistema, Python e VS Code
Imprime snapshot a cada CHECK_INTERVAL segundos.

Uso: python _monitor_resources.py [duração_minutos]
"""

import sys
import time
import psutil
from datetime import datetime

CHECK_INTERVAL = 60        # segundos entre snapshots
WARN_CPU_PCT    = 80       # alerta se CPU do sistema > X%
WARN_RAM_PCT    = 85       # alerta se RAM do sistema > X%
WARN_PROC_MB    = 1000     # alerta se processo individual > X MB


def ts():
    return datetime.now().strftime("%H:%M:%S")


def fmt_mb(rss_bytes):
    return f"{rss_bytes / 1024 / 1024:.0f} MB"


def color(text, code):
    return f"\033[{code}m{text}\033[0m"


def red(t):    return color(t, "91")
def yellow(t): return color(t, "93")
def cyan(t):   return color(t, "96")
def green(t):  return color(t, "92")
def bold(t):   return color(t, "1")


def snapshot():
    now = ts()

    # ── Sistema ──────────────────────────────────────────────────────────────
    cpu_pct  = psutil.cpu_percent(interval=1)
    ram      = psutil.virtual_memory()
    ram_pct  = ram.percent
    ram_used = ram.used / 1024 / 1024 / 1024
    ram_tot  = ram.total / 1024 / 1024 / 1024

    cpu_str = (red if cpu_pct > WARN_CPU_PCT else (yellow if cpu_pct > 60 else green))(f"{cpu_pct:.0f}%")
    ram_str = (red if ram_pct > WARN_RAM_PCT else (yellow if ram_pct > 70 else green))(f"{ram_pct:.0f}%")

    print(f"\n{bold('─'*62)}")
    print(f"  {bold('[SISTEMA]')}  {now}")
    print(f"  CPU: {cpu_str}   RAM: {ram_str} ({ram_used:.1f}/{ram_tot:.1f} GB)")

    # ── Processos Python ─────────────────────────────────────────────────────
    python_procs = []
    vscode_procs = []
    chrome_procs = []

    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "cmdline", "status"]):
        try:
            name = (proc.info["name"] or "").lower()
            if "python" in name:
                python_procs.append(proc)
            elif "code" in name:
                vscode_procs.append(proc)
            elif "chrome" in name:
                chrome_procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Coleta CPU dos Python (precisa de 2 amostras — já fez interval=1 acima)
    print(f"\n  {bold('[PYTHON]')}  {len(python_procs)} processo(s)")
    total_py_mb = 0
    for p in python_procs:
        try:
            mb = p.memory_info().rss / 1024 / 1024
            total_py_mb += mb
            cpu = p.cpu_percent(interval=None)
            cmd = " ".join(p.info.get("cmdline") or [])[-60:]
            mb_str = (red if mb > WARN_PROC_MB else (yellow if mb > 600 else ""))(f"{mb:.0f} MB") if mb > WARN_PROC_MB or mb > 600 else f"{mb:.0f} MB"
            print(f"    PID {p.pid:6}  CPU {cpu:5.1f}%  RAM {mb_str}  {cmd}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if python_procs:
        total_str = (red if total_py_mb > WARN_PROC_MB else (yellow if total_py_mb > 600 else green))(f"{total_py_mb:.0f} MB")
        print(f"    {'─'*20}")
        print(f"    Total Python RAM: {total_str}")

    # ── VS Code ───────────────────────────────────────────────────────────────
    if vscode_procs:
        total_vs_mb = sum(
            p.memory_info().rss / 1024 / 1024
            for p in vscode_procs
            if not isinstance(p.memory_info(), type(None))
        )
        print(f"\n  {bold('[VS CODE]')}  {len(vscode_procs)} processo(s)  total ~{total_vs_mb:.0f} MB")
    else:
        print(f"\n  {bold('[VS CODE]')}  não detectado")

    # ── Chrome ────────────────────────────────────────────────────────────────
    if chrome_procs:
        total_cr_mb = 0
        for p in chrome_procs:
            try:
                total_cr_mb += p.memory_info().rss / 1024 / 1024
            except Exception:
                pass
        cr_str = (red if total_cr_mb > 3000 else (yellow if total_cr_mb > 1500 else green))(f"{total_cr_mb:.0f} MB")
        print(f"  {bold('[CHROME]')}  {len(chrome_procs)} processo(s)  total ~{cr_str}")

    # ── Alertas ───────────────────────────────────────────────────────────────
    alerts = []
    if cpu_pct > WARN_CPU_PCT:
        alerts.append(f"CPU do sistema em {cpu_pct:.0f}%!")
    if ram_pct > WARN_RAM_PCT:
        alerts.append(f"RAM do sistema em {ram_pct:.0f}%!")
    if total_py_mb > WARN_PROC_MB:
        alerts.append(f"Python consumindo {total_py_mb:.0f} MB — watchdog vai agir em breve")

    for a in alerts:
        print(red(f"\n  ⚠  ALERTA: {a}"))

    print(f"{bold('─'*62)}", flush=True)


def run(duration_min=120):
    end_time = time.time() + duration_min * 60
    print(f"\n{'='*62}")
    print(f"  AutoRadar Resource Monitor")
    print(f"  Duração: {duration_min} min | Intervalo: {CHECK_INTERVAL}s")
    print(f"  Início: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Ctrl+C para sair")
    print(f"{'='*62}\n", flush=True)

    # Inicializa cpu_percent (primeira leitura é sempre 0)
    for p in psutil.process_iter(["pid", "name"]):
        try:
            p.cpu_percent(interval=None)
        except Exception:
            pass

    while time.time() < end_time:
        try:
            snapshot()
        except Exception as e:
            print(f"[MON ERROR] {e}", flush=True)
        time.sleep(CHECK_INTERVAL)

    print(f"\n{'='*62}")
    print(f"  Monitor encerrado — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*62}")


if __name__ == "__main__":
    mins = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    try:
        run(mins)
    except KeyboardInterrupt:
        print("\n[Resource Monitor encerrado]", flush=True)
