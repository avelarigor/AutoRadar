#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consolidação de Anúncios (versão estável mesclada)
Consolida anúncios de múltiplas fontes (Facebook; OLX desabilitado).
Created by Igor Avelar - avelar.igor@gmail.com
"""

import sys
import json
import re
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from path_utils import get_out_dir

BASE_DIR = Path(__file__).resolve().parent


def _canonical_url(listing: dict) -> str:
    url = (listing.get("url") or "").strip()
    if not url:
        return ""

    src = (listing.get("source") or "").lower()

    # 1) remove fragment (#...) sempre
    parts = urlsplit(url)
    url_no_frag = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))

    # 2) Facebook: manter só /marketplace/item/<ID>
    if "facebook" in src or "marketplace" in url_no_frag:
        m = re.search(r"/marketplace/item/(\d+)", url_no_frag)
        if m:
            return f"https://www.facebook.com/marketplace/item/{m.group(1)}/"
        # fallback: sem query
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    # 3) Mobiauto: manter até /detalhes/<ID>
    if "mobiauto" in src or "mobiauto.com.br" in url_no_frag:
        m = re.search(r"/detalhes/(\d+)", url_no_frag)
        if m:
            # mantém path original até o id
            base_path = re.sub(r"(\/detalhes\/\d+).*", r"\1", parts.path)
            return urlunsplit((parts.scheme, parts.netloc, base_path, "", ""))

    # 4) Webmotors: normalmente o path já identifica bem; remove query
    if "webmotors" in src or "webmotors.com.br" in url_no_frag:
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    # 5) OLX: remove query
    if "olx" in src or "olx.com.br" in url_no_frag:
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    # default: remove query e fragment
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

def consolidate_all_listings():
    """Consolida todos os anúncios em um único arquivo (listings_all_clean.json)."""
    print("🔄 Consolidando listagens de todas as plataformas...")

    all_listings = []
    out_dir = get_out_dir()

    fb_file = out_dir / "listings_facebook.json"
    if fb_file.exists():
        try:
            with open(fb_file, 'r', encoding='utf-8') as f:
                fb_listings = json.load(f)
                if isinstance(fb_listings, list):
                    all_listings.extend(fb_listings)
                    print(f"✅ Facebook: {len(fb_listings)} anúncios")
        except Exception as e:
            print(f"⚠️ Erro ao ler Facebook: {e}")

    wm_file = out_dir / "listings_webmotors.json"
    if wm_file.exists():
        try:
            with open(wm_file, 'r', encoding='utf-8') as f:
                wm_listings = json.load(f)
                if isinstance(wm_listings, list):
                    all_listings.extend(wm_listings)
                    print(f"✅ Webmotors: {len(wm_listings)} anúncios")
        except Exception as e:
            print(f"⚠️ Erro ao ler Webmotors: {e}")

    ma_file = out_dir / "listings_mobiauto.json"
    if ma_file.exists():
        try:
            with open(ma_file, 'r', encoding='utf-8') as f:
                ma_listings = json.load(f)
                if isinstance(ma_listings, list):
                    all_listings.extend(ma_listings)
                    print(f"✅ Mobiauto: {len(ma_listings)} anúncios")
        except Exception as e:
            print(f"⚠️ Erro ao ler Mobiauto: {e}")

    olx_file = out_dir / "listings_olx.json"
    if olx_file.exists():
        try:
            with open(olx_file, 'r', encoding='utf-8') as f:
                olx_listings = json.load(f)
                if isinstance(olx_listings, list):
                    all_listings.extend(olx_listings)
                    print(f"✅ OLX: {len(olx_listings)} anúncios")
        except Exception as e:
            print(f"⚠️ Erro ao ler OLX: {e}")

    seen = set()
    unique_listings = []
    for listing in all_listings:
        key = _canonical_url(listing) or (listing.get("url") or "").strip()
        if not key:
            # sem url: mantém (mas evita duplicar por id interno se existir)
            key = f'__no_url__:{listing.get("id") or listing.get("source") or ""}:{len(unique_listings)}'
        if key in seen:
            continue
        seen.add(key)
        unique_listings.append(listing)

    output_file = out_dir / "listings_all_clean.json"
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(unique_listings, f, indent=2, ensure_ascii=False)
        print(f"📊 Total consolidado: {len(unique_listings)} anúncios únicos")
        print(f"✅ Arquivo salvo: {output_file}")
    except Exception as e:
        print(f"❌ Erro ao salvar arquivo consolidado: {e}")

if __name__ == "__main__":
    consolidate_all_listings()
