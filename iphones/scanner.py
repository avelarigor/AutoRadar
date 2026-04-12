"""
Escaneia um link de iPhone (Facebook ou OLX), extrai título + preço +
descrição + condição + localização + tempo, faz match na tabela de
referência e salva como oportunidade se a margem for >= IPHONE_MARGIN_MIN.
"""

import re
import json
import sqlite3
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright
from shared_browser import get_scanner_page, get_olx_iphones_page

from iphones.matcher import match
from config_db import DB_PATH
from autoradar_config import IPHONE_MARGIN_MIN, IPHONE_CITY_FILTER, IPHONE_KEYWORDS_BLOCK


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _parse_price(text: str) -> int | None:
    """Extrai valor inteiro de strings como 'R$ 3.500' ou '3500'."""
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def _extract_time_string(body: str) -> str | None:
    """
    Extrai string de tempo como 'há 57 minutos', 'há 3 horas', 'há 2 dias'.
    Funciona para FB e OLX.
    """
    m = re.search(
        r"(h[aá]\s+\d+\s+(?:minuto|minutos|hora|horas|dia|dias|semana|semanas))",
        body, re.IGNORECASE
    )
    if m:
        return m.group(1).strip()
    m = re.search(
        r"(\d+\s+(?:minuto|minutos|hora|horas|dia|dias)\s+atr[aá]s)",
        body, re.IGNORECASE
    )
    return m.group(1).strip() if m else None


# Termos de produto iPhone usados para validar descrição
_IPHONE_PRODUCT_TERMS = (
    "iphone", "gb", "bateria", "tela", "original", "seminovo",
    "carregador", "caixa", "desbloqueado", "lacrado", "ios", "chip",
)


async def _extract_facebook(page) -> dict | None:
    """
    Extrai dados de um item do Facebook Marketplace.

    IMPORTANTE: O FB insere anúncios relacionados/patrocinados abaixo do produto
    principal (marcados com 'Patrocinado'). Toda extração usa body_main, que
    é o texto da página ANTES desse marcador, para evitar contaminação.
    """
    try:
        # ── Título ────────────────────────────────────────────────────────────
        # Confirmado pelo inspetor: título está em h1 > span[dir='auto']
        title = None
        try:
            title_span = await page.query_selector("h1 span[dir='auto']")
            if title_span:
                title = (await title_span.inner_text()).strip() or None
        except Exception:
            pass
        if not title:
            try:
                h1 = await page.query_selector("h1")
                if h1:
                    title = (await h1.inner_text()).strip() or None
            except Exception:
                pass

        # ── Preço ─────────────────────────────────────────────────────────────
        price_el = await page.query_selector("[aria-label*='R$']")
        price_text = (await price_el.inner_text()).strip() if price_el else None

        # ── Foto ──────────────────────────────────────────────────────────────
        photo_el = await page.query_selector("img[src*='scontent']")
        photo_url = await photo_el.get_attribute("src") if photo_el else None

        # ── Texto da página — cortar em 'Patrocinado' ─────────────────────────
        # Tudo após 'Patrocinado' são anúncios relacionados; descartamos para
        # evitar que spans de outros anúncios poluam título/descrição/localização.
        body = await page.inner_text("body")
        body_main = body.split("Patrocinado")[0] if "Patrocinado" in body else body

        # Fallback preço (raramente necessário)
        if not price_text:
            m = re.search(r"R\$\s*[\d.,]+", body_main)
            price_text = m.group(0) if m else None

        # ── Descrição ─────────────────────────────────────────────────────────
        # Procura o PRIMEIRO span[dir='auto'] cujo texto:
        #   1) Não é o título
        #   2) Contém termos de produto iPhone
        #   3) Aparece na seção principal da página (body_main)
        description = None
        try:
            dir_spans = await page.query_selector_all("span[dir='auto']")
            for el in dir_spans:
                text = (await el.inner_text()).strip()
                if len(text) < 20 or len(text) > 1500:
                    continue
                if title and text.lower() == title.lower():
                    continue
                # Verificar que pertence à seção principal (não é de anúncio patrocinado)
                if text not in body_main:
                    continue
                if any(term in text.lower() for term in _IPHONE_PRODUCT_TERMS):
                    description = text
                    break
        except Exception:
            pass

        # ── Condição ──────────────────────────────────────────────────────────
        condition = None
        cond_m = re.search(
            r"(Usado\s*[—\-]\s*[\w ]+|Novo|Seminovo|Excelente|Bom estado|Para conserto)",
            body_main, re.IGNORECASE
        )
        if cond_m:
            condition = cond_m.group(1).strip()

        # ── Localização ───────────────────────────────────────────────────────
        # Usa APENAS o padrão específico do FB "Anunciado em Cidade, UF".
        # Fallback genérico removido: capturava cidades da *descrição* do anúncio
        # (ex: "Comprado em São Paulo, SP"), gerando localização falsa.
        location = None
        loc_m = re.search(
            r"Anunciado[^,\n]{0,60}\bem\s+([A-Za-zÀ-Úà-ú][A-Za-zÀ-Úà-ú ]+,\s*[A-Z]{2})\b",
            body_main, re.IGNORECASE
        )
        if loc_m:
            location = loc_m.group(1).strip()

        # ── Tempo ─────────────────────────────────────────────────────────────
        published_at = _extract_time_string(body_main)

        return {
            "title": title,
            "price": _parse_price(price_text),
            "price_display": price_text,
            "photo_url": photo_url,
            "description": description,
            "condition": condition,
            "location": location,
            "published_at": published_at,
        }
    except Exception as e:
        print(f"[IPHONE SCAN FB] Erro ao extrair: {e}")
        return None


async def _extract_olx(page) -> dict | None:
    """Extrai todos os campos de uma página de anúncio OLX."""
    try:
        description = None
        condition = None
        location = None
        published_at = None

        # Tenta JSON-LD de schema.org primeiro
        ld_els = await page.query_selector_all('script[type="application/ld+json"]')
        for el in ld_els:
            try:
                data = json.loads(await el.inner_text())
                if isinstance(data, dict) and data.get("@type") == "Product":
                    title = data.get("name", "")
                    offer = (data.get("offers") or {})
                    price = int(float(offer.get("price", 0))) or None
                    image_raw = data.get("image")
                    if isinstance(image_raw, list):
                        first = image_raw[0] if image_raw else None
                        if isinstance(first, dict):
                            image = first.get("contentUrl") or first.get("url")
                        else:
                            image = first
                    elif isinstance(image_raw, dict):
                        image = image_raw.get("contentUrl") or image_raw.get("url")
                    else:
                        image = image_raw
                    description = data.get("description", "") or None
                    return {
                        "title": title,
                        "price": price,
                        "price_display": f"R$ {price:,}".replace(",", ".") if price else None,
                        "photo_url": image,
                        "description": description,
                        "condition": condition,
                        "location": location,
                        "published_at": published_at,
                    }
            except Exception:
                continue

        # Fallback seletores HTML
        title_el = await page.query_selector("h1")
        title = (await title_el.inner_text()).strip() if title_el else None

        price_el = await page.query_selector("[data-ds-component='DS-Text'][class*='price'], h2[class*='price']")
        price_text = (await price_el.inner_text()).strip() if price_el else None

        photo_el = await page.query_selector("img[src*='img.olx']")
        photo_url = await photo_el.get_attribute("src") if photo_el else None

        desc_el = await page.query_selector("[data-ds-component='DS-Text'][class*='description'], #description")
        if desc_el:
            description = (await desc_el.inner_text()).strip() or None

        body = await page.inner_text("body")
        published_at = _extract_time_string(body)

        return {
            "title": title,
            "price": _parse_price(price_text),
            "price_display": price_text,
            "photo_url": photo_url,
            "description": description,
            "condition": condition,
            "location": location,
            "published_at": published_at,
        }
    except Exception as e:
        print(f"[IPHONE SCAN OLX] Erro ao extrair: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# Scanner principal
# ─────────────────────────────────────────────────────────────

async def scan_iphone_link(url: str) -> dict | None:
    """
    Abre o link, extrai dados, faz match FIPE-like e retorna oportunidade
    ou None se não passar os critérios.
    """
    is_facebook = "facebook.com" in url
    is_olx = "olx.com.br" in url

    data = None

    if is_facebook:
        try:
            page = await get_scanner_page()
            await page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            # Confirma que a página navegou para o URL correto (detecta redirects)
            actual_url = page.url
            if actual_url and actual_url != url:
                print(f"[IPHONE SCAN FB] Redirect detectado: {url} → {actual_url}")
            else:
                print(f"[IPHONE SCAN FB] URL confirmado: {url}")
            data = await _extract_facebook(page)
        except Exception as e:
            print(f"[IPHONE SCAN] Erro Facebook: {e}")
            return None
    elif is_olx:
        try:
            page = await get_olx_iphones_page()
            await page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            data = await _extract_olx(page)
        except Exception as e:
            print(f"[IPHONE SCAN] Erro OLX: {e}")
            return None
    else:
        print(f"[IPHONE SCAN] Fonte desconhecida: {url}")
        return None

    if not data or not data.get("title") or not data.get("price"):
        print(f"[IPHONE SCAN] Dados insuficientes em: {url}")
        return None

    # OLX: se a página não retornou localização, infere pela URL do item.
    # URLs OLX de Montes Claros contêm 'montes-claros' ou 'regiao-de-montes-claros' no path.
    if is_olx and not (data.get("location") or "").strip():
        url_lower = url.lower()
        if "montes-claros" in url_lower or "regiao-de-montes-claros" in url_lower:
            data["location"] = "Montes Claros, MG"
            print(f"[IPHONE SCAN OLX] Localização inferida pela URL: Montes Claros, MG")

    title = data["title"]

    # Validação rápida: o título deve mencionar iPhone explicitamente
    # (evita processar carros/bicicletas que entraram na fila por engano)
    if not title or "iphone" not in title.lower():
        print(f"[IPHONE SCAN] Título não é iPhone: '{title}' → descartado")
        return None

    # Filtro de localização: estrito — sem localização detectada ou fora de Montes Claros → descarta
    location = data.get("location") or ""
    if not location:
        print(f"[IPHONE SCAN] Localização não detectada ({url[:60]}) → descartado por segurança")
        return None
    if IPHONE_CITY_FILTER.lower() not in location.lower():
        print(f"[IPHONE SCAN] Localização fora da área ({location}) → descartado")
        return None

    # Filtro de palavras bloqueadas (título ou descrição)
    description_raw = data.get("description") or ""
    _text_check = f"{title} {description_raw}".lower()
    for _kw in IPHONE_KEYWORDS_BLOCK:
        if _kw.lower() in _text_check:
            print(f"[IPHONE SCAN] Bloqueado por palavra-chave '{_kw}': {title}")
            return None

    price = data["price"]
    description = description_raw

    # Passa título + descrição ao matcher para ampliar detecção de storage
    model_key, storage_label, ref_price = match(title, description or "")

    if model_key is None:
        print(f"[IPHONE SCAN] Modelo não reconhecido: {title}")
        return None

    margin = ref_price - price

    if margin < IPHONE_MARGIN_MIN:
        print(f"[IPHONE SCAN] Margem insuficiente ({margin}) → {title}")
        return None

    source = "facebook" if is_facebook else "olx"
    print(f"[IPHONE OPORTUNIDADE] {title} | {storage_label} | preço={price} | ref={ref_price} | mg=R${margin} | src={source}")

    return {
        "url": url,
        "source": source,
        "title": title,
        "price": price,
        "price_display": data.get("price_display"),
        "ref_price": ref_price,
        "model_key": model_key,
        "storage_label": storage_label,
        "margin": margin,
        "photo_url": data.get("photo_url"),
        "description": description,
        "condition": data.get("condition"),
        "location": data.get("location"),
        "published_at": data.get("published_at"),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─────────────────────────────────────────────────────────────
# Persistência
# ─────────────────────────────────────────────────────────────

def save_iphone_opportunity(opp: dict):
    # Garantir que todos os campos sejam tipos primitivos (evita erro "type 'dict' is not supported")
    def _safe_str(v):
        if v is None:
            return None
        if isinstance(v, (list, dict)):
            return str(v)
        return v

    safe_opp = dict(opp)
    for field in ("photo_url", "description", "condition", "location", "published_at",
                  "price_display", "title", "source", "model_key", "storage_label", "url"):
        safe_opp[field] = _safe_str(safe_opp.get(field))

    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("""
            INSERT OR IGNORE INTO iphone_opportunities
            (url, source, title, price, price_display, ref_price, model_key, storage_label,
             margin, photo_url, description, condition, location, published_at,
             telegram_sent, created_at)
            VALUES (:url, :source, :title, :price, :price_display, :ref_price, :model_key,
                    :storage_label, :margin, :photo_url, :description, :condition,
                    :location, :published_at, 0, :created_at)
        """, safe_opp)
        conn.commit()
    finally:
        conn.close()
