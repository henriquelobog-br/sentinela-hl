"""Erro próprio da camada de persistência de sinais."""


class EventStoreError(RuntimeError):
    """Falha controlada na persistência canônica de Event."""


class ResearcherSignalStoreError(RuntimeError):
    """Falha externa de persistência (rede, HTTP 4xx/5xx, resposta
    inválida), já convertida pelo adapter. Nunca contém credenciais."""


__all__ = ["EventStoreError", "ResearcherSignalStoreError"]
