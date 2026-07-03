"""
Sentinela HL — OpenRouterClient (Documento 113.2).

Implementa LLMClient via OpenRouter. Modelo por variável de ambiente; a
aplicação nunca conhece o nome do modelo. Fallback primary → fallback.
`extra` faz merge no payload (response_format, provider, seed, ...). Sem
regra de negócio.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx

from sentinela.clients.base import LLMClient, LLMError, LLMTimeout

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterClient:
    def __init__(self, api_key: str, model_primary: str, model_fallback: Optional[str] = None,
                 *, base_url: str = OPENROUTER_URL, timeout: float = 60.0) -> None:
        self.api_key = api_key
        self.model_primary = model_primary
        self.model_fallback = model_fallback
        self.base_url = base_url
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "OpenRouterClient":
        key = os.environ.get("OPENROUTER_API_KEY", "")
        primary = os.environ.get("OPENROUTER_MODEL_PRIMARY", "")
        fallback = os.environ.get("OPENROUTER_MODEL_FALLBACK") or None
        if not key or not primary:
            raise LLMError("faltam OPENROUTER_API_KEY e/ou OPENROUTER_MODEL_PRIMARY no ambiente")
        return cls(key, primary, fallback)

    def _payload(self, model: str, system: str, user: str, temperature: float,
                 max_tokens: int, extra: Optional[dict]) -> dict:
        payload = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if extra:
            payload.update(extra)   # response_format, provider, seed, top_p, reasoning...
        return payload

    def _post(self, model: str, system: str, user: str, temperature: float,
              max_tokens: int, extra: Optional[dict]) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            resp = httpx.post(self.base_url, headers=headers,
                              json=self._payload(model, system, user, temperature, max_tokens, extra),
                              timeout=self.timeout)
        except httpx.TimeoutException as e:
            raise LLMTimeout(f"timeout do OpenRouter: {e}") from e
        except httpx.HTTPError as e:
            raise LLMError(f"erro de rede no OpenRouter: {e}") from e
        if resp.status_code >= 400:
            raise LLMError(f"OpenRouter {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            raise LLMError(f"resposta inesperada do OpenRouter: {e}") from e

    def complete(self, *, system: str, user: str, temperature: float = 0.0,
                 max_tokens: int = 1024, extra: Optional[dict] = None) -> str:
        try:
            return self._post(self.model_primary, system, user, temperature, max_tokens, extra)
        except LLMError:
            if self.model_fallback:
                return self._post(self.model_fallback, system, user, temperature, max_tokens, extra)
            raise
