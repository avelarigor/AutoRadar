"""
Formata mensagem Telegram para oportunidades de iPhone.
"""
import re
import html as _html


def _clean_for_telegram(text: str) -> str:
    """Remove/converte HTML e escapa caracteres especiais para texto seguro no parse_mode HTML."""
    if not text:
        return text
    # Converte <br>, <br/> em nova linha
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    # Remove outras tags HTML residuais
    text = re.sub(r'<[^>]+>', '', text)
    # Decodifica entidades HTML (ex: &amp; → &)
    text = _html.unescape(text)
    return text.strip()


def format_iphone_message(opp: dict) -> str:
    title         = opp.get("title", "iPhone")
    price         = opp.get("price", 0)
    ref_price     = opp.get("ref_price", 0)
    margin        = opp.get("margin", 0)
    storage_label = opp.get("storage_label", "")
    source        = opp.get("source", "")
    url           = opp.get("url", "")
    description   = _clean_for_telegram(opp.get("description") or "")
    condition     = _clean_for_telegram(opp.get("condition") or "")
    location      = _clean_for_telegram(opp.get("location") or "")
    published_at  = _clean_for_telegram(opp.get("published_at") or "")

    source_label = "Facebook Marketplace" if source == "facebook" else "OLX"

    # Título limpo: adiciona storage ao título se ainda não constar
    display_title = title
    if storage_label and storage_label not in ("?",) and storage_label.lower() not in title.lower():
        gb_str = "1TB" if storage_label == "1tb" else f"{storage_label}GB"
        display_title = f"{title} {gb_str}"

    price_fmt  = f"R$ {price:,.0f}".replace(",", ".")
    ref_fmt    = f"R$ {ref_price:,.0f}".replace(",", ".")
    margin_fmt = f"R$ {margin:,.0f}".replace(",", ".")

    lines = [
        f"📱 <b>{display_title}</b> | {source_label}",
        f"🔥 Margem: <b>{margin_fmt}</b>",
        "",
        f"💰 Preço: {price_fmt}",
        f"📊 Valor Base: {ref_fmt}",
    ]

    if description:
        lines += ["", f"💬 Descrição: {description}"]

    if condition:
        lines += ["", f"✨ Condição: {condition}"]

    if published_at and location:
        lines += ["", f"📍 Anunciado {published_at} em {location}"]
    elif location:
        lines += ["", f"📍 {location}"]
    elif published_at:
        lines += ["", f"⏱ Anunciado {published_at}"]

    lines += ["", f"🔗 {url}"]

    lines += ["", "( ( 📡 ) ) | AutoIphones 📱 🎯"]

    return "\n".join(lines)
