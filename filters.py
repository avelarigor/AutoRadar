import unicodedata
from pathlib import Path
import json
import re

def normalize_text(text: str) -> str:
    """
    Normalize a given text by converting it to lowercase,
    removing accents, and stripping whitespace.
    """
    text_lower = text.lower().strip()
    text_normalized = unicodedata.normalize("NFKD", text_lower)
    return "".join(c for c in text_normalized if not unicodedata.combining(c))

def is_blocked_title(title: str, blocked_words: list[str] = None) -> bool:
    """
    Verifica se alguma palavra/frase bloqueada aparece no título.
    - Frases (com espaço): checagem de substring no título completo.
    - Palavras únicas: checagem de palavra exata (word boundary).
    """

    if blocked_words is None:
        blocked_words = []

    normalized_title = normalize_text(title)
    title_words = set(normalized_title.split())

    for blocked in blocked_words:
        if not blocked:
            continue
        if " " in blocked:
            # Frase multi-palavra: substring match no título inteiro
            if blocked in normalized_title:
                return True
        else:
            # Palavra única: match exato contra as palavras do título
            if blocked in title_words:
                return True

    return False

def load_json_keywords(file_name: str) -> list[str]:
    """
    Load keywords from a JSON file.

    Args:
        file_name (str): The name of the JSON file.

    Returns:
        list[str]: List of keywords.
    """
    path = Path(file_name)
    if not path.exists():
        print(f"[FILTERS] File not found: {file_name}")
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return [normalize_text(str(word)) for word in data]
        elif isinstance(data, dict):
            return [normalize_text(str(word)) for word in data.get("keywords_block", [])]
    except Exception as e:
        print(f"[FILTERS] Error loading JSON file {file_name}: {e}")
        return []

def load_txt_keywords(file_name: str) -> list[str]:
    """
    Load keywords from a TXT file.

    Args:
        file_name (str): The name of the TXT file.

    Returns:
        list[str]: List of keywords.
    """
    path = Path(file_name)
    if not path.exists():
        print(f"[FILTERS] File not found: {file_name}")
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            return [normalize_text(line.strip()) for line in f if line.strip() and not line.startswith("#")]
    except Exception as e:
        print(f"[FILTERS] Error loading TXT file {file_name}: {e}")
        return []

# Palavras-chave de filtro incorporadas diretamente
BLOCKED_WORDS_JSON = [
    "caminhão", "caminhões", "carreta", "cavalinho mecânico", "rodotrem", 
    "bitrem", "vuc", "semirreboque", "baú carga", "sider", "graneleiro", 
    "caçamba", "implemento rodoviário", "motocicleta", "motocicletas", 
    "moto", "motos", "scooter", "motoneta", "biz", "125cc", "150cc", 
    "160cc", "190cc", "250cc", "300cc", "400cc", "450cc", "500cc", 
    "600cc", "650cc", "750cc", "800cc", "900cc", "1000cc", "1100cc", 
    "1200cc", "1250cc", "1300cc", "cilindradas", "guidão", "motoboy", 
    "motofrete", "bauleto", "capacete moto", "estribo caminhão", 
    "tacógrafo", "pneu carga", "Scania", "Iveco", "DAF", "Kenworth", 
    "Peterbilt", "Sinotruk", "Shacman", "Mack Trucks", "Man Trucks", 
    "Yamaha", "Dafra", "Kasinski", "Shineray", "Royal Enfield", 
    "Kawasaki", "Haojue", "Kymco", "Avelloz", "Voltz", "Indian Motorcycle", 
    "Triumph Motorcycle", "Ducati", "Benelli", "Husqvarna moto", "KTM", 
    "Can-Am", "bicombustível diesel", "cavalo mecânico", "truckado", 
    "bitruck", "carreteiro", "estradeiro carga", "furgão carga", "prancha transporte", 
    "yamaha", "cg", "bros", "nxr", "xre", "twister", "hornet", "cbr", "cb", "yz", "mt",
    "tornado", "lander", "iphone", "biz", "kawasaki", "cg150", "cg160", "corsica", 
    "fan", "gaiola", "sahara", "random", "new holland", "holland", "randon",
    "caterpillar", "buggy", "carrinho", "quadriciclo", "trator", "sprinter", "besta", 
    "Van", "outro", "motorizada", "carretinha", "fam", "gratuito", "ducato", "crf", "nx",
    "nc700", "cr", "pcx", "xlr", "6x2", "6x4", "quinta roda", "pino rei", "eixo direcional", 
    "suspensão a ar caminhão", "tração 6x2", "tração 6x4", "tração 4x2 carga", "reduzida", 
    "basculante", "porta contêiner", "tanque combustível", "frigorífico carga", 
    "carroceria aberta", "carroceria fechada", "prancha baixa", "cegonha", "bitrenzão", 
    "tritrem", "cabine leito", "teto alto", "climatizador caminhão", "freio motor", 
    "faixa refletiva", "peso bruto total", "PBT", "capacidade máxima de tração", "CMT", 
    "pedaleira moto", "manete", "protetor de mão", "peso de guidão", "mesa superior", 
    "mesa inferior", "amortecedor de direção", "coroa pinhão corrente", "relação moto", 
    "transmissão por corrente", "monobraço", "balança traseira", "garfo telescópico", 
    "suspensão invertida", "upside down", "radiador de óleo moto", "carenagem", 
    "bolha moto", "bacalhau moto", "eliminador de rabeta", "quadro elástico", 
    "chassi tubular", "naked", "custom", "chopper", "bobber", "big trail", "off-road", 
    "supermoto", "motocross", "enduro", "sportbike", "jaqueta motociclista", 
    "macacão couro moto", "intercomunicador capacete", "extrapesado", "semipesado", 
    "estradeiro carga", "protetor de cárter moto", "descanso central", "cavalete lateral", 
    "pedal de câmbio moto", "pedal de freio moto", "pop100", "pop110", "lead", "sh150", 
    "sh300", "adv150", "elite125", "nmax", "xmax", "neo125", "fazer250", "fazer150", "fz15", 
    "fz25", "rd350", "rd135", "dt180", "dt200", "tenere250", "tenere660", "xtz125", "xtz250", 
    "ybr125", "factor", "crypton", "mt03", "mt07", "mt09", "xj6", "r1", "r3", "r6", "yzf", 
    "gsx", "hayabusa", "s1000rr", "f800gs", "f850gs", "r1200gs", "r1250gs", "g310", 
    "ninja300", "ninja400", "z300", "z400", "z650", "z800", "z900", "z1000", "versys", 
    "vulcan", "intruder", "yes125", "vstrom", "dl650", "dl1000", "boulevard", "burgman", 
    "citycom", "dafra", "riva150", "apache200", "himalayan", "interceptor", "meteor", 
    "scrambler", "monster", "panigale", "multistrada", "diavel", "tiger800", "tiger900", 
    "tiger1200", "bonneville", "speedtriple", "streettriple", "crf230", "crf250", "crf450", 
    "yz125", "yz250", "kx250", "kx450", "exc250", "exc300", "klx", "drz", "fly150", 
    "sk150", "haojue", "comet250", "mirage250", "vespa", "lambretta", "nx400", "nx4", 
    "falcon400", "falcon", "xrv750", "africatwin", "transalp", "xl700", "xl700v", "nc750", 
    "nc750x", "cb500x", "cb500f", "cb650r", "cbr650r", "cb1000r", "cbr600rr", "cbr1000rr", 
    "fireblade", "vt600", "shadow600", "shadow750", "vtx1800", "goldwing", "gl1800", 
    "ctx700", "fmx650", "slr650", "dominator", "bros125", "bros150", "bros160", "nxr150", 
    "nxr160", "xre190", "xre300", "xr250", "tornado250", "titan125", "titan150", "titan160", 
    "fan125", "fan150", "fan160", "start150", "start160", "cargo125", "cargo150", "cargo160", 
    "job150", "ybr125", "factor125", "factor150", "fazer250", "fazer600", "fz6", "fz1", "fz8", 
    "xj6n", "xj6f", "mt01", "mt03", "mt07", "mt09", "tritown", "niken", "tmax", "tmax530", 
    "xmax250", "nmax160", "neo115", "neo125", "crypton115", "vmax", "virago", "virago250", 
    "virago535", "dragstar", "xv250", "xv535", "xvs650", "midnightstar", "r15", "r25", "r3", 
    "r6", "r1", "s1000r", "s1000xr", "f700gs", "f750gs", "f800r", "k1300", "k1600", "r18", 
    "g310r", "g310gs", "rninet", "er6n", "z750", "z800", "z900", "z1000", "zx6r", "zx10r", 
    "zx14", "klx250", "klx450", "dtracker", "versys300", "versys650", "versys1000", "vulcan650", 
    "vulcan900", "vulcan1500", "intruder125", "intruder250", "intruder800", "intruder1500", 
    "m800", "m1500", "c1500", "savage650", "gs500", "bandit", "bandit600", "bandit650", 
    "bandit1200", "bandit1250", "sv650", "vstrom650", "vstrom1000", "hayabusa1300", "gsxr750", 
    "gsxr1000", "tl1000", "katana", "dr650", "dr800", "drz400", "sky125", "fly125", "fly150", 
    "stx200", "sk150", "ex250", "hunter125", "max150", "scooter150", "scooter300", "cityclass", 
    "next250", "next300", "horizon150", "horizon250", "roadwin", "kymco", "downtown300", "people300", 
    "agility", "ak550", "tricity", "honda 125", "honda 150", "honda 160", "honda 190", "honda 250", 
    "honda 300", "honda 400", "honda 450", "honda 500", "honda 600", "honda 650", "honda 750", 
    "honda 1000", "honda 1100", "honda 1200", "honda 1250", "yamaha 125", "yamaha 150", "yamaha 160", 
    "yamaha 190", "yamaha 250", "yamaha 300", "yamaha 600", "yamaha 660", "yamaha 700", "yamaha 900", 
    "yamaha 1000", "suzuki 125", "suzuki 150", "suzuki 650", "suzuki 750", "suzuki 1000", "suzuki 1300", 
    "bmw f800", "bmw f850", "bmw g310", "bmw r1200", "bmw r1250", "bmw s1000", "kawasaki 300", 
    "kawasaki 400", "kawasaki 650", "kawasaki 900", "kawasaki 1000", "mxf", "honda xr", "honda xt",
    "honda cg", "honda xlr", "honda titan", "honda xtz", "honda cg", "titan 125", "honda nx",
    "cg 125", "cg 150", "titan", "barco", "lancha", "baú", "refrigerado", "fusca", "bike",
    "Traxx", "monkey", "d10", "nautica", "fish", "250f", "dafra", "sherco", "harley", "barco",
    "retroescavadeira", "trator", "escavadeira", "case", "valtra", "1313", "13x13", "carregadeira", 
    "Jet sky", "einfield", "1421", "d20", "c10", "f-4000", "f4000", "f 4000", "f-4000", "f4000", "f 4000",
    "kombi", "onibus", "microonibus", "ônibus", "microônibus", "sprinter", "triumph", "iveco", "deere",
    "nl10", "livina", "h-100", "agrale", "hawk", "1313", "retirada de peças", "sucata", "willys", "s 1000", 
    "S1000", "jcb", "gs ", " f 800", " f800", "f 850", "f850", "cbx", "master", "hummer", "A.P.C Motor Company",
    "nxr160bros", "massey", "Ferguson", "topic", "parcelado", "boleto", "parcelas", "truck", "fh 500", "fh500",
    "xadv", "esd", "sh150i", "motobi", "r 1250", "f 850", "cmx", "f 800", "nc 750x abs", "nc 750x", "750x",
    "r1250", "gw250", "f700", "today", "prestações", "750", "1935", "veraneio", "6 160", "volare", "foutrax", 
    "changlin", "parcelas", "leilao", "leilão", "quitacao", "quitação"
]

# Adicionar palavras relacionadas a motos no filtro
BLOCKED_WORDS = [
    "cg",
    "xr",
    "fan",
    "biz",
    "bros",
    "cb",
    "xre",
    "nxr",
    "ybr",
    "mt",
    "fazer",
    "twister",
    "titan",
    "cr",
    "G310",
    "F800",
    "F850",
    "R1200",
    "R1250",
    "S1000",
    "DT180",
    "DT200",
    "FACTOR",
    "LANDER",
    "XT660",
    "TENERE",
    "TDM",
    "CROSSER",
    "INTRUDER",
    "YES",
    "CHOPPER",
    "NMAX",
    "PCX",
    "XMAX",
    "SH",
    "ADV",
    "Z400",
    "Z900",
    "NINJA",
    "VERSYS",
    "VULCAN",
    "TIGER",
    "BONNEVILLE",
    "SCRAMBLER",
    "GSX",
    "V-STROM",
    "BOULEVARD",
    "BURGMAN",
    "POP",
    "LEAD",
    "DAELIM",
    "A.P.C Motor Company",
    "A.P.C",
    "company",
    "buell",
    "MTC",
    "bull", 
    "start",
    "ml",
    "elite", 
    "f850",
    "g 310",
    "r 1250"
]

# Garantir que essas palavras sejam carregadas no sistema de bloqueio
_BLOCKED_WORDS_CACHE = None

def get_all_blocked_words() -> list[str]:
    """
    Retorna lista unificada de palavras bloqueadas já normalizadas.
    Utiliza apenas listas internas (BLOCKED_WORDS_JSON + BLOCKED_WORDS).
    """

    global _BLOCKED_WORDS_CACHE

    if _BLOCKED_WORDS_CACHE is not None:
        return _BLOCKED_WORDS_CACHE

    # Unifica todas as palavras
    combined = BLOCKED_WORDS_JSON + BLOCKED_WORDS

    # Normaliza e remove duplicadas
    normalized = {normalize_text(word) for word in combined if word}

    _BLOCKED_WORDS_CACHE = list(normalized)

    print(f"[FILTER_INIT] Total palavras bloqueadas: {len(_BLOCKED_WORDS_CACHE)}")

    return _BLOCKED_WORDS_CACHE

MOTO_STRONG_PATTERN = re.compile(
    r"\b(cbx|f800|f850|s1000|hornet|xre|xtz|cbr|ninja|titan|bros|cg)\b",
    re.IGNORECASE
)

# Padrões que exigem contexto do título inteiro (não buscam palavras isoladas)
MOTO_CONTEXT_PATTERN = re.compile(
    # BMW motos: R 1200, R 1250, F 800, F 850, G 310, S 1000, K 1600, etc.
    r"bmw\s+[rfgsk]\s*\d{3,4}"
    # Honda motos: XL (linha off-road), XRV, Africa Twin, Transalp
    r"|honda\s+xl\b"
    r"|honda\s+xrv\b"
    r"|honda\s+africa\s+twin"
    r"|honda\s+transalp",
    re.IGNORECASE
)

def is_motorcycle_strong(title: str) -> bool:
    if not title:
        return False
    return bool(MOTO_STRONG_PATTERN.search(title)) or bool(MOTO_CONTEXT_PATTERN.search(title))

def is_valid_listing(listing: dict) -> bool:
    """
    Verifica se o título da listagem contém palavras bloqueadas.

    Args:
        listing (dict): Dicionário contendo os dados da listagem.

    Returns:
        bool: True se a listagem for válida, False caso contrário.
    """
    title = listing.get("title", "")
    blocked_words = get_all_blocked_words()

    if is_blocked_title(title, blocked_words):
        print(f"[FILTER DEBUG] Rejeitado: {title}")
        return False

    if is_motorcycle_strong(title):
        print(f"[FILTER MOTO] Rejeitado: {title}")
        return False

    return True