# log_config.py - Configuração de log em arquivo desde o início (para debug)
# Created by Igor Avelar - avelar.igor@gmail.com
import logging
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "log"
LOG_FILE = LOG_DIR / "autoradar.log"

_log_initialized = False


def setup_logging():
    """Configura log em arquivo + console. Chamar no início do run_app."""
    global _log_initialized
    if _log_initialized:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("autoradar")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    # Arquivo (UTF-8)
    try:
        fh = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        log.addHandler(fh)
    except Exception:
        pass
    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(ch)
    _log_initialized = True
    log.info(f"--- Sessão iniciada {datetime.now().isoformat()} ---")


def get_logger():
    """Retorna o logger 'autoradar'. Chame setup_logging() antes no run_app."""
    return logging.getLogger("autoradar")
