"""
Sentinela HL — modelos da Taxonomia Científica (Documento 112.7A).

Vocabulário científico CONTROLADO — não é lista de palavras-chave. A relação
entre conceitos importa mais que os sinônimos: é ela que permitirá, nas camadas
seguintes (Fingerprint, Interest Engine), conectar evidências que não compartilham
termos literais (ex.: "aeolian dust" ↔ "atmospheric transport" ↔ "South Atlantic").

Determinístico, sem LLM, sem embeddings, sem banco (ADR-007).
A taxonomia representa conhecimento científico estável; não conhece pesquisadores.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# id de conceito: snake_case estável (é referência cruzada, não texto livre)
_ID_RE = re.compile(r"^[a-z0-9_]+$")


def normalize_term(term: str) -> str:
    """minúsculas, sem acento, espaços colapsados — comparação canônica."""
    t = unicodedata.normalize("NFKD", term or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t.lower()).strip()


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Concept(_Base):
    """Um conceito científico do vocabulário controlado."""
    id: str
    name: str
    domain: str                                     # id do domínio (ex.: atmospheric_science)
    synonyms: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)   # ids de conceitos relacionados
    parent: Optional[str] = None                        # id do conceito pai (hierarquia)
    description: Optional[str] = None

    @field_validator("id", "domain")
    @classmethod
    def _snake(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(f"id deve ser snake_case ([a-z0-9_]+): {v!r}")
        return v

    @field_validator("parent")
    @classmethod
    def _snake_opt(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _ID_RE.match(v):
            raise ValueError(f"parent deve ser snake_case: {v!r}")
        return v

    @field_validator("synonyms")
    @classmethod
    def _dedup_synonyms(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for s in v:
            key = normalize_term(s)
            if key and key not in seen:
                seen.add(key)
                out.append(s.strip())
        return out


class Domain(_Base):
    """Um domínio científico (arquivo YAML = um domínio)."""
    id: str
    name: str
    description: Optional[str] = None
    concepts: list[Concept] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _snake(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(f"id de domínio deve ser snake_case: {v!r}")
        return v


class Taxonomy(_Base):
    """A taxonomia inteira: união dos domínios carregados e validados."""
    version: str = "1"
    domains: list[Domain] = Field(default_factory=list)

    @property
    def concepts(self) -> list[Concept]:
        return [c for d in self.domains for c in d.concepts]


__all__ = ["Concept", "Domain", "Taxonomy", "normalize_term"]
