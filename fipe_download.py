#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download da tabela FIPE real (API Parallelum / fipe.online).
Gera out/fipe_db.json e, em seguida, out/fipe_db_norm.json para uso offline no ranking.

API base: https://parallelum.com.br/fipe/api/v1
Limite sem token: ~500 requisições/dia. Com token (FIPE_API_TOKEN no .env): até 1000/dia.
Para tabela completa: rode várias vezes (o script salva progresso e retoma de onde parou).
UI e linha de comando usam o mesmo arquivo de progresso (pasta do script). Use sempre o mesmo projeto para retomar.

Execute: .\\venv\\Scripts\\python.exe fipe_download.py
         ou: python fipe_download.py --tipos carros  (só carros)
         ou: python fipe_download.py --tipos carros,motos,caminhoes  (padrão)
         Para baixar só o que faltou (ex.: caminhões): python fipe_download.py --tipos caminhoes
         Padrão: sempre consultar API (valor online prevalece). --incremental para só baixar o que falta (valores já na base não são atualizados).

Created by Igor Avelar - avelar.igor@gmail.com
"""
import sys
import json
import re
import time
import argparse
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Usar sempre a pasta do script para out/ e progresso — assim UI e linha de comando compartilham o mesmo estado
OUT_DIR = BASE_DIR / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

try:
    from path_utils import get_out_dir
except ImportError:
    pass

API_BASE = "https://parallelum.com.br/fipe/api/v1"
FIPE_RAW = OUT_DIR / "fipe_db.json"
FIPE_NORM = OUT_DIR / "fipe_db_norm.json"
PROGRESS_FILE = OUT_DIR / "fipe_download_progress.json"
DELAY_SEC = 1.8  # Entre requisições para evitar rate limit (500/dia sem token)
TOKEN_FILE = BASE_DIR / "fipe_token.txt"


def _get_fipe_token() -> Optional[str]:
    """Lê o token: primeiro fipe_token.txt (fácil de trocar), depois .env"""
    if TOKEN_FILE.exists():
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                token = (f.read() or "").strip()
                if token:
                    return token
        except Exception:
            pass
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("FIPE_API_TOKEN"):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    import os
    return os.environ.get("FIPE_API_TOKEN")


def _parse_valor(s: str) -> Optional[float]:
    if not s:
        return None
    s = s.replace("R$", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(s)
    except ValueError:
        return None


# Erros que indicam falta de internet: aguardar e tentar de novo em vez de pular
def _is_network_error(exc: Exception) -> bool:
    s = (str(exc) or "").lower()
    if "getaddrinfo failed" in s or "name resolution" in s or "nodename nor servname" in s:
        return True
    if "connection" in s and ("refused" in s or "error" in s or "failed" in s):
        return True
    if "timeout" in s or "timed out" in s or "max retries" in s:
        return True
    if "network is unreachable" in s or "no route to host" in s:
        return True
    exc_type = type(exc).__name__
    if "ConnectionError" in exc_type or "Timeout" in exc_type or "NameResolutionError" in exc_type:
        return True
    return False


def _get(url: str, token: Optional[str] = None) -> Optional[Any]:
    headers = {}
    if token:
        headers["X-Subscription-Token"] = token
    try:
        r = requests.get(url, headers=headers or None, timeout=15)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 402:
            print("   ⚠️ HTTP 402: token inválido ou limite excedido")
    except Exception as e:
        print(f"   ⚠️ Erro GET {url[:60]}...: {e}")
    return None


WAIT_RECONNECT_SEC = 30  # Tempo de espera quando não há internet (depois tenta de novo)


def _get_with_retry(
    url: str,
    token: Optional[str] = None,
    progress_callback: Optional[Any] = None,
    current_global: Optional[int] = None,
    total: Optional[int] = None,
    context_msg: str = "",
) -> Optional[Any]:
    """
    Faz GET com retry em caso de falha de rede (sem internet).
    Não pula o item: aguarda reconexão e tenta de novo até conseguir.
    """
    headers = {}
    if token:
        headers["X-Subscription-Token"] = token
    wait_sec = WAIT_RECONNECT_SEC
    while True:
        try:
            r = requests.get(url, headers=headers or None, timeout=15)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 402:
                print("   ⚠️ HTTP 402: token inválido ou limite excedido")
                return None
            # Outros HTTP: não retentar indefinidamente
            return None
        except Exception as e:
            if _is_network_error(e):
                msg = "Sem internet. Aguardando %ds para reconectar..." % wait_sec
                if progress_callback is not None and current_global is not None and total is not None:
                    try:
                        progress_callback(current_global, total, msg + " " + (context_msg or ""))
                    except Exception:
                        pass
                print("   ⚠️ " + msg + " (" + str(e)[:80] + ")")
                time.sleep(wait_sec)
                wait_sec = min(120, wait_sec + 15)  # Aumenta até 120s
                continue
            print(f"   ⚠️ Erro GET {url[:60]}...: {e}")
            return None


def _get_reference_month_from_v2() -> Optional[str]:
    """Obtém o mês/ano de referência da base FIPE (ex.: 'fevereiro de 2026') via API v2 /references."""
    try:
        r = requests.get("https://parallelum.com.br/fipe/api/v2/references", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and len(data) > 0:
                month = data[0].get("month") or data[0].get("mes") or data[0].get("MesReferencia")
                if month:
                    return str(month).strip()
    except Exception:
        pass
    return None


def _extract_reference_from_detail(detail: Dict[str, Any]) -> Optional[str]:
    """Extrai mês/ano de referência da resposta de detalhe (v1 ou v2)."""
    for key in ("referenceMonth", "MesReferencia", "Referencia", "month", "mes"):
        val = detail.get(key)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    mes = detail.get("MesReferencia") or detail.get("mes")
    ano = detail.get("AnoReferencia") or detail.get("ano")
    if mes is not None and ano is not None:
        return "%s/%s" % (mes, ano)
    return None


def _fetch_marcas(
    tipo: str,
    token: Optional[str] = None,
    retries: int = 2,
) -> List[Dict[str, Any]]:
    """Retorna lista de marcas do tipo. Se vier vazia por falha de rede, tenta até retries vezes."""
    url = f"{API_BASE}/{tipo}/marcas"
    for attempt in range(max(1, retries + 1)):
        data = _get_with_retry(
            url,
            token=token,
            progress_callback=None,
            context_msg="%s (marcas)" % tipo,
        )
        if data and isinstance(data, list) and len(data) > 0:
            return data
        if attempt < retries:
            print("   ⚠️ Lista de marcas vazia para %s; tentando novamente em 5s..." % tipo)
            time.sleep(5)
    return []


def _download_tipo(
    tipo: str,
    existing: Dict[str, Any],
    progress: Dict[str, Any],
    token: Optional[str] = None,
    progress_callback: Optional[Any] = None,
    ref_capture: Optional[List] = None,
    marcas: Optional[List[Dict[str, Any]]] = None,
    global_offset: int = 0,
    global_total: Optional[int] = None,
    incremental: bool = False,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Baixa marcas -> modelos -> anos -> valor para um tipo. progress_callback(global_current, global_total, message).
    Se marcas for passado, usa essa lista; senão busca. global_offset/global_total = progresso global 0-100%.
    incremental=True: não requisita preço para (marca, modelo, ano) que já existem na base (estilo robocopy)."""
    if marcas is None:
        marcas = _fetch_marcas(tipo, token=token)
    if not marcas:
        print(f"   ❌ Nenhuma marca para {tipo}")
        return existing, progress

    total_marcas = len(marcas)
    total = global_total if global_total is not None else total_marcas
    offset = global_offset

    def _report(cur: int, tot: int, msg: str) -> None:
        if progress_callback:
            try:
                progress_callback(cur, tot, msg)
            except Exception:
                pass

    _report(offset, total, "%s - Iniciando..." % tipo)
    skipped = 0  # incremental: já na base
    fetched = 0  # incremental: baixados nesta run

    # Onde começar: em modo incremental NÃO usamos progresso — sempre do início; só pulamos (marca, modelo, ano) já na base.
    # Sem --incremental: retomamos de onde parou (marca → modelo → ano; não pula a marca inteira).
    start = 0
    resume_brand_id = None
    resume_model_id = None
    resume_ano_code = None
    if not incremental:
        if progress.get("last_tipo") == tipo and progress.get("last_brand_id") is not None:
            resume_brand_id = str(progress.get("last_brand_id"))
            resume_model_id = str(progress.get("last_modelo_id")) if progress.get("last_modelo_id") is not None else None
            resume_ano_code = str(progress.get("last_ano_code")) if progress.get("last_ano_code") is not None else None
            for i, m in enumerate(marcas):
                if str(m.get("codigo")) == resume_brand_id:
                    start = i  # retomar a partir da PRÓPRIA marca
                    break
            if start < len(marcas):
                marca_nome_resume = (marcas[start].get("nome") or "").strip() or f"(id {resume_brand_id})"
                print(f"   ⏩ Retomando {tipo} dentro da marca \"{marca_nome_resume}\" (marca {start + 1}/{len(marcas)})")
                if resume_model_id:
                    print(f"      ↳ modelo_id={resume_model_id} ano_code={resume_ano_code or '-'}")

    for i, marca in enumerate(marcas[start:], start=start):
        marca_id = marca.get("codigo")
        marca_nome = (marca.get("nome") or "").strip()
        if not marca_nome:
            continue
        is_resume_brand = (not incremental) and (resume_brand_id is not None) and (str(marca_id) == resume_brand_id)
        skip_until_model_id = resume_model_id if is_resume_brand else None
        skip_until_ano_code = resume_ano_code if is_resume_brand else None
        if marca_nome not in existing:
            existing[marca_nome] = {}

        current_global = offset + (i + 1)
        _report(current_global, total, "%s - %s" % (tipo, marca_nome))

        modelos = _get_with_retry(
            f"{API_BASE}/{tipo}/marcas/{marca_id}/modelos",
            token=token,
            progress_callback=_report,
            current_global=current_global,
            total=total,
            context_msg="%s - %s (modelos)" % (tipo, marca_nome),
        )
        time.sleep(DELAY_SEC)
        if not modelos:
            continue

        modelos_list = modelos.get("modelos") if isinstance(modelos, dict) else modelos
        if not modelos_list:
            continue

        for modelo in modelos_list:
            modelo_id = modelo.get("codigo")
            modelo_nome = (modelo.get("nome") or "").strip()
            if not modelo_nome:
                continue
            if skip_until_model_id is not None:
                if str(modelo_id) != str(skip_until_model_id):
                    continue
                skip_until_model_id = None

            _report(current_global, total, "%s - %s - %s (consultando anos...)" % (tipo, marca_nome, modelo_nome[:40]))

            anos = _get_with_retry(
                f"{API_BASE}/{tipo}/marcas/{marca_id}/modelos/{modelo_id}/anos",
                token=token,
                progress_callback=_report,
                current_global=current_global,
                total=total,
                context_msg="%s - %s (anos)" % (marca_nome, modelo_nome[:30]),
            )
            time.sleep(DELAY_SEC)
            if not anos:
                continue

            for ano_item in anos:
                ano_code = (ano_item.get("codigo") or "").strip()
                if not ano_code:
                    continue
                if skip_until_ano_code is not None:
                    if str(ano_code) != str(skip_until_ano_code):
                        continue
                    skip_until_ano_code = None
                    continue
                ano_str = ano_code.split("-")[0].strip()
                if not ano_str.isdigit():
                    continue
                ano = int(ano_str)

                # Incremental (robocopy): pular se já temos valor para (marca, modelo, ano)
                # JSON guarda ano como string; aceitar int ou str para não reprocessar
                mod_anos = existing.get(marca_nome, {}).get(modelo_nome, {})
                if incremental and mod_anos is not None and (ano in mod_anos or str(ano) in mod_anos):
                    skipped += 1
                    continue

                _report(current_global, total, "%s - %s - %s (%s) (consultando preço...)" % (tipo, marca_nome, (modelo_nome or "")[:30], ano_str))

                progress["last_tipo"] = tipo
                progress["last_brand_id"] = marca_id
                progress["last_modelo_id"] = modelo_id
                progress["last_ano_code"] = ano_code
                try:
                    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                        json.dump(progress, f, indent=2, ensure_ascii=False)
                except Exception:
                    pass

                detail = _get_with_retry(
                    f"{API_BASE}/{tipo}/marcas/{marca_id}/modelos/{modelo_id}/anos/{ano_code}",
                    token=token,
                    progress_callback=_report,
                    current_global=current_global,
                    total=total,
                    context_msg="%s - %s (%s)" % (marca_nome, (modelo_nome or "")[:20], ano_str),
                )
                time.sleep(DELAY_SEC)
                if not detail:
                    continue

                if ref_capture is not None and len(ref_capture) > 0 and ref_capture[0] is None:
                    ref = _extract_reference_from_detail(detail)
                    if ref:
                        ref_capture[0] = ref

                valor = _parse_valor(detail.get("Valor") or detail.get("valor") or "")
                if valor is None or valor <= 0:
                    continue

                fetched += 1
                if modelo_nome not in existing[marca_nome]:
                    existing[marca_nome][modelo_nome] = {}
                if ano not in existing[marca_nome][modelo_nome] or valor < existing[marca_nome][modelo_nome][ano]:
                    existing[marca_nome][modelo_nome][ano] = int(round(valor))

        progress["last_tipo"] = tipo
        progress["last_brand_id"] = marca_id
        progress["last_modelo_id"] = None
        progress["last_ano_code"] = None
        try:
            with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump(progress, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        n_modelos = sum(len(v) for v in existing[marca_nome].values())
        print(f"   [{tipo}] {marca_nome}: {len(existing[marca_nome])} modelos, {n_modelos} entradas")

    if incremental and (skipped > 0 or fetched > 0):
        print(f"   📥 [{tipo}] Incremental: {skipped} pulados (já na base), {fetched} baixados")

    progress["last_brand_id"] = None
    progress["last_tipo"] = None
    progress["last_modelo_id"] = None
    progress["last_ano_code"] = None
    return existing, progress


def main(
    progress_callback: Optional[Any] = None,
    tipos: Optional[List[str]] = None,
    no_resume: bool = False,
):
    """Pode ser chamado pela linha de comando (argparse) ou pela UI (progress_callback, tipos, no_resume)."""
    incremental = False  # Padrão: sempre consultar API (valor online prevalece sobre o local)
    marca_filter = ""
    if tipos is None:
        parser = argparse.ArgumentParser(description="Download tabela FIPE (API Parallelum) para uso offline")
        parser.add_argument("--tipos", default="carros,motos,caminhoes", help="Tipos: carros,motos,caminhoes")
        parser.add_argument("--no-resume", action="store_true", help="Ignorar progresso e recomeçar do zero")
        parser.add_argument("--incremental", action="store_true", help="Só baixar o que falta na base; entradas já existentes NÃO são atualizadas (economia de cota). Padrão: sempre consultar API para que o valor online prevaleça.")
        parser.add_argument("--marca", default="", help="Filtrar por marca (ex.: honda). Vazio = todas")
        args = parser.parse_args()
        tipos = [t.strip() for t in args.tipos.split(",") if t.strip()]
        no_resume = getattr(args, "no_resume", False)
        incremental = getattr(args, "incremental", False)
        marca_filter = (getattr(args, "marca", "") or "").strip().lower()
    if not tipos:
        tipos = ["carros", "motos", "caminhoes"]

    print("=" * 60)
    print("Download tabela FIPE (API Parallelum)")
    print("=" * 60)
    print(f"Tipos: {', '.join(tipos)}")
    if marca_filter:
        print(f"Filtro de marca: \"{marca_filter}\" (apenas marcas que contêm esse texto)")
    print(f"Saída: {FIPE_RAW} -> normalizado em {FIPE_NORM}")
    print(f"Progresso (retomada): {PROGRESS_FILE}")
    print(f"Delay entre requisições: {DELAY_SEC}s (limite ~500/dia sem token)")
    print()

    existing = {}
    progress = {}
    if not no_resume and FIPE_RAW.exists():
        try:
            with open(FIPE_RAW, "r", encoding="utf-8") as f:
                existing = json.load(f)
            n_existing = sum(sum(len(a) for a in m.values()) for m in existing.values())
            print(f"📂 Base existente carregada: {FIPE_RAW} ({n_existing} entradas)")
            if incremental:
                print("   📥 Modo incremental: entradas já na base serão puladas; valores locais NÃO serão atualizados.")
            else:
                print("   🌐 Valor online prevalece: entradas existentes serão (re)consultadas na API para manter preços atuais.")
        except Exception as e:
            print(f"⚠️ Não foi possível carregar {FIPE_RAW}: {e}")
    else:
        if incremental:
            print("📥 Modo incremental (--incremental): só baixar o que falta.")
        else:
            print("🌐 Valor online prevalece: todas as entradas serão consultadas na API.")

    if not no_resume and PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                progress = json.load(f)
            if progress.get("last_brand_id") is not None:
                if incremental:
                    print(f"   ℹ️  Modo incremental: progresso de retomada será ignorado. O script percorre tudo do início e só consulta preço do que não está na base.")
                else:
                    print(f"▶️ Retomando de onde parou: {progress.get('last_tipo')} (marca id {progress.get('last_brand_id')})")
                    print(f"   (progresso em: {PROGRESS_FILE})")
        except Exception as e:
            print(f"⚠️ Não foi possível ler o progresso: {e}")
    elif no_resume:
        print("🔄 Iniciando do zero (--no-resume)")

    token = _get_fipe_token()
    if token:
        print("🔑 Token FIPE encontrado (fipe_token.txt ou .env) — até 1000 req/dia")
    else:
        print("⚠️ Sem token — limite ~500 req/dia. Use fipe_token.txt ou .env (ver COMO_TROCAR_TOKEN_FIPE.txt)")

    # Pré-buscar marcas de cada tipo para progresso global (0–100%) e evitar requisição duplicada
    listas_marcas: List[List[Dict[str, Any]]] = []
    total_global = 0
    for tipo in tipos:
        marcas_tipo = _fetch_marcas(tipo, token=token)
        if marca_filter:
            marcas_tipo = [m for m in marcas_tipo if (m.get("nome") or "").strip().lower().find(marca_filter) >= 0]
        listas_marcas.append(marcas_tipo)
        total_global += len(marcas_tipo)

    # No PS (sem UI) mostrar progresso no terminal
    if progress_callback is None and total_global > 0:
        def _cli_progress(current: int, total: int, message: str) -> None:
            if total and total > 0:
                pct = min(100.0, 100 * current / total)
                print(f"\r   Progresso: {current}/{total} ({pct:.0f}%) — {(message or '')[:55]}   ", end="", flush=True)
            else:
                print(f"   {message}")
        progress_callback = _cli_progress

    if progress_callback and total_global > 0:
        try:
            progress_callback(0, total_global, "Iniciando download (%d marcas no total)..." % total_global)
        except Exception:
            pass

    # Retomada por tipo: só quando NÃO é incremental (ex.: continuar de onde parou após interrupção).
    # Com --incremental: sempre do início (carros → motos → caminhões), pulando só (marca, modelo, ano) já na base.
    if incremental:
        tipo_start_idx = 0
    else:
        resume_tipo = progress.get("last_tipo") if progress.get("last_brand_id") is not None else None
        tipo_start_idx = tipos.index(resume_tipo) if resume_tipo and resume_tipo in tipos else 0

    global_offset = 0
    for idx, tipo in enumerate(tipos):
        if idx < tipo_start_idx:
            n_skip = len(listas_marcas[idx]) if idx < len(listas_marcas) and listas_marcas[idx] else 0
            global_offset += n_skip
            print(f"\n⏭️ Pulando {tipo} (já completo na retomada).")
            continue
        print(f"\n🔄 Baixando {tipo}...")
        marcas_tipo = listas_marcas[idx] if idx < len(listas_marcas) else None
        if marcas_tipo is None or len(marcas_tipo) == 0:
            # Rebuscar marcas (retomada ou lista vazia por falha de rede)
            marcas_tipo = _fetch_marcas(tipo, token=token)
            if marca_filter and marcas_tipo:
                marcas_tipo = [m for m in marcas_tipo if (m.get("nome") or "").strip().lower().find(marca_filter) >= 0]
        existing, progress = _download_tipo(
            tipo,
            existing,
            progress,
            token=token,
            progress_callback=progress_callback,
            marcas=marcas_tipo,
            global_offset=global_offset,
            global_total=total_global if total_global > 0 else None,
            incremental=incremental,
        )
        global_offset += len(marcas_tipo)

    # Salvar JSON bruto
    try:
        with open(FIPE_RAW, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        total = sum(
            sum(len(anos) for anos in modelos.values())
            for modelos in existing.values()
        )
        print(f"\n✅ Salvo {FIPE_RAW.resolve()} ({total} entradas)")
    except Exception as e:
        print(f"❌ Erro ao salvar {FIPE_RAW.resolve()}: {e}")
        return 1

    # Normalizar para formato do ranking (fipe_db_norm.json)
    try:
        from fipe_normalize_db import normalize_db
        normalize_db()
        print(f"✅ Normalizado: {FIPE_NORM.resolve()}")
    except Exception as e:
        print(f"⚠️ Normalização: {e}")
        print("   Rode manualmente: python fipe_normalize_db.py")

    # Salvar data da última atualização e mês/ano de referência da base FIPE
    try:
        import datetime
        cache_dir = OUT_DIR / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        last_update_file = cache_dir / "fipe_last_update.json"
        now = datetime.datetime.now()
        ref_month = _get_reference_month_from_v2()
        data = {
            "last_update": now.strftime("%Y-%m-%d"),
            "iso": now.isoformat(),
            "next_due": (now + datetime.timedelta(days=30)).strftime("%Y-%m-%d"),
            "fipe_reference_month": ref_month,
        }
        with open(last_update_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"📅 Data da atualização salva: {last_update_file} (próxima em 30 dias: {data['next_due']})")
        if ref_month:
            print(f"📅 Mês/ano de referência da base FIPE: {ref_month}")
    except Exception as e:
        print(f"⚠️ Não foi possível salvar data da atualização: {e}")

    print("\nPróximo passo: usar o ranking com a tabela real (out/fipe_db_norm.json)")
    # Lembrete: para baixar só o que faltou (ex.: caminhões), rode: python fipe_download.py --tipos caminhoes
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
