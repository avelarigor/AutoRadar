#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Importa a base FIPE a partir do CSV (ex.: tabela-fipe-historico-precos.csv).
Usa a referência mais recente (anoReferencia, mesReferencia) por (marca, modelo, anoModelo).
Gera out/fipe_db.json e out/fipe_db_norm.json — como se fosse o primeiro download.

Depois, ao rodar fipe_download.py, ele carrega essa base e só atualiza os valores pela API.

Uso:
  python fipe_import_csv.py
  python fipe_import_csv.py "C:\caminho\para\tabela-fipe-historico-precos.csv"

Created by Igor Avelar - avelar.igor@gmail.com
"""
import sys
import csv
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from path_utils import get_out_dir
from fipe_normalize_db import normalize_db

OUT_DIR = get_out_dir()
FIPE_RAW = OUT_DIR / "fipe_db.json"
DEFAULT_CSV = BASE_DIR / "trash" / "tabela-fipe-historico-precos.csv"


def _parse_float(s):
    if s is None or s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def import_csv(csv_path: Path) -> dict:
    """
    Lê o CSV e retorna estrutura marca -> modelo -> ano -> valor.
    Para cada (marca, modelo, anoModelo) usa o valor da linha com (anoReferencia, mesReferencia) mais recente.
    """
    # (marca, modelo, anoModelo) -> (ano_ref, mes_ref, valor)
    best = defaultdict(lambda: (-1, -1, None))

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return {}
        for row in reader:
            marca = (row.get("marca") or "").strip()
            modelo = (row.get("modelo") or "").strip()
            ano_s = (row.get("anoModelo") or "").strip()
            mes_ref_s = (row.get("mesReferencia") or "").strip()
            ano_ref_s = (row.get("anoReferencia") or "").strip()
            valor = _parse_float(row.get("valor"))

            if not marca or not modelo or not ano_s or valor is None or valor <= 0:
                continue
            try:
                ano_modelo = int(ano_s)
            except ValueError:
                continue
            try:
                ano_ref = int(ano_ref_s)
            except ValueError:
                ano_ref = 0
            try:
                mes_ref = int(mes_ref_s)
            except ValueError:
                mes_ref = 0

            key = (marca, modelo, ano_modelo)
            if (ano_ref, mes_ref) > (best[key][0], best[key][1]):
                best[key] = (ano_ref, mes_ref, int(round(valor)))

    # Converter para marca -> modelo -> ano -> valor
    result = {}
    for (marca, modelo, ano), (_, _, valor) in best.items():
        if marca not in result:
            result[marca] = {}
        if modelo not in result[marca]:
            result[marca][modelo] = {}
        result[marca][modelo][str(ano)] = valor

    return result


def main():
    csv_path = DEFAULT_CSV
    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1])

    if not csv_path.exists():
        print(f"❌ Arquivo não encontrado: {csv_path}")
        print("   Uso: python fipe_import_csv.py [caminho/para/tabela-fipe-historico-precos.csv]")
        return 1

    print("=" * 60)
    print("Importação da base FIPE a partir do CSV")
    print("=" * 60)
    print(f"CSV: {csv_path}")
    print("Usando a referência mais recente por (marca, modelo, ano)...")
    print()

    data = import_csv(csv_path)
    if not data:
        print("❌ Nenhum dado válido no CSV.")
        return 1

    total = sum(
        sum(len(anos) for anos in modelos.values())
        for modelos in data.values()
    )
    print(f"✅ {total} entradas (marca/modelo/ano) importadas.")

    with open(FIPE_RAW, "w", encoding="utf-8") as f:
        import json
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"✅ Salvo: {FIPE_RAW}")

    normalize_db()
    print(f"✅ Base normalizada: {OUT_DIR / 'fipe_db_norm.json'}")

    print()
    print("Próximo passo: rodar fipe_download.py quando quiser atualizar os valores pela API.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
