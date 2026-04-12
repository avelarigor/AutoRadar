"""
Formata mensagem Telegram para oportunidades de PS5.
"""
import re
import html as _html


def _clean_for_telegram(text: str) -> str:
    """Remove/converte HTML e escapa caracteres especiais para texto seguro no parse_mode HTML."""
    if not text:
        return text
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = _html.unescape(text)
    return text.strip()


def format_ps5_message(opp: dict) -> str:
    title        = opp.get("title", "PS5")
    price        = opp.get("price", 0)
    ref_price    = opp.get("ref_price", 0)
    margin       = opp.get("margin", 0)
    source       = opp.get("source", "")
    url          = opp.get("url", "")
    description  = _clean_for_telegram(opp.get("description") or "")
    condition    = _clean_for_telegram(opp.get("condition") or "")
    location     = _clean_for_telegram(opp.get("location") or "")
    published_at = _clean_for_telegram(opp.get("published_at") or "")

    source_label = "Facebook Marketplace" if source == "facebook" else "OLX"

    price_fmt  = f"R$ {price:,.0f}".replace(",", ".")
    ref_fmt    = f"R$ {ref_price:,.0f}".replace(",", ".")
    margin_fmt = f"R$ {margin:,.0f}".replace(",", ".")

    lines = [
        f"🎮 <b>{title}</b> | {source_label}",
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

    lines += ["", "( ( 📡 ) ) | AutoPS5 🎮 🎯"]

    return "\n".join(lines)
