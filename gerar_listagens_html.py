#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera out/UI/listagens.html a partir de out/listings_all_clean.json.
Use quando quiser ver a tabela de anúncios processados sem rodar o pipeline.

  python gerar_listagens_html.py

Ou, na pasta do projeto:  py gerar_listagens_html.py
"""
import sys
import json
import html
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from path_utils import get_out_dir, get_ui_dir
from ranking_mvp import _get_source_name


def main():
    out_dir = get_out_dir()
    ui_dir = get_ui_dir()
    listings_json = out_dir / "listings_all_clean.json"
    if not listings_json.exists():
        print("❌ Arquivo não encontrado: %s" % listings_json)
        print("   Rode o pipeline (coleta + scan) pelo menos uma vez para gerar esse arquivo.")
        return 1
    with open(listings_json, "r", encoding="utf-8") as f:
        all_listings = json.load(f)
    rows = []
    for item in all_listings:
        src = _get_source_name(item)
        title = html.escape(str(item.get("title", "—"))[:120])
        year = item.get("year") or "—"
        price = item.get("price")
        price_str = ("R$ " + f"{price:,.0f}".replace(",", ".")) if price else "—"
        km = item.get("km")
        km_str = ("%s km" % f"{km:,}".replace(",", ".")) if km else "—"
        city = html.escape(str(item.get("city", "—"))[:40])
        url = html.escape(item.get("url", ""))
        rows.append(
            f'<tr><td>{html.escape(src)}</td><td>{title}</td><td>{year}</td><td>{price_str}</td><td>{km_str}</td><td>{city}</td><td><a href="{url}" target="_blank">Ver</a></td></tr>'
        )
    listagens_html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Anúncios processados (listings_all_clean)</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
    h1 {{ color: #333; }}
    p {{ color: #666; }}
    table {{ width: 100%; border-collapse: collapse; background: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
    th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; font-size: 13px; }}
    th {{ background: #2196F3; color: white; }}
    tr:hover {{ background: #f5f5f5; }}
    a {{ color: #2196F3; }}
  </style>
</head>
<body>
  <h1>Anúncios processados</h1>
  <p>Conteúdo de <strong>out/listings_all_clean.json</strong> — anúncios que entram no ranking. Total: {len(all_listings)}.</p>
  <p><a href="index.html">← Voltar ao relatório de oportunidades</a></p>
  <table>
    <thead><tr><th>Origem</th><th>Título</th><th>Ano</th><th>Preço</th><th>Km</th><th>Cidade</th><th>Link</th></tr></thead>
    <tbody>
{"".join(rows)}
    </tbody>
  </table>
</body>
</html>"""
    listagens_file = ui_dir / "listagens.html"
    ui_dir.mkdir(parents=True, exist_ok=True)
    with open(listagens_file, "w", encoding="utf-8") as f:
        f.write(listagens_html)
    print("📄 Listagens gerado: %s" % listagens_file.resolve())
    print("   Abra no navegador para ver a tabela.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main() or 0)
