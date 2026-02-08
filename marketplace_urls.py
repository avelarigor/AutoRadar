# marketplace_urls.py - URLs do Facebook Marketplace para Veículos
# Created by Igor Avelar - avelar.igor@gmail.com
#
# Regra: sempre categoria veículos.
# Dois formatos suportados:
# 1) /marketplace/category/vehicles?location=...&minPrice=...&maxPrice=...
# 2) /marketplace/{region_id}/search/?category_id=546583916084032&query=Veículos (igual ao navegador)
# www (não m.) para evitar "Facebook is not available on this browser".

from urllib.parse import quote

# ID da categoria Veículos no Marketplace (igual ao link que o navegador abre)
VEHICLES_CATEGORY_ID = "546583916084032"


def build_marketplace_url(
    city: str,
    state: str,
    price_min: int,
    price_max: int,
    marketplace_region_id: str = "",
) -> str:
    """
    Monta URL do Marketplace → apenas Veículos.
    Se marketplace_region_id for informado (ex.: 103996099635518), usa o mesmo
    formato do navegador: /marketplace/{id}/search/?category_id=...&query=Veículos.
    Senão usa: /marketplace/category/vehicles?location=...&minPrice=...&maxPrice=...
    """
    if marketplace_region_id and marketplace_region_id.strip():
        # Formato igual ao que o Facebook abre no navegador (veículos)
        base = f"https://www.facebook.com/marketplace/{marketplace_region_id.strip()}/search/"
        params = [
            "category_id=" + VEHICLES_CATEGORY_ID,
            "query=" + quote("Veículos", safe=""),
            "referral_ui_component=category_menu_item",
        ]
        if price_min and price_min > 0:
            params.append(f"minPrice={price_min}")
        if price_max and price_max > 0:
            params.append(f"maxPrice={price_max}")
        return base + "?" + "&".join(params)

    base = "https://www.facebook.com/marketplace/category/vehicles"
    params = []
    if city and state:
        location = f"{city.strip()}, {state.strip()}"
        params.append("location=" + quote(location, safe=""))
    if price_min and price_min > 0:
        params.append(f"minPrice={price_min}")
    if price_max and price_max > 0:
        params.append(f"maxPrice={price_max}")
    if params:
        return base + "?" + "&".join(params)
    return base
