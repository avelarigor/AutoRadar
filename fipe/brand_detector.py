import json
import os
import re
import unicodedata

from fipe.brand_alias import MARCAS_ALIAS, MARCAS_BASE


DATA_PATH = os.path.join("data", "marcas_cache.json")


def load_brands():

    if not os.path.exists(DATA_PATH):
        print("[BRAND DETECTOR] marcas_cache.json não encontrado")
        return []

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    brands = []

    for item in data:

        if isinstance(item, dict):

            if "nome" in item:
                brands.append(item["nome"].lower())

            elif "name" in item:
                brands.append(item["name"].lower())

        elif isinstance(item, str):
            brands.append(item.lower())

    return brands


BRANDS_CACHE = load_brands()


def normalize(text):

    if not text:
        return ""

    text = text.lower()

    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))

    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def detect_brand(title):

    if not title:
        return None

    title_norm = normalize(title)

    tokens = title_norm.split()

    for token in tokens:

        if token in MARCAS_ALIAS:
            return MARCAS_ALIAS[token]

    for brand in MARCAS_BASE:

        brand_norm = normalize(brand)

        if brand_norm in title_norm:
            return brand_norm

    for brand in BRANDS_CACHE:

        brand_norm = normalize(brand)

        if brand_norm in title_norm:
            return brand_norm

    return None