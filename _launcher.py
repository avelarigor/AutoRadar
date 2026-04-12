# _launcher.py
# Wrapper de inicialização do AutoRadar
# Responsabilidades:
#   - Garantir instância única (via PID file)
#   - Limpar lockfiles de execuções anteriores
#   - Redirecionar stdout/stderr para arquivos de log
#   - Iniciar run_app.py como subprocesso e registrar seu PID

import os
import sys
import subprocess
import time
from pathlib import Path
from datetime import datetime


def kill_orphan_chromes():
    """Mata apenas processos chrome.exe pertencentes ao AutoRadar (perfis profiles/facebook e profiles/olx).
    Não interrompe o Chrome pessoal do usuário.
    """
    import psutil
    killed = 0
    app_profile_markers = (
        str(BASE_DIR / "profiles" / "facebook").lower(),
        str(BASE_DIR / "profiles" / "olx").lower(),
        "profiles\\facebook",
        "profiles\\olx",
        "profiles/facebook",
        "profiles/olx",
    )
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            nm = (proc.info["name"] or "").lower()
            if "chrome" not in nm:
                continue
            cmdline = " ".join(proc.info["cmdline"] or []).lower()
            if any(marker in cmdline for marker in app_profile_markers):
                proc.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception:
            pass
    if killed > 0:
        print(f"[{ts()}] [LAUNCHER] {killed} Chrome(s) do app encerrado(s)", flush=True)

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

LAUNCHER_PID_FILE = LOGS_DIR / "app_launcher_pid.txt"
APP_PID_FILE      = LOGS_DIR / "app_pid.txt"
STDOUT_LOG        = LOGS_DIR / "launcher_out.log"
STDERR_LOG        = LOGS_DIR / "launcher_err.log"

PYTHON_EXE = sys.executable
RUN_APP    = BASE_DIR / "run_app.py"


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_pid_running(pid: int) -> bool:
    """Verifica se um PID está ativo no Windows."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, timeout=5
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def check_single_instance():
    """Encerra se já houver outra instância do launcher rodando."""
    if LAUNCHER_PID_FILE.exists():
        try:
            existing_pid = int(LAUNCHER_PID_FILE.read_text().strip())
            if existing_pid != os.getpid() and is_pid_running(existing_pid):
                print(f"[{ts()}] [LAUNCHER] Instância já ativa (PID {existing_pid}). Encerrando.", flush=True)
                sys.exit(0)
        except (ValueError, OSError):
            pass  # PID inválido → ignora e continua


def cleanup_pid_files():
    """Remove PID files órfãos de execuções anteriores."""
    for pid_file in (LAUNCHER_PID_FILE, APP_PID_FILE):
        try:
            if pid_file.exists():
                pid_file.unlink()
        except OSError:
            pass


def write_pid(pid_file: Path, pid: int):
    try:
        pid_file.write_text(str(pid))
    except OSError as e:
        print(f"[{ts()}] [LAUNCHER] Aviso: não foi possível escrever {pid_file.name}: {e}", flush=True)


def run():
    check_single_instance()
    cleanup_pid_files()
    write_pid(LAUNCHER_PID_FILE, os.getpid())

    print(f"[{ts()}] [LAUNCHER] Iniciando AutoRadar (PID launcher: {os.getpid()})", flush=True)
    print(f"[{ts()}] [LAUNCHER] Python: {PYTHON_EXE}", flush=True)
    print(f"[{ts()}] [LAUNCHER] App:    {RUN_APP}", flush=True)
    print(f"[{ts()}] [LAUNCHER] Logs:   {STDOUT_LOG}", flush=True)

    if not RUN_APP.exists():
        print(f"[{ts()}] [LAUNCHER] ERRO: {RUN_APP} não encontrado!", flush=True)
        sys.exit(1)

    restart_count = 0
    proc = None

    try:
        while True:
            restart_count += 1
            print(f"[{ts()}] [LAUNCHER] Iniciando app (tentativa #{restart_count})...", flush=True)

            # Mata Chromes órfãos antes de subir (evita acúmulo entre restarts)
            kill_orphan_chromes()

            # Sem redirecionamento: run_app.py já faz tee para arquivo via production_logger.
            proc = subprocess.Popen(
                [PYTHON_EXE, str(RUN_APP)],
                cwd=str(BASE_DIR),
            )

            write_pid(APP_PID_FILE, proc.pid)
            print(f"[{ts()}] [LAUNCHER] Processo app iniciado (PID: {proc.pid})", flush=True)

            return_code = proc.wait()

            print(f"[{ts()}] [LAUNCHER] Processo app encerrado (código: {return_code})", flush=True)

            delay = 5 if return_code == 0 else 20
            print(f"[{ts()}] [LAUNCHER] Reiniciando em {delay}s...", flush=True)
            time.sleep(delay)

    except KeyboardInterrupt:
        print(f"\n[{ts()}] [LAUNCHER] Interrompido pelo usuário.", flush=True)
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass

    finally:
        cleanup_pid_files()


if __name__ == "__main__":
    run()
