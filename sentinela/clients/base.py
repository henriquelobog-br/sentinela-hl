"""
Sentinela HL — abstração de LLM (Documento 113.1).

O resto da aplicação conhece SÓ o `LLMClient`. Nunca o provedor, nunca o nome
do modelo. Trocar Claude → GPT → Gemini → DeepSeek não toca em mais nada.

Sem regra de negócio aqui: o client só transporta texto.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class LLMError(RuntimeError):
    """Falha do provedor (HTTP 4xx/5xx, rede, resposta inválida)."""


class LLMTimeout(LLMError):
    """O modelo não respondeu dentro do tempo limite."""


@runtime_checkable
class LLMClient(Protocol):
    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        """Recebe system + user; devolve o TEXTO da resposta do modelo."""
        ...
