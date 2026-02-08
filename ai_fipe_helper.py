#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper opcional com IA para:
1) Extrair marca/modelo/ano do título e descrição e sugerir melhor casamento FIPE.
2) Avaliar risco de golpe na descrição (além da lista de palavras).

Opções (uma das duas):
- Gratuito: Ollama (modelo local). Coloque "use_ollama": true em ai_config.json; baixe o modelo (ollama pull llama3.2). O app aquece o modelo sozinho ao iniciar.
- Pago: OPENAI_API_KEY em .env ou ai_config.json (ChatGPT Pro NÃO inclui API; a API é cobrada à parte).

Created by Igor Avelar - avelar.igor@gmail.com
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

BASE_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
OLLAMA_MODEL = "llama3.2"
# Timeout curto para não travar a interface se o Ollama estiver lento ou fora do ar
OLLAMA_TIMEOUT = 12

# Processo Ollama iniciado pelo app (para fechar ao sair)
_ollama_process = None


def _get_openai_key() -> Optional[str]:
    """Lê a chave da API OpenAI: .env (OPENAI_API_KEY) ou ai_config.json."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    config = BASE_DIR / "ai_config.json"
    if config.exists():
        try:
            with open(config, "r", encoding="utf-8") as f:
                data = json.load(f)
                return (data.get("openai_api_key") or "").strip()
        except Exception:
            pass
    return None


def _use_ollama() -> bool:
    """True se ai_config.json tem use_ollama: true (IA gratuita local)."""
    config = BASE_DIR / "ai_config.json"
    if not config.exists():
        return False
    try:
        with open(config, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("use_ollama") is True
    except Exception:
        return False


def _is_ollama_running() -> bool:
    """Verifica se o Ollama está rodando (porta 11434 respondendo ou processo ativo)."""
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        pass
    # Fallback: verificar processo no Windows
    try:
        import subprocess
        if sys.platform == 'win32':
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq ollama.exe", "/FO", "CSV"],
                capture_output=True,
                text=True,
                timeout=3
            )
            return "ollama.exe" in result.stdout.lower()
        else:
            result = subprocess.run(
                ["pgrep", "-f", "ollama"],
                capture_output=True,
                timeout=3
            )
            return result.returncode == 0
    except Exception:
        pass
    return False


def start_ollama_if_needed() -> bool:
    """
    Inicia o Ollama se não estiver rodando e use_ollama estiver ativo.
    Retorna True se iniciou o Ollama (para fechar ao sair).
    """
    global _ollama_process
    if not _use_ollama():
        return False
    if _is_ollama_running():
        return False  # Já está rodando, não iniciamos
    try:
        import subprocess
        import sys
        # Tentar encontrar o executável ollama
        ollama_exe = None
        if sys.platform == 'win32':
            # Windows: tentar caminhos comuns
            for path in [
                Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
                Path("C:/Program Files/Ollama/ollama.exe"),
                Path("C:/Program Files (x86)/Ollama/ollama.exe"),
            ]:
                if path.exists():
                    ollama_exe = str(path)
                    break
            # Se não encontrou, tentar pelo PATH
            if not ollama_exe:
                try:
                    result = subprocess.run(["where", "ollama"], capture_output=True, text=True, timeout=3)
                    if result.returncode == 0 and result.stdout.strip():
                        ollama_exe = result.stdout.strip().split("\n")[0]
                except Exception:
                    pass
        else:
            # Linux/Mac: tentar pelo PATH
            try:
                result = subprocess.run(["which", "ollama"], capture_output=True, text=True, timeout=3)
                if result.returncode == 0 and result.stdout.strip():
                    ollama_exe = result.stdout.strip()
            except Exception:
                pass
        if not ollama_exe:
            return False  # Ollama não encontrado
        # Iniciar o servidor Ollama
        _ollama_process = subprocess.Popen(
            [ollama_exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        # Aguardar um pouco para o servidor iniciar
        import time
        for _ in range(10):  # 10 tentativas de 0.5s = 5s máximo
            time.sleep(0.5)
            if _is_ollama_running():
                return True  # Iniciado com sucesso
        # Se não iniciou em 5s, tentar matar o processo
        if _ollama_process:
            try:
                _ollama_process.terminate()
                _ollama_process.wait(timeout=2)
            except Exception:
                try:
                    _ollama_process.kill()
                except Exception:
                    pass
            _ollama_process = None
        return False
    except Exception:
        return False


def stop_ollama_if_started_by_us() -> None:
    """Fecha o processo Ollama se foi iniciado pelo app."""
    global _ollama_process
    if _ollama_process is None:
        return
    try:
        _ollama_process.terminate()
        try:
            _ollama_process.wait(timeout=3)
        except Exception:
            try:
                _ollama_process.kill()
            except Exception:
                pass
    except Exception:
        pass
    finally:
        _ollama_process = None


def warm_up_ollama() -> None:
    """
    Envia uma requisição mínima ao Ollama em background para carregar o modelo na memória.
    Assim o app pode rodar sozinho: ao iniciar, aquece o modelo; quando chegam os anúncios, a IA já está pronta.
    Timeout longo (60s) porque roda em thread separada e não bloqueia a interface.
    """
    if not _use_ollama():
        return
    try:
        import requests
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": "ok"}],
            "options": {"temperature": 0, "num_predict": 5},
        }
        requests.post(OLLAMA_URL, json=payload, timeout=60)
    except Exception:
        pass


def _call_ollama(system: str, user: str, max_tokens: int = 500) -> Optional[str]:
    """Chama Ollama local (gratuito). Requer: ollama pull llama3.2 e ollama serve."""
    try:
        import requests
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user[:8000]},
            ],
            "options": {"temperature": 0.1, "num_predict": max_tokens},
        }
        r = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        return (msg.get("content") or "").strip()
    except Exception:
        return None


def _call_openai(system: str, user: str, max_tokens: int = 500) -> Optional[str]:
    """Chama a API OpenAI (Chat Completions). Cobrança à parte (ChatGPT Pro não inclui)."""
    key = _get_openai_key()
    if not key:
        return None
    try:
        import requests
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user[:8000]},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.1,
        }
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        return (msg.get("content") or "").strip()
    except Exception:
        return None


def _call_llm(system: str, user: str, max_tokens: int = 500) -> Optional[str]:
    """Tenta OpenAI; se não tiver chave, tenta Ollama (gratuito) se use_ollama estiver ativo."""
    out = _call_openai(system, user, max_tokens)
    if out:
        return out
    if _use_ollama():
        return _call_ollama(system, user, max_tokens)
    return None


def extract_vehicle_for_fipe(title: str, description: str) -> Optional[Dict[str, Any]]:
    """
    Usa IA para extrair marca, modelo sugerido (nome FIPE) e ano do título e da descrição.
    Ajuda a melhorar o casamento com a tabela FIPE (ex.: "EcoSport Storm 2.0 AWD" na descrição).
    Retorna {"marca": str, "modelo_sugerido": str, "ano": int} ou None.
    Se a IA não estiver disponível ou der erro, retorna None (fluxo continua sem IA).
    """
    try:
        if not title:
            return None
        system = """Você é um assistente que extrai dados de veículos de anúncios.
Responda APENAS com um JSON válido, sem markdown, no formato:
{"marca": "nome da marca em minúsculo", "modelo_sugerido": "nome do modelo como na FIPE (ex: EcoSport Storm 2.0 AWD)", "ano": número do ano}}
Use a descrição para refinar o modelo quando o título for vago (ex: título "Ford ecosport" e descrição "Storm 2.0 AWD" -> modelo_sugerido "EcoSport Storm 2.0 AWD").
Ano: só número (ex: 2019). Se não achar ano, use 0."""
        user = f"Título do anúncio: {title}\n\nDescrição (trecho): { (description or '')[:2000] }"
        out = _call_llm(system, user, max_tokens=150)
        if not out:
            return None
        out = re.sub(r"^```\w*\n?", "", out).strip()
        out = re.sub(r"\n?```\s*$", "", out).strip()
        data = json.loads(out)
        marca = (data.get("marca") or "").strip().lower()
        modelo = (data.get("modelo_sugerido") or "").strip()
        ano = data.get("ano")
        if isinstance(ano, str) and ano.isdigit():
            ano = int(ano)
        if not isinstance(ano, int) or ano <= 0:
            ano = None
        if marca and modelo:
            return {"marca": marca, "modelo_sugerido": modelo, "ano": ano}
    except Exception:
        return None
    return None


def extract_vehicle_for_fipe_batch(
    items: List[Tuple[str, str]],
) -> List[Optional[Dict[str, Any]]]:
    """
    Extrai marca, modelo sugerido (FIPE) e ano para vários anúncios numa única chamada à IA.
    items: lista de (title, description). Retorna lista de mesmo tamanho com dict ou None.
    """
    if not items:
        return []
    try:
        if not is_ai_configured():
            return [None] * len(items)
        system = """Você é um assistente que extrai dados de veículos de anúncios.
Para cada anúncio abaixo, responda com um JSON por linha, no formato:
{"marca": "marca em minúsculo", "modelo_sugerido": "modelo como na FIPE", "ano": número}
Use a descrição para refinar o modelo quando o título for vago. Ano: só número (ex: 2019). Se não achar ano, use 0.
Responda APENAS com uma linha JSON por anúncio, na mesma ordem, sem markdown."""
        lines = []
        for i, (title, desc) in enumerate(items, 1):
            title = (title or "").strip()
            desc = (desc or "")[:2000]
            lines.append(f"{i}. Título: {title}\n   Descrição: {desc[:500]}")
        user = "Anúncios:\n" + "\n\n".join(lines) + "\n\nUm JSON por linha (mesma ordem):"
        out = _call_llm(system, user, max_tokens=min(150 * len(items), 2000))
        if not out:
            return [None] * len(items)
        out = re.sub(r"^```\w*\n?", "", out).strip()
        out = re.sub(r"\n?```\s*$", "", out).strip()
        result = []
        for line in out.split("\n"):
            line = (line or "").strip()
            if not line:
                result.append(None)
                continue
            try:
                data = json.loads(line)
                marca = (data.get("marca") or "").strip().lower()
                modelo = (data.get("modelo_sugerido") or "").strip()
                ano = data.get("ano")
                if isinstance(ano, str) and ano.isdigit():
                    ano = int(ano)
                if not isinstance(ano, int) or ano <= 0:
                    ano = None
                if marca and modelo:
                    result.append({"marca": marca, "modelo_sugerido": modelo, "ano": ano})
                else:
                    result.append(None)
            except Exception:
                result.append(None)
        while len(result) < len(items):
            result.append(None)
        return result[: len(items)]
    except Exception:
        return [None] * len(items)


def analyze_scam_risk(
    title: str,
    description: str,
    price: Optional[float] = None,
    valor_fipe: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """
    Usa IA para avaliar risco de golpe no anúncio (título, descrição e, se informados, preço vs FIPE).
    Retorna {"risco_alto": bool, "motivo": str} ou None. risco_alto=True -> sugerir filtrar do ranking.
    Se price e valor_fipe forem informados, a IA considera se o preço é plausível (R$ 0 ou absurdo = suspeito).
    """
    try:
        if not title:
            return None
        system = """Você é um assistente que detecta possíveis golpes em anúncios de veículos.
Responda APENAS com um JSON válido, sem markdown:
{"risco_alto": true ou false, "motivo": "breve explicação em uma linha"}
Indicadores de risco: preço R$ 0 ou ausente; preço absurdamente abaixo do valor de referência (ex.: carro de 50 mil por 10 mil = golpe, isca ou erro); placa mascarada, documento irregular, leilão, sinistro, descrição vaga ou contraditória com o título, pedido de sinal/antecipado.
Quando receber "Preço do anúncio" e "Valor de referência (FIPE)", avalie se o preço é plausível. Valor 0 ou muito abaixo do FIPE (ex.: menos da metade) deve ser risco_alto: true.
Se parecer anúncio normal e preço coerente, use risco_alto: false."""
        user = f"Título: {title}\n\nDescrição: { (description or '')[:2000] }"
        if price is not None and valor_fipe is not None and valor_fipe > 0:
            user += f"\n\nPreço do anúncio: R$ {price:,.0f}\nValor de referência (FIPE) aproximado: R$ {valor_fipe:,.0f}"
        out = _call_llm(system, user, max_tokens=120)
        if not out:
            return None
        out = re.sub(r"^```\w*\n?", "", out).strip()
        out = re.sub(r"\n?```\s*$", "", out).strip()
        data = json.loads(out)
        risco = data.get("risco_alto") is True
        motivo = (data.get("motivo") or "").strip()
        return {"risco_alto": risco, "motivo": motivo or ("Risco indicado pela IA" if risco else "Sem indício de golpe")}
    except Exception:
        return None


def is_ai_configured() -> bool:
    """True se OpenAI key OU Ollama está ativo (IA disponível). Nunca levanta exceção."""
    try:
        return _get_openai_key() is not None or _use_ollama()
    except Exception:
        return False


def estimate_fipe_value_ia(marca: str, modelo: str, ano: int) -> Optional[float]:
    """
    Pede à IA uma estimativa do MENOR preço de referência FIPE (versão de entrada) para o veículo no Brasil.
    A IA é a primeira opção para buscar FIPE; deve retornar o menor valor entre as versões disponíveis.
    Retorna o valor em reais (float) ou None. Nunca levanta exceção.
    """
    try:
        if not marca or not modelo or not ano or ano <= 0:
            return None
        system = """Você é um assistente que conhece a tabela FIPE brasileira de veículos.
Responda APENAS com um JSON válido, sem markdown: {"valor_reais": número}
IMPORTANTE: Retorne SEMPRE o MENOR valor FIPE (versão de entrada, mais básica) para o veículo indicado, considerando dados atuais (2025/2026).
Para caminhonetes (Hilux, Ranger, S10, Strada, Amarok, L200, etc.), se não houver informação sobre cabine simples (CS) ou dupla (CD), retorne o valor da CABINE SIMPLES (CS), que é sempre o menor.
Exemplo: Se houver Compass Sport (R$ 77.412), Longitude (R$ 89.776) e Limited (R$ 95.248), retorne 77412 (o menor).
Exemplo: Se houver Hilux CD (R$ 150.000) e Hilux CS (R$ 130.000), retorne 130000 (CS, o menor).
Só o número, sem R$ nem texto."""
        user = f"Marca: {marca}\nModelo/versão: {modelo}\nAno: {ano}\nQual o MENOR valor FIPE de referência (versão de entrada, mais básica) em reais para este veículo? Para caminhonetes sem especificação de cabine, use cabine simples (CS). Apenas o número."
        out = _call_llm(system, user, max_tokens=80)
        if not out:
            return None
        out = re.sub(r"^```\w*\n?", "", out).strip()
        out = re.sub(r"\n?```\s*$", "", out).strip()
        data = json.loads(out)
        val = data.get("valor_reais") or data.get("valor") or data.get("valor_fipe")
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val) if val > 0 else None
        if isinstance(val, str):
            val = val.replace("R$", "").replace(".", "").replace(",", ".").strip()
            return float(val) if val else None
    except Exception:
        pass
    return None


def estimate_fipe_value_ia_batch(
    items: List[Tuple[str, str, int]],
) -> List[Optional[float]]:
    """
    Estima valor FIPE (menor/entrada) para vários veículos numa única chamada à IA.
    items: lista de (marca, modelo, ano). Retorna lista de mesmo tamanho com float ou None.
    """
    if not items:
        return []
    try:
        if not is_ai_configured():
            return [None] * len(items)
        lines = []
        for i, (marca, modelo, ano) in enumerate(items, 1):
            if not marca or not modelo or not ano or ano <= 0:
                continue
            lines.append(f"{i}. Marca: {marca} | Modelo: {modelo} | Ano: {ano}")
        if not lines:
            return [None] * len(items)
        system = """Você é um assistente que conhece a tabela FIPE brasileira.
Para cada veículo abaixo, retorne o MENOR valor FIPE (versão de entrada) em reais.
Responda APENAS com uma linha por veículo: só o número (ex: 77412), na mesma ordem.
Dados atuais 2025/2026. Sem R$ nem texto."""
        user = "Veículos:\n" + "\n".join(lines) + "\n\nNúmeros (um por linha, mesma ordem):"
        out = _call_llm(system, user, max_tokens=min(50 * len(items), 1000))
        if not out:
            return [None] * len(items)
        out = re.sub(r"^```\w*\n?", "", out).strip()
        out = re.sub(r"\n?```\s*$", "", out).strip()
        result = []
        for line in out.split("\n"):
            line = (line or "").strip()
            if not line:
                result.append(None)
                continue
            val = line.replace("R$", "").replace(".", "").replace(",", ".").strip()
            try:
                f = float(val)
                result.append(f if f > 0 else None)
            except Exception:
                result.append(None)
        while len(result) < len(items):
            result.append(None)
        return result[: len(items)]
    except Exception:
        return [None] * len(items)
