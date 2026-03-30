import sqlite3
import re
import os
import time
import requests

DB_PATH = "data/fipe_official.db"
FIPE_API = "https://parallelum.com.br/fipe/api/v1"

# Mapeamento de marca normalizada → padrão SQL LIKE para busca no banco
# O banco armazena: "VW - VolksWagen", "GM - Chevrolet", "Chevrolet", "Mercedes-Benz", etc.
BRAND_SQL_MAP = {
    "volkswagen":    "%volkswagen%",
    "vw":            "%volkswagen%",
    "chevrolet":     "%chevrolet%",
    "gm":            "%chevrolet%",
    "mercedes benz": "%mercedes-benz%",
    "mercedes":      "%mercedes-benz%",
    "bmw":           "%bmw%",
    "fiat":          "%fiat%",
    "ford":          "%ford%",
    "toyota":        "%toyota%",
    "honda":         "%honda%",
    "hyundai":       "%hyundai%",
    "renault":       "%renault%",
    "nissan":        "%nissan%",
    "jeep":          "%jeep%",
    "audi":          "%audi%",
    "kia":           "%kia%",
    "kia motors":    "%kia%",
    "mitsubishi":    "%mitsubishi%",
    "peugeot":       "%peugeot%",
    "citroen":       "%citr%",
    "citro\u00ebn":  "%citr%",
    "volvo":         "%volvo%",
    "land rover":    "%land rover%",
    "ram":           "%ram%",
    "chery":         "%chery%",
    "caoa chery":    "%chery%",
}

# Tokens a remover do título para extrair o modelo (por marca)
BRAND_STOP = {
    "volkswagen":    {"vw", "volkswagen", "volks"},
    "vw":            {"vw", "volkswagen", "volks"},
    "chevrolet":     {"chevrolet", "gm", "chevy"},
    "gm":            {"chevrolet", "gm", "chevy"},
    "mercedes benz": {"mercedes", "benz"},
    "mercedes":      {"mercedes", "benz"},
    "mercedes-benz": {"mercedes", "benz"},
    "bmw":           {"bmw"},
    "fiat":          {"fiat"},
    "ford":          {"ford"},
    "toyota":        {"toyota"},
    "honda":         {"honda"},
    "hyundai":       {"hyundai"},
    "renault":       {"renault"},
    "nissan":        {"nissan"},
    "jeep":          {"jeep"},
    "audi":          {"audi"},
    "kia":           {"kia"},
    "kia motors":    {"kia"},
    "mitsubishi":    {"mitsubishi"},
}

# Alternativas de busca para modelos cujo nome muda após normalização
# Ex: "HRV" no título → DB armazena "HR-V" → token normalizado é "hr"
# Ex: "C180" → DB tem "C-180" → SQL '%c%' + _row_matches filtra por token "c"+"180"
MODEL_FALLBACKS = {
    "hrv":  ["hr"],       # Honda HR-V
    "c180": ["c"],        # Mercedes C-180
    "c200": ["c"],
    "c300": ["c"],
    "a200": ["a 200"],    # Mercedes Classe A 200 (busca '%a 200%')
    "a250": ["a 250"],
}

# Modelos onde o nome no anúncio difere do nome na FIPE.
# Ao não encontrar exatamente, tenta os aliases antes de ir à API.
# Cada entrada: token_normalizado → lista de termos SQL alternativos
MODEL_NAME_ALIASES = {
    # Fiat Siena (versão pré-2012) → Grand Siena (nome FIPE a partir de ~2013)
    # Quando alguém anuncia "Siena 2022", o carro na FIPE é "Grand Siena"
    "siena": ["%grand%siena%"],
    # Mitsubishi ASX → banco local tem só versões a partir de 2017
    # Se não achar no ano exato, tenta o modelo genérico (já tratado pelo fallback de anos)
}

# Subfamílias a excluir quando buscando pelo modelo base.
# Evita retornar um veículo de família diferente que começa com o mesmo token.
# Ex: busca "hilux" não deve retornar "Hilux SW4" (outro veículo distinto)
MODEL_SUBFAMILY_EXCLUDE = {
    "hilux": {"sw4"},
    # Evita "Grand Siena" quando buscando "Siena"
    "siena": {"grand"},
    # Evita "Pajero Full / Sport / TR4" quando buscando "Pajero" genérico sem qualificador
    # (aplicado opcionalmente via lógica de título)
}

# Prefixos de subfamília: tokens que aparecem ANTES do modelo base no nome do banco.
# Ex: "Grand Siena" → o token "grand" precede "siena" → deve ser excluído.
MODEL_PREFIX_EXCLUDE = {
    "siena": {"grand"},
}

# Carrocerias alternativas: só são consideradas se explicitamente mencionadas no título.
# Garante que um anúncio genérico nunca receba FIPE de perua, conversível ou cabine dupla.
BODY_VARIANT_TERMS = frozenset([
    "cabriolet", "cabrio", "roadster", "spider", "spyder",  # conversíveis
    "cc",                                                    # Peugeot 307 CC / 308 CC (conversível)
    "variant", "avant", "touring", "combi",                 # peruas / station wagons
    # "sw" removido: pode ser confundido com iniciais (ex: "SW4" já coberto por MODEL_SUBFAMILY_EXCLUDE)
    # "cd" / "ce" removidos: Cabine Dupla / Estendida em pickups — diferença pequena e todos S10/Ranger são CD
    # versões esportivas de alto valor que nunca devem ser matched por padrão
    "evolution", "evol", "evo",                              # Mitsubishi Lancer Evolution
    "ralliart",                                              # Mitsubishi Lancer Ralliart
    "m",                                                     # BMW X5 M, M3, M5 (token isolado)
    "rs", "gts", "gt3", "gt4",                              # Porsche esportivos
    "svr", "svj", "performante",                            # Land Rover / Lamborghini esportivos
    # top-trims que inflam a FIPE vs a versão entrada-de-linha do mesmo modelo.
    # Se o anúncio não mencionar explicitamente o trim, usamos a versão mais barata disponível.
    "especial",   # Hyundai Tucson Ed. Especial, outros Ed. Especial
    "limited",    # Jeep Compass/Renegade/Commander Limited, Hyundai Limited
    "executive",  # Toyota Corolla Executive, versões executivas genéricas
    "exclusive",  # Renault/Peugeot versões Exclusive
    # divisões de performance de fabricante — nunca devem ser matched por padrão
    "amg",        # Mercedes-AMG (C-450 AMG, C-63 AMG, etc.)
    "nismo",      # Nissan NISMO
    # ── Trims VW: diferença de FIPE significativa entre versões ─────────────
    "sense",       # T-Cross/Polo Sense PCD — valor ~15-20% menor que Highline
    "comfortline", # VW linha intermediária
    "highline",    # VW linha top
    "sportline",   # VW linha esportiva
    "trendline",   # VW linha base (alguns modelos)
    # ── Trims mercado brasileiro ─────────────────────────────────────────────
    "premier",     # Chevrolet Onix/Tracker Premier (topo de linha)
    "diamond",     # Hyundai Creta Diamond (topo)
    "platinum",    # Hyundai versões Platinum
    "trekking",    # Fiat Pulse/Fastback Trekking
    "volcano",     # Fiat Pulse/Fastback Volcano (topo)
    "overland",    # Jeep Compass/Commander Overland (topo)
    "summit",      # Jeep Commander Summit (topo)
    "trailhawk",   # Jeep Compass Trailhawk
    "titanium",    # Ford Territory/EcoSport/Ranger Titanium (topo)
    "iconic",      # Renault Kardian/Captur Iconic
    "intens",      # Renault Captur/Stepway Intens
])

# Modelos com hífen cujo token normalizado é ambíguo.
# "T-Cross" → normalize → "t cross" → token[0] = "t" (muito genérico)
# Mapeamos o token composto para o padrão SQL correto.
HYPHENATED_MODELS = {
    # token_normalizado_sem_espaco -> (termo_sql_like, token_para_row_matches)
    "tcross":  ("t%cross%",  "tcross"),
    "hrv":     ("hr%v%",     "hrv"),
    "crv":     ("cr%v%",     "crv"),
    "crhatch": ("cr%",       "cr"),
    "s10":     ("s10%",      "s10"),   # S-10 → "s 10" → tokens = ["s","10"]
    "s 10":    ("s10%",      "s10"),
}


class FipeEngineV2:

    def __init__(self):

        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM fipe")
        count = cur.fetchone()[0]

        print(f"[FIPE] Base oficial carregada: {count} registros.")

    # -----------------------------------------------------

    def normalize(self, text):
        """Limpeza básica: minúsculas, remove especiais, normaliza espaços."""
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r"[^a-z0-9 ]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _brand_sql(self, marca):
        """Retorna o padrão SQL LIKE para buscar esta marca no banco."""
        key = self.normalize(marca)
        if key in BRAND_SQL_MAP:
            return BRAND_SQL_MAP[key]
        # Tenta pela primeira palavra (ex: 'mercedes benz' → 'mercedes')
        first = key.split()[0] if key else key
        if first in BRAND_SQL_MAP:
            return BRAND_SQL_MAP[first]
        # Fallback seguro: usa apenas caracteres alfanuméricos do primeiro token
        safe = re.sub(r"[^a-z0-9]", "", first)
        return f"%{safe}%" if safe else "%"

    def _brand_stop(self, marca):
        """Retorna conjunto de tokens a ignorar ao extrair modelo do título."""
        key = self.normalize(marca)
        if key in BRAND_STOP:
            return BRAND_STOP[key]
        first = key.split()[0] if key else key
        return BRAND_STOP.get(first, {first})

    # -----------------------------------------------------

    def parse_fipe_value(self, value):

        if value is None:
            return 0.0

        value = str(value)
        value = value.replace("R$", "").replace(".", "").replace(",", ".").strip()

        try:
            return float(value)
        except ValueError:
            return 0.0

    # -----------------------------------------------------

    def extract_model_from_title(self, titulo, marca):

        titulo_norm = self.normalize(titulo)
        stop = self._brand_stop(marca) | {
            "vw", "gm", "chevrolet", "fiat", "ford", "honda", "toyota",
            "hyundai", "renault", "nissan", "bmw", "mercedes", "benz",
            "volkswagen", "jeep", "audi", "kia", "mitsubishi", "peugeot",
        }

        for token in titulo_norm.split():
            if token not in stop and not (token.isdigit() and len(token) == 4):
                return token

        return titulo_norm.split()[0] if titulo_norm else None

    # -----------------------------------------------------

    def save_model(self, marca, modelo, ano_modelo, valor):

        if valor is None or valor <= 0:
            return

        cur = self.conn.cursor()

        cur.execute("""
            INSERT INTO fipe
            (marca, modelo, ano_modelo, valor, referencia)
            VALUES (?, ?, ?, ?, 'api')
        """, (marca, modelo, ano_modelo, valor))

        self.conn.commit()

    # -----------------------------------------------------

    def _api_get(self, url, timeout=5):
        """GET com retry automático em 429 (rate limit) e erros de rede.
        Timeout reduzido (5s) e apenas 2 tentativas para não bloquear threads por minutos.
        """
        delays = [0.5, 1]
        for attempt, delay in enumerate(delays):
            try:
                resp = requests.get(url, timeout=timeout)
                if resp.status_code == 200:
                    return resp
                if resp.status_code == 429:
                    print(f"[FIPE API] rate limit (429), aguardando {delay}s ...")
                    time.sleep(delay)
                    continue
                print(f"[FIPE API] HTTP {resp.status_code} em {url}")
                return None
            except requests.RequestException as e:
                if attempt < len(delays) - 1:
                    print(f"[FIPE API] erro de rede ({e}), tentativa {attempt+2} em {delay}s ...")
                    time.sleep(delay)
                else:
                    print(f"[FIPE API ERROR] {e}")
                    return None
        return None

    def _model_match_api(self, nome_api, modelo_norm):
        """Verifica se um modelo da API corresponde ao modelo_norm buscado.
        Compara tokens normalizados E versão sem espaços para cobrir casos como:
        - 'hrv' matches 'HR-V LX...' → normalize → 'hr v lx...' → sem espaços → 'hrlx...' contains 'hr'
          Mas 'hrv' in 'hrv...' (sem espaços de 'hr v') → True
        - 'a200' matches 'Classe A 200...' → 'classea200...' contains 'a200' → True
        """
        nome_norm  = self.normalize(nome_api)
        nome_dense = nome_norm.replace(" ", "")          # remove todos os espaços
        mod_dense  = modelo_norm.replace(" ", "")        # modelo sem espaços

        if modelo_norm in nome_norm:
            return True
        if nome_norm.startswith(modelo_norm):
            return True
        if mod_dense and mod_dense in nome_dense:
            return True
        return False

    def update_model_from_api(self, marca, modelo):

        if len(modelo) < 2:
            return

        print(f"[FIPE API] Atualizando modelo: {marca} {modelo}")

        resp = self._api_get(f"{FIPE_API}/carros/marcas")
        if not resp:
            print("[FIPE API] erro ao buscar marcas")
            return

        marcas_api = resp.json()
        marca_id = None
        marca_pattern = self._brand_sql(marca).replace("%", "").strip()

        for m in marcas_api:
            nome_lower = m["nome"].lower()
            if marca_pattern in nome_lower or nome_lower.replace("-", " ") == marca_pattern.replace("-", " "):
                marca_id = m["codigo"]
                break

        if not marca_id:
            print(f"[FIPE API] marca não encontrada: {marca}")
            return

        resp2 = self._api_get(f"{FIPE_API}/carros/marcas/{marca_id}/modelos")
        if not resp2:
            return

        modelos_api = resp2.json().get("modelos", [])
        modelo_norm = self.normalize(modelo)

        # Termos alternativos para matching (ex: "hrv" → também testa "hr")
        alt_terms = [modelo_norm] + [
            self.normalize(alt)
            for alt in MODEL_FALLBACKS.get(modelo_norm, [])
        ]

        for m_item in modelos_api:
            if any(self._model_match_api(m_item["nome"], term) for term in alt_terms):
                mod_id = m_item["codigo"]
                resp_anos = self._api_get(f"{FIPE_API}/carros/marcas/{marca_id}/modelos/{mod_id}/anos")
                if not resp_anos:
                    continue
                for ano_item in resp_anos.json():
                    resp_dado = self._api_get(
                        f"{FIPE_API}/carros/marcas/{marca_id}/modelos/{mod_id}/anos/{ano_item['codigo']}"
                    )
                    if resp_dado:
                        dado = resp_dado.json()
                        self.save_model(
                            marca, m_item["nome"],
                            int(dado.get("AnoModelo", 0)),
                            self.parse_fipe_value(dado.get("Valor"))
                        )

    # -----------------------------------------------------

    def _row_matches(self, row_modelo, search_base, exclude_second=None, exclude_prefix=None):
        """Verifica se o modelo do banco corresponde ao modelo buscado.
        Trata casos especiais como 'C-180' vs 'c180', 'HR-V' vs 'hrv', 'Classe A 200' vs 'a200'.
        exclude_second: tokens que, na 2ª posição do banco, invalidam o match.
          Ex: {'sw4'} → não retorna 'Hilux SW4' quando buscando 'hilux'.
        exclude_prefix: tokens que, na 1ª posição do banco, invalidam o match.
          Ex: {'grand'} → não retorna 'Grand Siena' quando buscando 'siena'.
        """
        tokens = self.normalize(row_modelo).split()
        if not tokens:
            return False
        row_first  = tokens[0]
        row_first2 = "".join(tokens[:2]) if len(tokens) >= 2 else row_first

        # Rejeitar modelos com prefixo diferente antes do token buscado
        # Ex: "Grand Siena" → row_first="grand" ≠ "siena" → rejeita quando buscando "siena"
        if exclude_prefix and row_first in exclude_prefix:
            return False

        # Rejeitar subfamílias explicitamente excluídas (segundo token)
        if exclude_second and len(tokens) >= 2 and tokens[1] in exclude_second:
            return False

        # Comparação direta e prefixo
        if row_first == search_base:
            return True
        # Para tokens muito curtos (1 char), exige match exato do primeiro token.
        # Evita que busca por "c" (Mercedes C-class) bata com "Classe A/B", "CLA", "CLS".
        if len(search_base) == 1:
            return False
        if row_first.startswith(search_base) or (search_base.startswith(row_first) and len(row_first) >= 2):
            return True
        # Dois tokens concatenados (ex: 'c'+'180' = 'c180', 's'+'10' = 's10')
        if row_first2 == search_base or row_first2.startswith(search_base):
            return True
        if search_base.startswith(row_first2) and len(row_first2) >= 2:
            return True
        # Três tokens concatenados: apenas match exato ou prefixo — nunca subcadeia solta.
        # Bug anterior: "siena" in "grandsiena1" = True → falso positivo com Grand Siena.
        if len(tokens) >= 3 and len(search_base) >= 4:
            row_first3 = "".join(tokens[:3])
            if row_first3 == search_base or row_first3.startswith(search_base):
                return True
            if search_base.startswith(row_first3) and len(row_first3) >= 3:
                return True
        return False

    def search(self, marca, titulo, ano):

        marca_sql  = self._brand_sql(marca)
        brand_stop = self._brand_stop(marca)
        titulo_norm = self.normalize(titulo)

        # Remove tokens da marca e anos (4 dígitos) do título
        tokens = [
            t for t in titulo_norm.split()
            if t not in brand_stop and not (t.isdigit() and len(t) == 4)
        ]

        if not tokens:
            return None

        modelo_base     = tokens[0]
        modelo_composto = " ".join(tokens[:2]) if len(tokens) >= 2 else modelo_base

        # Detectar modelos hifenados: "T-Cross" → titulo_norm = "t cross" → tokens = ["t","cross"]
        # O token "t" é muito genérico; precisamos usar o par "t cross" como token primário.
        modelo_composto_dense = modelo_composto.replace(" ", "")  # "tcross", "s10"
        if modelo_composto_dense in HYPHENATED_MODELS:
            sql_pattern_override, row_match_base = HYPHENATED_MODELS[modelo_composto_dense]
            modelo_base    = row_match_base       # usado no _row_matches
            modelo_composto = row_match_base
        elif modelo_base in HYPHENATED_MODELS:
            sql_pattern_override, row_match_base = HYPHENATED_MODELS[modelo_base]
            modelo_base = row_match_base
        else:
            sql_pattern_override = None

        cur = self.conn.cursor()
        exclude_tokens = MODEL_SUBFAMILY_EXCLUDE.get(modelo_base)
        exclude_prefix = MODEL_PREFIX_EXCLUDE.get(modelo_base)

        title_words = set(titulo_norm.split())

        # Tokens de versão/trim do título para pontuar candidatos FIPE.
        # São os tokens após o modelo base (não-marca, não-ano-4d, ≥3 chars).
        # Exclui apenas anos de 4 dígitos — "200", "250", "320" são engine codes, não anos.
        _model_slots = 2 if modelo_composto_dense in HYPHENATED_MODELS else 1
        _trim_tokens = [
            t for t in tokens[_model_slots:]
            if len(t) >= 3 and not (t.isdigit() and len(t) == 4)
        ]

        def query_local(termo, strict=True, anos=None, strict_body=True, sql_pattern=None,
                        bypass_prefix_exclude=False, contains_match=False):
            if anos is None:
                anos = [ano]
            if sql_pattern:
                pattern = sql_pattern
            else:
                pattern = f"{termo}%" if strict else f"%{termo}%"
            ep = None if bypass_prefix_exclude else exclude_prefix
            for year in anos:
                rows = cur.execute("""
                    SELECT modelo, ano_modelo, valor
                    FROM fipe
                    WHERE lower(marca) LIKE ? AND lower(modelo) LIKE ? AND ano_modelo = ? AND valor > 0
                    ORDER BY valor ASC
                """, (marca_sql, pattern, year)).fetchall()

                candidates = []
                for row in rows:
                    if strict_body:
                        # Pula carrocerias/trims não mencionados no título
                        model_words = set(self.normalize(row["modelo"]).split())
                        if BODY_VARIANT_TERMS & model_words - title_words:
                            continue
                    if contains_match:
                        if modelo_base in self.normalize(row["modelo"]):
                            candidates.append(row)
                    else:
                        if self._row_matches(
                            row["modelo"], modelo_base,
                            exclude_second=exclude_tokens,
                            exclude_prefix=ep,
                        ):
                            candidates.append(row)

                if not candidates:
                    continue

                # Pontua candidatos pelo overlap de trim com o título.
                # Se algum tiver score > 0, retorna o de maior score (e mais barato entre empatados).
                if _trim_tokens:
                    def _tscore(r):
                        fn = set(self.normalize(r["modelo"]).split())
                        return sum(1 for t in _trim_tokens if t in fn)
                    scored = [(_tscore(r), r) for r in candidates]
                    best_score, _ = max(scored, key=lambda x: x[0])
                    if best_score > 0:
                        # Entre empatados, o mais barato (conservador)
                        top = [r for s, r in scored if s == best_score]
                        winner = min(top, key=lambda r: float(r["valor"]))
                        return {
                            "fipe_model": winner["modelo"],
                            "fipe_price": float(winner["valor"]),
                            "ano_modelo":  int(winner["ano_modelo"]),
                        }

                # Sem match de trim (ou título sem tokens de trim): retorna o mais barato
                cheapest = candidates[0]  # já ordenado ASC
                return {
                    "fipe_model": cheapest["modelo"],
                    "fipe_price": float(cheapest["valor"]),
                    "ano_modelo":  int(cheapest["ano_modelo"]),
                }
            return None

        def search_for_years(anos):
            """Todas as tentativas para uma lista de anos (banco local)."""
            # modelo composto no início (ou padrão SQL override para hifenados)
            if sql_pattern_override:
                res = query_local(modelo_base, anos=anos, sql_pattern=sql_pattern_override)
                if res: return res
            else:
                res = query_local(modelo_composto, anos=anos)
                if res: return res
                # modelo base no início
                res = query_local(modelo_base, anos=anos)
                if res: return res
                # busca elástica (ex: "%320%" para "320iA")
                res = query_local(modelo_base, strict=False, anos=anos)
                if res: return res
                # fallback de nomes especiais: "hrv"→"hr", "a200"→"a 200", etc.
                for alt in MODEL_FALLBACKS.get(modelo_base, []):
                    res = query_local(alt, strict=False, anos=anos)
                    if res: return res
                # alias de nomes alternativos: "siena" → tenta "%grand%siena%"
                for alias_pattern in MODEL_NAME_ALIASES.get(modelo_base, []):
                    res = query_local(modelo_base, anos=anos, sql_pattern=alias_pattern,
                                      strict_body=True, contains_match=True)
                    if res: return res
            # Fallback: título sem trim reconhecível e banco só tem versões nomeadas.
            # Aceita qualquer versão (mais conservador: retorna a mais barata).
            if sql_pattern_override:
                res = query_local(modelo_base, anos=anos, sql_pattern=sql_pattern_override, strict_body=False)
            else:
                res = query_local(modelo_composto, anos=anos, strict_body=False)
                if not res:
                    res = query_local(modelo_base, anos=anos, strict_body=False)
            if res:
                print(f"[FIPE TRIM FALLBACK] Versão não identificada no título — usando mais barata: {res['fipe_model']}")
                return res

        # Trims do título que estão em BODY_VARIANT_TERMS — exigem match explícito na FIPE.
        # Se o título menciona "Sense", só aceitamos uma FIPE que também mencione "Sense".
        _required_trims = BODY_VARIANT_TERMS & set(titulo_norm.split())

        def _trim_ok(fipe_model: str) -> bool:
            """Retorna True se os trims obrigatórios do título batem com a versão FIPE."""
            if not _required_trims:
                return True
            m_words = set(self.normalize(fipe_model).split())
            # Todos os trims exigidos pelo título devem estar na versão FIPE
            return _required_trims.issubset(m_words)

        def search_exact_year():
            """Tentativas com ano exato."""
            return search_for_years([ano])

        # 1ª tentativa: banco local com ano exato
        res = search_exact_year()
        if res and _trim_ok(res["fipe_model"]): return res

        # 2ª tentativa: anos próximos (±2) — antes de chamar a API
        # Útil quando o banco tem o modelo mas não para o ano exato (ex: S10 2023, ASX 2012)
        anos_proximos = [ano - 1, ano + 1, ano - 2, ano + 2]
        res = search_for_years(anos_proximos)
        if res and _trim_ok(res["fipe_model"]): return res

        # 3ª tentativa: API — baixa toda a família do modelo (todos os anos/versões)
        # e atualiza o banco; depois repete a busca com ano exato.
        self.update_model_from_api(marca, modelo_base)

        res = search_exact_year()
        if res and _trim_ok(res["fipe_model"]): return res

        # 4ª tentativa: anos próximos após atualização da API
        res = search_for_years(anos_proximos)
        if res and _trim_ok(res["fipe_model"]): return res

        if res:
            # Encontrou algo mas o trim não bate — falso positivo, recusa o match
            print(f"[FIPE TRIM MISMATCH] Título pede '{_required_trims}' mas só há '{res['fipe_model']}' — descartado")
            return None

        print(f"[FIPE NÃO ENCONTRADA] {titulo}")
        return None

    def get_price(self, marca, titulo, ano):
        """Alias de search() — mantém compatibilidade com callers externos."""
        return self.search(marca, titulo, ano)

    # -----------------------------------------------------

    def close(self):
        self.conn.close()