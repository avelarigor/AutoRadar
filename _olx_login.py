"""
Script auxiliar: abre o Google Chrome REAL com o perfil OLX para resolver o Cloudflare manualmente.

O Chrome real é usado (em vez do Chromium do Playwright) para que o TLS fingerprint (JA3/JA4)
seja idêntico ao de um browser comum, contornando a detecção do Cloudflare.

USO:
    python _olx_login.py

O browser ficará aberto por 5 minutos. Navegue para olx.com.br, resolva o CAPTCHA/challenge
e deixe a página de resultado de busca carregar. Depois feche o browser ou deixe o timeout encerrar.
O cookie cf_clearance será salvo automaticamente no perfil.
"""
import asyncio
import subprocess
import time
from pathlib import Path
from playwright.async_api import async_playwright

OLX_URL = (
    "https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/"
    "estado-mg/regiao-de-montes-claros-e-diamantina/montes-claros"
)
OLX_PROFILE_DIR = Path("profiles/olx").resolve()
CDP_PORT = 9222

_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

def _find_chrome() -> str:
    import os
    candidates = list(_CHROME_CANDIDATES)
    user = os.environ.get("USERNAME", "")
    candidates.append(
        rf"C:\Users\{user}\AppData\Local\Google\Chrome\Application\chrome.exe"
    )
    for path in candidates:
        if Path(path).exists():
            return path
    raise FileNotFoundError(
        "Google Chrome não encontrado. Instale o Chrome ou ajuste _CHROME_CANDIDATES em _olx_login.py"
    )


async def main():
    OLX_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    chrome_exe = _find_chrome()

    print(f"[OLX LOGIN] Chrome encontrado: {chrome_exe}")
    print(f"[OLX LOGIN] Perfil: {OLX_PROFILE_DIR}")
    print(f"[OLX LOGIN] Porta CDP: {CDP_PORT}")
    print(f"[OLX LOGIN] URL alvo: {OLX_URL}")
    print("[OLX LOGIN] ⚠️  Resolva o Cloudflare/CAPTCHA manualmente se aparecer.")
    print("[OLX LOGIN] ⏱  O browser ficará aberto por 5 minutos, depois fecha automaticamente.")

    cmd = [
        chrome_exe,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={OLX_PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-sync",
        "--window-size=1366,768",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[OLX LOGIN] Chrome iniciado (PID {proc.pid}) — aguardando DevTools...")

    # Aguarda DevTools ficar disponível
    async with async_playwright() as pw:
        cdp_url = f"http://localhost:{CDP_PORT}"
        browser = None
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                browser = await pw.chromium.connect_over_cdp(cdp_url)
                break
            except Exception:
                await asyncio.sleep(0.8)

        if browser is None:
            print("[OLX LOGIN] ❌ Não foi possível conectar ao Chrome via CDP.")
            proc.terminate()
            return

        contexts = browser.contexts
        ctx = contexts[0] if contexts else await browser.new_context()
        pages = ctx.pages
        page = pages[0] if pages else await ctx.new_page()

        await page.goto(OLX_URL, wait_until="domcontentloaded", timeout=30000)

        print("[OLX LOGIN] Browser aberto. Aguardando 5 minutos...")
        for remaining in range(300, 0, -30):
            await asyncio.sleep(30)
            try:
                title = await page.title()
            except Exception:
                title = ""
            print(f"[OLX LOGIN] {remaining}s restantes | Página atual: {title[:60]}")
            if "olx" in title.lower() and not any(
                kw in title.lower() for kw in ("cloudflare", "attention", "just a moment")
            ):
                print("[OLX LOGIN] ✅ OLX carregado com sucesso! Cookie salvo no perfil.")
                await asyncio.sleep(5)
                break

        # disconnect() não envia Browser.close ao Chrome — o processo
        # é encerrado exclusivamente via proc.terminate() pelo PID.
        await browser.disconnect()

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        pass

    print("[OLX LOGIN] Browser fechado. Perfil OLX atualizado.")
    print("[OLX LOGIN] Agora reinicie o AutoRadar para que as coletas OLX funcionem.")


if __name__ == "__main__":
    asyncio.run(main())
