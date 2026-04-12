from datetime import datetime as _dt
import re as _re
import html as _html_mod


def _clean_html(text: str) -> str:
    """Remove tags HTML residuais que podem quebrar o parse_mode=HTML do Telegram."""
    if not text:
        return text or ""
    text = _re.sub(r'<br\s*/?>', ' ', text, flags=_re.IGNORECASE)
    text = _re.sub(r'<[^>]+>', '', text)
    text = _html_mod.unescape(text)
    return text.strip()


def format_currency(value):
    """Formata valor monetário no padrão brasileiro: R$ 89.900,00"""
    if value is None:
        return "N/D"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    # f"{n:,.2f}" → "89,900.00" (US) → trocar separadores → "89.900,00" (BR)
    formatted = f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def safe_cap(value):
    return (value or "").capitalize()


def _format_elapsed_time(total_seconds: int) -> str:
    """Retorna texto como 'Publicado há 2 horas', 'Publicado há 1 mês e 15 dias', etc."""
    if total_seconds < 3600:
        mins = max(1, total_seconds // 60)
        return f"⏱ Publicado há {mins} {'minuto' if mins == 1 else 'minutos'}"
    if total_seconds < 86400:
        hours = total_seconds // 3600
        return f"⏱ Publicado há {hours} {'hora' if hours == 1 else 'horas'}"
    days = total_seconds // 86400
    if days < 30:
        return f"⏱ Publicado há {days} {'dia' if days == 1 else 'dias'}"
    months = days // 30
    rem_days = days % 30
    mes = 'mês' if months == 1 else 'meses'
    if rem_days > 0:
        dia = 'dia' if rem_days == 1 else 'dias'
        return f"⏱ Publicado há {months} {mes} e {rem_days} {dia}"
    return f"⏱ Publicado há {months} {mes}"


def _olx_publication_line(published_at) -> str:
    """Calcula tempo relativo para anúncios OLX. 'Detectado agora' apenas se < 30 min."""
    if not published_at:
        return "⏱ Detectado agora"
    try:
        if isinstance(published_at, str):
            pub_dt = _dt.strptime(published_at[:19], "%Y-%m-%d %H:%M:%S")
        elif isinstance(published_at, _dt):
            pub_dt = published_at
        else:
            return "⏱ Detectado agora"
        delta = _dt.now() - pub_dt
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            return "⏱ Detectado agora"
        if total_seconds < 1800:  # < 30 minutos
            return "⏱ Detectado agora"
        return _format_elapsed_time(total_seconds)
    except Exception:
        return "⏱ Detectado agora"





def format_telegram_message(listing: dict) -> str:

    title = _clean_html(listing.get("title") or "Sem título")
    
    km = listing.get("km")

    if km:
        km_text = f"{km:,} km".replace(",", ".")
    else:
        km_text = "Km não informado"
    
    
    # Garantir que price_display seja sempre formatado como moeda BR (R$ X.XXX,XX)
    _price_int = listing.get("price")
    _price_str = listing.get("price_display")
    if _price_int:
        price_display = format_currency(_price_int)
    elif _price_str:
        price_display = _price_str
    else:
        price_display = "N/D"

    fipe = format_currency(listing.get("fipe_price"))
    margin = format_currency(listing.get("margin_value"))

    fipe_model = _clean_html(listing.get("fipe_model") or "Modelo não identificado")

    city = listing.get("city")
    state = listing.get("state")

    if city and state:
        location = f"{city} - {state}"
    elif city:
        location = city
    else:
        location = "Local não informado"

    url = listing.get("url") or ""
    source_raw = (listing.get("source") or "facebook").lower()
    source = "OLX" if source_raw == "olx" else safe_cap(source_raw)

    publication_text = listing.get("published_at")

    if source_raw == "olx":
        publication_line = _olx_publication_line(publication_text)
    else:
        # Facebook: texto já vem formatado como "Publicado em X de Y"
        if publication_text:
            publication_line = f"⏱ {str(publication_text).split(' em ')[0]}"
        else:
            publication_line = "⏱ Detectado agora"

    # Descrição do anúncio — truncada a 200 chars para respeitar o limite de 1024 da caption do Telegram
    raw_description = _clean_html(listing.get("description") or "")
    if raw_description:
        raw_description = " ".join(raw_description.split())  # colapsa quebras de linha/espaços
        if len(raw_description) > 200:
            raw_description = raw_description[:200].rsplit(" ", 1)[0] + "…"
        description_line = f"\n📝 <i>{raw_description}</i>\n"
    else:
        description_line = ""

    message = (
        f"🚗 <b>{title}</b> | {source} Marketplace\n"
        f"🔥 <b>Margem:</b> {margin}\n"
        f"🛣️ <b>KM:</b> {km_text}\n\n"
        f"💰 <b>Preço:</b> {price_display}\n"
        f"📊 <b>Fipe:</b> {fipe}\n\n"
        f"🔎 <b>Modelo comparado:</b> {fipe_model}\n"
        f"📍 {location}"
        f"{description_line}\n"
        f"🔗 {url}\n\n"
        f"{publication_line}\n"
        + (
            f"\n⚠️ <b>ATENÇÃO:</b>\n"
            f"A ausência de padrões fixos no Facebook Marketplace pode gerar inconsistências no pareamento automático com os dados da tabela FIPE.\n\n"
            if source_raw == "facebook" else "\n"
        ) +
        f"🛡️ <b>Situação do Veículo (MG/SP/BA):</b>\n"
        f"🔗 https://avelarigor.github.io/AutoRadar\n\n"
        f"( ( 📡 ) ) | <b>AutoRadar 🎯</b>"
    )

    return message