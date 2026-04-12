# IMPORT NOVO
import asyncio
import random
import re
from pathlib import Path
from shared_browser import get_olx_cars_page

BASE_PATH_MOC = "https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/estado-mg/regiao-de-montes-claros-e-diamantina/montes-claros"

BASE_PATH_BH = "https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/estado-mg/belo-horizonte-e-regiao/grande-belo-horizonte"

OLX_BASE_PATHS = [
    BASE_PATH_MOC,
    # BASE_PATH_BH  # DESABILITADO até segunda ordem
]

_last_region_index = -1

def get_next_region():

    global _last_region_index

    _last_region_index = (_last_region_index + 1) % len(OLX_BASE_PATHS)

    return OLX_BASE_PATHS[_last_region_index]


OLX_STRATEGIES = [
    "",
    "?sf=1",
    "?sp=1",
    "?sp=5",
    "?ps=10000&sp=1"
]

_last_strategy_index = -1

def get_next_strategy():

    global _last_strategy_index

    _last_strategy_index = (_last_strategy_index + 1) % len(OLX_STRATEGIES)

    return OLX_STRATEGIES[_last_strategy_index]


async def collect_links_olx(max_pages=5):

    base_path = get_next_region()

    strategy = get_next_strategy()

    base_url = base_path + strategy

    print(f"[OLX] Região ativa: {base_path}")
    print(f"[OLX] Estratégia ativa: {strategy or 'NORMAL'}")

    links = set()

    # Reutiliza a página do scanner OLX (mesmo perfil persistente) — evita conflito de perfil
    # e garante que o cookie Cloudflare cf_clearance já esteja presente.
    page = await get_olx_cars_page()

    try:

        # Warm-up: verifica se a página já está em contexto OLX ou precisa de warm-up
        try:
            current_url = page.url
            if not current_url or "olx.com.br" not in current_url:
                print("[OLX] Warm-up: navegando para home OLX para renovar cookie CF...")
                await page.goto("https://www.olx.com.br/", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(random.uniform(5.0, 9.0))
                for _ in range(5):
                    ht = (await page.title()).lower()
                    if any(k in ht for k in ("attention required", "just a moment", "cloudflare")):
                        await asyncio.sleep(8)
                    else:
                        break
                print(f"[OLX] Warm-up concluído: {await page.title()}")
        except Exception as _wu:
            print(f"[OLX] Warm-up falhou (não crítico): {_wu}")

        for page_num in range(1, max_pages + 1):

            separator = "&" if "?" in base_url else "?"

            url = f"{base_url}{separator}o={page_num}"

            print(f"[OLX] Página {page_num}: {url}")

            await page.goto(url, wait_until="domcontentloaded", timeout=40000)

            # Pausa inicial
            await asyncio.sleep(random.uniform(3.0, 6.0))

            # Detecta e aguarda challenge Cloudflare resolver (JS challenge leva ~5-10s)
            for _cf_wait in range(6):  # tenta por até 30s
                title = await page.title()
                if any(kw in title.lower() for kw in ("attention required", "just a moment", "cloudflare")):
                    if _cf_wait == 0:
                        print(f"[OLX] Cloudflare challenge na página {page_num} — aguardando resolver...")
                    await asyncio.sleep(6)
                else:
                    break
            else:
                # Ainda bloqueado após 30s
                print(f"[OLX] Cloudflare não resolveu na página {page_num} — abortando rodada")
                break

            # Movimento de mouse simulado após carregar
            try:
                vw = page.viewport_size
                if vw:
                    await page.mouse.move(
                        random.randint(100, vw["width"] - 100),
                        random.randint(100, vw["height"] - 100)
                    )
                    await asyncio.sleep(random.uniform(0.3, 0.7))
            except Exception:
                pass

            anchors = await page.query_selector_all(
                'a[data-ds-component="DS-NewAdCard-Link"]'
            )

            if not anchors:
                anchors = await page.query_selector_all(
                    'a[href*="/autos-e-pecas/"]'
                )

            # Scroll gradual antes de extrair links: imita comportamento humano de leitura
            try:
                for frac in (0.25, 0.50, 0.75, 1.0):
                    await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {frac})")
                    await asyncio.sleep(random.uniform(0.7, 1.4))
                # Pequena pausa após chegar ao fim da página
                await asyncio.sleep(random.uniform(1.0, 2.0))
            except Exception:
                pass

            bruto_pagina = len(anchors)

            novos_pagina = 0
            duplicados_pagina = 0

            for a in anchors:

                href = await a.get_attribute("href")

                if not href:
                    continue

                if "carros-vans-e-utilitarios" not in href:
                    continue

                if not re.search(r"-\d{7,}", href):
                    continue

                if href.startswith("/"):
                    href = "https://www.olx.com.br" + href

                if href in links:

                    duplicados_pagina += 1

                else:

                    novos_pagina += 1

                    links.add(href)

            total_acumulado = len(links)

            print(
                f"[OLX][Page {page_num}] "
                f"Brutos={bruto_pagina} | "
                f"Duplicados={duplicados_pagina} | "
                f"Novos={novos_pagina} | "
                f"Total={total_acumulado}"
            )

            # Pausa entre páginas: mais longa para simular troca de página humana
            await asyncio.sleep(random.uniform(8.0, 15.0))

        print(f"[OLX DEBUG] Links encontrados: {len(links)}")

    except Exception as e:

        print(f"[OLX] Erro durante coleta: {e}")

    # NÃO fecha a página — ela é compartilhada com o scanner OLX
    return list(links)

    base_path = get_next_region()

    strategy = get_next_strategy()

    base_url = base_path + strategy

    print(f"[OLX] Região ativa: {base_path}")
    print(f"[OLX] Estratégia ativa: {strategy or 'NORMAL'}")

    links = set()

    # Browser OLX com perfil persistente (headed) — evita bloqueio Cloudflare
    OLX_PROFILE_DIR = Path("profiles/olx").resolve()
    OLX_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(OLX_PROFILE_DIR),
        headless=False,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-default-apps",
            "--disable-sync",
            "--no-first-run",
            "--disable-blink-features=AutomationControlled",
            "--js-flags=--max-old-space-size=128",
        ],
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        viewport={"width": 1366, "height": 768},
        extra_http_headers={
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
    )
    await browser.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['pt-BR','pt','en-US','en']});
        window.chrome = {runtime: {}};
    """)
    pages = browser.pages
    page = pages[0] if pages else await browser.new_page()

    try:

        # Warm-up: visita a home do OLX antes de ir direto para a busca.
        # O cookie cf_clearance é emitido para o domínio, não por URL específica.
        # Isso ajuda o Cloudflare a reconhecer o perfil como humano.
        try:
            home_title = (await page.title()).lower()
            is_fresh = not any(k in home_title for k in ("olx", "autos", "carros"))
            if is_fresh:
                print("[OLX] Warm-up: acessando home OLX para renovar cookie CF...")
                await page.goto("https://www.olx.com.br/", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(random.uniform(6.0, 10.0))
                # Aguarda desafio resolver
                for _ in range(5):
                    ht = (await page.title()).lower()
                    if any(k in ht for k in ("attention required", "just a moment", "cloudflare")):
                        await asyncio.sleep(8)
                    else:
                        break
                print(f"[OLX] Home carregada: {await page.title()}")
        except Exception as _wu:
            print(f"[OLX] Warm-up falhou (não crítico): {_wu}")

        for page_num in range(1, max_pages + 1):

            separator = "&" if "?" in base_url else "?"

            url = f"{base_url}{separator}o={page_num}"

            print(f"[OLX] Página {page_num}: {url}")

            await page.goto(url, wait_until="domcontentloaded", timeout=40000)

            # Pausa inicial
            await asyncio.sleep(random.uniform(3.0, 6.0))

            # Detecta e aguarda challenge Cloudflare resolver (JS challenge leva ~5-10s)
            for _cf_wait in range(6):  # tenta por até 30s
                title = await page.title()
                if any(kw in title.lower() for kw in ("attention required", "just a moment", "cloudflare")):
                    if _cf_wait == 0:
                        print(f"[OLX] Cloudflare challenge na p\u00e1gina {page_num} \u2014 aguardando resolver...")
                    await asyncio.sleep(6)
                else:
                    break
            else:
                # Ainda bloqueado ap\u00f3s 30s
                print(f"[OLX] Cloudflare n\u00e3o resolveu na p\u00e1gina {page_num} \u2014 abortando rodada")
                break

            # Movimento de mouse simulado ap\u00f3s carregar
            try:
                vw = page.viewport_size
                if vw:
                    await page.mouse.move(
                        random.randint(100, vw["width"] - 100),
                        random.randint(100, vw["height"] - 100)
                    )
                    await asyncio.sleep(random.uniform(0.3, 0.7))
            except Exception:
                pass

            anchors = await page.query_selector_all(
                'a[data-ds-component="DS-NewAdCard-Link"]'
            )

            if not anchors:
                anchors = await page.query_selector_all(
                    'a[href*="/autos-e-pecas/"]'
                )

            # Scroll gradual antes de extrair links: imita comportamento humano de leitura
            try:
                for frac in (0.25, 0.50, 0.75, 1.0):
                    await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {frac})")
                    await asyncio.sleep(random.uniform(0.7, 1.4))
                # Pequena pausa após chegar ao fim da página
                await asyncio.sleep(random.uniform(1.0, 2.0))
            except Exception:
                pass

            bruto_pagina = len(anchors)

            novos_pagina = 0
            duplicados_pagina = 0

            for a in anchors:

                href = await a.get_attribute("href")

                if not href:
                    continue

                if "carros-vans-e-utilitarios" not in href:
                    continue

                if not re.search(r"-\d{7,}", href):
                    continue

                if href.startswith("/"):
                    href = "https://www.olx.com.br" + href

                if href in links:

                    duplicados_pagina += 1

                else:

                    novos_pagina += 1

                    links.add(href)

            total_acumulado = len(links)

            print(
                f"[OLX][Page {page_num}] "
                f"Brutos={bruto_pagina} | "
                f"Duplicados={duplicados_pagina} | "
                f"Novos={novos_pagina} | "
                f"Total={total_acumulado}"
            )

            # Pausa entre páginas: mais longa para simular troca de página humana
            await asyncio.sleep(random.uniform(8.0, 15.0))

        print(f"[OLX DEBUG] Links encontrados: {len(links)}")

    except Exception as e:

        print(f"[OLX] Erro durante coleta: {e}")

    finally:
        try:
            await page.close()
        except Exception:
            pass
        try:
            await browser.close()  # launch_persistent_context: browser == context
        except Exception:
            pass
        try:
            await playwright.stop()
        except Exception:
            pass

    return list(links)
    return list(links)