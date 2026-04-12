import sqlite3
import re
from pathlib import Path
from .brand_alias import MARCAS_ALIAS, MARCAS_BASE

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "fipe_official.db"


STOPWORDS_MODELO = {
    "1", "1.0", "1.3", "1.4", "1.5", "1.6", "1.8", "2.0", "2.4", "3.0",
    "8v", "16v", "flex", "gasolina", "diesel", "alcool",
    "mec", "manual", "aut", "automatico", "cvt",
    "4x2", "4x4", "turbo", "tsi", "mpi"
}


def normalize(text: str):
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'[^a-z0-9 ]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


class FipeCodeResolver:

    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row

    def resolve(self, title: str, year: int):

        if not title or not year:
            return None

        title_norm = normalize(title)

        marca_fipe = self._identificar_marca(title_norm)
        if not marca_fipe:
            return None

        cursor = self.conn.execute(
            """
            SELECT codigo_fipe, modelo, valor
            FROM fipe
            WHERE ano_modelo = ?
              AND lower(marca) LIKE ?
            """,
            (year, f"%{marca_fipe}%")
        )

        candidates = cursor.fetchall()
        if not candidates:
            return None

        melhor_score = 0
        melhor_valor = None
        melhor_codigo = None

        for row in candidates:
            modelo_norm = normalize(row["modelo"])
            tokens = [t for t in modelo_norm.split() if t not in STOPWORDS_MODELO]

            if not tokens:
                continue

            score = 0

            if tokens[0] in title_norm:
                score += 2

            for token in tokens[1:]:
                if token in title_norm:
                    score += 1

            if score == 0:
                continue

            if (
                score > melhor_score or
                (score == melhor_score and (melhor_valor is None or row["valor"] < melhor_valor))
            ):
                melhor_score = score
                melhor_valor = row["valor"]
                melhor_codigo = row["codigo_fipe"]

        numeros_versao = re.findall(r"\b\d{3}\b", title_norm)

        if not numeros_versao:
            menor = min(candidates, key=lambda x: x["valor"])
            return menor["codigo_fipe"]

        if melhor_score >= 2:
            return melhor_codigo

        return None

    def _identificar_marca(self, title_norm):

        for alias, nome_fipe in MARCAS_ALIAS.items():
            if alias in title_norm:
                return nome_fipe

        marcas_ordenadas = sorted(MARCAS_BASE, key=len, reverse=True)

        for marca in marcas_ordenadas:
            if marca.replace("-", " ") in title_norm:
                return marca

        return None