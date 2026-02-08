# Tutorial – AutoRadar (passo a passo)

**Created by Igor Avelar — avelar.igor@gmail.com**

**🇬🇧 English version at the end of this file.**

Este tutorial ensina qualquer pessoa a configurar e rodar o AutoRadar no Windows, do zero até o primeiro relatório de oportunidades.

---

## O que você vai precisar

- **Windows** (testado no 10/11).
- **Conta no Facebook** (para acessar o Marketplace).
- **Python 3.11 ou superior** instalado. Verifique no PowerShell: `python --version`.
- **Conexão com a internet** (Facebook, API FIPE, opcionalmente Telegram e IA).

---

## Passo 1: Obter o projeto

1. Coloque a pasta do projeto em: **`C:\Projects\AutoRadar`**.
   - Se você clonou ou descompactou em outro lugar, mova/copie a pasta para `C:\Projects\AutoRadar` (ou ajuste os caminhos deste tutorial).
2. Abra o **PowerShell** (ou Terminal) e vá até a pasta:
   ```powershell
   cd C:\Projects\AutoRadar
   ```

---

## Passo 2: Criar o ambiente virtual (venv)

1. Crie o ambiente virtual:
   ```powershell
   python -m venv venv
   ```
2. Ative o venv:
   ```powershell
   .\venv\Scripts\activate
   ```
   O prompt deve mostrar `(venv)` no início.
3. Instale as dependências:
   ```powershell
   pip install -r requirements.txt
   ```
   Aguarde terminar (playwright, requests, Pillow, pystray, etc.).

---

## Passo 3: (Opcional) Instalar navegador para o Playwright

- Se você **não** for usar o Chrome com depuração remota (passo 4), instale o Chromium do Playwright:
  ```powershell
  playwright install chromium
  ```
- Se for usar **apenas** o Chrome já instalado no PC com porta 9222, pode pular este passo.

---

## Passo 4: (Opcional) Usar o Chrome com login persistente

Para não precisar logar no Facebook a cada execução:

1. Feche **todas** as janelas do Google Chrome.
2. Abra o Chrome com depuração remota e um perfil fixo. No **PowerShell** (ou CMD):
   ```powershell
   & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\Projects\AutoRadar\chrome_login_profile"
   ```
   (Ajuste o caminho do `chrome.exe` se estiver em outro local.)
3. No Chrome que abriu, acesse **facebook.com**, faça login e abra o **Marketplace** pelo menos uma vez.
4. Deixe esse Chrome aberto (pode minimizar). O AutoRadar vai conectar nele na porta 9222.

Se pular este passo, o app pode abrir um navegador gerenciado e pedir que você faça login na primeira execução.

---

## Passo 5: Configurar preferências (cidade, preço, margem)

1. Na pasta `C:\Projects\AutoRadar`, procure o arquivo **`user_preferences.json`**.
2. Se **não existir**, execute o app uma vez (`python run_app.py`); ele cria o arquivo com valores padrão. Depois feche o app e edite o arquivo.
3. Abra `user_preferences.json` com o Bloco de Notas ou outro editor e ajuste:
   - **city**: nome da cidade (ex.: `"Montes Claros"`).
   - **state**: UF (ex.: `"MG"`).
   - **price_min** e **price_max**: em **0** = sem filtro de preço; ou valores em reais.
   - **margin_min_reais**: margem mínima em R$ para aparecer no ranking (ex.: `5000` = só oportunidades com ganho ≥ R$ 5.000).
   - **run_every_minutes**: intervalo em minutos para rodar automaticamente (ex.: `60` = a cada 1 hora).
   - **vehicle_types**: `"car"`, `"motorcycle"`, `"truck"` — `true` ou `false` para cada tipo.
4. Salve o arquivo.

Detalhes de cada campo: veja **`USER_PREFERENCES.md`**.

---

## Passo 6: Atualizar a tabela FIPE (recomendado antes da primeira execução)

Os valores de referência vêm da tabela FIPE. Para margens confiáveis:

1. **Opção A – Pelo app:** depois de abrir o AutoRadar, clique em **📊 Atualizar FIPE** na janela principal. Aguarde o download.
2. **Opção B – Pelo terminal:**
   ```powershell
   cd C:\Projects\AutoRadar
   .\venv\Scripts\activate
   python fipe_download.py
   ```
   Pode levar vários minutos; há limite de requisições/dia. O script salva o progresso e pode ser rodado de novo depois.

A base normalizada fica em `out/fipe_db_norm.json`. O app usa essa base no ranking.

---

## Passo 7: Iniciar o AutoRadar

1. Abra o PowerShell e vá até a pasta do projeto:
   ```powershell
   cd C:\Projects\AutoRadar
   .\venv\Scripts\activate
   python run_app.py
   ```
   **Ou** dê dois cliques em **`Iniciar_AutoRadar.bat`** (ele já roda `python run_app.py` na pasta correta).

2. Deve abrir a **janela principal** do AutoRadar (logo, barra de progresso, botões).

3. **Primeira vez sem sessão salva:**
   - O app pode abrir o navegador e pedir que você **faça login no Facebook**. Faça o login e, se aparecer, clique em **“Já fiz o login”** (ou equivalente) na janela do AutoRadar.
   - Depois disso, a sessão é salva em `browser_state.json` (ou no Chrome da porta 9222) para as próximas execuções.

4. O pipeline roda: **Coleta de links** → **Scan dos anúncios** → **Consolidação** → **Ranking (FIPE + opcional IA)**. Ao final, o **relatório HTML** é gerado e aberto automaticamente em `UI/index.html` (ranking de oportunidades).

---

## Passo 8: Ver o relatório e reenviar para o Telegram (opcional)

- O relatório é o arquivo **`UI/index.html`** (aberto ao final de cada execução).
- Para **reenviar** as oportunidades para o Telegram sem rodar o pipeline de novo: na janela do AutoRadar, clique em **📤 Reenviar anúncios** (é necessário ter configurado `telegram_config.json` antes).

---

## Passo 9: (Opcional) Configurar Telegram

1. Crie um bot no Telegram (com @BotFather) e anote o **token**.
2. Obtenha o **chat_id** do grupo ou canal onde quer receber as mensagens (há tutoriais na internet).
3. Na pasta `C:\Projects\AutoRadar`, copie **`telegram_config.example.json`** para **`telegram_config.json`**.
4. Edite `telegram_config.json` e preencha:
   - `"bot_token": "SEU_TOKEN"`
   - `"chat_id": "SEU_CHAT_ID"`
5. Salve. O app enviará as oportunidades ao Telegram ao final do pipeline (e você pode usar **Reenviar anúncios** a qualquer momento).

---

## Passo 10: (Opcional) Usar IA grátis com Ollama

Para melhor casamento FIPE e dicas de risco de golpe **sem custo**:

1. Instale o **Ollama** (Windows): https://ollama.com/download  
2. No PowerShell:
   ```powershell
   ollama pull llama3.2
   ```
3. Deixe o Ollama rodando (em geral inicia com o Windows e fica na bandeja).
4. Na pasta `C:\Projects\AutoRadar`, crie o arquivo **`ai_config.json`** com:
   ```json
   {
     "use_ollama": true
   }
   ```
5. Na próxima execução, o app usará o modelo local para ajudar no ranking. Mais detalhes: **`COMO_USAR_IA_GRATIS.md`**.

---

## Resumo rápido (checklist)

- [ ] Projeto em `C:\Projects\AutoRadar`
- [ ] `python -m venv venv` e `pip install -r requirements.txt`
- [ ] (Opcional) Chrome na porta 9222 com login no Facebook
- [ ] `user_preferences.json` com cidade, estado, margem e intervalo
- [ ] Tabela FIPE atualizada (botão **Atualizar FIPE** ou `python fipe_download.py`)
- [ ] Primeira execução: `python run_app.py` (ou `Iniciar_AutoRadar.bat`) e login no Facebook se pedido
- [ ] (Opcional) `telegram_config.json` para envio ao Telegram
- [ ] (Opcional) Ollama + `ai_config.json` para IA grátis

---

## Problemas comuns

- **“Margens estranhas ou altas demais”**  
  A tabela FIPE pode estar desatualizada. Use **📊 Atualizar FIPE** ou rode `python fipe_download.py`. Veja **`COMO_ATUALIZAR_FIPE.md`**.

- **Chrome não abre ou não conecta**  
  Se estiver usando a porta 9222, feche todos os Chromes e abra de novo com o comando do Passo 4. Confirme que nenhum outro programa está usando a porta 9222.

- **Erro de import ou módulo não encontrado**  
  Confirme que ativou o venv (`.\venv\Scripts\activate`) e que rodou `pip install -r requirements.txt`.

- **Relatório não abre**  
  Abra manualmente o arquivo `C:\Projects\AutoRadar\UI\index.html` no navegador; ele é atualizado ao final de cada execução.

---

## Créditos

**Created by Igor Avelar — avelar.igor@gmail.com**

---

# Tutorial – AutoRadar (English, step-by-step)

**Created by Igor Avelar — avelar.igor@gmail.com**

This tutorial walks you through setting up and running AutoRadar on Windows, from scratch to your first opportunity report.

---

## What you need

- **Windows** (tested on 10/11).
- A **Facebook account** (to access Marketplace).
- **Python 3.11 or newer**. Check in PowerShell: `python --version`.
- **Internet** (Facebook, FIPE API, optionally Telegram and AI).

---

## Step 1: Get the project

1. Place the project folder at: **`C:\Projects\AutoRadar`**.
2. Open **PowerShell** and go to the folder:
   ```powershell
   cd C:\Projects\AutoRadar
   ```

---

## Step 2: Create the virtual environment (venv)

1. Create the venv:
   ```powershell
   python -m venv venv
   ```
2. Activate it:
   ```powershell
   .\venv\Scripts\activate
   ```
3. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

---

## Step 3: (Optional) Install Playwright browser

If you will **not** use Chrome with remote debugging (Step 4), run:

```powershell
playwright install chromium
```

---

## Step 4: (Optional) Use Chrome with persistent login

1. Close all Google Chrome windows.
2. Start Chrome with remote debugging:
   ```powershell
   & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\Projects\AutoRadar\chrome_login_profile"
   ```
3. In that Chrome, go to **facebook.com**, log in, and open **Marketplace** at least once.
4. Keep that Chrome open. AutoRadar will connect to it on port 9222.

---

## Step 5: Configure preferences (city, price, margin)

1. In `C:\Projects\AutoRadar`, find **`user_preferences.json`** (created on first run if missing).
2. Edit: **city**, **state**, **price_min** / **price_max** (0 = no filter), **margin_min_reais**, **run_every_minutes**, **vehicle_types** (car, motorcycle, truck).
3. Save. See **`USER_PREFERENCES.md`** for details.

---

## Step 6: Update FIPE table (recommended before first run)

- **From the app:** click **📊 Atualizar FIPE** and wait.
- **From the terminal:** `python fipe_download.py` (from project folder with venv active).

---

## Step 7: Start AutoRadar

1. Run:
   ```powershell
   cd C:\Projects\AutoRadar
   .\venv\Scripts\activate
   python run_app.py
   ```
   Or double‑click **`Iniciar_AutoRadar.bat`**.

2. On first run without a saved session, log in to Facebook in the browser when prompted; then the app saves the session.

3. When the pipeline finishes, the HTML report opens automatically (`UI/index.html`).

---

## Step 8: Telegram (optional)

Copy `telegram_config.example.json` to `telegram_config.json`, set **bot_token** and **chat_id**, then save. The app will send opportunities to Telegram at the end of each run.

---

## Step 9: Free AI with Ollama (optional)

1. Install Ollama from https://ollama.com/download  
2. Run: `ollama pull llama3.2`  
3. Create **`ai_config.json`** with: `{"use_ollama": true}`  
4. See **`COMO_USAR_IA_GRATIS.md`** for more.

---

## Credits

**Created by Igor Avelar — avelar.igor@gmail.com**
