"""Erro próprio da camada de persistência de sinais."""


class ResearcherSignalStoreError(RuntimeError):
    """Falha externa de persistência (rede, HTTP 4xx/5xx, resposta
    inválida), já convertida pelo adapter. Nunca contém credenciais."""


__all__ = ["ResearcherSignalStoreError"]
