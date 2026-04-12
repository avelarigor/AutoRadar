# fipe/token_manager.py

import time
import random
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TokenState:
    token: str
    requests_ok: int = 0
    requests_fail: int = 0
    cooldown_until: float = 0.0  # epoch seconds


class TokenManager:
    """
    - Round-robin entre tokens
    - Se um token tomar 429, entra em cooldown
    - Se ocorrer erro temporário (5xx/522 etc), aplica backoff e pode alternar token
    """

    def __init__(self, tokens: List[str]):
        if not tokens:
            raise ValueError("Nenhum token informado em fipe_tokens.TOKENS")
        self.tokens: List[TokenState] = [TokenState(t) for t in tokens]
        self._idx = 0
        print(f"🔐 Token Manager inicializado ({len(self.tokens)} tokens)")

    def _now(self) -> float:
        return time.time()

    def get_token(self) -> str:
        # tenta achar um token fora de cooldown
        n = len(self.tokens)
        for _ in range(n):
            st = self.tokens[self._idx]
            self._idx = (self._idx + 1) % n
            if st.cooldown_until <= self._now():
                return st.token

        # se todos estão em cooldown, espera o menor cooldown
        soonest = min(self.tokens, key=lambda s: s.cooldown_until)
        wait_s = max(1.0, soonest.cooldown_until - self._now())
        print(f"⏳ Todos os tokens em cooldown. Aguardando {int(wait_s)}s...")
        time.sleep(wait_s)
        return soonest.token

    def mark_ok(self, token: str) -> None:
        for st in self.tokens:
            if st.token == token:
                st.requests_ok += 1
                return

    def mark_fail(self, token: str) -> None:
        for st in self.tokens:
            if st.token == token:
                st.requests_fail += 1
                return

    def cooldown(self, token: str, seconds: int) -> None:
        for st in self.tokens:
            if st.token == token:
                # jitter pra não “bater junto”
                jitter = random.randint(0, 2)
                st.cooldown_until = max(st.cooldown_until, self._now() + seconds + jitter)
                return

    def stats_str(self) -> str:
        parts = []
        for i, st in enumerate(self.tokens, start=1):
            cd = int(max(0, st.cooldown_until - self._now()))
            parts.append(f"T{i}: ok={st.requests_ok} fail={st.requests_fail} cd={cd}s")
        return " | ".join(parts)


# instância global
try:
    from .fipe_tokens import TOKENS
    token_manager = TokenManager(TOKENS)
except Exception as e:
    token_manager = None
    print(f"⚠️ Token Manager NÃO inicializado: {e}")