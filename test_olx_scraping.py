#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de Teste para Scraping OLX Mobile
Testa acesso, estrutura HTML, coleta de links e extração de dados básicos.
Created by Igor Avelar - avelar.igor@gmail.com
"""

import sys
import json
import time
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
CHROME_PROFILE_DIR = BASE_DIR / "chrome_login_profile"
CACHE_DIR = BASE_DIR / "test_olx_cache"
CACHE_DIR.mkdir(exist_ok=True)

# URL de teste (Montes Claros, MG - mais recentes)
# Testar desktop primeiro (funciona), depois tentar forçar mobile
TEST_URL_DESKTOP = "https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/estado-mg/regiao-de-montes-claros-e-diamantina/montes-claros?sf=1"
TEST_URL_MOBILE = "https://m.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/estado-mg/regiao-de-montes-claros-e-diamantina/montes-claros?sf=1"
# Começar com desktop para validar acesso, depois tentar mobile
TEST_URL = TEST_URL_DESKTOP
FORCE_MOBILE_UA = True  # Forçar User-Agent mobile mesmo na URL desktop


def _log(message: str, level: str = "INFO"):
    """Log detalhado com timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    level_str = level.ljust(6)
    print(f"[{timestamp}] [{level_str}] {message}")
    # Também salva em arquivo
    log_file = CACHE_DIR / "test_log.txt"
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] [{level_str}] {message}\n")
    except Exception:
        pass


def _save_html_cache(page_content: str, filename: str):
    """Salva HTML em cache para análise posterior"""
    cache_file = CACHE_DIR / filename
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            f.write(page_content)
        _log(f"HTML salvo em cache: {filename}", "CACHE")
    except Exception as e:
        _log(f"Erro ao salvar cache {filename}: {e}", "ERROR")


def _detect_cloudflare_challenge(page) -> bool:
    """Detecta se há página de desafio Cloudflare"""
    try:
        # Verificar título da página
        title = page.title().lower()
        if "just a moment" in title or "checking your browser" in title:
            _log("⚠️ Detectado: Página de desafio Cloudflare (título)", "WARN")
            return True
        
        # Verificar elementos comuns do Cloudflare
        cf_selectors = [
            'text="Just a moment"',
            'text="Checking your browser"',
            'text="Verificando seu navegador"',
            '[id*="cf-"]',
            '.cf-browser-verification',
        ]
        for selector in cf_selectors:
            try:
                element = page.query_selector(selector)
                if element:
                    _log(f"⚠️ Detectado: Elemento Cloudflare encontrado ({selector})", "WARN")
                    return True
            except Exception:
                continue
        
        # Verificar URL
        url = page.url.lower()
        if "challenge" in url or "cf-challenge" in url:
            _log(f"⚠️ Detectado: URL de desafio Cloudflare: {url}", "WARN")
            return True
            
    except Exception as e:
        _log(f"Erro ao detectar Cloudflare: {e}", "ERROR")
    
    return False


def _detect_login_redirect(page) -> bool:
    """Detecta se foi redirecionado para página de login (não apenas botão no header)"""
    try:
        url = page.url.lower()
        # Se a URL contém /login ou /entrar, é redirecionamento real
        if "/login" in url or "/entrar" in url or "/signin" in url:
            _log(f"⚠️ Detectado: Redirecionamento para login: {url}", "WARN")
            return True
        
        # Verificar se é realmente uma página de login (não apenas botão no header)
        # Procurar por campos de formulário de login
        login_form_selectors = [
            'form[action*="login"]',
            'form[action*="entrar"]',
            'form[action*="signin"]',
            '[name="email"][type="email"]',
            '[name="email"][type="text"]',
            '[name="password"][type="password"]',
            'input[type="password"]',  # Campo de senha é indicativo forte
        ]
        form_found = False
        for selector in login_form_selectors:
            try:
                element = page.query_selector(selector)
                if element:
                    form_found = True
                    break
            except Exception:
                continue
        
        # Se encontrou formulário de login E a URL não é a página principal, é login
        if form_found:
            # Verificar se não é apenas um botão no header (verificar se há múltiplos elementos de login)
            try:
                password_fields = page.query_selector_all('input[type="password"]')
                if len(password_fields) > 0:
                    # Verificar se há título indicando página de login
                    title = page.title().lower()
                    if "entrar" in title or "login" in title or "sign in" in title:
                        _log(f"⚠️ Detectado: Página de login (formulário + título)", "WARN")
                        return True
            except Exception:
                pass
        
    except Exception as e:
        _log(f"Erro ao detectar login: {e}", "ERROR")
    
    return False


def test_mobile_access():
    """Testa acesso à versão mobile da OLX (forçando mobile mesmo de PC)"""
    _log("=" * 80)
    _log("TESTE 1: Acesso à versão mobile (m.olx.com.br) - User-Agent Mobile")
    _log("=" * 80)
    
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _log("❌ Playwright não instalado. Instale com: pip install playwright", "ERROR")
        return False
    
    success = False
    try:
        with sync_playwright() as p:
            # Tentar usar Chrome existente via CDP primeiro
            browser = None
            use_cdp = False
            try:
                browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
                use_cdp = True
                _log("✅ Conectado ao Chrome existente (CDP porta 9222)", "SUCCESS")
            except Exception:
                # Se não conseguir CDP, lançar novo browser com perfil
                try:
                    browser = p.chromium.launch(
                        headless=False,
                        args=[
                            f"--user-data-dir={CHROME_PROFILE_DIR}",
                            "--start-minimized",
                            "--window-size=1280,800",
                        ]
                    )
                    _log("✅ Browser lançado com perfil Chrome", "SUCCESS")
                except Exception as e:
                    _log(f"❌ Erro ao lançar browser: {e}", "ERROR")
                    return False
            
            try:
                # Criar contexto - se FORCE_MOBILE_UA=True, usar User-Agent mobile mesmo na URL desktop
                # Isso força o site a servir versão mobile mesmo acessando www.olx.com.br
                if FORCE_MOBILE_UA:
                    # User-Agent de Android Chrome (simula dispositivo móvel real)
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
                        viewport={"width": 375, "height": 667},  # Tamanho típico de celular
                        locale="pt_BR",
                        # Headers adicionais para parecer mais mobile
                        extra_http_headers={
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                            "Accept-Encoding": "gzip, deflate, br",
                            "DNT": "1",
                            "Connection": "keep-alive",
                            "Upgrade-Insecure-Requests": "1",
                        }
                    )
                else:
                    # User-Agent desktop normal
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        viewport={"width": 1920, "height": 1080},
                        locale="pt_BR",
                    )
                page = context.new_page()
                
                _log(f"🌐 Acessando: {TEST_URL}")
                _log("⏳ Aguardando carregamento (timeout: 90s)...")
                
                # Acessar página com timeout maior
                try:
                    response = page.goto(TEST_URL, wait_until="load", timeout=90000)
                    # Verificar status HTTP
                    if response:
                        status = response.status
                        _log(f"📊 Status HTTP: {status}")
                        if status >= 400:
                            _log(f"⚠️ Erro HTTP {status} detectado", "WARN")
                    _log("✅ Página carregada com sucesso", "SUCCESS")
                except Exception as e:
                    _log(f"⚠️ Timeout no carregamento inicial: {e}", "WARN")
                    _log("⏳ Tentando com domcontentloaded...")
                    try:
                        response = page.goto(TEST_URL, wait_until="domcontentloaded", timeout=60000)
                        if response:
                            status = response.status
                            _log(f"📊 Status HTTP: {status}")
                        _log("✅ Página carregada (parcial)", "SUCCESS")
                    except Exception as e2:
                        _log(f"❌ Erro ao carregar página: {e2}", "ERROR")
                        return False
                
                # Aguardar um pouco para JavaScript carregar
                time.sleep(3)
                
                # Verificar título da página
                title = page.title()
                _log(f"📄 Título da página: {title}")
                
                # Verificar URL final
                final_url = page.url
                _log(f"🔗 URL final: {final_url}")
                
                # Verificar erros HTTP (502, 503, etc)
                page_content = page.content()
                if "502" in title or "503" in title or "Bad Gateway" in title or "Service Unavailable" in title:
                    _log("❌ ERRO HTTP DETECTADO: %s" % title, "ERROR")
                    _log("💡 Isso pode ser um problema temporário do servidor OLX", "INFO")
                    _log("💡 Tentando aguardar mais tempo ou usar versão diferente...", "INFO")
                    _save_html_cache(page_content, "01_http_error.html")
                    # Aguardar um pouco e tentar novamente
                    time.sleep(5)
                    try:
                        page.reload(wait_until="domcontentloaded", timeout=60000)
                        time.sleep(3)
                        title = page.title()
                        _log(f"📄 Título após reload: {title}")
                        if "502" not in title and "503" not in title:
                            _log("✅ Página carregou após reload", "SUCCESS")
                        else:
                            return False
                    except Exception as e:
                        _log(f"❌ Erro ao recarregar: {e}", "ERROR")
                        return False
                
                # Detectar bloqueios
                if _detect_cloudflare_challenge(page):
                    _log("❌ BLOQUEIO DETECTADO: Cloudflare Challenge", "ERROR")
                    _save_html_cache(page_content, "01_cloudflare_challenge.html")
                    return False
                
                if _detect_login_redirect(page):
                    _log("❌ BLOQUEIO DETECTADO: Redirecionamento para Login", "ERROR")
                    _save_html_cache(page_content, "01_login_redirect.html")
                    return False
                
                # Salvar HTML da primeira página
                html_content = page.content()
                _save_html_cache(html_content, "01_homepage.html")
                
                # Verificar estrutura básica
                _log("🔍 Analisando estrutura da página...")
                
                # Verificar se há resultados
                results_text = page.query_selector('text=/resultados?/i')
                if results_text:
                    results_count = results_text.inner_text()
                    _log(f"📊 {results_count}")
                
                # Verificar se há cards de anúncios
                # (Vamos tentar alguns seletores comuns)
                possible_selectors = [
                    'a[href*="/autos-e-pecas/"]',
                    '[data-testid*="ad"]',
                    '.olx-ad-card',
                    'a[href*="/d/"]',
                ]
                
                found_links = []
                for selector in possible_selectors:
                    try:
                        elements = page.query_selector_all(selector)
                        if elements:
                            _log(f"✅ Encontrados {len(elements)} elementos com seletor: {selector}", "SUCCESS")
                            found_links = elements[:10]  # Primeiros 10 para teste
                            break
                    except Exception:
                        continue
                
                if not found_links:
                    _log("⚠️ Nenhum link de anúncio encontrado com seletores comuns", "WARN")
                    _log("💡 Verifique o arquivo 01_homepage.html no cache para análise manual", "INFO")
                else:
                    _log(f"✅ Estrutura básica OK: {len(found_links)} links encontrados", "SUCCESS")
                
                success = True
                
            finally:
                if not use_cdp:
                    try:
                        context.close()
                        browser.close()
                    except Exception:
                        pass
                else:
                    try:
                        context.close()
                    except Exception:
                        pass
                    
    except Exception as e:
        _log(f"❌ Erro geral no teste: {e}", "ERROR")
        import traceback
        _log(traceback.format_exc(), "ERROR")
    
    return success


def test_collect_links():
    """Testa coleta de links da primeira página"""
    _log("=" * 80)
    _log("TESTE 2: Coleta de links da primeira página")
    _log("=" * 80)
    
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _log("❌ Playwright não instalado", "ERROR")
        return []
    
    links = []
    try:
        with sync_playwright() as p:
            browser = None
            use_cdp = False
            try:
                browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
                use_cdp = True
                _log("✅ Conectado ao Chrome existente (CDP)", "SUCCESS")
            except Exception:
                try:
                    browser = p.chromium.launch(
                        headless=False,
                        args=[
                            f"--user-data-dir={CHROME_PROFILE_DIR}",
                            "--start-minimized",
                        ]
                    )
                except Exception as e:
                    _log(f"❌ Erro ao lançar browser: {e}", "ERROR")
                    return []
            
            try:
                # Contexto MOBILE para forçar versão mobile mesmo rodando de PC
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
                    viewport={"width": 375, "height": 667},
                    locale="pt_BR",
                    extra_http_headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                        "Accept-Encoding": "gzip, deflate, br",
                        "DNT": "1",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1",
                    }
                )
                page = context.new_page()
                
                _log(f"🌐 Acessando: {TEST_URL}")
                page.goto(TEST_URL, wait_until="domcontentloaded", timeout=90000)
                time.sleep(5)  # Aguardar JavaScript
                
                # Detectar bloqueios
                if _detect_cloudflare_challenge(page) or _detect_login_redirect(page):
                    _log("❌ Bloqueio detectado, abortando coleta", "ERROR")
                    return []
                
                # Scroll para carregar mais conteúdo (se necessário)
                _log("📜 Fazendo scroll para carregar conteúdo...")
                for i in range(3):
                    page.evaluate("window.scrollBy(0, 500)")
                    time.sleep(2)
                
                # Tentar extrair links de anúncios
                _log("🔍 Procurando links de anúncios...")
                
                # Padrão comum: links que contêm /d/ (detalhes) ou /autos-e-pecas/.../d/
                all_links = page.query_selector_all('a[href]')
                seen_urls = set()
                
                for link_elem in all_links:
                    try:
                        href = link_elem.get_attribute('href')
                        if not href:
                            continue
                        
                        # Normalizar URL
                        if href.startswith('/'):
                            href = f"https://m.olx.com.br{href}"
                        elif not href.startswith('http'):
                            continue
                        
                        # Filtrar apenas links de anúncios
                        if '/d/' in href or '/autos-e-pecas/' in href:
                            # Remover query params para normalizar
                            base_url = href.split('?')[0].split('#')[0]
                            if base_url not in seen_urls and 'olx.com.br' in base_url:
                                seen_urls.add(base_url)
                                links.append({
                                    "url": base_url,
                                    "href_original": href,
                                })
                    except Exception:
                        continue
                
                _log(f"✅ Coletados {len(links)} links únicos", "SUCCESS")
                
                # Salvar links em JSON
                links_file = CACHE_DIR / "02_links_collected.json"
                with open(links_file, 'w', encoding='utf-8') as f:
                    json.dump(links, f, indent=2, ensure_ascii=False)
                _log(f"💾 Links salvos em: {links_file}", "CACHE")
                
                # Salvar HTML atualizado
                _save_html_cache(page.content(), "02_page_with_links.html")
                
            finally:
                if not use_cdp:
                    try:
                        context.close()
                        browser.close()
                    except Exception:
                        pass
                else:
                    try:
                        context.close()
                    except Exception:
                        pass
                        
    except Exception as e:
        _log(f"❌ Erro na coleta: {e}", "ERROR")
        import traceback
        _log(traceback.format_exc(), "ERROR")
    
    return links


def test_extract_data(links: List[Dict[str, str]], max_items: int = 5):
    """Testa extração de dados básicos de alguns anúncios"""
    _log("=" * 80)
    _log(f"TESTE 3: Extração de dados básicos (máximo {max_items} anúncios)")
    _log("=" * 80)
    
    if not links:
        _log("⚠️ Nenhum link disponível para teste", "WARN")
        return []
    
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _log("❌ Playwright não instalado", "ERROR")
        return []
    
    results = []
    test_links = links[:max_items]
    
    try:
        with sync_playwright() as p:
            browser = None
            use_cdp = False
            try:
                browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
                use_cdp = True
            except Exception:
                try:
                    browser = p.chromium.launch(
                        headless=False,
                        args=[
                            f"--user-data-dir={CHROME_PROFILE_DIR}",
                            "--start-minimized",
                        ]
                    )
                except Exception as e:
                    _log(f"❌ Erro ao lançar browser: {e}", "ERROR")
                    return []
            
            try:
                # Contexto MOBILE para forçar versão mobile mesmo rodando de PC
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
                    viewport={"width": 375, "height": 667},
                    locale="pt_BR",
                    extra_http_headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                        "Accept-Encoding": "gzip, deflate, br",
                        "DNT": "1",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1",
                    }
                )
                page = context.new_page()
                
                for i, link_data in enumerate(test_links, 1):
                    url = link_data["url"]
                    _log(f"📄 [{i}/{len(test_links)}] Processando: {url[:60]}...")
                    
                    try:
                        # Acessar página do anúncio
                        page.goto(url, wait_until="domcontentloaded", timeout=60000)
                        time.sleep(3)  # Aguardar carregamento
                        
                        # Detectar bloqueios
                        if _detect_cloudflare_challenge(page) or _detect_login_redirect(page):
                            _log(f"⚠️ Bloqueio detectado em {url[:50]}...", "WARN")
                            continue
                        
                        # Extrair dados básicos
                        data = {
                            "url": url,
                            "title": None,
                            "price": None,
                            "year": None,
                            "km": None,
                            "city": None,
                            "photo_url": None,
                        }
                        
                        # Tentar extrair título
                        title_selectors = [
                            'h1',
                            '[data-testid="ad-title"]',
                            '.ad-title',
                            'h2',
                        ]
                        for selector in title_selectors:
                            try:
                                elem = page.query_selector(selector)
                                if elem:
                                    data["title"] = elem.inner_text().strip()
                                    break
                            except Exception:
                                continue
                        
                        # Tentar extrair preço
                        price_selectors = [
                            '[data-testid="ad-price"]',
                            '.ad-price',
                            'text=/R\\$[\\s\\d\\.]+/i',
                        ]
                        for selector in price_selectors:
                            try:
                                if selector.startswith('text='):
                                    # Buscar por regex no texto
                                    text = page.inner_text('body')
                                    price_match = re.search(r'R\$\s*([\d\.]+)', text)
                                    if price_match:
                                        data["price"] = price_match.group(1).replace('.', '')
                                        break
                                else:
                                    elem = page.query_selector(selector)
                                    if elem:
                                        price_text = elem.inner_text()
                                        price_match = re.search(r'([\d\.]+)', price_text)
                                        if price_match:
                                            data["price"] = price_match.group(1).replace('.', '')
                                            break
                            except Exception:
                                continue
                        
                        # Tentar extrair ano
                        year_match = re.search(r'\b(19|20)\d{2}\b', page.inner_text('body'))
                        if year_match:
                            data["year"] = int(year_match.group())
                        
                        # Tentar extrair km
                        km_match = re.search(r'(\d+\.?\d*)\s*km', page.inner_text('body'), re.IGNORECASE)
                        if km_match:
                            data["km"] = int(km_match.group(1).replace('.', ''))
                        
                        # Tentar extrair cidade
                        city_selectors = [
                            '[data-testid="location"]',
                            '.ad-location',
                            'text=/Montes Claros|MG/i',
                        ]
                        for selector in city_selectors:
                            try:
                                if selector.startswith('text='):
                                    text = page.inner_text('body')
                                    city_match = re.search(r'Montes Claros', text, re.IGNORECASE)
                                    if city_match:
                                        data["city"] = "Montes Claros"
                                        break
                                else:
                                    elem = page.query_selector(selector)
                                    if elem:
                                        data["city"] = elem.inner_text().strip()
                                        break
                            except Exception:
                                continue
                        
                        # Tentar extrair foto principal
                        photo_selectors = [
                            'img[data-testid="ad-image"]',
                            '.ad-image img',
                            'img[src*="olx"]',
                        ]
                        for selector in photo_selectors:
                            try:
                                img = page.query_selector(selector)
                                if img:
                                    data["photo_url"] = img.get_attribute('src')
                                    break
                            except Exception:
                                continue
                        
                        results.append(data)
                        _log(f"✅ Extraído: {data['title'] or 'Sem título'} - R$ {data['price'] or 'N/A'}", "SUCCESS")
                        
                        # Delay entre requisições
                        if i < len(test_links):
                            delay = 5
                            _log(f"⏳ Aguardando {delay}s antes do próximo...")
                            time.sleep(delay)
                        
                    except Exception as e:
                        _log(f"❌ Erro ao processar {url[:50]}...: {e}", "ERROR")
                        continue
                
                # Salvar resultados
                results_file = CACHE_DIR / "03_extracted_data.json"
                with open(results_file, 'w', encoding='utf-8') as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)
                _log(f"💾 Dados extraídos salvos em: {results_file}", "CACHE")
                
            finally:
                if not use_cdp:
                    try:
                        context.close()
                        browser.close()
                    except Exception:
                        pass
                else:
                    try:
                        context.close()
                    except Exception:
                        pass
                        
    except Exception as e:
        _log(f"❌ Erro na extração: {e}", "ERROR")
        import traceback
        _log(traceback.format_exc(), "ERROR")
    
    return results


def test_pagination():
    """Testa navegação para segunda página"""
    _log("=" * 80)
    _log("TESTE 4: Paginação (segunda página)")
    _log("=" * 80)
    
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _log("❌ Playwright não instalado", "ERROR")
        return []
    
    links_page2 = []
    try:
        with sync_playwright() as p:
            browser = None
            use_cdp = False
            try:
                browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
                use_cdp = True
            except Exception:
                try:
                    browser = p.chromium.launch(
                        headless=False,
                        args=[
                            f"--user-data-dir={CHROME_PROFILE_DIR}",
                            "--start-minimized",
                        ]
                    )
                except Exception as e:
                    _log(f"❌ Erro ao lançar browser: {e}", "ERROR")
                    return []
            
            try:
                # Contexto MOBILE para forçar versão mobile mesmo rodando de PC
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
                    viewport={"width": 375, "height": 667},
                    locale="pt_BR",
                    extra_http_headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                        "Accept-Encoding": "gzip, deflate, br",
                        "DNT": "1",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1",
                    }
                )
                page = context.new_page()
                
                # Construir URL da segunda página (geralmente ?o=2 ou ?page=2)
                page2_url = TEST_URL + ("&o=2" if "?" in TEST_URL else "?o=2")
                _log(f"🌐 Acessando segunda página: {page2_url}")
                
                page.goto(page2_url, wait_until="domcontentloaded", timeout=90000)
                time.sleep(5)
                
                # Detectar bloqueios
                if _detect_cloudflare_challenge(page) or _detect_login_redirect(page):
                    _log("❌ Bloqueio detectado na segunda página", "ERROR")
                    return []
                
                # Scroll
                for i in range(3):
                    page.evaluate("window.scrollBy(0, 500)")
                    time.sleep(2)
                
                # Coletar links
                all_links = page.query_selector_all('a[href]')
                seen_urls = set()
                
                for link_elem in all_links:
                    try:
                        href = link_elem.get_attribute('href')
                        if not href:
                            continue
                        
                        if href.startswith('/'):
                            href = f"https://m.olx.com.br{href}"
                        elif not href.startswith('http'):
                            continue
                        
                        if '/d/' in href or '/autos-e-pecas/' in href:
                            base_url = href.split('?')[0].split('#')[0]
                            if base_url not in seen_urls and 'olx.com.br' in base_url:
                                seen_urls.add(base_url)
                                links_page2.append({
                                    "url": base_url,
                                    "href_original": href,
                                })
                    except Exception:
                        continue
                
                _log(f"✅ Coletados {len(links_page2)} links da segunda página", "SUCCESS")
                
                # Salvar
                links_file = CACHE_DIR / "04_links_page2.json"
                with open(links_file, 'w', encoding='utf-8') as f:
                    json.dump(links_page2, f, indent=2, ensure_ascii=False)
                _save_html_cache(page.content(), "04_page2.html")
                
            finally:
                if not use_cdp:
                    try:
                        context.close()
                        browser.close()
                    except Exception:
                        pass
                else:
                    try:
                        context.close()
                    except Exception:
                        pass
                        
    except Exception as e:
        _log(f"❌ Erro na paginação: {e}", "ERROR")
        import traceback
        _log(traceback.format_exc(), "ERROR")
    
    return links_page2


def generate_report():
    """Gera relatório final dos testes"""
    _log("=" * 80)
    _log("GERANDO RELATÓRIO FINAL")
    _log("=" * 80)
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "test_url": TEST_URL,
        "cache_dir": str(CACHE_DIR),
        "files_generated": [],
    }
    
    # Listar arquivos gerados
    for file in sorted(CACHE_DIR.glob("*")):
        if file.is_file():
            size = file.stat().st_size
            report["files_generated"].append({
                "name": file.name,
                "size_bytes": size,
                "size_kb": round(size / 1024, 2),
            })
    
    # Salvar relatório
    report_file = CACHE_DIR / "00_test_report.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    _log("=" * 80)
    _log("RELATÓRIO FINAL")
    _log("=" * 80)
    _log(f"📁 Diretório de cache: {CACHE_DIR}")
    _log(f"📄 Arquivos gerados: {len(report['files_generated'])}")
    for file_info in report["files_generated"]:
        _log(f"   • {file_info['name']} ({file_info['size_kb']} KB)")
    _log("=" * 80)
    _log("💡 Analise os arquivos HTML salvos para identificar os seletores corretos")
    _log("💡 Os links coletados estão em JSON para referência")
    _log("=" * 80)


def main():
    """Executa todos os testes"""
    _log("🚀 Iniciando testes de scraping OLX Mobile")
    _log(f"📁 Cache será salvo em: {CACHE_DIR}")
    _log("")
    
    # Teste 1: Acesso básico
    if not test_mobile_access():
        _log("❌ Teste de acesso falhou. Abortando testes subsequentes.", "ERROR")
        generate_report()
        return 1
    
    _log("")
    time.sleep(2)
    
    # Teste 2: Coleta de links
    links = test_collect_links()
    
    _log("")
    time.sleep(2)
    
    # Teste 3: Extração de dados (se houver links)
    if links:
        test_extract_data(links, max_items=5)
    else:
        _log("⚠️ Pulando teste de extração (nenhum link coletado)", "WARN")
    
    _log("")
    time.sleep(2)
    
    # Teste 4: Paginação (opcional)
    _log("💡 Teste de paginação será executado...")
    links_page2 = test_pagination()
    
    _log("")
    
    # Relatório final
    generate_report()
    
    _log("✅ Testes concluídos!")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        _log("⚠️ Testes interrompidos pelo usuário", "WARN")
        sys.exit(1)
    except Exception as e:
        _log(f"❌ Erro fatal: {e}", "ERROR")
        import traceback
        _log(traceback.format_exc(), "ERROR")
        sys.exit(1)
