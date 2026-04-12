*English version is right below the Portuguese version.*

---

# AutoRadar

Bot de monitoramento de anúncios de veículos que rastreia o **Facebook Marketplace** e a **OLX** em busca de oportunidades abaixo do preço FIPE, notificando via **Telegram** em tempo real.

## O que faz

- Coleta links de anúncios de carros no Facebook Marketplace e na OLX de forma contínua
- Compara o preço anunciado com o valor FIPE do veículo
- Filtra anúncios que estão abaixo do preço de mercado com base em uma margem mínima configurável por região
- Envia alertas via Telegram com preço, margem de desconto, fotos e link direto do anúncio
- Reenfileira anúncios antigos periodicamente para detectar quedas de preço
- Inclui módulos separados para monitoramento de **iPhones** e **PS5** via OLX

## Funcionamento

```
Collector Loop
  ├── Facebook Marketplace → collect_links_mobile.py
  └── OLX                  → collect_links_olx.py
          ↓
     link_queue.db (SQLite)
          ↓
Scanner Loop
  ├── extractor_olx.py   → extrai dados estruturados (dataLayer / JSON-LD)
  ├── normalizer_olx.py  → normaliza marca, modelo, ano, km
  ├── fipe/engine_v2.py  → busca código FIPE e valor de referência
  └── filters.py         → bloqueia motos, caminhões, palavras-chave indesejadas
          ↓
     Telegram (send_telegram.py / telegram_dispatcher.py)
```

## Requisitos

- Python 3.11+
- Google Chrome instalado (necessário para contornar o Cloudflare da OLX via CDP)
- Playwright (`pip install playwright`)
- Conta no Telegram com um bot criado via [@BotFather](https://t.me/BotFather)

## Configuração

1. Clone o repositório e crie o ambiente virtual:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   playwright install chromium
   ```

2. Crie o telegram_config.json com base no exemplo:
   ```json
   {
     "TOKEN": "seu-token-aqui",
     "CHAT_ID": "seu-chat-id-aqui"
   }
   ```

3. Configure o .env:
   ```
   FIPE_API_TOKEN=seu-token-fipe
   ```

4. Ajuste os parâmetros em autoradar_config.py (cidade, estado, preços mínimo/máximo, margens por região)

5. Inicialize o cookie da OLX (necessário apenas na primeira execução):
   ```bash
   python _olx_login.py
   ```
   Um Chrome real será aberto — navegue até olx.com.br e aguarde carregar. Feche quando concluído.

6. Inicie o app:
   ```bash
   python run_app.py
   # ou pelo .bat:
   Iniciar_AutoRadar.bat
   ```

## Arquitetura anti-Cloudflare

O app lança o **Google Chrome real** via subprocess com `--remote-debugging-port` e o Playwright conecta via CDP (`connect_over_cdp`). Isso preserva o TLS fingerprint do Chrome legítimo, contornando a detecção por JA3/JA4 do Cloudflare — que identifica o Chromium empacotado do Playwright mesmo em modo headed.

- Porta 9222 → scanner de carros
- Porta 9223 → scanner de iPhones/PS5

## Observações

- O app foi desenvolvido para uso pessoal e fins educacionais
- Respeite os termos de uso das plataformas monitoradas
- Credenciais (telegram_config.json, .env, profiles) estão no .gitignore e nunca são commitadas

---
# AutoRadar

A vehicle listing monitor bot that tracks **Facebook Marketplace** and **OLX** looking for deals priced below the FIPE reference value, sending real-time alerts via **Telegram**.

## What it does

- Continuously collects car listings from Facebook Marketplace and OLX
- Compares the listed price against the FIPE market reference value for the vehicle
- Filters listings that are below market price based on a configurable minimum margin per region
- Sends Telegram alerts with price, discount margin, photos, and a direct link to the listing
- Periodically re-queues old listings to detect price drops
- Includes separate modules for monitoring **iPhones** and **PS5** deals on OLX

## How it works

```
Collector Loop
  ├── Facebook Marketplace → collect_links_mobile.py
  └── OLX                  → collect_links_olx.py
          ↓
     link_queue.db (SQLite)
          ↓
Scanner Loop
  ├── extractor_olx.py   → extracts structured data (dataLayer / JSON-LD)
  ├── normalizer_olx.py  → normalizes brand, model, year, mileage
  ├── fipe/engine_v2.py  → resolves FIPE code and reference price
  └── filters.py         → blocks motorcycles, trucks, unwanted keywords
          ↓
     Telegram (send_telegram.py / telegram_dispatcher.py)
```

## Requirements

- Python 3.11+
- Google Chrome installed (required to bypass OLX Cloudflare protection via CDP)
- Playwright (`pip install playwright`)
- A Telegram bot created via [@BotFather](https://t.me/BotFather)

## Setup

1. Clone the repository and create the virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   playwright install chromium
   ```

2. Create telegram_config.json:
   ```json
   {
     "TOKEN": "your-bot-token",
     "CHAT_ID": "your-chat-id"
   }
   ```

3. Create .env:
   ```
   FIPE_API_TOKEN=your-fipe-token
   ```

4. Adjust parameters in autoradar_config.py (city, state, price range, per-region margins)

5. Seed the OLX Cloudflare cookie (first run only):
   ```bash
   python _olx_login.py
   ```
   A real Chrome window will open — navigate to olx.com.br and wait for it to load. Close when done.

6. Start the app:
   ```bash
   python run_app.py
   # or via .bat:
   Iniciar_AutoRadar.bat
   ```

## Anti-Cloudflare architecture

The app launches the **real Google Chrome** via subprocess with `--remote-debugging-port` and Playwright connects to it via CDP (`connect_over_cdp`). This preserves the legitimate Chrome TLS fingerprint, bypassing Cloudflare's JA3/JA4 bot detection — which identifies Playwright's bundled Chromium even in headed mode.

- Port 9222 → car scanner
- Port 9223 → iPhone/PS5 scanner

## Notes

- This project was built for personal use and educational purposes
- Please respect the terms of service of the monitored platforms
- Credentials (telegram_config.json, .env, profiles) are listed in .gitignore and are never committed
