# -*- coding: utf-8 -*-
"""
FIPE lookup helper
- Tries fipe.online (v2) if FIPE_API_TOKEN is available (paid).
- Falls back to Parallelum FIPE API (v1) if token is missing or calls fail.

Why this exists:
- Avoid "FIPE aproximada" via IA (hallucination risk).
- Make matching robust: token-based scoring + safe year selection.

Public functions kept stable:
- search_fipe_value(marca, modelo, ano, vehicle_type="car") -> Optional[float]
- get_fipe_from_cache_or_api(marca, modelo, ano, vehicle_type="car") -> Optional[float]
"""

from __future__ import annotations

import datetime
import json
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

BASE_DIR = Path(__file__).resolve().parent

# Versão do formato do cache; ao aumentar, entradas antigas deixam de ser usadas.
CACHE_VERSION = 2

# ---------------------------
# Normalization / Matching
# ---------------------------

_STOPWORDS = {
    "de","da","do","das","dos","e","com","sem","para","em","no","na","nos","nas",
    "ano","km","automatico","automatica","aut","manual","flex","gasolina","diesel",
    "cv","hp","turbo","turbodiesel","sedan","hatch","hatchback","crossover","suv",
    "4p","2p","4","2","16v","8v","20v","12v","24v"
}

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9\s\-\/]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _tokens(s: str) -> List[str]:
    s = _norm(s)
    toks = [t for t in re.split(r"[\s\-\/]+", s) if t and t not in _STOPWORDS]
    # remove pure numbers unless it's 4-digit year (keep year is useful sometimes)
    out = []
    for t in toks:
        if t.isdigit() and len(t) != 4:
            continue
        out.append(t)
    return out

def _score_name(query: str, name: str) -> int:
    q = _tokens(query)
    n = _tokens(name)
    if not q or not n:
        return -10
    nset = set(n)
    hits = sum(1 for t in q if t in nset)
    misses = len(q) - hits
    # prefer tighter names when tie
    score = hits * 3 - misses * 2
    if hits == len(q):
        score += 10
    score -= max(0, len(n) - len(q))  # penalize very long names a bit
    return score

def _pick_best(items: List[Dict[str, Any]], query: str, key: str = "nome") -> Optional[Dict[str, Any]]:
    if not items:
        return None
    best = None
    best_score = -10_000
    for it in items:
        name = str(it.get(key, "") or "")
        sc = _score_name(query, name)
        if sc > best_score:
            best_score = sc
            best = it
    # require at least 1 hit token (avoid random pick)
    if best is None:
        return None
    # quick sanity: score must be > 0 for a meaningful match
    if best_score <= 0:
        return None
    return best

def _parse_year_from_name(name: str) -> Optional[int]:
    # year names often like "2021 Gasolina" or "2021-1" etc.
    m = re.search(r"\b(19\d{2}|20\d{2})\b", str(name))
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

def _pick_best_year(year_items: List[Dict[str, Any]], ano: int) -> Optional[Dict[str, Any]]:
    if not year_items:
        return None
    # exact match first
    for y in year_items:
        yname = y.get("nome") or y.get("name") or y.get("ano") or ""
        yint = _parse_year_from_name(str(yname))
        if yint == ano:
            return y
    # closest year (prefer same or nearest below/above)
    best = None
    best_dist = 10_000
    for y in year_items:
        yname = y.get("nome") or y.get("name") or y.get("ano") or ""
        yint = _parse_year_from_name(str(yname))
        if yint is None:
            continue
        dist = abs(yint - ano)
        if dist < best_dist:
            best_dist = dist
            best = y
        elif dist == best_dist and best is not None:
            # tie-break: prefer higher year (conservative for margin? actually can inflate FIPE; prefer lower)
            if yint < (_parse_year_from_name(best.get("nome") or best.get("name") or "") or 9999):
                best = y
    return best or year_items[0]


# ---------------------------
# Providers
# ---------------------------

# fipe.online v2 (paid) - needs X-Subscription-Token and reference (YYYY-MM)
_FIPE_ONLINE_BASE = "https://fipe.online/api/v2"
# Parallelum v1 (free)
_PARALLELUM_BASE = "https://parallelum.com.br/fipe/api/v1"

_VEHICLE_MAP = {
    "car": ("cars", "carros"),
    "motorcycle": ("motorcycles", "motos"),
    "truck": ("trucks", "caminhoes"),
}

def _get_token(token_file: str = "fipe_token.txt") -> Optional[str]:
    # 1) env
    tok = os.getenv("FIPE_API_TOKEN")
    if tok:
        return tok.strip()
    # 2) .env (no diretório do script)
    for env_path in (BASE_DIR / ".env", BASE_DIR.parent / ".env"):
        try:
            if env_path.exists():
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("FIPE_API_TOKEN="):
                            return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    # 3) token file (no diretório do script)
    token_path = BASE_DIR / token_file
    try:
        if token_path.exists():
            with open(token_path, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return None

def _safe_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 20) -> Optional[Any]:
    try:
        r = requests.get(url, headers=headers or {}, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None

@lru_cache(maxsize=128)
def _online_brands(vehicle_type: str, reference: str, token: str) -> Optional[List[Dict[str, Any]]]:
    vt = _VEHICLE_MAP.get(vehicle_type, _VEHICLE_MAP["car"])[0]
    url = f"{_FIPE_ONLINE_BASE}/{vt}/brands?reference={reference}"
    data = _safe_get(url, headers={"X-Subscription-Token": token})
    return data if isinstance(data, list) else None

@lru_cache(maxsize=512)
def _online_models(vehicle_type: str, reference: str, token: str, brand_id: str) -> Optional[List[Dict[str, Any]]]:
    vt = _VEHICLE_MAP.get(vehicle_type, _VEHICLE_MAP["car"])[0]
    url = f"{_FIPE_ONLINE_BASE}/{vt}/{brand_id}/models?reference={reference}"
    data = _safe_get(url, headers={"X-Subscription-Token": token})
    return data if isinstance(data, list) else None

@lru_cache(maxsize=2048)
def _online_years(vehicle_type: str, reference: str, token: str, brand_id: str, model_id: str) -> Optional[List[Dict[str, Any]]]:
    vt = _VEHICLE_MAP.get(vehicle_type, _VEHICLE_MAP["car"])[0]
    url = f"{_FIPE_ONLINE_BASE}/{vt}/{brand_id}/{model_id}/years?reference={reference}"
    data = _safe_get(url, headers={"X-Subscription-Token": token})
    return data if isinstance(data, list) else None

def _online_value(vehicle_type: str, reference: str, token: str, brand_id: str, model_id: str, year_id: str) -> Optional[float]:
    vt = _VEHICLE_MAP.get(vehicle_type, _VEHICLE_MAP["car"])[0]
    url = f"{_FIPE_ONLINE_BASE}/{vt}/{brand_id}/{model_id}/{year_id}?reference={reference}"
    data = _safe_get(url, headers={"X-Subscription-Token": token})
    if not isinstance(data, dict):
        return None
    value_str = data.get("value") or data.get("valor") or ""
    m = re.search(r"([\d\.,]+)", str(value_str))
    if not m:
        return None
    try:
        return float(m.group(1).replace(".", "").replace(",", "."))
    except Exception:
        return None

@lru_cache(maxsize=128)
def _par_brands(vehicle_type: str) -> Optional[List[Dict[str, Any]]]:
    vt = _VEHICLE_MAP.get(vehicle_type, _VEHICLE_MAP["car"])[1]
    url = f"{_PARALLELUM_BASE}/{vt}/marcas"
    data = _safe_get(url)
    return data if isinstance(data, list) else None

@lru_cache(maxsize=512)
def _par_models(vehicle_type: str, brand_id: str) -> Optional[List[Dict[str, Any]]]:
    vt = _VEHICLE_MAP.get(vehicle_type, _VEHICLE_MAP["car"])[1]
    url = f"{_PARALLELUM_BASE}/{vt}/marcas/{brand_id}/modelos"
    data = _safe_get(url)
    if not isinstance(data, dict):
        return None
    modelos = data.get("modelos")
    return modelos if isinstance(modelos, list) else None

@lru_cache(maxsize=2048)
def _par_years(vehicle_type: str, brand_id: str, model_id: str) -> Optional[List[Dict[str, Any]]]:
    vt = _VEHICLE_MAP.get(vehicle_type, _VEHICLE_MAP["car"])[1]
    url = f"{_PARALLELUM_BASE}/{vt}/marcas/{brand_id}/modelos/{model_id}/anos"
    data = _safe_get(url)
    return data if isinstance(data, list) else None

def _par_value(vehicle_type: str, brand_id: str, model_id: str, year_id: str) -> Optional[float]:
    vt = _VEHICLE_MAP.get(vehicle_type, _VEHICLE_MAP["car"])[1]
    url = f"{_PARALLELUM_BASE}/{vt}/marcas/{brand_id}/modelos/{model_id}/anos/{year_id}"
    data = _safe_get(url)
    if not isinstance(data, dict):
        return None
    val = data.get("Valor") or data.get("value") or ""
    m = re.search(r"([\d\.,]+)", str(val))
    if not m:
        return None
    try:
        return float(m.group(1).replace(".", "").replace(",", "."))
    except Exception:
        return None


# ---------------------------
# Public API
# ---------------------------

def search_fipe_value(marca: str, modelo: str, ano: int, vehicle_type: str = "car") -> Optional[float]:
    """
    Returns FIPE value (float) or None.
    vehicle_type: "car" | "motorcycle" | "truck"
    """
    marca = (marca or "").strip()
    modelo = (modelo or "").strip()
    if not marca or not modelo or not ano:
        return None

    # 1) Try fipe.online (paid) if token exists
    token = _get_token()
    if token:
        reference = f"{datetime.datetime.now().year}-{datetime.datetime.now().month:02d}"
        brands = _online_brands(vehicle_type, reference, token) or []
        brand_item = _pick_best(brands, marca, key="name") or _pick_best(brands, marca, key="nome")
        if brand_item:
            brand_id = str(brand_item.get("id") or brand_item.get("codigo") or "")
            if brand_id:
                models = _online_models(vehicle_type, reference, token, brand_id) or []
                model_item = _pick_best(models, modelo, key="name") or _pick_best(models, modelo, key="nome")
                if model_item:
                    model_id = str(model_item.get("id") or model_item.get("codigo") or "")
                    if model_id:
                        years = _online_years(vehicle_type, reference, token, brand_id, model_id) or []
                        year_item = _pick_best_year(years, int(ano))
                        if year_item:
                            year_id = str(year_item.get("id") or year_item.get("codigo") or "")
                            if year_id:
                                val = _online_value(vehicle_type, reference, token, brand_id, model_id, year_id)
                                if val:
                                    return val

    # 2) Fallback: Parallelum (free)
    brands = _par_brands(vehicle_type) or []
    brand_item = _pick_best(brands, marca)  # key is "nome"
    if not brand_item:
        return None
    brand_id = str(brand_item.get("codigo") or brand_item.get("id") or "")
    if not brand_id:
        return None

    models = _par_models(vehicle_type, brand_id) or []
    model_item = _pick_best(models, modelo)
    if not model_item:
        return None
    model_id = str(model_item.get("codigo") or model_item.get("id") or "")
    if not model_id:
        return None

    years = _par_years(vehicle_type, brand_id, model_id) or []
    year_item = _pick_best_year(years, int(ano))
    if not year_item:
        return None
    year_id = str(year_item.get("codigo") or year_item.get("id") or "")
    if not year_id:
        return None

    return _par_value(vehicle_type, brand_id, model_id, year_id)


def _load_cache(cache_file: str) -> Dict[str, Any]:
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_cache(cache_file: str, cache: Dict[str, Any]) -> None:
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def get_cached_fipe(marca: str, modelo: str, ano: int, vehicle_type: str = "car") -> Optional[float]:
    """Obtém valor FIPE do cache"""
    try:
        from path_utils import get_out_dir  # type: ignore
        cache_file = str(get_out_dir() / "fipe_api_cache.json")
    except Exception:
        cache_file = "fipe_api_cache.json"

    cache = _load_cache(cache_file)
    key = f"CACHE_VERSION={CACHE_VERSION}|"+f"{vehicle_type}:{marca}|{modelo}|{ano}"
    val = cache.get(key)
    try:
        return float(val) if val is not None else None
    except Exception:
        return None

def cache_fipe_result(marca: str, modelo: str, ano: int, valor: float, vehicle_type: str = "car") -> None:
    """Salva valor FIPE no cache"""
    try:
        from path_utils import get_out_dir  # type: ignore
        cache_file = str(get_out_dir() / "fipe_api_cache.json")
    except Exception:
        cache_file = "fipe_api_cache.json"

    cache = _load_cache(cache_file)
    key = f"CACHE_VERSION={CACHE_VERSION}|"+f"{vehicle_type}:{marca}|{modelo}|{ano}"
    cache[key] = float(valor)
    _save_cache(cache_file, cache)

def get_fipe_from_cache_or_api(marca: str, modelo: str, ano: int, vehicle_type: str = "car") -> Optional[float]:
    """Busca FIPE no cache primeiro, depois na API se necessário."""
    cached = get_cached_fipe(marca, modelo, ano, vehicle_type=vehicle_type)
    if cached:
        return cached
    valor = search_fipe_value(marca, modelo, ano, vehicle_type=vehicle_type)
    if valor:
        cache_fipe_result(marca, modelo, ano, valor, vehicle_type=vehicle_type)
        return valor
    return None
