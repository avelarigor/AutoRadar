"""
Faz o match entre título+descrição de anúncio de PS5 e a tabela de preços de referência.

Lógica:
  - Detecta variante (pro, slim, digital) no título
  - Retorna (modelo_chave, preco_ref) ou (None, None)

Todos os modelos têm preço único R$3200 — o matcher é conservador:
retorna sempre que detectar "ps5" ou "playstation 5" no título.
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


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Aliases para variações comuns nos títulos de anúncios
_ALIASES = [
    (r"\bplaystation\s*5\b",       "ps5"),
    (r"\bplaystation\s*v\b",       "ps5"),
    (r"\bps\s*5\b",                "ps5"),
    (r"\bps5\s*slim\b",            "ps5 slim"),
    (r"\bps5\s*pro\b",             "ps5 pro"),
    (r"\bps5\s*digital\b",         "ps5 digital"),
    (r"\bps5\s*slim\s*digital\b",  "ps5 slim digital"),
]


def match(title: str, description: str = ""):
    """
    Recebe título e descrição do anúncio.
    Retorna (modelo_chave, preco_ref) ou (None, None).

    Exemplos:
      match("PS5 Slim 1TB")           → ("ps5 slim", 3200)
      match("PlayStation 5 Pro")      → ("ps5 pro", 3200)
      match("PS5 Digital Edition")    → ("ps5 digital", 3200)
      match("PS5")                    → ("ps5", 3200)
      match("Controle PS5 DualSense") → (None, None)  ← sem console identificado
    """
    combined = f"{title} {description}"
    norm = _normalize(combined)

    # Aplica aliases para padronizar variações
    for pattern, replacement in _ALIASES:
        norm = re.sub(pattern, replacement, norm)

    # ── Verifica se é um PS5 (e não só acessório/jogo) ──────────────────────
    if "ps5" not in norm:
        return None, None

    # ── Detecta variante mais específica primeiro ────────────────────────────
    if "ps5 slim digital" in norm:
        key = "ps5 slim digital"
    elif "ps5 slim" in norm:
        key = "ps5 slim"
    elif "ps5 pro" in norm:
        key = "ps5 pro"
    elif "ps5 digital" in norm:
        key = "ps5 digital"
    else:
        key = "ps5"

    ref_price = PRICES.get(key, PRICES["ps5"])
    return key, ref_price
