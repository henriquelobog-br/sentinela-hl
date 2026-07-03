"""Sentinela HL — FakeLLMClient: dublê de teste do LLMClient. Sem rede."""
from __future__ import annotations
from typing import Optional
from sentinela.clients.base import LLMTimeout


class FakeLLMClient:
    def __init__(self, response: str = "", *, raise_timeout: bool = False):
        self._response = response
        self._raise_timeout = raise_timeout
        self.last_extra: Optional[dict] = None

    def complete(self, *, system: str, user: str, temperature: float = 0.0,
                 max_tokens: int = 1024, extra: Optional[dict] = None) -> str:
        self.last_extra = extra
        if self._raise_timeout:
            raise LLMTimeout("timeout simulado")
        return self._response
