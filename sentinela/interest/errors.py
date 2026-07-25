"""Erros públicos do Interest Engine — Documento 112.7F §48."""


class InterestEngineError(Exception):
    """Base dos erros públicos do Interest Engine."""


class InterestEngineConfigError(InterestEngineError):
    """Configuração inválida na fronteira ou na revalidação do construtor."""


class InterestEngineInputError(InterestEngineError):
    """Entradas estruturalmente inválidas ou evento inelegível."""


class InterestEngineVersionError(InterestEngineError):
    """Versão de algoritmo não suportada."""


class InterestEngineCompatibilityError(InterestEngineError):
    """Incompatibilidade de versões entre entradas e configuração."""


class InterestEventFingerprintMismatchError(InterestEngineError):
    """event.id diverge de fingerprint.event_id."""


class InterestEngineArithmeticError(InterestEngineError):
    """Violação de invariante aritmética interna."""


__all__ = [
    "InterestEngineArithmeticError",
    "InterestEngineCompatibilityError",
    "InterestEngineConfigError",
    "InterestEngineError",
    "InterestEngineInputError",
    "InterestEngineVersionError",
    "InterestEventFingerprintMismatchError",
]
