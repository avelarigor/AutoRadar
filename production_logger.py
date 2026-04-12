# production_logger.py
# Criado por: Igor Avelar - avelar.igor@gmail.com
# Log unificado, arquivo único, flush em tempo real

import logging
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Arquivo único por dia
LOG_FILE = LOG_DIR / f"autoradar_{datetime.now().strftime('%Y%m%d')}.log"


class _TeeStream:
    """
    Intercepta writes de sys.stdout ou sys.stderr:
      - Exibe no terminal original
      - Grava no arquivo de log com timestamp, linha a linha, em tempo real
    """

    def __init__(self, original, log_handle, label: str):
        self._orig = original
        self._log = log_handle
        self._label = label
        self._pending = ""

    def write(self, text: str) -> int:
        self._orig.write(text)
        try:
            self._orig.flush()
        except Exception:
            pass
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            if line.rstrip():
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._log.write(f"{ts} | {self._label} | {line}\n")
                self._log.flush()
        return len(text)

    def flush(self):
        try:
            self._orig.flush()
        except Exception:
            pass
        if self._pending.rstrip():
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._log.write(f"{ts} | {self._label} | {self._pending}\n")
            self._log.flush()
            self._pending = ""

    def fileno(self):
        return self._orig.fileno()

    def isatty(self):
        return False

    def readable(self):
        return False

    def writable(self):
        return True

    @property
    def encoding(self):
        return getattr(self._orig, "encoding", "utf-8")

    @property
    def errors(self):
        return getattr(self._orig, "errors", "replace")

    def __getattr__(self, name):
        return getattr(self._orig, name)


def setup_logging() -> str:
    """
    Configura o sistema de log unificado:
      - Arquivo único: logs/autoradar_YYYYMMDD.log
      - Flush em tempo real (seguro contra taskkill / Ctrl+C)
      - Captura todos os print() do app (stdout + stderr)
      - logging.info/warning/error também gravados no mesmo arquivo

    Deve ser chamado uma única vez, no início de run_app.py.
    Retorna o caminho do arquivo de log.
    """
    # Abre o arquivo de log com line-buffering (buffering=1)
    log_handle = open(LOG_FILE, "a", encoding="utf-8", buffering=1)

    # ── logging module → mesmo arquivo ───────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Handler de arquivo (via StreamHandler para aproveitar o handle já aberto)
    file_handler = logging.StreamHandler(log_handle)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Handler de console (aponta para o stdout original, antes do Tee)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
    root.addHandler(console_handler)

    # ── Interceptar stdout / stderr (captura todos os print()) ───────────────
    sys.stdout = _TeeStream(sys.stdout, log_handle, "OUT")
    sys.stderr = _TeeStream(sys.stderr, log_handle, "ERR")

    logging.info(f"=== Log iniciado: {LOG_FILE} ===")
    return str(LOG_FILE)


# ── Funções de conveniência ────────────────────────────────────────────────────
def log_info(msg: str):     logging.info(msg)
def log_warning(msg: str):  logging.warning(msg)
def log_error(msg: str):    logging.error(msg)
def log_critical(msg: str): logging.critical(msg)
def get_log_file_path() -> str: return str(LOG_FILE)



def get_log_file_path() -> str:
    """Retorna o caminho do arquivo de log atual"""
    return str(LOG_FILE)
