#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geração de Ranking - AutoRadar (versão estável mesclada)
Compara anúncios com tabela FIPE e calcula oportunidades.
Created by Igor Avelar - avelar.igor@gmail.com
"""

import sys
import json
import re
import html
import unicodedata
import hashlib
from datetime import datetime
from difflib import SequenceMatcher
from itertools import groupby
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
DEBUG_LOG_PATH = Path(__file__).resolve().parent.parent / ".cursor" / "debug.log"

# Debug pesado: compara FIPE vs preços reais (carrega out/listings_all_clean.json).
# Para performance, fica DESLIGADO por padrão.
ENABLE_FIPE_VS_REAL_DEBUG = False

# Cache em memória de listings_all_clean.json (evita abrir arquivo a cada anúncio)
_ALL_LISTINGS_CACHE = None
_ALL_LISTINGS_CACHE_LOADED = False




def _log(msg: str) -> None:
    """Log simples para compatibilidade (log_config ou print)."""
    try:
        from log_config import get_logger
        get_logger().info(msg)
    except Exception:
        print(msg)


def _debug_log(location: str, message: str, data: dict, hypothesis_id: str = ""):
    try:
        import time
        payload = {"sessionId": "debug-session", "runId": "run1", "location": location, "message": message, "data": data, "timestamp": int(time.time() * 1000)}
        if hypothesis_id:
            payload["hypothesisId"] = hypothesis_id
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
# #region agent log
# #endregion

GENERIC_WORDS = {
    'carro', 'automovel', 'automóvel', 'veiculo', 'veículo',
    'vendo', 'venda', 'vendendo', 'anuncio', 'anúncio',
    'marketplace', 'facebook', 'olx', 'webmotors'
}

MOTO_KEYWORDS = {
    'biz', 'factor', 'cg', 'titan', 'twister', 'xre', 'cb',
    'hornet', 'pop', 'start', 'broz', 'crosser', 'landing',
    'fazer', 'r1', 'r3', 'mt', 'xtz', 'ténéré', 'tenere',
    'scrambler', 'versys', 'ninja', 'z', 'er', 'nmax',
    'pcx', 'sh', 'lead', 'elite', 'burgman', 'skywave',
    'moto', 'motocicleta', 'motorbike'
}

TRUCK_KEYWORDS = {
    'caminhao', 'caminhão', 'truck', 'f4000', 'f-4000', 'f250', 'f350',
    'iveco', 'scania', 'volvo', 'mb', 'atego', 'mercedes', 'cargo',
    'vuc', 'toco', 'trator', 'carreta', 'bitrem', 'semi'
}

# Aliases de marca (anúncio pode vir "vw", "gm" etc.; FIPE usa nome completo)
MARCA_ALIASES = {
    "vw": "volkswagen", "volks": "volkswagen",
    "gm": "chevrolet", "chev": "chevrolet",
    "mb": "mercedes", "bmw": "bmw", "audi": "audi",
    "fiat": "fiat", "ford": "ford", "honda": "honda", "toyota": "toyota",
    "hyundai": "hyundai", "jeep": "jeep", "nissan": "nissan", "renault": "renault",
    "peugeot": "peugeot", "citroen": "citroen", "mitsubishi": "mitsubishi",
    "mazda": "mazda", "suzuki": "suzuki", "kia": "kia", "volvo": "volvo",
}


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return text.lower().strip()


def _normalize_key(text: str) -> str:
    """Normaliza chave (marca/modelo) para comparação/aliases: sem acento e sem pontuação."""
    norm = _normalize_text(text)
    # mantém apenas letras e números (ex.: 'G.M.' -> 'gm', 'V-W' -> 'vw')
    norm = re.sub(r"[^a-z0-9]+", "", norm)
    return norm


def _dedupe_consecutive_words(text: str) -> str:
    """Remove palavras consecutivas repetidas: 'ford ford 2015' -> 'ford 2015'."""
    if not text or not text.strip():
        return text
    words = text.split()
    return " ".join(w for w, _ in groupby(words))


def _extract_model_tokens(title: str) -> Set[str]:
    normalized = _normalize_text(title)
    normalized = _dedupe_consecutive_words(normalized)
    tokens = list(re.findall(r'\b[a-z]{3,}\b', normalized))
    # Modelos com hífen: hr-v -> hrv, i-30 -> i30 (para FIPE casar)
    for m in re.findall(r"\b[a-z]{1,3}-[a-z0-9]{1,3}\b", normalized):
        tokens.append(m.replace("-", ""))
    # Tokens alfanuméricos que identificam linha do modelo (ex: hb20, c180, renegade já é só letras)
    tokens.extend(re.findall(r'\b[a-z]{2,}\d+[a-z]*\b', normalized))
    tokens.extend(re.findall(r'\b\d+[a-z]{2,}\b', normalized))
    # Na FIPE normalizada o modelo pode vir sem espaços (ex: paliosporting16flex); extrair letras entre dígitos
    if not tokens and re.search(r"[a-z]{3,}", normalized):
        parts = re.split(r"\d+", normalized)
        tokens.extend(p for p in parts if len(p) >= 3)
    tokens = [t for t in tokens if t not in GENERIC_WORDS and len(t) >= 3]
    return set(tokens)


def _normalize_title_for_fipe(title: str) -> str:
    """Trata o título ANTES de comparar com a FIPE: remove ruído e normaliza espaços."""
    if not title:
        return ""
    t = title.strip()
    t = t.replace("Marketplace", "").replace("Facebook", "")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _clean_display_title(title: str) -> str:
    if not title:
        return ""
    title = title.replace("Marketplace", "").replace("Facebook", "")
    title = re.sub(r'\s+', ' ', title).strip()
    return title


def _is_moto(text: str) -> bool:
    normalized = _normalize_text(text)
    for keyword in MOTO_KEYWORDS:
        if keyword in normalized:
            return True
    return False


def _is_truck(text: str) -> bool:
    normalized = _normalize_text(text)
    for keyword in TRUCK_KEYWORDS:
        if keyword in normalized:
            return True
    return False


def _vehicle_type(title: str) -> str:
    """Classifica anúncio em car / motorcycle / truck (filtro por preferências)."""
    if _is_moto(title):
        return "motorcycle"
    if _is_truck(title):
        return "truck"
    return "car"


def _vehicle_type_from_row(row: Dict[str, Any], title: str) -> str:
    """Prioriza tipo_veiculo do anúncio (OLX/outros); fallback = _vehicle_type(title)."""
    tipo = (row.get("tipo_veiculo") or "").strip()
    if not tipo and isinstance(row.get("detalhes"), dict):
        tipo = (row.get("detalhes", {}).get("Tipo") or row.get("detalhes", {}).get("tipo_veiculo") or "").strip()
    if not tipo:
        return _vehicle_type(title)
    tipo_lower = _normalize_text(tipo)
    if "moto" in tipo_lower or "motocicleta" in tipo_lower:
        return "motorcycle"
    # Caminhonete / pick-up / utilitário leve → tratar como carro (não caminhão)
    if "caminhonete" in tipo_lower or "pick" in tipo_lower or "pickup" in tipo_lower or "pick-up" in tipo_lower:
        return "car"
    # Caminhão de carga / VUC → truck
    if "caminhao" in tipo_lower or "caminhão" in tipo_lower or "truck" in tipo_lower or "vuc" in tipo_lower:
        return "truck"
    return "car"


def _resolve_marca(row: Dict[str, Any], title_lower: str, marcas_conhecidas: List[str]) -> Optional[str]:
    """Marca: prioriza row['marca']/detalhes['Marca'], aliases, learned typos, fixos, depois título."""
    _ensure_learned_loaded()
    raw = (row.get("marca") or "").strip()
    if not raw and isinstance(row.get("detalhes"), dict):
        raw = (row.get("detalhes", {}).get("Marca") or row.get("detalhes", {}).get("marca") or "").strip()
    raw_original = (raw.strip().lower() if raw else "")
    if raw:
        raw_work = _apply_learned_brand(raw)
        key = _normalize_key(raw_work)
        key = MARCA_ALIASES.get(key, key)
        key = _FIPE_MARCA_TYPO_FIX.get(key, key) if key else key
        if key in marcas_conhecidas:
            try:
                _learn_brand_typo_immediate(raw_original, key, set(marcas_conhecidas))
            except Exception:
                pass
            return key
        for m in marcas_conhecidas:
            if m in key or key in m:
                try:
                    _learn_brand_typo_immediate(raw_original, m, set(marcas_conhecidas))
                except Exception:
                    pass
                return m
    m_final = next((m for m in marcas_conhecidas if m in title_lower), None)
    if m_final and raw_original:
        try:
            _learn_brand_typo_immediate(raw_original, m_final, set(marcas_conhecidas))
        except Exception:
            pass
    return m_final

# =========================
# De-duplicação (ranking/telegram)
# =========================
def _safe_int(v, default=None):
    try:
        if v is None:
            return default
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v)
        s = re.sub(r"[^\d]", "", s)
        return int(s) if s else default
    except Exception:
        return default

def _norm_txt(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s

def _signature_from_item(item: dict) -> str:
    '''
    Gera uma assinatura "quase única" do veículo para agrupar duplicados (mesmo carro anunciado 2x).
    Preferimos dados estáveis: marca_norm + modelo_fipe (ou modelo) + ano + km (aprox).
    '''
    marca = _norm_txt(item.get("marca_norm") or item.get("marca") or item.get("marca_resolvida"))
    modelo = _norm_txt(item.get("modelo_fipe") or item.get("modelo") or item.get("modelo_resolvido") or item.get("title"))
    ano = _safe_int(item.get("ano") or item.get("year"))
    km = _safe_int(item.get("km"))
    km_bucket = None
    if km is not None:
        km_bucket = int(round(km / 1000.0))  # 1.000 km
    return f"{marca}|{modelo}|{ano}|{km_bucket}"

def _price_from_item(item: dict):
    p = item.get("preco")
    if p is None:
        p = item.get("price")
    return _safe_int(p)

def _dedupe_rank_items(items: list) -> list:
    '''
    Mantém apenas 1 item por assinatura.
    Critério: menor preço; em empate, maior margem; em empate, mantém o primeiro.
    '''
    best = {}
    for it in items or []:
        sig = _signature_from_item(it)
        if not sig or sig == "||None|None":
            sig = f"__nosig__:{it.get('url') or id(it)}"
        cur = best.get(sig)
        if cur is None:
            best[sig] = it
            continue

        p_new = _price_from_item(it)
        p_old = _price_from_item(cur)

        if p_old is None and p_new is not None:
            best[sig] = it
            continue
        if p_new is None and p_old is not None:
            continue

        if p_new is not None and p_old is not None and p_new < p_old:
            best[sig] = it
            continue

        if p_new == p_old:
            m_new = _safe_int(it.get("margem") or it.get("margin"))
            m_old = _safe_int(cur.get("margem") or cur.get("margin"))
            if m_new is not None and (m_old is None or m_new > m_old):
                best[sig] = it

    return list(best.values())




def _modelo_query_for_api(marca: str, modelo_tokens: Set[str]) -> str:
    """String estável para API/cache FIPE: tokens ordenados, sem marca nem trim/versão."""
    version_generic = {'flex', 'mec', 'aut', 'manual', 'automatic', 'gasolina', 'diesel', 'etanol', 'v8', 'v6', '16v', '8v', '12v', 'turbo', 'cv', 'ce', 'cd', 'cs', 'cvt'}
    marca_lower = _normalize_text(marca or "")
    exclude = version_generic | GENERIC_WORDS | _VERSION_TRIM_WORDS | {marca_lower}
    tokens = [t for t in modelo_tokens if len(t) >= 2 and t not in exclude]
    return " ".join(sorted(tokens)) if tokens else ""


# --- Helpers para otimização de IA (pré-filtro, cache, truncagem) ---
DESCRIPTION_MAX_CHARS_IA = 800


def _truncate_description_for_ia(description: str, max_chars: int = DESCRIPTION_MAX_CHARS_IA) -> str:
    """Trunca descrição para reduzir tokens enviados à IA; remove linhas repetidas."""
    if not description or not description.strip():
        return ""
    lines = [ln.strip() for ln in description.splitlines() if ln.strip()]
    seen = set()
    unique_lines = []
    for ln in lines:
        if ln.lower() not in seen:
            seen.add(ln.lower())
            unique_lines.append(ln)
    text = "\n".join(unique_lines)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(maxsplit=1)[0] or text[:max_chars]


def _is_ia_candidate(
    row: Dict[str, Any],
    keywords_avoid: List[str],
    vehicle_types: Dict[str, bool],
    marcas_conhecidas: List[str],
) -> bool:
    """Pré-filtro barato: só True se o anúncio passaria em título, ano, preço, tipo, keywords e marca (evita IA para lixo)."""
    raw_title = row.get("title", "")
    title = _normalize_title_for_fipe(raw_title)
    description = row.get("description", "")
    price = row.get("price")
    year = row.get("year")
    currency = (row.get("currency") or "").strip().upper()
    if currency and currency != "BRL":
        return False
    if not title or not year:
        return False
    if price is None or (isinstance(price, (int, float)) and price <= 0):
        return False
    vt = _vehicle_type_from_row(row, title)
    if not vehicle_types.get(vt, True):
        return False
    title_lower = _normalize_text(title)
    description_lower = _normalize_text(description)
    if any(kw.lower() in title_lower for kw in keywords_avoid) or any(kw.lower() in description_lower for kw in keywords_avoid):
        return False
    modelo_tokens = _extract_model_tokens(title)
    if not modelo_tokens:
        return False
    marca = _resolve_marca(row, title_lower, marcas_conhecidas)
    if not marca:
        return False
    return True


def _ai_cache_key_vehicle(title: str, description: str, year: Any, price: Any) -> str:
    """Chave de cache para resultado de extração de veículo (title + desc normalizada + year + price)."""
    norm_t = _normalize_text((title or "").strip())
    norm_d = _normalize_text((description or "")[:2000])
    raw = f"{norm_t}|{norm_d}|{year}|{price}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _ai_cache_key_fipe(marca: str, modelo: str, ano: int) -> str:
    """Chave de cache para valor FIPE estimado por IA."""
    raw = f"{_normalize_text(marca or '')}|{_normalize_text(modelo or '')}|{ano}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _load_ai_cache(cache_path: Path) -> Dict[str, Any]:
    """Carrega cache de IA do disco (JSON)."""
    if not cache_path.exists():
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_ai_cache(cache_path: Path, data: Dict[str, Any]) -> None:
    """Salva cache de IA no disco."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=0)
    except Exception:
        pass


def _jaccard_similarity(set1: Set[str], set2: Set[str]) -> float:
    if not set1 or not set2:
        return 0.0
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0


# Chaves alternativas no fipe_db_norm: API pode retornar "GM Chevrolet" / "VW Volkswagen"
# que viram "gmchevrolet" / "vwvolkswagen"; anúncios usam "chevrolet" / "volkswagen".
_FIPE_MARCA_ALIASES = {"chevrolet": ["gmchevrolet"], "volkswagen": ["vwvolkswagen"]}

# Erros de digitação comuns em títulos (anúncio ou IA) para corrigir antes do lookup na FIPE
_FIPE_MARCA_TYPO_FIX = {
    "peuggeot": "peugeot",
    "peugeott": "peugeot",
    "peugot": "peugeot",
    "pegeot": "peugeot",
    "mitsubisshi": "mitsubishi",
    "mitsubish": "mitsubishi",
    "mitsubichi": "mitsubishi",
    "mitsubishy": "mitsubishi",
    "mitsubshi": "mitsubishi",
    "chhevrolet": "chevrolet",
    "chevrollet": "chevrolet",
    "chevrolt": "chevrolet",
    "chevorlet": "chevrolet",
    "chevroleet": "chevrolet",
    "volksvagen": "volkswagen",
    "volkswagem": "volkswagen",
    "volkwagen": "volkswagen",
    "foord": "ford",
    "fordd": "ford",
    "hiundai": "hyundai",
    "hyundau": "hyundai",
    "hondda": "honda",
    "toyotta": "toyota",
    "nisan": "nissan",
    "citroën": "citroen",
    "citröen": "citroen",
    "renaut": "renault",
    "mazdaa": "mazda",
    "auudi": "audi",
    "mercedez": "mercedes",
}

# --- Aprendizado de typos (marca e modelo): out/typo_learned_brand.json e out/typo_learned_model.json ---
def _out_dir_typo() -> Path:
    try:
        from path_utils import get_out_dir
        return get_out_dir()
    except Exception:
        return BASE_DIR / "out"

_LEARN_TYPO_DIR = _out_dir_typo()
_LEARN_TYPO_DIR.mkdir(parents=True, exist_ok=True)
LEARN_BRAND_PATH = _LEARN_TYPO_DIR / "typo_learned_brand.json"
LEARN_MODEL_PATH = _LEARN_TYPO_DIR / "typo_learned_model.json"
_LEARN_BRAND: Dict[str, Any] = {}
_LEARN_MODEL: Dict[str, Any] = {}
_LEARNED_LOADED = False
LEARN_SAVE_EVERY = 10  # buffer: gravar JSON a cada N aprendizados (evita dezenas de writes por run)
_LEARN_PENDING_COUNT = 0


def _ensure_learned_loaded() -> None:
    global _LEARNED_LOADED
    if not _LEARNED_LOADED:
        _load_learned()
        _LEARNED_LOADED = True


def _dedup_keep_order(seq: List[str]) -> List[str]:
    """Remove duplicatas preservando ordem (consistência de cache/API)."""
    seen: Set[str] = set()
    out: List[str] = []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a or "", b or "").ratio()


def _load_learned() -> None:
    global _LEARN_BRAND, _LEARN_MODEL
    try:
        _LEARN_BRAND = json.loads(LEARN_BRAND_PATH.read_text(encoding="utf-8")) if LEARN_BRAND_PATH.exists() else {}
    except Exception:
        _LEARN_BRAND = {}
    try:
        _LEARN_MODEL = json.loads(LEARN_MODEL_PATH.read_text(encoding="utf-8")) if LEARN_MODEL_PATH.exists() else {}
    except Exception:
        _LEARN_MODEL = {}


def _save_learn_brand() -> None:
    try:
        LEARN_BRAND_PATH.write_text(json.dumps(_LEARN_BRAND, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _save_learn_model() -> None:
    try:
        LEARN_MODEL_PATH.write_text(json.dumps(_LEARN_MODEL, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _flush_learned() -> None:
    """Persiste marca e modelo no disco e zera o contador do buffer."""
    global _LEARN_PENDING_COUNT
    _save_learn_brand()
    _save_learn_model()
    _LEARN_PENDING_COUNT = 0


def _maybe_flush_learned(delta: int = 1) -> None:
    """Incrementa contador de aprendizados e grava a cada LEARN_SAVE_EVERY."""
    global _LEARN_PENDING_COUNT
    _LEARN_PENDING_COUNT += delta
    if _LEARN_PENDING_COUNT >= LEARN_SAVE_EVERY:
        _flush_learned()


def _apply_learned_brand(word: str) -> str:
    w = (word or "").strip().lower()
    if not w:
        return w
    entry = _LEARN_BRAND.get(w)
    if isinstance(entry, dict) and entry.get("to"):
        return entry["to"]
    if isinstance(entry, str):
        return entry
    return w


def _apply_learned_model_token(tok: str) -> str:
    t = (tok or "").strip().lower()
    if not t:
        return t
    entry = _LEARN_MODEL.get(t)
    if isinstance(entry, dict) and entry.get("to"):
        return entry["to"]
    if isinstance(entry, str):
        return entry
    return t


def _learn_brand_typo_immediate(bad: str, good: str, marcas_conhecidas: Set[str]) -> bool:
    bad = (bad or "").strip().lower()
    good = (good or "").strip().lower()
    if not bad or not good:
        return False
    if len(bad) < 4:
        return False
    if good not in marcas_conhecidas:
        return False
    if bad in marcas_conhecidas:
        return False
    if _sim(bad, good) < 0.86:
        return False
    now = datetime.now().strftime("%Y-%m-%d")
    entry = _LEARN_BRAND.get(bad)
    if not entry:
        _LEARN_BRAND[bad] = {"to": good, "count": 1, "last_seen": now}
    else:
        c = entry if isinstance(entry, dict) else {}
        _LEARN_BRAND[bad] = {"to": good, "count": int(c.get("count", 0)) + 1, "last_seen": now}
    _maybe_flush_learned(1)
    return True


def _tokenize_simple(s: str) -> List[str]:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return [t for t in s.split() if len(t) >= 3]


def _learn_model_typos_immediate(modelo_tokens: List[str], modelo_fipe: str) -> int:
    if not modelo_tokens or not modelo_fipe or (isinstance(modelo_fipe, str) and modelo_fipe.strip().startswith("(")):
        return 0
    good_tokens = _tokenize_simple(modelo_fipe)
    bad_tokens = [t for t in modelo_tokens if t and t not in GENERIC_WORDS]
    good_tokens = [t for t in good_tokens if t and t not in GENERIC_WORDS]
    learned = 0
    now = datetime.now().strftime("%Y-%m-%d")
    for bt in bad_tokens:
        bt = (bt or "").strip().lower()
        if not bt or bt.isdigit():
            continue
        if bt in _LEARN_MODEL:
            continue
        best = None
        best_score = 0.0
        for gt in good_tokens:
            if not gt or gt.isdigit():
                continue
            score = _sim(bt, gt)
            if score > best_score:
                best_score = score
                best = gt
        if best and best_score >= 0.88 and abs(len(bt) - len(best)) <= 2 and bt != best:
            entry = _LEARN_MODEL.get(bt)
            cnt = int(entry.get("count", 0)) + 1 if isinstance(entry, dict) else 1
            _LEARN_MODEL[bt] = {"to": best, "count": cnt, "last_seen": now, "score": round(best_score, 3)}
            learned += 1
    if learned:
        _maybe_flush_learned(learned)
    return learned


# Nomes de modelo no anúncio que não batem com a FIPE; tentar estes na ordem no fallback __min_por_base
_FIPE_MODELO_BASE_ALIASES = {
    "pikap": ["l200", "pajero", "l200triton", "triton"],
    "tempra": ["tempra"],
    "palio": ["palio", "paliofire", "palioweek"],
    "cronos": ["cronos", "cronosdrive"],
    "toro": ["toro", "torovulcano"],
    "strada": ["strada", "stradacabine"],
    "uno": ["uno", "unofire", "unomille"],
    "siena": ["siena", "sienafire"],
    "punto": ["punto", "puntoevo"],
    "bravo": ["bravo", "bravo"],
    "ducato": ["ducato"],
    "fiorino": ["fiorino"],
    "linea": ["linea"],
    "grandsiena": ["siena", "grandsiena"],
    "gol": ["gol", "golpower", "goltrend"],
    "fox": ["fox", "fox"],
    "polo": ["polo", "polotrack"],
    "voyage": ["voyage"],
    "saveiro": ["saveiro"],
    "jetta": ["jetta"],
    "passat": ["passat"],
    "tiguan": ["tiguan"],
    "amarok": ["amarok"],
    "virtus": ["virtus"],
    "taos": ["taos"],
    "nivus": ["nivus"],
    "onix": ["onix", "onixplus"],
    "prisma": ["prisma"],
    "tracker": ["tracker"],
    "cruze": ["cruze"],
    "spin": ["spin"],
    "s10": ["s10", "s10pickup"],
    "montana": ["montana"],
    "classic": ["classic", "corsa"],
    "corsa": ["corsa", "corsa"],
    "celta": ["celta"],
    "ka": ["ka", "kase"],
    "focus": ["focus"],
    "fusion": ["fusion"],
    "ranger": ["ranger"],
    "ecosport": ["ecosport"],
    "fiesta": ["fiesta"],
    "corolla": ["corolla"],
    "hilux": ["hilux"],
    "etios": ["etios"],
    "yaris": ["yaris"],
    "camry": ["camry"],
    "civic": ["civic"],
    "fit": ["fit"],
    "hrv": ["hrv", "hr-v"],
    "city": ["city"],
    "wr-v": ["wrv", "wr-v"],
    "hb20": ["hb20", "hb20s", "hb20x"],
    "creta": ["creta"],
    "ix35": ["ix35", "ix35"],
    "tucson": ["tucson"],
    "santa": ["santafe", "santa fe"],
    "kicks": ["kicks"],
    "versa": ["versa"],
    "march": ["march"],
    "sentra": ["sentra"],
    "frontier": ["frontier"],
    "duster": ["duster"],
    "sandero": ["sandero"],
    "logan": ["logan"],
    "captur": ["captur"],
    "kwid": ["kwid"],
    "oroch": ["oroch"],
    "208": ["208"],
    "2008": ["2008"],
    "308": ["308"],
    "3008": ["3008"],
    "partner": ["partner"],
    "expert": ["expert"],
    "outlander": ["outlander"],
    "asx": ["asx"],
    "l200": ["l200", "l200triton", "triton"],
    "pajero": ["pajero", "pajerosport"],
    "renegade": ["renegade"],
    "compass": ["compass"],
}

# Palavras de versão/trim (não usar como core_tokens para match na base FIPE — evita "Sem FIPE na base").
_VERSION_TRIM_WORDS = {
    "vision", "evolution", "sport", "sporting", "limited", "economy", "fire", "flex",
    "4portas", "5portas", "2portas", "4p", "5p", "2p",
    "at", "aut", "mec", "manual", "automatic",
    "attractive", "italia", "titanium", "premier", "highline", "comfortline", "trendline",
    "sensation", "exclusive", "expression", "dynamique", "authentic", "ambition",
    "elegance", "avantgarde", "sportline", "xei", "gli", "dynamique",
}
# Motores comuns: 1.0, 1.4, 1.6, 1.8, 2.0 (normalizados sem ponto para match na FIPE)
_ENGINE_HINTS = {"10", "14", "16", "18", "20", "24", "12", "08"}


def _extract_version_trim_hints(raw_title: str) -> Set[str]:
    """Extrai do título dicas de versão/trim para casar com a linha correta da FIPE (ex.: Vision 1.6 AT, 4 portas)."""
    if not raw_title:
        return set()
    norm = _normalize_text(raw_title)
    hints = set()
    # Motores: 1.0, 1.6, 2.0 -> 10, 16, 20
    for m in re.findall(r"\d+[.,]\d+", raw_title):
        t = m.replace(",", ".").replace(".", "").strip()
        if len(t) >= 2:
            hints.add(t)
    # Palavras de versão que aparecem no título
    for w in _VERSION_TRIM_WORDS:
        if w in norm:
            hints.add(w)
    # 4 portas, 5 portas, 2 portas
    if "4 portas" in norm or "4portas" in norm or " 4p " in norm or norm.endswith("4p"):
        hints.add("4portas")
        hints.add("4p")
    if "5 portas" in norm or "5portas" in norm or " 5p " in norm or norm.endswith("5p"):
        hints.add("5portas")
        hints.add("5p")
    if "2 portas" in norm or "2portas" in norm or " 2p " in norm or norm.endswith("2p"):
        hints.add("2portas")
        hints.add("2p")
    return hints


def _best_year_value_leq(base_anos: dict, ano: int):
    """
    Retorna (ano_usado, valor) usando o maior ano disponível <= ano informado.
    Ex.: ano=2021, base tem 2019/2020/2022 => retorna (2020, valor_2020).
    Conservador: evita usar ano+1 que infla FIPE.
    """
    if not base_anos:
        return (None, None)
    try:
        anos_int = sorted(int(k) for k in base_anos.keys() if str(k).isdigit())
        candidatos = [a for a in anos_int if a <= int(ano)]
        if not candidatos:
            return (None, None)
        ano_usado = candidatos[-1]
        return (ano_usado, base_anos.get(str(ano_usado)))
    except Exception:
        return (None, None)


def _pick_best_fipe_for_models(
    fipe_db: Dict[str, Any],
    marca: str,
    modelo_tokens: Set[str],
    ano: int,
    modelo_sugerido_ai: Optional[str] = None,
) -> Tuple[Optional[str], Optional[int], Optional[float]]:
    """
    Regras: (1) Ano exatamente igual ao do anúncio. (2) Entre TODAS as versões FIPE que batem
    no modelo (mesmo ano), retorna SEMPRE a de MENOR valor do ano correspondente. Desempate
    por sugestão da IA e depois por similaridade. Objetivo: usar sempre o menor valor FIPE
    do ano como referência conservadora (ex.: HB20 = menor entre Vision, X, etc.; Palio = menor entre 2p, 4p).
    """
    modelo_tokens = set(modelo_tokens) if not isinstance(modelo_tokens, set) else modelo_tokens
    marca_norm = _normalize_text(marca)
    marca_norm = _FIPE_MARCA_TYPO_FIX.get(marca_norm, marca_norm)
    # Resolver alias: fipe_db pode ter "gmchevrolet" / "vwvolkswagen" em vez de "chevrolet" / "volkswagen"
    # Também usar alias quando a chave existe mas está VAZIA (ex.: "volkswagen": {} e dados em "vwvolkswagen")
    lookup_key = marca_norm
    if lookup_key not in fipe_db and marca_norm in _FIPE_MARCA_ALIASES:
        for alias in _FIPE_MARCA_ALIASES[marca_norm]:
            if alias in fipe_db:
                lookup_key = alias
                break
    # Se a marca está no fipe_db mas sem modelos (dict vazio), tentar alias
    if lookup_key in fipe_db:
        modelos_fipe_raw = fipe_db[lookup_key]
        if isinstance(modelos_fipe_raw, dict):
            count_models = len([k for k in modelos_fipe_raw if k != "__min_por_base" and isinstance(modelos_fipe_raw.get(k), dict)])
            if count_models == 0 and marca_norm in _FIPE_MARCA_ALIASES:
                for alias in _FIPE_MARCA_ALIASES[marca_norm]:
                    if alias in fipe_db and alias != lookup_key:
                        alt = fipe_db[alias]
                        if isinstance(alt, dict) and len([k for k in alt if k != "__min_por_base" and isinstance(alt.get(k), dict)]) > 0:
                            lookup_key = alias
                            break
    if lookup_key not in fipe_db:
        # #region agent log
        _debug_log("ranking_mvp:_pick_best_fipe", "marca nao encontrada no fipe_db", {"marca_norm": marca_norm, "ano": ano}, "H4")
        # #endregion
        return None, None, None
    # Ignorar chave especial da base (mínimo por modelo/ano)
    modelos_fipe = {k: v for k, v in fipe_db[lookup_key].items() if k != "__min_por_base" and isinstance(v, dict)}
    version_generic = {'flex', 'mec', 'aut', 'manual', 'automatic', 'gasolina', 'diesel', 'etanol', 'v8', 'v6', '16v', '8v', '12v', 'turbo', 'cv', 'ce', 'cd', 'cs', 'cvt'}
    # Normalizar sugestão da IA primeiro (antes de usar)
    ai_hint_norm = _normalize_text(modelo_sugerido_ai) if modelo_sugerido_ai else ""
    # Tokens de cabine: CS (cabine simples) e CD (cabine dupla) - importante para diferenciar versões
    # Aplica-se a TODAS as caminhonetes: Hilux, Ranger, S10, Strada, Amarok, L200, etc.
    cabine_tokens = {'cs', 'cd', 'cabine', 'simples', 'dupla'}
    # Modelos de caminhonetes que sempre têm versões CS/CD na FIPE
    caminhonetes_models = {'hilux', 'ranger', 's10', 'strada', 'amarok', 'l200', 'l200triton', 'triton', 'frontier', 'navara', 'dmax', 'd-max', 'saveiro', 'montana', 'torino'}
    # Verificar se é uma caminhonete (pode ter CS/CD)
    is_caminhonete = any(modelo in _normalize_text(marca + " " + " ".join(modelo_tokens)) for modelo in caminhonetes_models)
    # Verificar se há indicação de cabine no título/descrição ou na sugestão da IA
    has_cabine_info = any(t in modelo_tokens for t in cabine_tokens) or (ai_hint_norm and any(t in ai_hint_norm for t in cabine_tokens))
    # core_tokens: modelo/base apenas; excluir versão/trim para não perder match (ex.: attractive, italia, titanium)
    core_tokens = {t for t in modelo_tokens if len(t) >= 3 and t not in version_generic and t not in GENERIC_WORDS and t not in _VERSION_TRIM_WORDS}
    candidates_same_year = []
    for modelo_fipe, anos_fipe in modelos_fipe.items():
        modelo_fipe_norm = _normalize_text(modelo_fipe)
        # Incluir qualquer versão FIPE que bata no modelo (ex.: HB20, Palio) para depois escolher a de MENOR valor
        if core_tokens and not any(t in modelo_fipe_norm for t in core_tokens):
            continue
        if str(ano) not in anos_fipe:
            continue
        valor = anos_fipe[str(ano)]
        modelo_fipe_tokens = _extract_model_tokens(modelo_fipe)
        similarity = _jaccard_similarity(modelo_tokens, modelo_fipe_tokens)
        ai_match = 1 if (ai_hint_norm and ai_hint_norm in modelo_fipe_norm) else 0
        
        # Priorizar CS (cabine simples) quando não há informação explícita sobre cabine
        # CS geralmente é mais barato e é o padrão quando não especificado
        # IMPORTANTE: Aplica-se a TODAS as caminhonetes (Hilux, Ranger, S10, etc.)
        cabine_priority = 0
        if is_caminhonete and not has_cabine_info:
            # Para caminhonetes sem informação explícita, SEMPRE priorizar CS (menor valor)
            if 'cs' in modelo_fipe_norm or ('cabine' in modelo_fipe_norm and 'simples' in modelo_fipe_norm):
                cabine_priority = 2  # Prioridade MUITO alta para CS em caminhonetes quando não especificado
            elif 'cd' in modelo_fipe_norm or ('cabine' in modelo_fipe_norm and 'dupla' in modelo_fipe_norm):
                cabine_priority = -2  # Prioridade MUITO baixa para CD em caminhonetes quando não especificado
        elif not has_cabine_info:
            # Para outros veículos sem informação, também priorizar CS mas com menor peso
            if 'cs' in modelo_fipe_norm or ('cabine' in modelo_fipe_norm and 'simples' in modelo_fipe_norm):
                cabine_priority = 1  # Prioridade alta para CS quando não especificado
            elif 'cd' in modelo_fipe_norm or ('cabine' in modelo_fipe_norm and 'dupla' in modelo_fipe_norm):
                cabine_priority = -1  # Prioridade baixa para CD quando não especificado
        else:
            # Quando há informação explícita, priorizar match exato
            modelo_tokens_lower = {t.lower() for t in modelo_tokens}
            if any(t in modelo_fipe_norm for t in ['cs', 'cabine', 'simples']) and any(t in modelo_tokens_lower for t in ['cs', 'cabine', 'simples']):
                cabine_priority = 3  # Match exato CS (prioridade máxima)
            elif any(t in modelo_fipe_norm for t in ['cd', 'cabine', 'dupla']) and any(t in modelo_tokens_lower for t in ['cd', 'cabine', 'dupla']):
                cabine_priority = 3  # Match exato CD (prioridade máxima)
        
        candidates_same_year.append((modelo_fipe, ano, valor, similarity, ai_match, cabine_priority))
    if not candidates_same_year:
        # Fallback: tentar __min_por_base para obter pelo menos o menor valor do ano para algum "base" (ex.: gol, strada)
        min_por_base = fipe_db.get("__min_por_base") or {}
        # Tentar lookup_key (ex.: vwvolkswagen) e também marca_norm (ex.: volkswagen) para compatibilidade
        by_marca = min_por_base.get(lookup_key) or min_por_base.get(marca_norm) or {}
        bases_to_try = []
        for base in core_tokens:
            if base == marca_norm:
                continue
            if base not in bases_to_try:
                bases_to_try.append(base)
            for alt in _FIPE_MODELO_BASE_ALIASES.get(base, []):
                if alt not in bases_to_try:
                    bases_to_try.append(alt)
        for base in bases_to_try:
            base_anos = by_marca.get(base, {})
            v = base_anos.get(str(ano))
            ano_usado = ano if v is not None else None
            if v is None and base_anos:
                ano_usado, v = _best_year_value_leq(base_anos, ano)
            if v is not None:
                # #region agent log
                _debug_log("ranking_mvp:_pick_best_fipe", "fallback __min_por_base", {"marca_norm": marca_norm, "ano": ano, "base": base, "valor": v, "modelo_tokens": list(modelo_tokens)[:8]}, "H4")
                # #endregion
                return "(menor valor do ano)", ano_usado or ano, v
        # Log: evitar repetir marca (ex.: "ford ford 2015" -> "ford 2015")
        model_display = " ".join(t for t in sorted(modelo_tokens)[:5] if t != marca_norm)
        _log("⚠️ FIPE: nenhum candidato encontrado para %s %s %d (marca_norm=%s, core_tokens=%s)" % (
            marca, model_display or "(sem modelo)", ano, marca_norm, list(core_tokens)[:5]
        ))
        # #region agent log - debug sem_fipe e fallback
        sample_models = list(modelos_fipe.keys())[:15]
        sample_with_year = [(m, list(v.keys())) for m, v in list(modelos_fipe.items())[:10] if str(ano) in v]
        bases_tried = [b for b in core_tokens if b != marca_norm]
        lookup_samples = {b: (list(by_marca.get(b, {}).keys())[:5], by_marca.get(b, {}).get(str(ano))) for b in list(bases_tried)[:5]}
        _debug_log("ranking_mvp:_pick_best_fipe", "sem_candidatos_detalhe", {
            "marca_norm": marca_norm, "lookup_key": lookup_key, "ano": ano,
            "core_tokens": list(core_tokens)[:10], "bases_tried": bases_tried[:10],
            "by_marca_keys": list(by_marca.keys())[:15], "lookup_samples": lookup_samples,
            "sample_models": sample_models, "sample_with_year": sample_with_year
        }, "H4")
        # #endregion
        return None, None, None
    # Regra fixa: SEMPRE o menor valor FIPE do ano correspondente (valor ascendente).
    # Desempate: 1) Prioridade de cabine (CS quando não especificado), 2) Match da IA, 3) Maior similaridade
    candidates_same_year.sort(key=lambda x: (float(x[2]), -int(x[5]), -int(x[4]), -float(x[3])))
    
    # #region agent log - Debug candidatos FIPE
    _debug_log("ranking_mvp:_pick_best_fipe", "todos_candidatos_fipe", {
        "marca": marca_norm,
        "ano": ano,
        "modelo_tokens": list(modelo_tokens)[:10],
        "total_candidatos": len(candidates_same_year),
        "candidatos_completos": [
            {
                "modelo": m,
                "valor": v,
                "similarity": s,
                "ai_match": ai,
                "cabine_priority": cp
            }
            for m, _, v, s, ai, cp in candidates_same_year[:15]
        ],
        "menor_valor": candidates_same_year[0][2] if candidates_same_year else None,
        "maior_valor": candidates_same_year[-1][2] if candidates_same_year else None,
        "diferenca_percentual": ((candidates_same_year[-1][2] - candidates_same_year[0][2]) / candidates_same_year[0][2] * 100) if len(candidates_same_year) > 1 and candidates_same_year[0][2] > 0 else None
    }, "H2")
    # #endregion
    
    modelo_fipe, ano_fipe, valor_fipe, _, _, _ = candidates_same_year[0]
    # Usar o mínimo entre os candidatos e o __min_por_base (menor valor do ano para aquele modelo base)
    min_por_base = fipe_db.get("__min_por_base") or {}
    by_marca = min_por_base.get(lookup_key) or min_por_base.get(marca_norm) or {}
    for base in core_tokens:
        if base == marca_norm:
            continue
        v = by_marca.get(base, {}).get(str(ano))
        if v is not None and v < valor_fipe:
            valor_fipe = v
            modelo_fipe = "(menor valor do ano)"
    # #region agent log
    _debug_log("ranking_mvp:_pick_best_fipe", "candidatos e escolhido", {"marca_norm": marca_norm, "ano": ano, "modelo_tokens": list(modelo_tokens)[:15], "has_cabine_info": has_cabine_info, "candidates": [{"modelo": m, "valor": v, "cabine_priority": cp} for m, _, v, _, _, cp in candidates_same_year[:8]], "chosen_modelo": modelo_fipe, "chosen_valor": valor_fipe}, "H1")
    # #endregion
    return modelo_fipe, ano_fipe, valor_fipe


def _get_fipe_api_func():
    try:
        from fipe_api import get_fipe_from_cache_or_api
        return get_fipe_from_cache_or_api
    except ImportError:
        return None


def _get_all_listings_cache() -> Optional[List[Dict[str, Any]]]:
    """Carrega out/listings_all_clean.json uma única vez (cache em memória).

    Usado apenas para debug pesado (FIPE vs preços reais). Mantém o app rápido.
    """
    global _ALL_LISTINGS_CACHE, _ALL_LISTINGS_CACHE_LOADED
    if _ALL_LISTINGS_CACHE_LOADED:
        return _ALL_LISTINGS_CACHE
    _ALL_LISTINGS_CACHE_LOADED = True
    if not ENABLE_FIPE_VS_REAL_DEBUG:
        _ALL_LISTINGS_CACHE = None
        return None
    try:
        from path_utils import get_out_dir
        out_dir = get_out_dir()
        cache_file = out_dir / "listings_all_clean.json"
        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                _ALL_LISTINGS_CACHE = json.load(f)
        else:
            _ALL_LISTINGS_CACHE = None
    except Exception:
        _ALL_LISTINGS_CACHE = None
    return _ALL_LISTINGS_CACHE


def evaluate_one_listing(
    row: Dict[str, Any],
    fipe_db: Dict[str, Any],
    keywords_avoid: List[str],
    margin_min_reais: float,
    vehicle_types: Dict[str, bool],
    get_fipe_from_cache_or_api: Optional[Any] = None,
    drop_reasons: Optional[Dict[str, int]] = None,
    precomputed_ai_vehicle: Optional[Dict[str, Any]] = None,
    precomputed_ia_valor: Optional[float] = None,
    precomputed_ia_used: bool = False,
    return_drop_reason: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Avalia um único anúncio: filtros (moeda, tipo, golpe, IA), FIPE e margem.
    Retorna o dicionário do item de ranking se for oportunidade, ou None.
    Se drop_reasons for passado, incrementa o motivo quando retornar None (para relatório).
    Se return_drop_reason=True, retorna tupla (item, None) se aprovado ou (None, motivo) se excluído.
    """
    drop_reason_holder = [None]  # Para capturar o motivo de exclusão
    
    def _drop(reason: str) -> None:
        if drop_reasons is not None:
            drop_reasons[reason] = drop_reasons.get(reason, 0) + 1
        if return_drop_reason:
            drop_reason_holder[0] = reason

    raw_title = row.get("title", "")
    title = _normalize_title_for_fipe(raw_title)
    description = row.get("description", "")
    price = row.get("price")
    year = row.get("year")
    km = row.get("km", 0)
    url = row.get("url", "")
    city = row.get("city", "")
    currency = (row.get("currency") or "").strip().upper()

    if currency and currency != "BRL":
        _drop("moeda")
        return (None, "moeda") if return_drop_reason else None
    if not title or not year:
        _drop("sem_título_ou_ano")
        return (None, "sem_título_ou_ano") if return_drop_reason else None
    if price is None or (isinstance(price, (int, float)) and price <= 0):
        _drop("sem_preço")
        return (None, "sem_preço") if return_drop_reason else None
    vt = _vehicle_type_from_row(row, title)
    if not vehicle_types.get(vt, True):
        _drop("tipo_veículo")
        return (None, "tipo_veículo") if return_drop_reason else None
    title_lower = _normalize_text(title)
    description_lower = _normalize_text(description)
    if any(kw.lower() in title_lower for kw in keywords_avoid) or any(kw.lower() in description_lower for kw in keywords_avoid):
        _drop("palavra_chave")
        return (None, "palavra_chave") if return_drop_reason else None
    _ensure_learned_loaded()
    modelo_tokens = _extract_model_tokens(title)
    if not modelo_tokens:
        _drop("sem_modelo")
        return (None, "sem_modelo") if return_drop_reason else None
    modelo_tokens = _dedup_keep_order([_apply_learned_model_token(t) for t in modelo_tokens])
    marcas_conhecidas = ['honda', 'toyota', 'ford', 'chevrolet', 'volkswagen', 'fiat', 'hyundai', 'jeep', 'nissan', 'renault', 'peugeot', 'citroen', 'mitsubishi', 'mazda', 'suzuki', 'kia', 'audi', 'bmw', 'mercedes', 'volvo']
    marca = _resolve_marca(row, title_lower, marcas_conhecidas)
    if not marca:
        _drop("sem_marca")
        return (None, "sem_marca") if return_drop_reason else None

    modelo_sugerido_ai = None
    ia_checked = False
    if precomputed_ai_vehicle is not None:
        ai_vehicle = precomputed_ai_vehicle
        if ai_vehicle and str(ai_vehicle.get("ano")) == str(year) and (ai_vehicle.get("marca") or "").lower() == marca:
            modelo_sugerido_ai = ai_vehicle.get("modelo_sugerido")
            ia_checked = True
    else:
        try:
            from ai_fipe_helper import is_ai_configured, extract_vehicle_for_fipe
            if is_ai_configured():
                ia_checked = True
                ai_vehicle = extract_vehicle_for_fipe(raw_title, description)
                if ai_vehicle and str(ai_vehicle.get("ano")) == str(year) and (ai_vehicle.get("marca") or "").lower() == marca:
                    modelo_sugerido_ai = ai_vehicle.get("modelo_sugerido")
        except ImportError:
            pass
        except Exception:
            pass

    # 1) Obter valor FIPE da tabela offline primeiro (mais rápido e confiável)
    modelo_fipe, ano_fipe, valor_tabela = _pick_best_fipe_for_models(fipe_db, marca, modelo_tokens, year, modelo_sugerido_ai=modelo_sugerido_ai)
    # #region agent log
    _debug_log("ranking_mvp:evaluate_one", "apos _pick_best_fipe", {"title": raw_title[:80], "year": year, "marca": marca,
            "marca_norm": marca,
 "modelo_tokens": list(modelo_tokens)[:12], "modelo_fipe": modelo_fipe, "valor_tabela": valor_tabela}, "H2")
    # #endregion
    
    # 2) Se não encontrou na base, tentar API (modelo_query estável = melhor cache e match)
    if not valor_tabela and get_fipe_from_cache_or_api:
        try:
            modelo_query = _modelo_query_for_api(marca, modelo_tokens)
            if modelo_query:
                valor_tabela = get_fipe_from_cache_or_api(marca, modelo_query, year)
            if valor_tabela and ano_fipe is None:
                ano_fipe = year
            if valor_tabela and not modelo_fipe:
                modelo_fipe = modelo_query or " ".join(sorted(modelo_tokens))
            # Piso conservador: se a API vier alta, trava no menor valor do ano da base (__min_por_base)
            if valor_tabela:
                try:
                    marca_norm = _normalize_text(marca)
                    marca_norm = _FIPE_MARCA_TYPO_FIX.get(marca_norm, marca_norm)
                    lookup_key = marca_norm
                    if lookup_key not in fipe_db and marca_norm in _FIPE_MARCA_ALIASES:
                        for alias in _FIPE_MARCA_ALIASES[marca_norm]:
                            if alias in fipe_db:
                                lookup_key = alias
                                break
                    version_generic = {'flex', 'mec', 'aut', 'manual', 'automatic', 'gasolina', 'diesel', 'etanol', 'v8', 'v6', '16v', '8v', '12v', 'turbo', 'cv', 'ce', 'cd', 'cs', 'cvt'}
                    core_tokens = {t for t in modelo_tokens if len(t) >= 3 and t not in version_generic and t not in GENERIC_WORDS and t not in _VERSION_TRIM_WORDS}
                    min_por_base = fipe_db.get("__min_por_base") or {}
                    by_marca = min_por_base.get(lookup_key) or min_por_base.get(marca_norm) or {}
                    piso = None
                    piso_ano = None
                    for base in core_tokens:
                        if base == marca_norm:
                            continue
                        anos_map = (by_marca.get(base, {}) or {})
                        if not anos_map:
                            continue
                        ay, vv = _best_year_value_leq(anos_map, year)
                        if vv is None:
                            continue
                        if piso is None or float(vv) < float(piso):
                            piso = float(vv)
                            piso_ano = ay
                    if piso is not None:
                        if float(valor_tabela) > float(piso) * 1.35:
                            valor_tabela = float(piso)
                            modelo_fipe = "(piso anti-suspeita)"
                        elif float(valor_tabela) > float(piso):
                            valor_tabela = float(piso)
                            modelo_fipe = "(piso base %s)" % piso_ano if piso_ano else "(piso base)"
                except Exception:
                    pass
        except Exception:
            pass

    # 3) Se ainda não encontrou FIPE, usar IA com título + descrição para identificar modelo mais próximo
    # A IA vai vasculhar o anúncio completo e determinar o modelo mais próximo, sempre retornando o MENOR valor FIPE
    ia_valor = None
    fipe_ia_used = False
    modelo_para_ia = " ".join(sorted(modelo_tokens)).strip()
    
    if not valor_tabela:
        # Se não encontrou na base/API, usar IA como fallback
        if precomputed_ia_used:
            ia_valor = precomputed_ia_valor  # pode ser None se o batch não retornou valor
        else:
            try:
                from ai_fipe_helper import is_ai_configured, estimate_fipe_value_ia, extract_vehicle_for_fipe
                if is_ai_configured():
                    # Primeiro: usar IA para identificar modelo mais preciso do título + descrição
                    if not modelo_sugerido_ai:
                        ai_vehicle = extract_vehicle_for_fipe(raw_title, description)
                        if ai_vehicle and str(ai_vehicle.get("ano")) == str(year) and (ai_vehicle.get("marca") or "").lower() == marca:
                            modelo_sugerido_ai = ai_vehicle.get("modelo_sugerido")
                            modelo_para_ia = modelo_sugerido_ai or modelo_para_ia
                            # Tentar buscar na base novamente com o modelo sugerido pela IA
                            if modelo_sugerido_ai:
                                modelo_fipe_ia, ano_fipe_ia, valor_tabela_ia = _pick_best_fipe_for_models(
                                    fipe_db, marca, set(modelo_sugerido_ai.lower().split()), year, modelo_sugerido_ai=modelo_sugerido_ai
                                )
                                if valor_tabela_ia:
                                    valor_tabela = valor_tabela_ia
                                    modelo_fipe = modelo_fipe_ia or modelo_sugerido_ai
                                    ano_fipe = ano_fipe_ia or year
                                    _log("✅ FIPE encontrado via IA (modelo sugerido): %s %s %d = R$ %.0f" % (marca, modelo_sugerido_ai, year, valor_tabela))
                    
                    # Se ainda não encontrou, pedir à IA estimativa direta do menor valor FIPE
                    if not valor_tabela:
                        ia_valor = estimate_fipe_value_ia(marca, modelo_para_ia, year)
                        if ia_valor:
                            _log("✅ FIPE estimado pela IA: %s %s %d = R$ %.0f" % (marca, modelo_para_ia, year, ia_valor))
            except Exception as e:
                _log("⚠️ Erro ao usar IA para FIPE: %s" % e)
                pass
    
    # 4) Usar o MENOR entre IA e fipe_db (quando ambos existirem)
    # #region agent log
    _debug_log("ranking_mvp:evaluate_one", "valores antes de decidir", {"title": raw_title[:60], "ia_valor": ia_valor, "valor_tabela": valor_tabela}, "H3")
    # #endregion
    if ia_valor is not None and ia_valor > 0 and valor_tabela is not None and valor_tabela > 0:
        valor_fipe = min(ia_valor, valor_tabela)
        fipe_ia_used = True
        _debug_log("ranking_mvp:evaluate_one", "fonte min(IA,tabela)", {"valor_fipe": valor_fipe, "ia_valor": ia_valor, "valor_tabela": valor_tabela}, "H5")
    elif ia_valor is not None and ia_valor > 0:
        valor_fipe = ia_valor
        fipe_ia_used = True
        if not modelo_fipe:
            modelo_fipe = modelo_para_ia or "-"
        if ano_fipe is None:
            ano_fipe = year
        _debug_log("ranking_mvp:evaluate_one", "fonte so IA", {"valor_fipe": valor_fipe, "ia_valor": ia_valor}, "H5")
    else:
        valor_fipe = valor_tabela
        _debug_log("ranking_mvp:evaluate_one", "fonte so tabela", {"valor_fipe": valor_fipe, "modelo_fipe": modelo_fipe}, "H2")

    # Fallback: FIPE Webmotors (quando base/API/IA falharam e o scan capturou fipe_webmotors)
    if not valor_fipe and row.get("source") == "webmotors":
        fw = row.get("fipe_webmotors")
        if fw is not None and isinstance(fw, (int, float)) and fw > 0:
            valor_fipe = float(fw)
            if not modelo_fipe:
                modelo_fipe = "FIPE Webmotors"
            if ano_fipe is None:
                ano_fipe = year

    # Aprender typos de modelo (imediato): só quando temos modelo_fipe "real" (não placeholder de piso)
    if valor_fipe and modelo_fipe and isinstance(modelo_fipe, str):
        mf = modelo_fipe.strip()
        if mf and not mf.startswith("("):
            try:
                _learn_model_typos_immediate(list(modelo_tokens), modelo_fipe)
            except Exception:
                pass

    if not valor_fipe:
        # Log detalhado para debug: por que não encontrou FIPE?
        debug_info = {
            "marca": marca,
            "marca_norm": marca,

            "modelo_tokens": list(modelo_tokens)[:10],
            "ano": year,
            "titulo": raw_title[:100],
            "valor_tabela": valor_tabela,
            "ia_valor": ia_valor,
            "modelo_fipe": modelo_fipe,
            "modelo_sugerido_ai": modelo_sugerido_ai,
        }
        model_display = " ".join(t for t in sorted(modelo_tokens)[:5] if t != marca.lower())
        _log("⚠️ Sem FIPE para: %s %s %d - tabela=%s, IA=%s, modelo_fipe=%s" % (
            marca, model_display or "(sem modelo)", year,
            valor_tabela if valor_tabela else "None",
            ia_valor if ia_valor else "None",
            modelo_fipe if modelo_fipe else "None"
        ))
        _drop("sem_fipe")
        return (None, "sem_fipe") if return_drop_reason else None

    # Preço absurdo em relação ao FIPE (ex.: carro de 50 mil por 10 mil = golpe/erro/isca)
    if valor_fipe and valor_fipe > 0:
        razao = price / valor_fipe
        if razao < 0.40:
            _drop("preço_suspeito")
            return (None, "preço_suspeito") if return_drop_reason else None  # Preço menor que 40% do FIPE → suspeito
        
        # #region agent log - Debug FIPE vs preços reais
        if ENABLE_FIPE_VS_REAL_DEBUG:
            try:
                all_listings = _get_all_listings_cache() or []
                similar_prices = []
                marca_lower = (marca or "").lower()
                for listing in all_listings:
                    listing_title = (listing.get("title") or "").lower()
                    listing_year = listing.get("year")
                    listing_price = listing.get("price")
                    if listing_year == year and listing_price and listing_price > 0:
                        if marca_lower and marca_lower in listing_title:
                            listing_tokens = _extract_model_tokens(listing.get("title", ""))
                            common_tokens = set(modelo_tokens).intersection(set(listing_tokens))
                            if len(common_tokens) >= 2:
                                similar_prices.append(listing_price)

                similar_prices_sorted = sorted(similar_prices) if similar_prices else []
                p10_price = similar_prices_sorted[int(len(similar_prices_sorted) * 0.10)] if len(similar_prices_sorted) >= 10 else (similar_prices_sorted[0] if similar_prices_sorted else None)
                p25_price = similar_prices_sorted[int(len(similar_prices_sorted) * 0.25)] if len(similar_prices_sorted) >= 4 else None
                min_price = similar_prices_sorted[0] if similar_prices_sorted else None

                fipe_vs_real_ratio = None
                if p10_price and valor_fipe > 0:
                    fipe_vs_real_ratio = valor_fipe / p10_price

                _debug_log("ranking_mvp:fipe_vs_real", "comparacao_fipe_precos_reais", {
                    "marca": marca,
            "marca_norm": marca,

                    "modelo_tokens": list(modelo_tokens)[:10],
                    "ano": year,
                    "preco_anuncio_atual": price,
                    "valor_fipe_escolhido": valor_fipe,
                    "modelo_fipe": modelo_fipe,
                    "fipe_ia_used": fipe_ia_used,
                    "similar_listings_count": len(similar_prices),
                    "min_price_real": min_price,
                    "p10_price_real": p10_price,
                    "p25_price_real": p25_price,
                    "fipe_vs_p10_ratio": fipe_vs_real_ratio,
                    "fipe_suspeita_alta": fipe_vs_real_ratio > 1.4 if fipe_vs_real_ratio else False
                }, "H4")
            except Exception:
                pass
        # #endregion

    margem_reais = valor_fipe - price
    margem = ((valor_fipe - price) / valor_fipe) * 100
    margin_threshold = max(0, margin_min_reais * 0.9)
    if margem < 0 or margem_reais < margin_threshold:
        _drop("margem_insuficiente")
        return (None, "margem_insuficiente") if return_drop_reason else None

    # IA: análise de golpe só para itens que já passaram (FIPE, preço plausível, margem) — evita gastar IA com rejeitados
    ia_checked = False
    scam = None
    try:
        from ai_fipe_helper import is_ai_configured, analyze_scam_risk
        if is_ai_configured():
            ia_checked = True
            scam = analyze_scam_risk(raw_title, description, price=price, valor_fipe=valor_fipe)
            if scam and scam.get("risco_alto"):
                _drop("risco_ia")
                return (None, "risco_ia") if return_drop_reason else None
    except ImportError:
        pass
    except Exception:
        pass

    risco_golpe = "Alto" if (scam and scam.get("risco_alto")) else ("Baixo" if scam else "—")
    risco_motivo = (scam.get("motivo") or "").strip() if scam else ""

    # #region agent log
    _debug_log("ranking_mvp:evaluate_one", "item aprovado valor_fipe vs preco", {"modelo": raw_title[:70], "ano": year, "preco_anuncio": price, "valor_fipe_usado": valor_fipe, "modelo_fipe": modelo_fipe, "fipe_ia_used": fipe_ia_used}, "H1")
    # #endregion

    price_display = (row.get("price_display") or "").strip() or f"R$ {price:,.0f}"
    result = {
        "modelo": _clean_display_title(raw_title),
        "title_original": raw_title,
        "title_normalized": title,
        "modelo_fipe": modelo_fipe or "-",
            "ano": year,
        "ano_fipe": ano_fipe,
        "km": km,
            "preco": price,
        "price_display": price_display,
        "fipe": valor_fipe,
        "fipe_ia_used": fipe_ia_used,
        "margem": round(margem, 1),
        "margem_reais": round(margem_reais, 0),
        "cidade": city or "-",
        "url": url,
        "main_photo_path": row.get("main_photo_path") or "",
        "main_photo_url": (row.get("main_photo_url") or row.get("image_url") or "").strip(),
        "ia_checked": ia_checked,
        "risco_golpe": risco_golpe,
        "risco_motivo": risco_motivo,
        "cambio": row.get("cambio"),
        "cor_externa": row.get("cor_externa"),
        "cor_interna": row.get("cor_interna"),
        "combustivel": row.get("combustivel"),
        "tipo_veiculo": row.get("tipo_veiculo"),
        "potencia_motor": row.get("potencia_motor"),
        "categoria": row.get("categoria"),
        "detalhes": row.get("detalhes"),
    }
    return (result, None) if return_drop_reason else result


def build_ranking_with_batch_ia(
    listings: List[Dict[str, Any]],
    fipe_db: Dict[str, Any],
    keywords_avoid: List[str],
    margin_min_reais: float,
    vehicle_types: Dict[str, bool],
    get_fipe_from_cache_or_api: Optional[Any],
    drop_reasons: Dict[str, int],
    progress_callback: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    Avalia todos os anúncios usando IA em lote (uma chamada para extrair veículos, uma para valor FIPE).
    Chama evaluate_one_listing com valores pré-computados. Retorna lista de itens aprovados.
    """
    ranking = []
    get_fipe = get_fipe_from_cache_or_api or _get_fipe_api_func()
    marcas_conhecidas = ['honda', 'toyota', 'ford', 'chevrolet', 'volkswagen', 'fiat', 'hyundai', 'jeep', 'nissan', 'renault', 'peugeot', 'citroen', 'mitsubishi', 'mazda', 'suzuki', 'kia', 'audi', 'bmw', 'mercedes', 'volvo']
    ai_vehicles: List[Optional[Dict[str, Any]]] = [None] * len(listings)
    ia_values: List[Optional[float]] = [None] * len(listings)
    try:
        from ai_fipe_helper import is_ai_configured, extract_vehicle_for_fipe_batch, estimate_fipe_value_ia_batch
        if is_ai_configured() and listings:
            candidate_idx = [i for i, r in enumerate(listings) if _is_ia_candidate(r, keywords_avoid, vehicle_types, marcas_conhecidas)]
            from path_utils import get_out_dir
            cache_dir = get_out_dir() / "cache"
            cache_vehicle_path = cache_dir / "ai_vehicle_cache.json"
            cache_fipe_path = cache_dir / "ai_fipe_cache.json"
            vehicle_cache = _load_ai_cache(cache_vehicle_path)
            fipe_cache = _load_ai_cache(cache_fipe_path)

            batch_vehicle_indices = []
            batch_vehicle_payloads: List[Tuple[str, str]] = []
            for i in candidate_idx:
                row = listings[i]
                title = row.get("title") or ""
                desc = _truncate_description_for_ia(row.get("description") or "")
                year = row.get("year")
                price = row.get("price")
                key = _ai_cache_key_vehicle(title, desc, year, price)
                if key in vehicle_cache:
                    cached = vehicle_cache[key]
                    ai_vehicles[i] = cached if isinstance(cached, dict) else None
                else:
                    batch_vehicle_indices.append(i)
                    batch_vehicle_payloads.append((title, desc))
            if batch_vehicle_payloads:
                batch_vehicle_results = extract_vehicle_for_fipe_batch(batch_vehicle_payloads)
                for j, idx in enumerate(batch_vehicle_indices):
                    if j < len(batch_vehicle_results):
                        ai_vehicles[idx] = batch_vehicle_results[j]
                        row = listings[idx]
                        key = _ai_cache_key_vehicle(
                            row.get("title") or "",
                            _truncate_description_for_ia(row.get("description") or ""),
                            row.get("year"),
                            row.get("price"),
                        )
                        vehicle_cache[key] = batch_vehicle_results[j]
                _save_ai_cache(cache_vehicle_path, vehicle_cache)

            ia_fipe_inputs_by_candidate: List[Tuple[int, Tuple[str, str, int]]] = []
            for i in candidate_idx:
                row = listings[i]
                title = row.get("title") or ""
                year = row.get("year")
                title_norm = _normalize_title_for_fipe(title)
                title_lower = _normalize_text(title_norm)
                marca = _resolve_marca(row, title_lower, marcas_conhecidas)
                modelo_tokens = _extract_model_tokens(title_norm)
                ai_v = ai_vehicles[i] if i < len(ai_vehicles) else None
                if ai_v and str(ai_v.get("ano")) == str(year) and (ai_v.get("marca") or "").lower() == marca:
                    modelo_para_ia = (ai_v.get("modelo_sugerido") or "").strip() or " ".join(sorted(modelo_tokens)).strip()
                else:
                    modelo_para_ia = " ".join(sorted(modelo_tokens)).strip() if modelo_tokens else ""
                ia_fipe_inputs_by_candidate.append((i, (marca or "", modelo_para_ia, year or 0)))

            batch_fipe_indices: List[int] = []
            batch_fipe_inputs: List[Tuple[str, str, int]] = []
            for i, (marca, modelo, ano) in ia_fipe_inputs_by_candidate:
                key = _ai_cache_key_fipe(marca, modelo, ano)
                if key in fipe_cache:
                    val = fipe_cache[key]
                    ia_values[i] = float(val) if val is not None else None
                else:
                    batch_fipe_indices.append(i)
                    batch_fipe_inputs.append((marca, modelo, ano))
            if batch_fipe_inputs:
                batch_fipe_results = estimate_fipe_value_ia_batch(batch_fipe_inputs)
                for j, idx in enumerate(batch_fipe_indices):
                    if j < len(batch_fipe_results):
                        ia_values[idx] = batch_fipe_results[j]
                        if j < len(batch_fipe_inputs):
                            marca, modelo, ano = batch_fipe_inputs[j]
                            key = _ai_cache_key_fipe(marca, modelo, ano)
                            fipe_cache[key] = batch_fipe_results[j]
                _save_ai_cache(cache_fipe_path, fipe_cache)
    except ImportError:
        ai_vehicles = [None] * len(listings)
        ia_values = [None] * len(listings)
    except Exception:
        ai_vehicles = [None] * len(listings)
        ia_values = [None] * len(listings)

    total = len(listings)
    for i, row in enumerate(listings):
        if progress_callback and total:
            try:
                progress_callback(i + 1, total)
            except Exception:
                pass
        pre_ai = ai_vehicles[i] if i < len(ai_vehicles) else None
        pre_val = ia_values[i] if i < len(ia_values) else None
        use_pre = bool(ai_vehicles or ia_values)
        item = evaluate_one_listing(
            row, fipe_db, keywords_avoid, margin_min_reais, vehicle_types,
            get_fipe, drop_reasons=drop_reasons,
            precomputed_ai_vehicle=pre_ai,
            precomputed_ia_valor=pre_val,
            precomputed_ia_used=use_pre,
        )
        if item:
            ranking.append(item)

    ranking.sort(key=lambda x: x["margem"], reverse=True)
    return ranking


def build_ranking_with_rejected(
    listings: List[Dict[str, Any]],
    fipe_db: Dict[str, Any],
    keywords_avoid: List[str],
    margin_min_reais: float,
    vehicle_types: Dict[str, bool],
    get_fipe_from_cache_or_api: Optional[Any],
    drop_reasons: Dict[str, int],
    progress_callback: Optional[Any] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Avalia todos os anúncios e retorna (aprovados, rejeitados).
    rejeitados contém informações básicas do anúncio + motivo de exclusão.
    """
    _ensure_learned_loaded()
    approved = []
    rejected = []
    get_fipe = get_fipe_from_cache_or_api or _get_fipe_api_func()
    marcas_conhecidas = ['honda', 'toyota', 'ford', 'chevrolet', 'volkswagen', 'fiat', 'hyundai', 'jeep', 'nissan', 'renault', 'peugeot', 'citroen', 'mitsubishi', 'mazda', 'suzuki', 'kia', 'audi', 'bmw', 'mercedes', 'volvo']
    ai_vehicles: List[Optional[Dict[str, Any]]] = [None] * len(listings)
    ia_values: List[Optional[float]] = [None] * len(listings)
    try:
        from ai_fipe_helper import is_ai_configured, extract_vehicle_for_fipe_batch, estimate_fipe_value_ia_batch
        if is_ai_configured() and listings:
            candidate_idx = [i for i, r in enumerate(listings) if _is_ia_candidate(r, keywords_avoid, vehicle_types, marcas_conhecidas)]
            from path_utils import get_out_dir
            cache_dir = get_out_dir() / "cache"
            cache_vehicle_path = cache_dir / "ai_vehicle_cache.json"
            cache_fipe_path = cache_dir / "ai_fipe_cache.json"
            vehicle_cache = _load_ai_cache(cache_vehicle_path)
            fipe_cache = _load_ai_cache(cache_fipe_path)

            # Batch extração de veículo só para candidatos; usar cache quando existir; descrição truncada
            batch_vehicle_indices = []
            batch_vehicle_payloads: List[Tuple[str, str]] = []
            for i in candidate_idx:
                row = listings[i]
                title = row.get("title") or ""
                desc = _truncate_description_for_ia(row.get("description") or "")
                year = row.get("year")
                price = row.get("price")
                key = _ai_cache_key_vehicle(title, desc, year, price)
                if key in vehicle_cache:
                    cached = vehicle_cache[key]
                    ai_vehicles[i] = cached if isinstance(cached, dict) else None
                else:
                    batch_vehicle_indices.append(i)
                    batch_vehicle_payloads.append((title, desc))
            if batch_vehicle_payloads:
                batch_vehicle_results = extract_vehicle_for_fipe_batch(batch_vehicle_payloads)
                for j, idx in enumerate(batch_vehicle_indices):
                    if j < len(batch_vehicle_results):
                        ai_vehicles[idx] = batch_vehicle_results[j]
                        row = listings[idx]
                        key = _ai_cache_key_vehicle(
                            row.get("title") or "",
                            _truncate_description_for_ia(row.get("description") or ""),
                            row.get("year"),
                            row.get("price"),
                        )
                        vehicle_cache[key] = batch_vehicle_results[j]
                _save_ai_cache(cache_vehicle_path, vehicle_cache)

            # ia_fipe_inputs só para candidatos (usa ai_vehicles já preenchido)
            ia_fipe_inputs_by_candidate: List[Tuple[int, Tuple[str, str, int]]] = []
            for i in candidate_idx:
                row = listings[i]
                title = row.get("title") or ""
                year = row.get("year")
                title_norm = _normalize_title_for_fipe(title)
                title_lower = _normalize_text(title_norm)
                marca = _resolve_marca(row, title_lower, marcas_conhecidas)
                modelo_tokens = _extract_model_tokens(title_norm)
                ai_v = ai_vehicles[i] if i < len(ai_vehicles) else None
                if ai_v and str(ai_v.get("ano")) == str(year) and (ai_v.get("marca") or "").lower() == marca:
                    modelo_para_ia = (ai_v.get("modelo_sugerido") or "").strip() or " ".join(sorted(modelo_tokens)).strip()
                else:
                    modelo_para_ia = " ".join(sorted(modelo_tokens)).strip() if modelo_tokens else ""
                ia_fipe_inputs_by_candidate.append((i, (marca or "", modelo_para_ia, year or 0)))

            # Batch FIPE IA só para candidatos; usar cache quando existir
            batch_fipe_indices: List[int] = []
            batch_fipe_inputs: List[Tuple[str, str, int]] = []
            for i, (marca, modelo, ano) in ia_fipe_inputs_by_candidate:
                key = _ai_cache_key_fipe(marca, modelo, ano)
                if key in fipe_cache:
                    val = fipe_cache[key]
                    ia_values[i] = float(val) if val is not None else None
                else:
                    batch_fipe_indices.append(i)
                    batch_fipe_inputs.append((marca, modelo, ano))
            if batch_fipe_inputs:
                batch_fipe_results = estimate_fipe_value_ia_batch(batch_fipe_inputs)
                for j, idx in enumerate(batch_fipe_indices):
                    if j < len(batch_fipe_results):
                        ia_values[idx] = batch_fipe_results[j]
                        if j < len(batch_fipe_inputs):
                            marca, modelo, ano = batch_fipe_inputs[j]
                            key = _ai_cache_key_fipe(marca, modelo, ano)
                            fipe_cache[key] = batch_fipe_results[j]
                _save_ai_cache(cache_fipe_path, fipe_cache)
    except ImportError:
        ai_vehicles = [None] * len(listings)
        ia_values = [None] * len(listings)
    except Exception:
        ai_vehicles = [None] * len(listings)
        ia_values = [None] * len(listings)

    total = len(listings)
    for i, row in enumerate(listings):
        if progress_callback and total:
            try:
                progress_callback(i + 1, total)
            except Exception:
                pass
        pre_ai = ai_vehicles[i] if i < len(ai_vehicles) else None
        pre_val = ia_values[i] if i < len(ia_values) else None
        use_pre = bool(ai_vehicles or ia_values)
        result = evaluate_one_listing(
            row, fipe_db, keywords_avoid, margin_min_reais, vehicle_types,
            get_fipe, drop_reasons=drop_reasons,
            precomputed_ai_vehicle=pre_ai,
            precomputed_ia_valor=pre_val,
            precomputed_ia_used=use_pre,
            return_drop_reason=True,
        )
        if isinstance(result, tuple):
            item, drop_reason = result
            if item:
                approved.append(item)
            else:
                rejected.append({
                    "url": row.get("url", ""),
                    "title": row.get("title", "Sem título"),
                    "price": row.get("price"),
                    "price_display": row.get("price_display", ""),
                    "year": row.get("year"),
                    "km": row.get("km"),
                    "city": row.get("city", ""),
                    "drop_reason": drop_reason or "desconhecido",
                    "description": (row.get("description") or "")[:200],
                })
        elif result:
            approved.append(result)
        else:
            rejected.append({
                "url": row.get("url", ""),
                "title": row.get("title", "Sem título"),
                "price": row.get("price"),
                "price_display": row.get("price_display", ""),
                "year": row.get("year"),
                "km": row.get("km"),
                "city": row.get("city", ""),
                "drop_reason": "desconhecido",
                "description": (row.get("description") or "")[:200],
            })

    # ✅ Dedupe por "mesmo veículo" (URLs diferentes), mantendo o menor preço
    before = len(approved)
    approved = _dedupe_keep_lowest_price(approved)
    after = len(approved)
    if after != before:
        print(f"🧹 Dedupe veículo: {before} -> {after} (mantido menor preço por veículo)")


    approved.sort(key=lambda x: x["margem"], reverse=True)
    _flush_learned()  # persiste aprendizados de marca/modelo em buffer (a cada LEARN_SAVE_EVERY)
    return (approved, rejected)


def _build_ranking(
    listings: List[Dict[str, Any]],
    fipe_db: Dict[str, Any],
    keywords_avoid: List[str],
    margin_min_reais: float = 0,
    vehicle_types: Optional[Dict[str, bool]] = None
) -> tuple:
    """Retorna (ranking, rejected). rejected contém anúncios excluídos com drop_reason."""
    if vehicle_types is None:
        vehicle_types = {"car": True, "motorcycle": True, "truck": True}
    get_fipe_from_cache_or_api = _get_fipe_api_func()

    print(f"🔍 Avaliando {len(listings)} anúncios")
    try:
        from ai_fipe_helper import is_ai_configured
        if is_ai_configured():
            print("🤖 IA ativa: análise de golpe e sugestão de modelo FIPE (em lote)")
    except ImportError:
        pass

    drop_reasons: Dict[str, int] = {}
    ranking, rejected = build_ranking_with_rejected(
        listings, fipe_db, keywords_avoid, margin_min_reais, vehicle_types,
        get_fipe_from_cache_or_api, drop_reasons, progress_callback=None,
    )

    # Relatório de por que anúncios foram excluídos (ajuda a ajustar FIPE/keywords/margem)
    if drop_reasons and len(ranking) == 0:
        total_drop = sum(drop_reasons.values())
        if total_drop > 0:
            print("📋 Motivos de exclusão (por que 0 oportunidades):")
            for reason, count in sorted(drop_reasons.items(), key=lambda x: -x[1]):
                label = {
                    "palavra_chave": "palavra-chave evitada (ex.: quitado, sinistro)",
                    "sem_fipe": "sem valor FIPE na base",
                    "margem_insuficiente": "margem abaixo de R$ %.0f" % (margin_min_reais * 0.9),
                    "tipo_veículo": "tipo desativado (moto/caminhão)",
                    "sem_marca": "marca não reconhecida",
                    "risco_ia": "risco de golpe (IA)",
                    "preço_suspeito": "preço muito abaixo da FIPE",
                    "sem_modelo": "não foi possível extrair modelo",
                    "sem_título_ou_ano": "sem título ou ano",
                    "sem_preço": "sem preço válido",
                    "moeda": "moeda diferente de BRL",
                }.get(reason, reason)
                print("   • %s: %d" % (label, count))
            print("   💡 Dica: termos como 'quitado' ou 'permuta' em keywords_golpe.txt excluem anúncios legítimos. Use Atualizar FIPE para base mais recente.")

    ranking.sort(key=lambda x: x["margem"], reverse=True)
    return (ranking, rejected)


def _get_source_name(item: Dict[str, Any]) -> str:
    """
    Identifica a origem do anúncio pelo campo 'source' ou pela URL.
    Retorna: 'FB Marketplace', 'OLX', 'Webmotors', 'Mobiauto' ou 'Desconhecido'
    """
    source = item.get("source", "").lower()
    url = item.get("url", "").lower()
    
    if source == "facebook" or "facebook.com" in url or "marketplace" in url:
        return "FB Marketplace"
    elif source == "olx" or "olx.com.br" in url:
        return "OLX"
    elif source == "webmotors" or "webmotors.com.br" in url:
        return "Webmotors"
    elif source == "mobiauto" or "mobiauto.com.br" in url:
        return "Mobiauto"
    else:
        return "Desconhecido"

from urllib.parse import urlsplit

def _canon_url(u: str) -> str:
    """Remove query/hash pra não tratar a mesma página como URLs diferentes."""
    try:
        if not u:
            return ""
        p = urlsplit(u.strip())
        return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/")
    except Exception:
        return (u or "").strip()

def _safe_int(x, default=None):
    try:
        if x is None:
            return default
        if isinstance(x, (int, float)):
            return int(x)
        s = str(x).strip().lower()
        s = s.replace(".", "").replace(",", ".")
        # pegar só dígitos (km/ano/price às vezes vêm com texto)
        import re
        m = re.findall(r"\d+", s)
        return int(m[0]) if m else default
    except Exception:
        return default

def _normalize_model_key(s: str) -> str:
    """Chave estável do modelo: prioriza modelo_fipe; fallback modelo_abrev/título."""
    s = (s or "").strip().lower()
    import re
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # corta lixo comum
    stop = {"completo","top","extra","impecavel","novo","único","unico","oportunidade","financio","financia"}
    toks = [t for t in s.split() if t not in stop]
    # limita pra não virar “texto todo do anúncio”
    return " ".join(toks[:6])

def _vehicle_signature(item: dict) -> str:
    """
    Assinatura do veículo:
    marca + modelo_key + ano + km_bucket
    (km_bucket deixa tolerante a pequenas diferenças de km/ausência)
    """
    marca = (item.get("marca_norm") or item.get("marca") or "").strip().lower()
    modelo_key = (
        item.get("modelo_fipe")
        or item.get("modelo_abrev")
        or item.get("modelo")
        or item.get("title")
        or ""
    )
    modelo_key = _normalize_model_key(modelo_key)

    ano = _safe_int(item.get("year"), 0) or 0
    km = _safe_int(item.get("km"), None)

    # bucket de km: 0-20k / 20-50k / 50-100k / 100-150k / 150k+
    if km is None:
        km_bucket = "km?"
    elif km < 20000:
        km_bucket = "km<20k"
    elif km < 50000:
        km_bucket = "km<50k"
    elif km < 100000:
        km_bucket = "km<100k"
    elif km < 150000:
        km_bucket = "km<150k"
    else:
        km_bucket = "km150k+"

    return f"{marca}|{modelo_key}|{ano}|{km_bucket}"

def _dedupe_keep_lowest_price(items: list) -> list:
    """
    Agrupa por assinatura do veículo e mantém o MENOR PREÇO.
    Se preço empatar/ausente, usa maior margem como desempate.
    """
    best = {}
    for it in items or []:
        sig = _vehicle_signature(it)
        price = _safe_int(it.get("price"), None)
        margem = it.get("margem")
        try:
            margem = float(margem) if margem is not None else None
        except Exception:
            margem = None

        if sig not in best:
            best[sig] = it
            continue

        cur = best[sig]
        cur_price = _safe_int(cur.get("price"), None)
        cur_margem = cur.get("margem")
        try:
            cur_margem = float(cur_margem) if cur_margem is not None else None
        except Exception:
            cur_margem = None

        # regra: menor preço ganha
        if price is not None and (cur_price is None or price < cur_price):
            best[sig] = it
        elif price is not None and cur_price is not None and price == cur_price:
            # desempate: maior margem
            if margem is not None and (cur_margem is None or margem > cur_margem):
                best[sig] = it

    return list(best.values())



# Ordem das fontes no resumo do relatório
_SOURCE_ORDER = ("FB Marketplace", "OLX", "Webmotors", "Mobiauto")


def _count_by_source(items: List[Dict[str, Any]]) -> Dict[str, int]:
    """Conta itens por origem (FB Marketplace, OLX, Webmotors, Mobiauto)."""
    counts = {s: 0 for s in _SOURCE_ORDER}
    for item in items or []:
        name = _get_source_name(item)
        if name in counts:
            counts[name] += 1
    return counts


def _format_source_counts(counts: Dict[str, int]) -> str:
    """Formata contagem por fonte: 'X FB Marketplace | X OLX | X Webmotors | X Mobiauto'."""
    return " | ".join("%d %s" % (counts.get(s, 0), s) for s in _SOURCE_ORDER)


def write_ranking_report(ranking: List[Dict[str, Any]], out_dir: Optional[Path] = None, ui_dir: Optional[Path] = None, rejected: Optional[List[Dict[str, Any]]] = None) -> None:
    """
    Gera cache FIPE, relatório HTML e envia oportunidades ao Telegram.
    Se out_dir/ui_dir forem None, usa path_utils.
    rejected: lista opcional de anúncios rejeitados com motivo de exclusão.
    """
    from path_utils import get_out_dir, get_ui_dir
    if out_dir is None:
        out_dir = get_out_dir()
    if ui_dir is None:
        ui_dir = get_ui_dir()

    def _safe_display_title(item: Dict[str, Any]) -> str:
        """Título para exibição; fallback do slug da URL quando título é 'Descrição' (OLX)."""
        t = (item.get("title") or "").strip()
        if (t or "").lower() == "descrição" or not t:
            marca = (item.get("marca") or "").strip()
            det = item.get("detalhes") or {}
            modelo = (det.get("Modelo") or det.get("modelo") or "").strip()
            if marca or modelo:
                return ("%s %s" % (marca, modelo)).strip()
            url = (item.get("url") or "").strip()
            if url and "olx" in url.lower():
                slug = (url.rstrip("/").split("/")[-1] or "").split("?")[0]
                if slug:
                    with_spaces = slug.replace("-", " ").strip()
                    if with_spaces and len(with_spaces) > 2:
                        if " " in with_spaces and with_spaces.rsplit(" ", 1)[-1].isdigit():
                            with_spaces = with_spaces.rsplit(" ", 1)[0].strip()
                        if with_spaces:
                            return with_spaces[:80]
        return t or "—"

    def _safe_display_city(item: Dict[str, Any]) -> str:
        """Cidade para exibição; fallback da URL (ex.: Mobiauto)."""
        c = (item.get("city") or "").strip()
        if c and len(c) <= 80 and not c.startswith("{") and '"props"' not in c and '"pageProps"' not in c:
            return c[:40]
        url = (item.get("url") or "").strip()
        if url and "mobiauto" in url.lower():
            m = re.search(r'/comprar/[^/]+/([a-z]{2})-([a-z0-9-]+)(?:/|$)', url)
            if not m:
                m = re.search(r'/([a-z]{2})-([a-z0-9-]+)(?:/|$)', url)
            if m:
                uf, slug = m.group(1).upper(), m.group(2).replace("-", " ").title()
                if slug and uf and len(slug) < 50:
                    return (slug + " - " + uf)[:40]
        return "—"

    # HTML com anúncios processados (listings_all_clean.json) — ao lado do index.html
    listings_json = out_dir / "listings_all_clean.json"
    if listings_json.exists():
        try:
            with open(listings_json, "r", encoding="utf-8") as f:
                all_listings = json.load(f)
            rows = []
            for item in all_listings:
                src = _get_source_name(item)
                title = html.escape(_safe_display_title(item))[:120]
                year = item.get("year") or "—"
                price = item.get("price")
                price_str = ("R$ " + f"{price:,.0f}".replace(",", ".")) if price else "—"
                km = item.get("km")
                km_str = "%s km" % f"{km:,}".replace(",", ".") if km else "—"
                city = html.escape(_safe_display_city(item))
                url = html.escape(item.get("url", ""))
                rows.append(
                    f'<tr><td>{html.escape(src)}</td><td>{title}</td><td>{year}</td><td>{price_str}</td><td>{km_str}</td><td>{city}</td><td><a href="{url}" target="_blank">Ver</a></td></tr>'
                )
            listagens_html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Anúncios processados (listings_all_clean)</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
    h1 {{ color: #333; }}
    p {{ color: #666; }}
    table {{ width: 100%; border-collapse: collapse; background: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
    th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; font-size: 13px; }}
    th {{ background: #2196F3; color: white; }}
    tr:hover {{ background: #f5f5f5; }}
    a {{ color: #2196F3; }}
  </style>
</head>
<body>
  <h1>Anúncios processados</h1>
  <p>Conteúdo de <strong>out/listings_all_clean.json</strong> — anúncios que entram no ranking. Total: {len(all_listings)}.</p>
  <p><a href="index.html">← Voltar ao relatório de oportunidades</a></p>
  <table>
    <thead><tr><th>Origem</th><th>Título</th><th>Ano</th><th>Preço</th><th>Km</th><th>Cidade</th><th>Link</th></tr></thead>
    <tbody>
{"".join(rows)}
    </tbody>
  </table>
</body>
</html>"""
            listagens_file = ui_dir / "listagens.html"
            with open(listagens_file, "w", encoding="utf-8") as f:
                f.write(listagens_html)
            print(f"📄 Listagens (processados): {listagens_file}")
        except Exception as e:
            print(f"⚠️ Erro ao gerar listagens.html: {e}")

    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fipe_match_cache_file = cache_dir / "fipe_match_cache.json"
    fipe_match_cache = {}
    for item in ranking:
        fipe_match_cache[item["url"]] = {
            "title_original": item.get("title_original", ""),
            "title_normalized": item.get("title_normalized", ""),
            "modelo_fipe": item.get("modelo_fipe", "-"),
            "valor_fipe": item.get("fipe"),
            "ano_fipe": item.get("ano_fipe"),
        }
    try:
        with open(fipe_match_cache_file, "w", encoding="utf-8") as f:
            json.dump(fipe_match_cache, f, indent=2, ensure_ascii=False)
        print(f"📁 Cache FIPE (título normalizado + match): {fipe_match_cache_file}")
    except Exception as e:
        print(f"⚠️ Erro ao salvar cache FIPE: {e}")

    # Referência FIPE (mês/ano dos preços) e data do arquivo para o relatório
    fipe_ref_str = ""
    fipe_date_str = ""
    fipe_warning = ""
    try:
        last_update_file = cache_dir / "fipe_last_update.json"
        if last_update_file.exists():
            with open(last_update_file, "r", encoding="utf-8") as f:
                _fipe_meta = json.load(f)
            fipe_ref_str = (_fipe_meta.get("fipe_reference_month") or _fipe_meta.get("reference_month") or "").strip()
            _last = _fipe_meta.get("last_update") or (_fipe_meta.get("iso") or "")[:10]
            if _last:
                fipe_date_str = _last[8:10] + "/" + _last[5:7] + "/" + _last[:4]
        from fipe_update_if_due import get_last_update_date
        last_fipe = get_last_update_date()
        if last_fipe and not fipe_date_str:
            fipe_date_str = last_fipe.strftime("%d/%m/%Y")
        if last_fipe:
            import datetime
            days_old = (datetime.date.today() - last_fipe).days
            if days_old > 60:
                fipe_warning = (
                    f'<p style="background:#fff3cd;padding:10px;border-radius:6px;">'
                    f'⚠️ <strong>Tabela FIPE pode estar desatualizada</strong> (última atualização: {fipe_date_str}). '
                    f'Valores de 2022/2023 superestimam as margens. Use o botão <strong>Atualizar FIPE</strong> no app para obter preços de referência atuais.</p>'
                )
    except Exception:
        pass
    if not fipe_ref_str:
        fipe_ref_str = "não informada"
    if not fipe_date_str:
        fipe_date_str = "não registrada"

    html_file = ui_dir / "index.html"
    rejected_count = len(rejected) if rejected else 0
    total_evaluated = len(ranking) + rejected_count
    approved_by_source = _count_by_source(ranking)
    rejected_by_source = _count_by_source(rejected)
    approved_source_str = _format_source_counts(approved_by_source)
    rejected_source_str = _format_source_counts(rejected_by_source)
    # Contagem por motivo de rejeição (para o resumo no topo)
    drop_reason_labels = {
        "moeda": "Moeda diferente de BRL",
        "sem_título_ou_ano": "Sem título ou ano",
        "sem_preço": "Sem preço válido",
        "tipo_veículo": "Tipo de veículo desativado",
        "palavra_chave": "Palavra-chave evitada (ex.: quitado, sinistro)",
        "sem_modelo": "Não foi possível extrair modelo",
        "sem_marca": "Marca não reconhecida",
        "sem_fipe": "Sem valor FIPE na base",
        "preço_suspeito": "Preço muito abaixo da FIPE",
        "risco_ia": "Risco de golpe (IA)",
        "margem_insuficiente": "Margem abaixo do mínimo",
        "desconhecido": "Motivo desconhecido",
    }
    reason_counts = {}
    for item in (rejected or []):
        r = item.get("drop_reason", "desconhecido")
        reason_counts[r] = reason_counts.get(r, 0) + 1
    rejection_summary_lines = []
    for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
        label = drop_reason_labels.get(reason, reason)
        rejection_summary_lines.append("• %s: %d" % (label, count))
    rejection_summary_html = "<br>\n        ".join(html.escape(line) for line in rejection_summary_lines) if rejection_summary_lines else "—"
    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AutoRadar - Ranking de Oportunidades</title>
  <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        h1 {{ color: #333; }}
        h2 {{ color: #555; margin-top: 30px; }}
        .tabs {{ display: flex; gap: 10px; margin: 20px 0; }}
        .tab {{ padding: 10px 20px; background: #ddd; cursor: pointer; border-radius: 5px 5px 0 0; }}
        .tab.active {{ background: #4CAF50; color: white; }}
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}
        table {{ width: 100%; border-collapse: collapse; background: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-top: 10px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; font-size: 14px; }}
        th {{ background: #4CAF50; color: white; font-weight: bold; }}
        .rejected-table th {{ background: #f44336; }}
        tr:hover {{ background: #f5f5f5; }}
        .margem-positiva {{ color: green; font-weight: bold; }}
        .drop-reason {{ color: #d32f2f; font-weight: bold; }}
        a {{ color: #2196F3; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .stats {{ background: white; padding: 15px; border-radius: 5px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .stats-by-source {{ font-size: 14px; color: #444; margin: 6px 0; }}
  </style>
    <script>
        function showTab(tabName) {{
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById(tabName).classList.add('active');
        }}
    </script>
</head>
<body>
    <h1>🚗 AutoRadar - Relatório Completo</h1>
    <div class="stats">
        <p><strong>{total_evaluated} anúncios enviados no último scan.</strong></p>
        <p><strong>Total avaliado:</strong> {total_evaluated} anúncios</p>
        <p><strong>✅ Aprovados:</strong> {len(ranking)} oportunidades</p>
        <p class="stats-by-source">→ {approved_source_str}</p>
        <p><strong>❌ Rejeitados:</strong> {rejected_count} anúncios</p>
        <p class="stats-by-source">→ {rejected_source_str}</p>
        {('<p><strong>Motivos de rejeição:</strong></p><p class="stats-by-source">' + rejection_summary_html + '</p>') if rejected_count > 0 else ''}
        <p style="color:#666;font-size:13px;">📅 Referência FIPE (mês/ano dos preços): <strong>{fipe_ref_str}</strong> — arquivo: {fipe_date_str}</p>
    </div>
    {fipe_warning}
    <div class="tabs">
        <div class="tab active" onclick="showTab('approved')">✅ Oportunidades ({len(ranking)})</div>
        <div class="tab" onclick="showTab('rejected')">❌ Rejeitados ({rejected_count})</div>
    </div>
    <div id="approved" class="tab-content active">
    <h2>Oportunidades Encontradas</h2>
    <table>
        <thead>
            <tr>
                <th>Modelo</th>
                <th>IA</th>
                <th>Modelo FIPE Aprox</th>
                <th>Ano</th>
                <th>Km</th>
                <th>Preço</th>
                <th>FIPE Aprox</th>
                <th>Margem R$</th>
                <th>Margem %</th>
                <th>Risco golpe</th>
                <th>Cidade</th>
                <th>Detalhes</th>
                <th>Link</th>
            </tr>
        </thead>
        <tbody>
"""
    for item in ranking:
        km_str = f"{item['km']:,}" if item.get('km') else "-"
        margem_reais = item.get("margem_reais", item["fipe"] - item["preco"])
        preco_cel = html.escape(str(item.get("price_display") or f"R$ {item['preco']:,.2f}"))
        ia_badge = "🤖 IA Check" if item.get("ia_checked") else "—"
        fipe_val = "R$ {0:,.2f}".format(item['fipe'])
        if item.get("fipe_ia_used"):
            fipe_cel = fipe_val + " <small>(est. IA)</small>"
        else:
            fipe_cel = fipe_val
        rg = item.get("risco_golpe")
        risco_cel = html.escape(str(rg)) if rg in ("Alto", "Médio") else ""
        # Alerta de margem suspeita (>25%)
        margem_val = item.get("margem", 0)
        margem_suspeita_badge = ""
        if margem_val > 25.0:
            margem_suspeita_badge = ' <span style="color:#ff6600;font-weight:bold;">⚠️ Margem suspeita. Atenção</span>'
        det_parts = []
        if item.get("cambio"):
            det_parts.append(f"Câmbio: {item['cambio']}")
        if item.get("cor_externa"):
            det_parts.append(f"Cor ext.: {item['cor_externa']}")
        if item.get("cor_interna"):
            det_parts.append(f"Cor int.: {item['cor_interna']}")
        if item.get("combustivel"):
            det_parts.append(f"Comb.: {item['combustivel']}")
        details_cel = html.escape(" · ".join(det_parts)) if det_parts else "—"
        source_name = _get_source_name(item)
        html_content += f"""
            <tr>
                <td><strong>{html.escape(source_name)}</strong></td>
                <td>{html.escape(str(item['modelo']))}{margem_suspeita_badge}</td>
                <td>{ia_badge}</td>
                <td>{html.escape(str(item['modelo_fipe']))}</td>
                <td>{item['ano']}</td>
                <td>{km_str} km</td>
                <td>{preco_cel}</td>
                <td>{fipe_cel}</td>
                <td class="margem-positiva">R$ {margem_reais:,.0f}</td>
                <td class="margem-positiva">{item['margem']:.1f}%</td>
                <td title="{html.escape(str(item.get('risco_motivo') or ''))}">{risco_cel}</td>
                <td>{html.escape(str(item['cidade']))}</td>
                <td>{details_cel}</td>
                <td><a href="{html.escape(item['url'])}" target="_blank">Ver Anúncio</a></td>
            </tr>
"""
    html_content += """
        </tbody>
    </table>
    </div>
    <div id="rejected" class="tab-content">
    <h2>Anúncios Rejeitados</h2>
"""
    if rejected and len(rejected) > 0:
        drop_reason_labels = {
            "moeda": "Moeda diferente de BRL",
            "sem_título_ou_ano": "Sem título ou ano",
            "sem_preço": "Sem preço válido",
            "tipo_veículo": "Tipo de veículo desativado",
            "palavra_chave": "Palavra-chave evitada",
            "sem_modelo": "Não foi possível extrair modelo",
            "sem_marca": "Marca não reconhecida",
            "sem_fipe": "Sem valor FIPE na base",
            "preço_suspeito": "Preço muito abaixo da FIPE (<40%)",
            "risco_ia": "Risco de golpe (IA)",
            "margem_insuficiente": "Margem abaixo do mínimo",
            "desconhecido": "Motivo desconhecido",
        }
        html_content += """
    <table class="rejected-table">
    <thead>
      <tr>
        <th>Origem</th>
        <th>Título</th>
        <th>Preço</th>
        <th>Ano</th>
        <th>Km</th>
        <th>Cidade</th>
        <th>Motivo de Exclusão</th>
        <th>Link</th>
      </tr>
    </thead>
        <tbody>
"""
        for item in rejected:
            title = html.escape(_safe_display_title(item))[:100]
            price = item.get("price")
            price_str = f"R$ {price:,.0f}" if price else "—"
            year = item.get("year") or "—"
            km = f"{item.get('km'):,} km" if item.get("km") else "—"
            city = html.escape(_safe_display_city(item))
            drop_reason = item.get("drop_reason", "desconhecido")
            reason_label = drop_reason_labels.get(drop_reason, drop_reason)
            url = html.escape(item.get("url", ""))
            source_name = _get_source_name(item)
            html_content += f"""
            <tr>
                <td><strong>{html.escape(source_name)}</strong></td>
                <td>{title}</td>
                <td>{price_str}</td>
                <td>{year}</td>
                <td>{km}</td>
                <td>{city}</td>
                <td class="drop-reason">{reason_label}</td>
                <td><a href="{url}" target="_blank">Ver Anúncio</a></td>
            </tr>
"""
        html_content += """
        </tbody>
  </table>
"""
    else:
        html_content += """
    <p>Nenhum anúncio foi rejeitado nesta execução.</p>
"""
    html_content += """
    </div>
</body>
</html>
"""
    try:
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"📄 Relatório HTML: {html_file}")
    except Exception as e:
        print(f"❌ Erro ao gerar HTML: {e}")

    try:
        from send_telegram import load_config, send_opportunities
        if load_config():
            # Log para debug: verificar origem dos anúncios no ranking
            if ranking:
                fb_count = len([r for r in ranking if 'facebook.com' in r.get('url', '')])
                wm_count = len([r for r in ranking if 'webmotors.com.br' in r.get('url', '')])
                ma_count = len([r for r in ranking if 'mobiauto.com.br' in r.get('url', '')])
                olx_count = len([r for r in ranking if 'olx.com.br' in r.get('url', '')])
                print(f"📱 Telegram: enviando {len(ranking)} oportunidades (FB: {fb_count}, WM: {wm_count}, MA: {ma_count}, OLX: {olx_count})")
            send_opportunities(ranking)
        if ranking:
            last_file = out_dir / "last_ranking_for_telegram.json"
            try:
                with open(last_file, "w", encoding="utf-8") as f:
                    json.dump(ranking, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
    except Exception as e:
        print(f"⚠️ Telegram: {e}")


def main():
    """Função principal: lê listings_all_clean.json, FIPE, keywords e gera UI/index.html"""
    from path_utils import get_out_dir, get_ui_dir

    out_dir = get_out_dir()
    ui_dir = get_ui_dir()

    listings_file = out_dir / "listings_all_clean.json"
    if not listings_file.exists():
        print(f"❌ Arquivo não encontrado: {listings_file}")
        return

    print(f"📖 Lendo {listings_file}...")
    try:
        with open(listings_file, 'r', encoding='utf-8') as f:
            listings = json.load(f)
    except Exception as e:
        print(f"❌ Erro ao ler arquivo: {e}")
        return

    fipe_file = out_dir / "fipe_db_norm.json"
    if not fipe_file.exists():
        print(f"❌ Arquivo FIPE não encontrado: {fipe_file}")
        return

    try:
        with open(fipe_file, 'r', encoding='utf-8') as f:
            fipe_db = json.load(f)
    except Exception as e:
        print(f"❌ Erro ao ler FIPE: {e}")
        return

    keywords_avoid = []
    keywords_file = BASE_DIR / "keywords_golpe.txt"
    if keywords_file.exists():
        try:
            with open(keywords_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        keywords_avoid.append(line)
        except Exception:
            pass

    margin_min_reais = 5000.0
    vehicle_types = {"car": True, "motorcycle": True, "truck": True}
    prefs_file = BASE_DIR / "user_preferences.json"
    if prefs_file.exists():
        try:
            with open(prefs_file, 'r', encoding='utf-8') as f:
                prefs = json.load(f)
                margin_min_reais = float(prefs.get("margin_min_reais", margin_min_reais))
                vehicle_types = prefs.get("vehicle_types", vehicle_types)
        except Exception:
            pass

    ranking, rejected = _build_ranking(listings, fipe_db, keywords_avoid, margin_min_reais, vehicle_types)

    if not ranking:
        print("⚠️ Nenhuma oportunidade encontrada")

    write_ranking_report(ranking, out_dir, ui_dir, rejected=rejected)
    return len(ranking)


if __name__ == "__main__":
    main()
