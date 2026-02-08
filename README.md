# AutoRadar

**Created by Igor Avelar — avelar.igor@gmail.com**

**🇧🇷 Versão em português no final do arquivo.**

---

## Overview (English)

**AutoRadar** is a desktop bot that monitors **Facebook Marketplace** for vehicle listings in a chosen city/region, scans each listing for details (price, make, model, year, mileage, description), compares them against the **FIPE** reference table (Brazilian used-vehicle pricing), and ranks **opportunities** by potential margin. Optionally it uses **AI** (local via Ollama or OpenAI API) to improve FIPE matching and to flag scam risk in descriptions. Results are shown in an HTML report and can be sent to **Telegram**.

### Main features

- **Link collection:** Uses Facebook Marketplace (mobile-style) with Playwright; supports login via existing Chrome (CDP on port 9222) or built-in browser. Saves session so you don’t have to log in every run.
- **Scan:** Visits each listing URL, extracts price, title, year, mileage, location, and description. Runs in the same browser session as collection.
- **FIPE:** Local normalized database (`out/fipe_db_norm.json`) built from the official FIPE table. You can update it with **“Atualizar FIPE”** in the app or by running `fipe_download.py`. The app can also check the FIPE API for individual listings when the local table is old or missing a match.
- **AI (optional):**  
  - **Ollama (free):** Set `"use_ollama": true` in `ai_config.json` and run a model (e.g. `ollama pull llama3.2`). The app warms up the model on start. Used for better FIPE matching and scam-risk hints.  
  - **OpenAI:** Put `OPENAI_API_KEY` in `.env` or `ai_config.json`. Note: ChatGPT Pro does not include API usage; the API is billed separately.
- **Ranking:** Compares listing price to FIPE (or API/IA estimate), applies a minimum margin (e.g. R$ 5,000), filters by vehicle type (car, motorcycle, truck) and scam keywords. Produces a ranked list of opportunities.
- **Parallel pipeline:** While the browser loads the next listing page, the previous listing is already being evaluated (FIPE + optional AI) in a worker thread, so total run time is reduced.
- **UI:** Progress window (PyStray + local HTML) with status, progress bar, “Atualizar FIPE” button, and optional login wait. Can run in the system tray.
- **Telegram:** If `telegram_config.json` is set (bot token + chat_id), the app can send the top opportunities to a Telegram chat (one message per listing with main photo and text).
- **Automation:** Can run the full pipeline on a schedule (e.g. every 60 minutes) defined in `user_preferences.json`. FIPE can be updated automatically in the background every 30 days.

### Tech stack

- **Python 3.11+**
- **Playwright** (browser automation; uses existing Chrome on 9222 when available)
- **Requests** (FIPE API, Telegram)
- **Pillow** (images)
- **PyStray** (tray icon and progress UI)

### Project structure (main files)

| File / folder      | Role |
|--------------------|------|
| `run_app.py`       | Main entry: orchestrates collection → scan → consolidation → ranking → report (and optional Telegram). |
| `collect_links_mobile.py` | Collects Marketplace listing URLs for city/state and price range; handles login and session. |
| `scan_mobile.py`   | Visits each link, extracts listing data (price, title, year, km, description, etc.). |
| `consolidate_listings.py` | Merges scan results and deduplicates. |
| `ranking_mvp.py`   | FIPE comparison, margin calculation, AI helpers, scam keywords; builds the opportunity ranking. |
| `ai_fipe_helper.py`| Optional AI: FIPE matching and scam-risk evaluation (Ollama or OpenAI). |
| `fipe_download.py` | Downloads FIPE table from API and builds the normalized DB. |
| `fipe_*.py`        | FIPE API client, CSV import, normalization, “update if due” logic. |
| `progress_ui.py`   | Progress window and tray icon. |
| `send_telegram.py` | Sends ranking opportunities to Telegram. |
| `UI/index.html`    | Local UI for progress and controls. |
| `user_preferences.json` | City, state, price range, margin, vehicle types, run interval (see `USER_PREFERENCES.md`). |
| `keywords_golpe.txt` | Keywords used to flag possible scam in descriptions. |

### Configuration (summary)

- **`user_preferences.json`** — City, state, price min/max, margin min (R$), vehicle types, run interval. Created with defaults if missing. See `USER_PREFERENCES.md`.
- **`ai_config.json`** — IA: `use_ollama: true` and/or `openai_api_key`. Use `ai_config.example.json` as template; do not commit real keys.
- **`telegram_config.json`** — Bot token and chat_id for Telegram. Use `telegram_config.example.json` as template.
- **`.env`** / **`fipe_token.txt`** — Optional FIPE API token for higher request limits.
- **`keywords_golpe.txt`** — One keyword per line (lines starting with `#` ignored).

All config files with secrets are in `.gitignore` (e.g. `.env`, `ai_config.json`, `telegram_config.json`, `user_preferences.json`, `browser_state.json`, `chrome_login_profile/`).

### How to run

1. **Prepare environment**
   ```powershell
   cd C:\Projects\AutoRadar
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   ```
   If you use **Chrome** with remote debugging (port 9222), you don’t need `playwright install chromium`; the app will attach to that browser.

2. **Optional: Chrome with debugging (for login persistence)**
   - Close Chrome, then start it with remote debugging, e.g.:
     `chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\Projects\AutoRadar\chrome_login_profile"`
   - Open Facebook, log in to Marketplace. The app will reuse this session.

3. **Start the app**
   ```powershell
   python run_app.py
   ```
   Or double‑click **`Iniciar_AutoRadar.bat`** (runs `python run_app.py` from the project folder).

4. **First run**
   - If no session exists, the app may ask you to log in to Facebook in the browser; use the progress window’s “wait for login” flow.
   - Adjust **city/state**, **price range**, **margin**, and **run interval** in `user_preferences.json` if needed.
   - Use **“Atualizar FIPE”** in the app (or run `python fipe_download.py`) to refresh the FIPE table (e.g. for Feb/2026). See `COMO_ATUALIZAR_FIPE.md`.

5. **IA (optional, free with Ollama)**
   - Install Ollama, run `ollama pull llama3.2`, ensure Ollama is running.
   - Create `ai_config.json` with `{"use_ollama": true}`. See `COMO_USAR_IA_GRATIS.md`.

Outputs (report, FIPE DB, cache) are under **`out/`**. The HTML report is opened automatically at the end of each run.

### Backup

The repo includes **`fazer_backup_zip.py`**, which creates a zip backup of the project (excluding venv and large/cache folders) in the parent directory. Run it manually when you want a snapshot.

### Documentation (in repo)

- `USER_PREFERENCES.md` — `user_preferences.json` fields.
- `COMO_ATUALIZAR_FIPE.md` — Why margins look wrong when FIPE is outdated; how to update FIPE (app button or `fipe_download.py`).
- `COMO_USAR_IA_GRATIS.md` — Using Ollama for free AI (FIPE matching + scam risk).
- `MOBILE_APP_ANALISE.md` — Notes on mobile Marketplace flow/analysis.

### Credits

**Created by Igor Avelar — avelar.igor@gmail.com**

### License and disclaimer

Use at your own risk. The project is for personal/educational use. Respect Facebook’s terms of service and automation policies. FIPE data is used for reference only; the app does not replace professional valuation.

---

## Visão geral (Português)

O **AutoRadar** é um bot de desktop que monitora o **Facebook Marketplace** em uma cidade/região escolhida: coleta links de anúncios de veículos, visita cada anúncio para extrair dados (preço, marca, modelo, ano, km, descrição), compara com a **tabela FIPE** e gera um **ranking de oportunidades** por margem. Opcionalmente usa **IA** (Ollama local ou API OpenAI) para melhorar o casamento FIPE e avaliar risco de golpe. O resultado aparece em relatório HTML e pode ser enviado ao **Telegram**.

### Principais funcionalidades

- **Coleta de links:** Usa o Marketplace no estilo mobile com Playwright; suporta login via Chrome já aberto (CDP na porta 9222) ou navegador gerenciado. Mantém sessão para não precisar logar a cada execução.
- **Scan:** Visita cada URL de anúncio e extrai preço, título, ano, km, local e descrição. Usa a mesma sessão do navegador da coleta.
- **FIPE:** Base local normalizada (`out/fipe_db_norm.json`) a partir da tabela FIPE. Atualize pelo botão **“Atualizar FIPE”** no app ou rodando `fipe_download.py`. O app também pode consultar a API FIPE por anúncio quando a base local está antiga ou sem correspondência.
- **IA (opcional):**  
  - **Ollama (grátis):** Coloque `"use_ollama": true` em `ai_config.json` e baixe um modelo (ex.: `ollama pull llama3.2`). O app aquece o modelo ao iniciar. Usado para melhor casamento FIPE e dicas de risco de golpe.  
  - **OpenAI:** Coloque `OPENAI_API_KEY` em `.env` ou `ai_config.json`. A assinatura ChatGPT Pro não inclui uso da API; a API é cobrada à parte.
- **Ranking:** Compara preço do anúncio com FIPE (ou estimativa API/IA), aplica margem mínima (ex.: R$ 5.000), filtra por tipo de veículo (carro, moto, caminhão) e palavras de golpe. Gera lista ordenada de oportunidades.
- **Pipeline paralelo:** Enquanto o navegador carrega a próxima página de anúncio, o anúncio anterior já é avaliado (FIPE + IA opcional) em thread separada, reduzindo o tempo total.
- **Interface:** Janela de progresso (PyStray + HTML local) com status, barra de progresso, botão “Atualizar FIPE” e espera por login. Pode ficar na bandeja do sistema.
- **Telegram:** Com `telegram_config.json` configurado (token do bot + chat_id), o app pode enviar as melhores oportunidades para um chat (uma mensagem por anúncio com foto principal e texto).
- **Automação:** Pode rodar o pipeline em intervalo configurável (ex. a cada 60 minutos) em `user_preferences.json`. A FIPE pode ser atualizada automaticamente em segundo plano a cada 30 dias.

### Stack técnica

- **Python 3.11+**
- **Playwright** (automação do navegador; usa Chrome na 9222 quando disponível)
- **Requests** (API FIPE, Telegram)
- **Pillow** (imagens)
- **PyStray** (ícone na bandeja e UI de progresso)

### Estrutura do projeto (principais arquivos)

| Arquivo / pasta    | Função |
|--------------------|--------|
| `run_app.py`       | Entrada principal: orquestra coleta → scan → consolidação → ranking → relatório (e Telegram opcional). |
| `collect_links_mobile.py` | Coleta URLs de anúncios do Marketplace para cidade/estado e faixa de preço; gerencia login e sessão. |
| `scan_mobile.py`   | Visita cada link e extrai dados do anúncio (preço, título, ano, km, descrição, etc.). |
| `consolidate_listings.py` | Consolida resultados do scan e remove duplicatas. |
| `ranking_mvp.py`   | Comparação FIPE, margem, helpers de IA, palavras de golpe; monta o ranking de oportunidades. |
| `ai_fipe_helper.py`| IA opcional: casamento FIPE e avaliação de risco de golpe (Ollama ou OpenAI). |
| `fipe_download.py` | Baixa tabela FIPE da API e gera a base normalizada. |
| `fipe_*.py`        | Cliente API FIPE, importação CSV, normalização e lógica “atualizar se vencido”. |
| `progress_ui.py`   | Janela de progresso e ícone na bandeja. |
| `send_telegram.py` | Envio das oportunidades do ranking para o Telegram. |
| `UI/index.html`    | Interface local de progresso e controles. |
| `user_preferences.json` | Cidade, estado, faixa de preço, margem, tipos de veículo, intervalo de execução (ver `USER_PREFERENCES.md`). |
| `keywords_golpe.txt` | Palavras usadas para sinalizar possível golpe na descrição. |

### Configuração (resumo)

- **`user_preferences.json`** — Cidade, estado, preço mín/máx, margem mín (R$), tipos de veículo, intervalo de execução. Criado com padrões se não existir. Ver `USER_PREFERENCES.md`.
- **`ai_config.json`** — IA: `use_ollama: true` e/ou `openai_api_key`. Use `ai_config.example.json` como modelo; não commitar chaves.
- **`telegram_config.json`** — Token do bot e chat_id do Telegram. Use `telegram_config.example.json` como modelo.
- **`.env`** / **`fipe_token.txt`** — Token opcional da API FIPE para maior limite de requisições.
- **`keywords_golpe.txt`** — Uma palavra por linha (linhas com `#` são ignoradas).

Arquivos com segredos estão no `.gitignore` (ex.: `.env`, `ai_config.json`, `telegram_config.json`, `user_preferences.json`, `browser_state.json`, `chrome_login_profile/`).

### Como rodar

1. **Ambiente**
   ```powershell
   cd C:\Projects\AutoRadar
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   ```
   Se usar **Chrome** com depuração remota (porta 9222), não é necessário `playwright install chromium`; o app conecta nesse navegador.

2. **Opcional: Chrome com depuração (para manter login)**
   - Feche o Chrome e inicie com depuração remota, por exemplo:
     `chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\Projects\AutoRadar\chrome_login_profile"`
   - Abra o Facebook e faça login no Marketplace. O app reutiliza essa sessão.

3. **Iniciar o app**
   ```powershell
   python run_app.py
   ```
   Ou execute **`Iniciar_AutoRadar.bat`** (roda `python run_app.py` na pasta do projeto).

4. **Primeira execução**
   - Se não houver sessão, o app pode pedir para você logar no Facebook no navegador; use o fluxo “aguardar login” na janela de progresso.
   - Ajuste **cidade/estado**, **faixa de preço**, **margem** e **intervalo** em `user_preferences.json` se precisar.
   - Use **“Atualizar FIPE”** no app (ou rode `python fipe_download.py`) para atualizar a tabela FIPE (ex.: fev/2026). Ver `COMO_ATUALIZAR_FIPE.md`.

5. **IA (opcional, grátis com Ollama)**
   - Instale o Ollama, execute `ollama pull llama3.2`, deixe o Ollama rodando.
   - Crie `ai_config.json` com `{"use_ollama": true}`. Ver `COMO_USAR_IA_GRATIS.md`.

Saídas (relatório, base FIPE, cache) ficam em **`out/`**. O relatório HTML é aberto ao final de cada execução.

### Backup

O repositório inclui **`fazer_backup_zip.py`**, que gera um zip de backup do projeto (excluindo venv e pastas de cache) na pasta pai. Execute manualmente quando quiser um snapshot.

### Documentação (no repositório)

- `TUTORIAL.md` — Passo a passo para configurar e rodar o app (PT + EN).
- `USER_PREFERENCES.md` — Campos de `user_preferences.json`.
- `COMO_ATUALIZAR_FIPE.md` — Por que as margens parecem erradas com FIPE desatualizada; como atualizar (botão no app ou `fipe_download.py`).
- `COMO_USAR_IA_GRATIS.md` — Usar Ollama para IA grátis (casamento FIPE e risco de golpe).
- `MOBILE_APP_ANALISE.md` — Notas sobre o fluxo do Marketplace mobile.

### Créditos

**Created by Igor Avelar — avelar.igor@gmail.com**

### Licença e aviso

Uso por sua conta e risco. O projeto é para uso pessoal/educacional. Respeite os termos e políticas do Facebook. Os dados FIPE são apenas referenciais; o app não substitui avaliação profissional.
