from typing import Dict, Any, Optional
from datetime import datetime
import re

def normalize_olx_listing(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza os dados brutos do extrator OLX em campos tipados e no nível raiz.
    """

    def parse_price(value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        value = re.sub(r"\D", "", str(value))
        return int(value) if value.isdigit() else None

    def parse_int(value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        value = re.sub(r"\D", "", str(value))
        return int(value) if value.isdigit() else None

    def parse_year(value: Optional[str]) -> Optional[int]:
        """Extrai o primeiro grupo de 4 dígitos que parece um ano."""
        if not value:
            return None
        m = re.search(r"(19[6-9]\d|20[012]\d)", str(value))
        return int(m.group(1)) if m else None

    def parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        # Tentar formato timestamp Unix (ms ou s)
        if str(value).isdigit():
            ts = int(value)
            if ts > 1e10:
                ts = ts // 1000
            try:
                return datetime.fromtimestamp(ts)
            except Exception:
                pass
        # Tentar formatos de texto comuns
        for fmt in ("%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(value)[:19], fmt)
            except ValueError:
                continue
        return None

    # -------------------------------------------------------
    # Campos extraídos diretamente do extrator (novo formato)
    # -------------------------------------------------------
    title = raw_data.get("title", "")
    brand = raw_data.get("brand") or raw_data.get("raw_details", {}).get("car_brand")
    model = raw_data.get("model") or raw_data.get("raw_details", {}).get("car_model")
    year = parse_year(raw_data.get("year_raw") or raw_data.get("raw_details", {}).get("regdate"))
    km = parse_int(raw_data.get("km_raw") or raw_data.get("raw_details", {}).get("mileage"))

    price = parse_price(raw_data.get("price_raw"))
    fipe_olx = parse_price(raw_data.get("fipe_olx_raw"))
    avg_price_olx = parse_price(raw_data.get("avg_price_olx_raw"))

    city = raw_data.get("city")
    state = raw_data.get("state")
    description = raw_data.get("description", "")

    cambio = raw_data.get("cambio")
    combustivel = raw_data.get("combustivel")
    cor_externa = raw_data.get("cor_externa")
    cor_interna = raw_data.get("raw_details", {}).get("interior_color")

    images = raw_data.get("images", [])
    published_at = parse_datetime(raw_data.get("published_at_raw"))

    return {
        "title": title,
        "brand": brand if brand else None,
        "model": model if model else None,
        "year": year,
        "km": km,
        "price": price,
        "fipe_olx": fipe_olx,
        "avg_price_olx": avg_price_olx,
        "city": city,
        "state": state,
        "description": description,
        "cambio": cambio,
        "combustivel": combustivel,
        "cor_externa": cor_externa,
        "cor_interna": cor_interna,
        "images": images,
        "published_at": published_at,
        "raw_details": raw_data.get("raw_details", {}),
    }
