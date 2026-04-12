# scanners/scan_facebook.py
# VERSÃO ESTÁVEL FINAL + EXTRAÇÃO DE DESCRIPTION

import re
from typing import Optional, Dict

from fipe.brand_detector import detect_brand


def extract_year(title: str) -> Optional[int]:
    if not title:
        return None

    m = re.search(r"\b(19|20)\d{2}\b", title)
    return int(m.group()) if m else None


def parse_price(text: str) -> Optional[int]:
    if not text:
        return None

    try:
        return int(
            text.replace("R$", "")
            .replace(".", "")
            .replace(",", "")
            .strip()
        )
    except Exception:
        return None


def clean_description(text: str) -> str:

    if not text:
        return None

    text = re.sub(r"\s+", " ", text)
    text = text.strip()

    if len(text) > 500:
        text = text[:500]

    return text


async def scan_facebook_listing(page, url: str) -> Optional[Dict]:

    print(f"[SCAN_FB] Abrindo: {url}")

    try:

        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(3000)

        # Confirma que a página navegou para o URL correto (detecta redirects/race)
        actual_url = page.url
        final_url = url
        if actual_url and actual_url != url:
            _orig_m = re.search(r"/marketplace/item/(\d+)", url)
            _act_m  = re.search(r"/marketplace/item/(\d+)", actual_url)
            if _orig_m and _act_m and _orig_m.group(1) != _act_m.group(1):
                # Redirect para item diferente — usa URL real para evitar link errado
                final_url = actual_url.split('?')[0].rstrip('/') + '/'
                print(f"[SCAN_FB] ⚠️ Redirect item {_orig_m.group(1)} → {_act_m.group(1)} — URL corrigida: {final_url}")
            else:
                print(f"[SCAN_FB] Redirect detectado (mesmo item ou params): {url} → {actual_url}")
        else:
            print(f"[SCAN_FB] URL confirmado: {url}")

        html = await page.content()

        main_photo_url = None

        meta_match = re.search(
            r'<meta property="og:image" content="(https?://[^"]+)"',
            html
        )

        if meta_match:
            main_photo_url = meta_match.group(1).replace("&amp;", "&")

        if not main_photo_url:
            img = page.locator("img[src*='scontent']").first
            if await img.count() > 0:
                main_photo_url = await img.get_attribute("src")

        title_el = page.locator("h1 span").first

        if await title_el.count() == 0:
            print("[SCAN_FB] Título não encontrado.")
            return None

        title = (await title_el.inner_text()).strip()

        price_el = page.locator("span:has-text('R$')").first

        if await price_el.count() == 0:
            print("[SCAN_FB] Preço não encontrado.")
            return None

        price_text = (await price_el.inner_text()).strip()

        price = parse_price(price_text)

        if not price:
            print("[SCAN_FB] Preço inválido.")
            return None

        # -------------------------
        # EXTRAÇÕES
        # -------------------------

        year = extract_year(title)

        brand = detect_brand(title)

        # -------------------------
        # EXTRAÇÃO DE KM
        # -------------------------

        km = None

        km_elements = page.locator("span:has-text('km')")

        count = await km_elements.count()

        if count > 0:

            for i in range(count):

                text = (await km_elements.nth(i).inner_text()).lower()

                km_match = re.search(
                    r'(\d{1,3}(?:\.\d{3})+|\d{4,6})',
                    text
                )

                if km_match:

                    try:

                        km = int(km_match.group(1).replace(".", ""))
                        break

                    except:
                        pass

        # -------------------------
        # EXTRAÇÃO DE DESCRIPTION
        # -------------------------

        description = None

        # Padrões de lixo do Facebook — UI, navegação, perguntas de compradores
        _fb_noise = (
            "lembranças", "para recordar", "tem lembranças",
            "marketplace", "enviar mensagem", "salvar", "compartilhar",
            "denunciar", "ver mais", "ver menos", "detalhes",
            "disponível", "adicionar ao carrinho",
            "raio de",
            "bom dia", "boa tarde", "boa noite",
            # Elementos de UI / navegação do Facebook
            "caixa de entrada", "caixa de mensagens", "mensagens",
            "notificações", "página inicial", "feed de notícias",
            "amigos", "grupos", "reels", "market", "watch",
            "curtir", "comentar", "responder", "reagir",
            "ver perfil", "adicionar amigo", "seguir",
            "criar anúncio", "fazer login", "criar conta",
        )

        def _is_fb_noise(text: str) -> bool:
            tl = text.lower()
            if any(n in tl for n in _fb_noise):
                return True
            if re.search(r'·\s*(no\s+)?raio\s+de', text, re.IGNORECASE):
                return True
            # Timestamp de publicação: "Anunciado Há 10 horas em Cidade, UF"
            # ou "Há 3 dias em Montes Claros, MG"
            if re.search(r'\bh[aá]\s+\d+\s+(hora|dia|semana|minuto|m[eê]s)', text, re.IGNORECASE):
                return True
            if re.search(r'\banunciado\b', text, re.IGNORECASE):
                return True
            return False

        def _is_category_label(text: str) -> bool:
            """
            Retorna True se o texto parece ser um nome de categoria do Facebook
            Marketplace — e NÃO uma descrição escrita pelo vendedor.

            Categorias são: frases curtas, sem dígitos, sem termos de anúncio de veículo.
            """
            # Texto longo é quase certamente descrição do vendedor
            if len(text) > 80:
                return False
            # Qualquer dígito → descrição real (km, ano, preço, telefone, etc.)
            if re.search(r'\d', text):
                return False
            # Termos que só aparecem em descrições de vendedor
            _seller_signals = (
                'km', 'vendo', 'troco', 'aceit', 'conservad', 'revisad',
                'completo', 'peças', 'pecas', 'motor', 'câmbio', 'cambio',
                'ipva', 'único', 'unico', 'dono', 'condiç', 'estado',
                'financ', 'document', 'placa', 'laudo', 'vistoria',
                'particular', 'multa', 'batid', 'novo', 'nova',
            )
            tl = text.lower()
            if any(s in tl for s in _seller_signals):
                return False
            # Sem nenhum sinal de vendedor → assume que é categoria
            return True

        def _decode_json_text(raw: str) -> str:
            return raw.replace("\\n", " ").replace('\\"', '"').strip()

        try:

            # Tentativa 1 — seletor DOM específico do Marketplace
            desc_el = page.locator("div[data-testid='marketplace_pdp_description']").first
            if await desc_el.count() > 0:
                candidate = (await desc_el.inner_text()).strip()
                # NÃO aplica _is_category_label aqui: este seletor é específico da descrição do vendedor
                if candidate and not _is_fb_noise(candidate):
                    description = candidate
                    print(f"[DESCRIPTION] Fonte: data-testid DOM")

            # Tentativa 2 — "redacted_description" no JSON
            # Este é o campo ESPECÍFICO do Facebook para o texto digitado pelo vendedor.
            # Diferente de "description", que pode ser preenchido com o nome da categoria.
            if not description:
                rd_matches = re.findall(r'"redacted_description":\{"text":"([^"]+)"', html)
                for m in rd_matches:
                    decoded = _decode_json_text(m)
                    if len(decoded) < 5:
                        continue
                    if _is_fb_noise(decoded) or _is_category_label(decoded):
                        continue
                    description = decoded
                    print(f"[DESCRIPTION] Fonte: redacted_description JSON")
                    break

            # Tentativa 3 — "description" genérico no JSON (com filtro agressivo)
            # Só aceita se passar pelo _is_category_label — rejeita nomes de categoria
            if not description:
                json_matches = re.findall(r'"description":\{"text":"([^"]+)"', html)
                valid_json = []
                for m in json_matches:
                    decoded = _decode_json_text(m)
                    if len(decoded) < 20:
                        continue
                    if _is_fb_noise(decoded) or _is_category_label(decoded):
                        continue
                    valid_json.append(decoded)
                if valid_json:
                    description = max(valid_json, key=len)
                    print(f"[DESCRIPTION] Fonte: description JSON ({len(valid_json)} candidatos)")

            # Tentativa 4 — varredura de spans (última opção)
            # _is_category_label NÃO é aplicada aqui: muito agressiva para fallback de span
            # (descrições curtas legítimas como "Carro em ótimo estado" seriam bloqueadas)
            if not description:
                body = await page.inner_text("body")
                body_main = body.split("Patrocinado")[0] if "Patrocinado" in body else body

                spans = page.locator("span[dir='auto']")
                span_count = await spans.count()

                for i in range(span_count):
                    text = (await spans.nth(i).inner_text()).strip()
                    if len(text) < 15 or len(text) > 800:
                        continue
                    if "R$" in text:
                        continue
                    if _is_fb_noise(text):
                        continue
                    if text not in body_main:
                        continue
                    if title and text.lower() == title.lower():
                        continue
                    description = text
                    print(f"[DESCRIPTION] Fonte: span DOM")
                    break

            if not description:
                print(f"[DESCRIPTION] Nenhuma descrição encontrada (vendedor não preencheu)")

        except Exception as e:

            print("[DESCRIPTION ERROR]", e)

        description = clean_description(description)

        # -------------------------

        published_at = None

        pub_el = page.locator("span:has-text('Há')").first
        if await pub_el.count() > 0:
            published_at = (await pub_el.inner_text()).strip()

        city = None
        state = None

        # 1) Tenta extrair cidade/estado do published_at — padrão "em Cidade, UF"
        if published_at:
            loc_m = re.search(
                r'\bem\s+([A-Za-zÀ-Úà-ú][A-Za-zÀ-Ú à-ú\-]+),\s*([A-Z]{2})\b',
                published_at
            )
            if loc_m:
                city = loc_m.group(1).strip()
                state = loc_m.group(2).strip()

        # 2) Fallback: varre spans em busca de "Cidade, UF" — ignora strings com dígitos
        #    ou palavras temporais para evitar extrair o texto de publicação como cidade
        if not city or not state:
            loc_candidates = await page.locator("span").all_inner_texts()
            for text in loc_candidates:
                if "," in text:
                    parts = text.split(",")
                    if len(parts) == 2 and len(parts[1].strip()) == 2:
                        candidate = parts[0].strip()
                        if (
                            len(candidate) < 60
                            and not re.search(
                                r'\d|Anunciado|semana|hora|minuto|Há\b|mês',
                                candidate, re.IGNORECASE
                            )
                        ):
                            city = candidate
                            state = parts[1].strip()
                            break

        # -------------------------
        # LISTING FINAL
        # -------------------------

        listing = {
            "url": final_url,
            "title": title,
            "brand": brand,
            "price": price,
            "price_display": f"R$ {price:,.0f}".replace(",", "."),
            "currency": "BRL",
            "year": year,
            "km": km,
            "city": city,
            "state": state,
            "description": description,
            "main_photo_url": main_photo_url,
            "published_at": published_at,
            "source": "facebook",
        }

        print(f"[SCAN_FB] Extraído: url={final_url} | title={title!r} | price={price} | city={city} | km={km}")
        return listing

    except Exception as e:

        print("[SCAN_FB ERRO]", e)

        return None