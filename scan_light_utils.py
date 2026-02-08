#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modo leve para scans: bloquear assets (imagem, CSS, fontes, trackers) e
extrair/baixar só a foto principal via og:image ou JSON-LD (sem carregar imagens no browser).
Uso: scan_webmotors, scan_mobiauto, scan_olx.
"""

import os
from pathlib import Path
from typing import Any, Optional

BASE_DIR = Path(__file__).resolve().parent

# Trackers/analytics a bloquear (reduz peso e acelera)
_TRACKER_SUBSTRINGS = [
    "doubleclick", "googletagmanager", "google-analytics",
    "facebook.net", "hotjar", "analytics", "gtag", "ga.js",
    "googlesyndication", "googleadservices",
]


def install_light_mode(page, block_stylesheet: bool = True) -> None:
    """
    Bloqueia image, media, font e (opcional) stylesheet + trackers.
    Deixe o navegador carregar só HTML/JS (e XHR se necessário).
    """
    try:
        def handler(route):
            req = route.request
            rt = req.resource_type
            url = (req.url or "").lower()
            if rt in ("image", "media", "font"):
                route.abort()
                return
            if block_stylesheet and rt == "stylesheet":
                route.abort()
                return
            if any(x in url for x in _TRACKER_SUBSTRINGS):
                route.abort()
                return
            route.continue_()

        page.route("**/*", handler)
    except Exception:
        pass


def extract_main_image_url(page) -> Optional[str]:
    """
    Extrai URL da foto principal sem depender de <img> carregado.
    Ordem: og:image -> twitter:image -> JSON-LD (image/thumbnailUrl) -> None.
    Sync API (Playwright).
    """
    # 1) og:image
    try:
        loc = page.locator('meta[property="og:image"]').first
        if loc.count() > 0:
            url = loc.get_attribute("content")
            if url and (url or "").strip().startswith("http"):
                return (url or "").strip()
    except Exception:
        pass

    # 2) twitter:image
    try:
        loc = page.locator('meta[name="twitter:image"]').first
        if loc.count() > 0:
            url = loc.get_attribute("content")
            if url and (url or "").strip().startswith("http"):
                return (url or "").strip()
    except Exception:
        pass

    # 3) JSON-LD (image / thumbnailUrl)
    try:
        raw = page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (let i = 0; i < Math.min(scripts.length, 6); i++) {
                    const s = scripts[i];
                    const raw = (s && s.textContent) ? s.textContent.trim() : '';
                    if (!raw) continue;
                    try {
                        const data = JSON.parse(raw);
                        const candidates = Array.isArray(data) ? data : [data];
                        for (const obj of candidates) {
                            if (!obj || typeof obj !== 'object') continue;
                            let img = obj.image || obj.thumbnailUrl;
                            if (typeof img === 'string' && img.trim().startsWith('http'))
                                return img.trim();
                            if (Array.isArray(img) && img.length && typeof img[0] === 'string' && img[0].trim().startsWith('http'))
                                return img[0].trim();
                        }
                    } catch (e) {}
                }
                return null;
            }
        """)
        if raw and isinstance(raw, str) and raw.startswith("http"):
            return raw.strip()
    except Exception:
        pass

    return None


def download_main_image(img_url: Optional[str], save_path: str) -> bool:
    """
    Baixa a imagem principal via HTTP (fora do browser). Retorna True se salvou com sucesso.
    """
    if not img_url or not (img_url or "").strip().startswith("http"):
        return False
    img_url = img_url.strip()
    try:
        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.google.com/",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        r = requests.get(img_url, headers=headers, stream=True, timeout=15)
        if not r.ok:
            return False
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
        return True
    except Exception:
        return False


def get_images_dir(source: str) -> Path:
    """Diretório out/images/<source>/ para salvar fotos baixadas."""
    try:
        from path_utils import get_out_dir
        out = get_out_dir()
    except Exception:
        out = BASE_DIR / "out"
    out.mkdir(parents=True, exist_ok=True)
    img_dir = out / "images" / source.replace(" ", "_").lower()
    img_dir.mkdir(parents=True, exist_ok=True)
    return img_dir
