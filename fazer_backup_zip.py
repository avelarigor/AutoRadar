#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cria backup .zip da pasta AutoRadar (executar a partir da pasta pai: python AutoRadar/fazer_backup_zip.py).
Created by Igor Avelar - avelar.igor@gmail.com
"""
import zipfile
from pathlib import Path
from datetime import datetime

SRC = Path(__file__).resolve().parent
# Zip na pasta pai, com data no nome
DEST = SRC.parent / f"AutoRadar_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"

def main():
    print(f"Compactando {SRC} -> {DEST} ...")
    count = 0
    skip = 0
    with zipfile.ZipFile(DEST, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in SRC.rglob("*"):
            if f.is_file():
                arcname = f.relative_to(SRC.parent)
                try:
                    zf.write(f, arcname)
                    count += 1
                except (PermissionError, OSError, ValueError):
                    skip += 1
                if (count + skip) % 500 == 0:
                    print(f"  {count} arquivos...")
    if skip:
        print(f"  (ignorados {skip} arquivos em uso)")
    print(f"Backup concluído: {DEST} ({count} arquivos)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
