# ============================================================
# AutoRadar — Global Configuration
# Criado por: Igor Avelar - avelar.igor@gmail.com
# ============================================================

"""
Configuração global do AutoRadar.

Este é o ÚNICO arquivo de configuração — edite aqui para ajustar
parâmetros operacionais (margens, preços, palavras-chave, portais).

DRY_RUN Mode:
- Quando True: pipeline completo executa (coleta, ranking, engines)
  MAS envio ao Telegram e marcação de "sent" são bloqueados.
- Quando False: operação normal (modo produção).
"""

import pathlib
from typing import Dict, List, Any

BASE_DIR = pathlib.Path(__file__).resolve().parent


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LOCALIZAÇÃO E PREÇOS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CITY      = "Montes Claros"
STATE     = "MG"
PRICE_MIN = 10000
PRICE_MAX = 1000000


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MARGEM MÍNIMA POR REGIÃO (carros)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Detectada pelo slug na URL do anúncio coletado:
#   - Links de "Belo Horizonte e região"      → MARGIN_BH
#   - Links de "Montes Claros e região"       → MARGIN_MC
#   - Demais URLs (Webmotors, outros portais) → MARGIN_DEFAULT

# Regiões ativas — controla coleta E envio do digest diário
REGION_MC_ENABLED = True   # Montes Claros
REGION_BH_ENABLED = False  # Belo Horizonte — DESABILITADO até segunda ordem

MARGIN_BH      = 12000   # R$ — Belo Horizonte e região (inclui Betim, Contagem, etc.)
MARGIN_MC      =  5000   # R$ — Montes Claros e região (inclui Bocaiuva, Pirapora, etc.)
MARGIN_DEFAULT =  5000   # R$ — Fallback para portais sem slug de cidade identificável

# Alias de compatibilidade para módulos que leem config.MARGIN_MIN_REAIS
MARGIN_MIN_REAIS = MARGIN_DEFAULT


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DETECÇÃO DE REGIÃO POR URL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Slugs que identificam cada região no URL do anúncio.
# OLX:      .../belo-horizonte-e-regiao/...  ou  .../regiao-de-montes-claros-e-diamantina/...
# Facebook: .../marketplace/belohorizonte/...  ou  .../marketplace/montesclaros/...

_REGION_BH_SLUGS = ["belo-horizonte", "belohorizonte"]
_REGION_MC_SLUGS = ["montes-claros", "montesclaros", "regiao-de-montes-claros"]


def get_margin_for_url(url: str, region: str = "") -> float:
    """Retorna a margem mínima (R$) adequada para a URL do anúncio.

    1) Inspeciona o slug da URL (funciona para OLX que inclui região no path).
    2) Fallback: usa o tag 'region' ("bh" ou "mc") gravado no link_queue na
       hora da coleta — necessário para Facebook (item URLs não têm slug).
    """
    url_lower = (url or "").lower()
    for slug in _REGION_BH_SLUGS:
        if slug in url_lower:
            return float(MARGIN_BH)
    for slug in _REGION_MC_SLUGS:
        if slug in url_lower:
            return float(MARGIN_MC)
    # Fallback por tag de região (Facebook e outros portais sem slug na URL)
    reg = (region or "").strip().lower()
    if reg == "bh":
        return float(MARGIN_BH)
    if reg == "mc":
        return float(MARGIN_MC)
    return float(MARGIN_DEFAULT)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TIMING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RUN_EVERY_MINUTES   = 30
SCAN_CACHE_DAYS     = 30
RESCAN_COOLDOWN_DAYS = 5   # dias para re-enfileirar anúncios DONE/FAILED para re-scan
DECOUPLED_MODE    = True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TIPOS DE VEÍCULOS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VEHICLE_TYPES: Dict[str, bool] = {
    "car":        True,
    "motorcycle": False,
    "truck":      False,
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PORTAIS — URLS DE BUSCA
# OLX e Facebook usam rotatividade automática (ver autoradar_workers.py
# e collect_links_olx.py); as URLs abaixo são referência/fallback.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WEBMOTORS_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "search_url": (
        "https://www.webmotors.com.br/carros-usados/mg-montes-claros"
        "?lkid=1000&tipoveiculo=carros-usados"
        "&localizacao=-16.7286406%2C-43.8582139x100km"
        "&estadocidade=Minas%20Gerais-Montes%20Claros&page=1"
    ),
}

MOBIAUTO_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "search_url": "https://www.mobiauto.com.br/comprar/carros-usados/mg-montes-claros",
}

OLX_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "search_url": "",  # OLX usa rotatividade automática em collect_links_olx.py
}

FACEBOOK_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "search_url": "https://www.facebook.com/marketplace/montesclaros/vehicles?minPrice=12000",
    "marketplace_region_id": "112130402135658",
}

FACEBOOK_REGION_ID: str = FACEBOOK_CONFIG.get("marketplace_region_id", "")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PALAVRAS-CHAVE A EVITAR
# Anúncios com qualquer um destes termos são descartados do ranking.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

KEYWORDS_AVOID: List[str] = [
    # Golpe / fraude
    "golpe", "golpista", "leilao", "sinistro", "batido",
    "recuperado", "recuperado de",
    "financiamento bloqueado", "financiamento bloqueada",
    "alienado", "alienada", "restricao", "restrição fiscal",
    "ipva", "ipva atrasado",
    "documentacao irregular", "doc irregular",
    "roubo", "furto", "perda total",
    "quebrado", "reparado", "reparada", "avaria",
    # Alterações / suspeitos
    "kit", "rebaixado", "rebaixada", "blindado", "blindada",
    "turbo", "preparado",
    # Financeiro / pagamento suspeito / consórcio
    "contemplada", "contempladas", "consorcio",
    "parcelas", "parcela", "boleto", "troco",
    "permuta", "permuto", "sinal", "reserva",
    "quitado", "debito", "penhor",
    "apreendido", "apreendida",
    # Outros
    "multa", "multas", "detran",
]


# Configuração de digest telegram (opcional)
TELEGRAM_DIGEST: Dict[str, Any] = {}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MÓDULO IPHONES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Ligar/desligar o módulo de iPhones sem tocar em mais nada
IPHONES_ENABLED = False  # DESABILITADO até segunda ordem
IPHONE_MARGIN_MIN = 1200  # R$ — margem mínima para considerar oportunidade
IPHONE_CITY_FILTER = "Montes Claros"  # Cidade alvo — anúncios fora são descartados

# Anúncios com qualquer um destes termos no título ou na descrição são descartados
IPHONE_KEYWORDS_BLOCK: List[str] = [
    "icloud bloqueado",
    "retirada de peças",
    "sucata",
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MÓDULO PS5
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Ligar/desligar o módulo de PS5 sem tocar em mais nada
PS5_ENABLED       = False  # DESABILITADO até segunda ordem
PS5_MARGIN_MIN    = 500   # R$ — margem mínima para considerar oportunidade
PS5_PRICE_MIN     = 2300  # R$ — preço mínimo (filtra controles, jogos e acessórios)
PS5_CITY_FILTER   = "Montes Claros"  # Cidade alvo — anúncios fora são descartados

# Anúncios com qualquer um destes termos no título ou na descrição são descartados
PS5_KEYWORDS_BLOCK: List[str] = [
    "controle",
    "controles",
    "jogo",
    "game",
    "hdmi",
    "suporte",
    "headset",
    "carregador",
    "manete",
    "gamestick",
    "cabo",
    "fone",
    "dualsense",
    "somente",
    "peças",
    "spare",
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# T22 — DRY RUN MODE (Single Source of Truth)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ATENÇÃO: DRY_RUN = True bloqueia envio ao Telegram
# Útil para:
# - Validar pipeline sem disparar notificações
# - Testar engines (T18, T19, T19.3, T20, T21)
# - Validar ranking sem impacto em usuário final
# - Debug de lógica sem side effects

DRY_RUN = False  # ⚠️ MODO SIMULAÇÃO ATIVO (T22.2 - Validação de 2 ciclos)


def is_dry_run() -> bool:
    """
    Retorna True se DRY_RUN mode está ativo.
    Usado por módulos que precisam checar o modo.
    """
    return DRY_RUN


def get_mode_label() -> str:
    """Retorna label legível do modo atual"""
    return "DRY_RUN (SIMULAÇÃO)" if DRY_RUN else "PRODUÇÃO"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_all_config() -> Dict[str, Any]:
    """Retorna todas as configurações como dict (útil para debug)."""
    return {
        "city": CITY,
        "state": STATE,
        "price_min": PRICE_MIN,
        "price_max": PRICE_MAX,
        "margin_bh": MARGIN_BH,
        "margin_mc": MARGIN_MC,
        "margin_default": MARGIN_DEFAULT,
        "run_every_minutes": RUN_EVERY_MINUTES,
        "scan_cache_days": SCAN_CACHE_DAYS,
        "decoupled_mode": DECOUPLED_MODE,
        "vehicle_types": VEHICLE_TYPES,
        "webmotors": WEBMOTORS_CONFIG,
        "mobiauto": MOBIAUTO_CONFIG,
        "olx": OLX_CONFIG,
        "facebook": FACEBOOK_CONFIG,
        "keywords_avoid": KEYWORDS_AVOID,
        "dry_run": DRY_RUN,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# T22.3 — Console Compact Mode (Visibilidade de Ciclos)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONSOLE_COMPACT_MODE = False  # Modo simplificado no console (ciclos visíveis) — DESABILITADO PARA LOG COMPLETO


def is_compact_mode() -> bool:
    """Retorna True se modo compacto no console está ativo."""
    return CONSOLE_COMPACT_MODE


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# T22.9 — Configuração Centralizada do Telegram
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Credenciais do bot Telegram (migradas de telegram_config.json)
# Lido de telegram_config.json se existir, senão usa valores padrão vazios
_telegram_creds = {"token": "", "chat_id": ""}

try:
    import json as _json_module
    _telegram_config_path = BASE_DIR / "telegram_config.json"
    if _telegram_config_path.exists():
        with open(_telegram_config_path, "r", encoding="utf-8") as _f:
            _tg_data = _json_module.load(_f)
            _telegram_creds["token"] = (_tg_data.get("bot_token") or "").strip()
            _telegram_creds["chat_id"] = (_tg_data.get("chat_id") or "").strip()
except Exception:
    pass

TELEGRAM_TOKEN = _telegram_creds.get("token", "")
TELEGRAM_CHAT_ID = _telegram_creds.get("chat_id", "")

ENABLE_OLX = True
OLX_MAX_PAGES = 2            # máx 2 páginas por rodada — cauteloso
OLX_INTERVAL_SECONDS = 2700  # 45 min entre rodadas
