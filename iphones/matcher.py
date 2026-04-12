"""
Faz o match entre título+descrição de anúncio e a tabela de preços de referência.

Lógica de piso (conservadora):
  - GB detectado + existe na tabela  → preço exato
  - GB detectado + não existe na tabela  → menor preço do modelo (piso)
  - GB não detectado  → menor preço do modelo (piso)

Retorna (chave_modelo, storage_label, preco_referencia) ou (None, None, None).
"""

import json
import re
from pathlib import Path

_PRICES_PATH = Path(__file__).parent / "prices.json"

def _load_prices() -> dict:
    with open(_PRICES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["prices"]


PRICES = _load_prices()

# Piso por modelo calculado dinamicamente a partir de PRICES.
# Ex: _MODEL_MIN["iphone 14"] = ("128", 2500)
_MODEL_MIN: dict[str, tuple[str, int]] = {}
for _key, _price in PRICES.items():
    _model, _storage = _key.rsplit("|", 1)
    if _model not in _MODEL_MIN or _price < _MODEL_MIN[_model][1]:
        _MODEL_MIN[_model] = (_storage, _price)


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Aliases para variações comuns nos títulos de anúncios
_ALIASES = [
    (r"\bpro\s*max\b",  "pro max"),
    (r"\bpromax\b",     "pro max"),
    (r"\bpro\+",        "pro max"),
    (r"\bi\s+phone\b",  "iphone"),
    (r"\biph\b",        "iphone"),
]

# Storage: padrões aceitos no título ou descrição
_STORAGE_PATTERNS = [
    (r"\b1\s*tb\b",      "1tb"),
    (r"\b1024\s*gb\b",   "1tb"),
    (r"\b512\s*gb\b",    "512"),
    (r"\b256\s*gb\b",    "256"),
    (r"\b128\s*gb\b",    "128"),
    (r"\b64\s*gb\b",     "64"),
]


def _extract_storage(text: str) -> str | None:
    """Extrai capacidade de armazenamento de qualquer texto."""
    t = text.lower()
    for pattern, value in _STORAGE_PATTERNS:
        if re.search(pattern, t):
            return value
    return None


def match(title: str, description: str = ""):
    """
    Recebe título e descrição do anúncio.
    Retorna (modelo_chave, storage_label, preco_ref) ou (None, None, None).

    Exemplos:
      match("iPhone 15 Pro Max 256GB")     → ("iphone 15 pro max", "256", 4650)  ← exato
      match("Iphone 14", "128GB perfeito") → ("iphone 14",         "128", 2500)  ← exato
      match("iPhone 13 Pro Max")           → ("iphone 13 pro max",  "128", 2900)  ← piso
      match("iPhone 14 Pro 2TB")           → ("iphone 14 pro",      "128", 3300)  ← piso (GB inválido)
      match("Samsung Galaxy S24")          → (None, None, None)
    """
    # Normaliza apenas o título para checar se é realmente um anúncio de iPhone.
    # Modelo DEVE estar no título — descrição só é usada para complementar storage.
    title_norm = _normalize(title or "")
    for pattern, replacement in _ALIASES:
        title_norm = re.sub(pattern, replacement, title_norm)
    title_norm = re.sub(r"\s+", " ", title_norm).strip()

    if "iphone" not in title_norm:
        # Título não contém iPhone → rejeitar (evita falsos positivos de bicicletas,
        # carros e outros itens cuja descrição menciona iPhone casualmente)
        return None, None, None

    # Junta título + descrição para ampliar a busca de storage
    combined = f"{title} {description or ''}"
    norm = _normalize(combined)
    for pattern, replacement in _ALIASES:
        norm = re.sub(pattern, replacement, norm)
    norm = re.sub(r"\s+", " ", norm).strip()

    # Extrai geração (12–17)
    m = re.search(r"iphone\s*(\d{2})", norm)
    if not m:
        return None, None, None
    gen = m.group(1)
    if gen not in ("12", "13", "14", "15", "16", "17"):
        return None, None, None

    # Detecta variante: pro max > pro > base
    if "pro max" in norm:
        variant = "pro max"
    elif "pro" in norm:
        variant = "pro"
    else:
        variant = ""

    model_key = f"iphone {gen}" + (f" {variant}" if variant else "")

    # Extrai storage do combined (título tem prioridade)
    storage = _extract_storage(title) or _extract_storage(description or "")

    # --- Busca exata: GB detectado E existe na tabela ---
    if storage:
        price = PRICES.get(f"{model_key}|{storage}")
        if price:
            return model_key, storage, price
        # GB detectado mas não na tabela → cai no piso de segurança

    # --- Piso: sem GB ou GB inválido → menor preço disponível do modelo ---
    floor = _MODEL_MIN.get(model_key)
    if floor:
        floor_storage, floor_price = floor
        return model_key, floor_storage, floor_price

    return None, None, None
