#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline de teste: reescaneia até 5 anúncios por fonte (usando URLs dos listings já salvos),
depois consolida e roda o ranking. Serve para validar alterações (OLX Detalhes, KM Webmotors,
cidade/KM Mobiauto, opcionais no Telegram) em poucos minutos sem rodar a coleta.
Requisito: ter out/listings_facebook.json, listings_webmotors.json, listings_mobiauto.json
e/ou listings_olx.json de uma execução anterior (links já coletados = listings já escaneados).
Após o teste, os arquivos originais são restaurados (backup feito antes de sobrescrever).
"""
import sys
import json
import shutil
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

MAX_POR_FONTE = 3

try:
    from path_utils import get_out_dir
except ImportError:
    def get_out_dir():
        return BASE_DIR / "out"

# Módulos de scan (mesmo padrão do run_app)
try:
    from scan_mobile import scan_listings as scan_listings_fb
    FB_AVAILABLE = True
except ImportError:
    FB_AVAILABLE = False

try:
    from scan_webmotors import scan_listings as scan_listings_webmotors
    WEBMOTORS_AVAILABLE = True
except ImportError:
    WEBMOTORS_AVAILABLE = False

try:
    from scan_mobiauto import scan_listings as scan_listings_mobiauto
    MOBIAUTO_AVAILABLE = True
except ImportError:
    MOBIAUTO_AVAILABLE = False

try:
    from scan_olx import scan_listings as scan_listings_olx
    OLX_AVAILABLE = True
except ImportError:
    OLX_AVAILABLE = False

try:
    from consolidate_listings import consolidate_all_listings
    from ranking_mvp import main as ranking_main
except ImportError as e:
    print(f"Erro ao importar consolidação/ranking: {e}")
    sys.exit(1)


def _urls_from_listings(listings, max_n):
    """Extrai até max_n URLs de uma lista de listings (chave 'url' ou 'link')."""
    urls = []
    for item in (listings or [])[:max_n]:
        u = item.get("url") or item.get("link")
        if u and isinstance(u, str):
            urls.append(u)
    return urls


def _backup_and_run():
    out_dir = get_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    sources = [
        ("Facebook", "listings_facebook.json", FB_AVAILABLE, scan_listings_fb),
        ("Webmotors", "listings_webmotors.json", WEBMOTORS_AVAILABLE, scan_listings_webmotors),
        ("Mobiauto", "listings_mobiauto.json", MOBIAUTO_AVAILABLE, scan_listings_mobiauto),
        ("OLX", "listings_olx.json", OLX_AVAILABLE, scan_listings_olx),
    ]

    backups = []
    any_has_data = False

    for nome, filename, available, scan_fn in sources:
        path = out_dir / filename
        if not path.exists() or not available:
            if path.exists():
                print(f"⏭ {nome}: arquivo existe mas módulo não disponível; pulando.")
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                print(f"⏭ {nome}: arquivo não é lista; pulando.")
                continue
            urls = _urls_from_listings(data, MAX_POR_FONTE)
            if not urls:
                print(f"⏭ {nome}: nenhuma URL encontrada nos primeiros {MAX_POR_FONTE} itens; pulando.")
                continue
            any_has_data = True
            backup_path = out_dir / (filename.replace(".json", "_backup_full.json"))
            shutil.copy2(path, backup_path)
            backups.append((path, backup_path, nome, scan_fn, urls))
            print(f"📂 {nome}: {len(urls)} URLs para reescaneamento (backup em {backup_path.name})")
        except Exception as e:
            print(f"⚠️ {nome}: erro ao ler arquivo - {e}")

    if not any_has_data or not backups:
        print("Nenhum arquivo de listing com URLs encontrado (ou módulos indisponíveis).")
        print("Rode o pipeline completo uma vez para gerar out/listings_*.json e tente de novo.")
        return False

    def _progress(current, total):
        print(f"  Scan: {current}/{total}", end="\r")

    for path, backup_path, nome, scan_fn, urls in backups:
        print(f"\n🔍 Escaneando {nome} ({len(urls)} anúncios)...")
        try:
            result = scan_fn(links=urls, progress_callback=_progress, listing_queue=None, browser=None)
            listings = result[0] if isinstance(result, tuple) else result
            if listings:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(listings, f, ensure_ascii=False, indent=2)
                print(f"   ✅ {nome}: {len(listings)} anúncios salvos em {path.name}")
            else:
                print(f"   ⚠️ {nome}: nenhum anúncio retornado; mantendo backup.")
        except Exception as e:
            print(f"   ❌ {nome}: erro no scan - {e}")
            # Restaurar deste backup
            try:
                shutil.copy2(backup_path, path)
                print(f"   Restaurado {path.name} a partir do backup.")
            except Exception:
                pass

    print("\n🔄 Consolidando listagens...")
    consolidate_all_listings()

    print("\n📊 Rodando ranking...")
    ranking_main()

    # Restaurar arquivos originais a partir dos backups
    print("\n📥 Restaurando listings originais (backup → listings_*.json)...")
    for path, backup_path, nome, _, _ in backups:
        try:
            shutil.copy2(backup_path, path)
            print(f"   ✅ {nome}: {path.name} restaurado.")
        except Exception as e:
            print(f"   ⚠️ {nome}: falha ao restaurar - {e}")

    return True


if __name__ == "__main__":
    print("Pipeline de TESTE (até 5 anúncios por fonte) — scan → consolidação → ranking")
    print("Usa URLs dos arquivos out/listings_*.json já existentes. Backups são restaurados ao final.\n")
    ok = _backup_and_run()
    sys.exit(0 if ok else 1)
