# path_utils.py - Caminhos base do projeto AutoRadar (mesclado)
# Created by Igor Avelar - avelar.igor@gmail.com
import os
from pathlib import Path

def get_base_dir() -> Path:
    """Retorna o diretório raiz do projeto."""
    return Path(__file__).resolve().parent

def get_out_dir() -> Path:
    """Diretório out/ para dados processados."""
    p = get_base_dir() / "out"
    p.mkdir(parents=True, exist_ok=True)
    return p

def get_ui_dir() -> Path:
    """Diretório UI/ para relatório HTML."""
    p = get_base_dir() / "UI"
    p.mkdir(parents=True, exist_ok=True)
    return p

def get_cache_listing_dir() -> Path:
    """Diretório cache_listing/ para cache de anúncios."""
    p = get_base_dir() / "cache_listing"
    p.mkdir(parents=True, exist_ok=True)
    return p
