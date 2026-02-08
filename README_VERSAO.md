# AutoRadar – Versão com pipeline paralelo (IA)

Esta pasta é a **versão de desenvolvimento** para o pipeline em que o **scan** e a **avaliação (IA + FIPE)** rodam em paralelo.

- Enquanto o navegador carrega a próxima página de anúncio, a IA já avalia o anúncio anterior e atualiza o ranking.
- Objetivo: reduzir tempo total e aproveitar o tempo de espera do scan.

Para rodar, use o venv do projeto original (ou crie um nesta pasta). Instale as dependências primeiro:

```powershell
pip install -r requirements.txt
```

O app **usa sempre o Chrome local** (porta 9222) quando disponível; não é necessário rodar `playwright install chromium` se você usar o Chrome.

```powershell
C:\Projects\AutoRadar\venv\Scripts\python.exe run_app.py
```

Implementação em andamento: produtor (coleta + scan) e consumidor (IA + FIPE) em paralelo.
