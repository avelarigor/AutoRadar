# fipe_normalize_db.py - Normalização da base FIPE offline
# Lê out/fipe_db.json (manual), gera out/fipe_db_norm.json (ano puro, menor valor por ano)
# Created by Igor Avelar - avelar.igor@gmail.com
import json
import re
import unicodedata
from pathlib import Path

from path_utils import get_out_dir

OUT_DIR = get_out_dir()
FIPE_RAW = OUT_DIR / "fipe_db.json"
FIPE_NORM = OUT_DIR / "fipe_db_norm.json"


def _normalize_key(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _extract_year(key: str) -> str | None:
    # "2008", "2008 Gasolina", "2008/2009"
    m = re.search(r"\b(19\d{2}|20\d{2})\b", key)
    return m.group(1) if m else None


def normalize_db():
    if not FIPE_RAW.exists():
        print(f"Arquivo não encontrado: {FIPE_RAW}")
        print("Crie out/fipe_db.json com estrutura: { 'marca': { 'modelo': { 'ano': valor } } }")
        return
    with open(FIPE_RAW, "r", encoding="utf-8") as f:
        raw = json.load(f)
    result = {}
    # Mínimo por (marca, modelo_base, ano): primeiro token do nome do modelo (ex.: Hilux, Corolla)
    min_por_base = {}
    for marca, modelos in raw.items():
        mar_norm = _normalize_key(marca) or marca.lower()
        if mar_norm not in result:
            result[mar_norm] = {}
        if mar_norm not in min_por_base:
            min_por_base[mar_norm] = {}
        for modelo, anos in (modelos.items() if isinstance(modelos, dict) else []):
            mod_norm = _normalize_key(modelo) or modelo.lower()
            if mod_norm not in result[mar_norm]:
                result[mar_norm][mod_norm] = {}
            if not isinstance(anos, dict):
                continue
            # Modelo base = primeira palavra do nome (ex.: "Hilux" em "Hilux SW4 SR 4x4...")
            base_raw = (modelo or "").strip().split()[0] if modelo else ""
            base_norm = _normalize_key(base_raw) if base_raw else ""
            if base_norm and len(base_norm) >= 2:
                if base_norm not in min_por_base[mar_norm]:
                    min_por_base[mar_norm][base_norm] = {}
                for ano_key, valor in anos.items():
                    year = _extract_year(ano_key)
                    if not year:
                        continue
                    try:
                        v = int(float(valor)) if valor is not None else None
                    except (TypeError, ValueError):
                        continue
                    if v is None or v <= 0:
                        continue
                    if year not in min_por_base[mar_norm][base_norm] or v < min_por_base[mar_norm][base_norm][year]:
                        min_por_base[mar_norm][base_norm][year] = v
            for ano_key, valor in anos.items():
                year = _extract_year(ano_key)
                if not year:
                    continue
                try:
                    v = int(float(valor)) if valor is not None else None
                except (TypeError, ValueError):
                    continue
                if v is None or v <= 0:
                    continue
                if year not in result[mar_norm][mod_norm] or v < result[mar_norm][mod_norm][year]:
                    result[mar_norm][mod_norm][year] = v
    result["__min_por_base"] = min_por_base
    with open(FIPE_NORM, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Base normalizada salva em: {FIPE_NORM} (com __min_por_base para menor valor por modelo/ano)")


if __name__ == "__main__":
    normalize_db()
