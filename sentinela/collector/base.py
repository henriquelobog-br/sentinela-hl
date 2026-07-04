"""
Sentinela HL — contrato do Collector (Documento 112.2A).

O collector SÓ coleta. Saída = list[RawItem] (o contrato do 111, espelho de
raw.items). Nada de rótulo epistêmico nem confiança — isso é do classifier,
outro componente. Cada fonte (mock, arquivo, rss) é um adapter que produz o
MESMO RawItem, então trocar/adicionar fonte não toca em nada abaixo.
"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

from sentinela.core.models import RawItem, Source


@runtime_checkable
class Collector(Protocol):
    """Coleta itens brutos de uma fonte."""
    kind: str  # rótulo do adapter. Para fontes de produção (rss/api) coincide
               # com SourceKind.value; mock/file são adapters de dev, fora do enum SQL.

    def collect(self, source: Source) -> list[RawItem]:
        ...


def content_hash(*parts: str | None) -> str:
    """Hash estável para dedup por conteúdo (título + resumo/url)."""
    joined = "\u0001".join((p or "") for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
