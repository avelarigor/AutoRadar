#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Teste rápido do ranking (com ou sem IA).
Usa out/listings_all_clean.json e out/fipe_db_norm.json.
Rode: python test_ranking.py

Para teste rápido sem IA: renomeie ai_config.json (ex.: ai_config.json.bak)
ou edite e coloque "use_ollama": false. Com IA ativa e Ollama fora do ar, pode ficar lento (timeout por anúncio).

Created by Igor Avelar - avelar.igor@gmail.com
"""

import sys
import json
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))


def _load_config(out_dir):
    """Carrega FIPE, keywords e preferências (espelho do run_app._load_ranking_config)."""
    fipe_db = {}
    fipe_file = out_dir / "fipe_db_norm.json"
    if fipe_file.exists():
        try:
            with open(fipe_file, "r", encoding="utf-8") as f:
                fipe_db = json.load(f)
        except Exception:
            pass
    keywords_avoid = []
    kw_file = BASE_DIR / "keywords_golpe.txt"
    if kw_file.exists():
        try:
            with open(kw_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        keywords_avoid.append(line)
        except Exception:
            pass
    margin_min_reais = 0.0
    vehicle_types = {"car": True, "motorcycle": True, "truck": True}
    prefs_file = BASE_DIR / "user_preferences.json"
    if prefs_file.exists():
        try:
            with open(prefs_file, "r", encoding="utf-8") as f:
                prefs = json.load(f)
                margin_min_reais = float(prefs.get("margin_min_reais", 0))
                vehicle_types = prefs.get("vehicle_types", vehicle_types)
        except Exception:
            pass
    return fipe_db, keywords_avoid, margin_min_reais, vehicle_types


def main():
    from path_utils import get_out_dir
    from ranking_mvp import evaluate_one_listing, _get_fipe_api_func, write_ranking_report

    out_dir = get_out_dir()
    listings_file = out_dir / "listings_all_clean.json"
    fipe_file = out_dir / "fipe_db_norm.json"

    if not listings_file.exists():
        print(f"Arquivo não encontrado: {listings_file}")
        print("Rode antes: coleta + scan + consolidação, ou use dados existentes em out/.")
        return 1
    if not fipe_file.exists():
        print(f"Arquivo FIPE não encontrado: {fipe_file}")
        print("Rode o download da FIPE (botão Atualizar FIPE no app ou fipe_download.py).")
        return 1

    with open(listings_file, "r", encoding="utf-8") as f:
        listings = json.load(f)
    fipe_db, keywords_avoid, margin_min_reais, vehicle_types = _load_config(out_dir)
    get_fipe = _get_fipe_api_func()

    # Verificar se IA está configurada (apenas informativo)
    try:
        from ai_fipe_helper import is_ai_configured
        ia_ativa = is_ai_configured()
    except Exception:
        ia_ativa = False
    print("IA ativa: sim" if ia_ativa else "IA ativa: não (rodando só com FIPE e palavras de golpe)")

    print(f"Avaliando {len(listings)} anúncios...")
    results = []
    for row in listings:
        r = evaluate_one_listing(
            row, fipe_db, keywords_avoid, margin_min_reais, vehicle_types, get_fipe
        )
        if r is not None:
            results.append(r)

    results.sort(key=lambda x: x["margem"], reverse=True)
    print(f"Oportunidades encontradas: {len(results)}")

    if results:
        from path_utils import get_ui_dir
        write_ranking_report(results, out_dir, get_ui_dir())
        print("Relatório HTML e cache gerados em out/ e UI/.")
    else:
        print("Nenhuma oportunidade (margem/preço/tipo ou filtros podem ter excluído todos).")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"Erro: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
