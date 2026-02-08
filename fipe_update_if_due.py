#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verifica se já passaram 30 dias desde a última atualização da tabela FIPE.
Se sim, roda fipe_download.py automaticamente.

Use no Agendador de Tarefas do Windows (ou cron) para rodar todo dia:
  .\venv\Scripts\python.exe fipe_update_if_due.py

Se a última atualização foi há 30+ dias, o download será executado; caso contrário, nada faz.
Created by Igor Avelar - avelar.igor@gmail.com
"""
import sys
import json
import datetime
import subprocess
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

try:
    from path_utils import get_out_dir
except ImportError:
    def get_out_dir():
        return BASE_DIR / "out"

OUT_DIR = get_out_dir()
LAST_UPDATE_FILE = OUT_DIR / "cache" / "fipe_last_update.json"
DAYS_INTERVAL = 30


def get_last_update_date() -> Optional[datetime.date]:
    if not LAST_UPDATE_FILE.exists():
        return None
    try:
        with open(LAST_UPDATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        s = data.get("last_update") or data.get("iso", "")[:10]
        if s:
            return datetime.date.fromisoformat(s[:10])
    except Exception:
        pass
    return None


def run_fipe_download(in_process: bool = True) -> int:
    """
    Executa o download da tabela FIPE.
    in_process=True: importa e chama fipe_download.main() (para uso dentro do .exe/app).
    in_process=False: roda fipe_download.py em subprocess (para uso via linha de comando).
    Retorna o código de saída (0 = ok).
    """
    if in_process:
        try:
            import fipe_download
            return fipe_download.main() or 0
        except Exception as e:
            print("❌ Erro ao rodar fipe_download: %s" % e)
            return 1
    script = BASE_DIR / "fipe_download.py"
    if not script.exists():
        print("❌ fipe_download.py não encontrado.")
        return 1
    return subprocess.call(
        [sys.executable, str(script)],
        cwd=str(BASE_DIR),
    )


def run_update_if_due(in_process: bool = True) -> bool:
    """
    Se já passaram 30 dias desde a última atualização (ou não há data), roda o download.
    in_process: True para chamar fipe_download dentro do mesmo processo (uso no app/.exe).
    Retorna True se executou o update, False se não estava vencido.
    """
    today = datetime.date.today()
    last = get_last_update_date()
    if last is None:
        run_fipe_download(in_process=in_process)
        return True
    if (today - last).days >= DAYS_INTERVAL:
        run_fipe_download(in_process=in_process)
        return True
    return False


def main():
    today = datetime.date.today()
    last = get_last_update_date()

    if last is None:
        print("📅 Nenhuma data de atualização encontrada. Rodando fipe_download...")
        return run_fipe_download(in_process=False)

    delta = (today - last).days
    if delta >= DAYS_INTERVAL:
        print(f"📅 Última atualização: {last} ({delta} dias atrás). Rodando fipe_download...")
        return run_fipe_download(in_process=False)

    next_due = last + datetime.timedelta(days=DAYS_INTERVAL)
    print(f"✅ Tabela FIPE em dia (atualizada em {last}). Próxima atualização em {next_due}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
