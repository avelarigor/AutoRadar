import logging
from typing import Dict, Any

# Configuração básica do logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def update_fipe_from_olx(listing: Dict[str, Any]):
    """
    Atualiza a base FIPE interna usando o valor extraído da OLX.

    Args:
        listing (dict): Dados normalizados de um anúncio da OLX.
    """
    fipe_olx = listing.get("fipe_olx")

    if fipe_olx is None:
        logging.info("[FIPE_UPDATER] Nenhum valor FIPE encontrado no anúncio. Nenhuma ação realizada.")
        return

    # Simulação de base de dados interna
    fipe_database = {
        # Exemplo: "modelo_ano": valor_fipe
        "gol_2020": 45000,
        "onix_2021": 55000,
    }

    # Chave para identificar o registro na base (exemplo: título do anúncio ou outro identificador único)
    year_val = listing.get('year') or listing.get('raw_details', {}).get('regdate', '')
    key = f"{listing.get('title', '').lower()}_{year_val}"

    if key in fipe_database:
        if fipe_database[key] != fipe_olx:
            logging.info(f"[FIPE_UPDATER] Atualizando FIPE para {key}: {fipe_database[key]} -> {fipe_olx}")
            fipe_database[key] = fipe_olx
        else:
            logging.info(f"[FIPE_UPDATER] Valor FIPE para {key} já está atualizado.")
    else:
        logging.info(f"[FIPE_UPDATER] Inserindo novo registro FIPE para {key}: {fipe_olx}")
        fipe_database[key] = fipe_olx

    # Log final para confirmar a operação
    logging.info(f"[FIPE_UPDATER] Base FIPE atualizada: {fipe_database}")