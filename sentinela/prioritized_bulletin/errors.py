"""Erros públicos do Prioritized Bulletin — Documento 112.7G."""


class PrioritizedBulletinError(Exception):
    """Base dos erros públicos do Prioritized Bulletin."""


class PrioritizedBulletinInputError(PrioritizedBulletinError):
    """Entrada estruturalmente inválida durante build()."""


class PrioritizedBulletinAssociationError(PrioritizedBulletinError):
    """Associação Event–InterestResult inválida."""


class PrioritizedBulletinContextMismatchError(PrioritizedBulletinError):
    """InterestResult divergente do contexto do request."""


class PrioritizedBulletinDuplicateEntryError(PrioritizedBulletinError):
    """Chave de avaliação repetida dentro do request."""


class PrioritizedBulletinReviewMismatchError(PrioritizedBulletinError):
    """requires_human_review divergente do esperado pelo Event."""


class PrioritizedBulletinLimitError(PrioritizedBulletinError):
    """Limite operacional excedido."""


class PrioritizedBulletinConfigError(PrioritizedBulletinError):
    """Configuração inválida na revalidação do construtor."""


class PrioritizedBulletinVersionError(PrioritizedBulletinError):
    """Versão de algoritmo não suportada."""


__all__ = [
    "PrioritizedBulletinAssociationError",
    "PrioritizedBulletinConfigError",
    "PrioritizedBulletinContextMismatchError",
    "PrioritizedBulletinDuplicateEntryError",
    "PrioritizedBulletinError",
    "PrioritizedBulletinInputError",
    "PrioritizedBulletinLimitError",
    "PrioritizedBulletinReviewMismatchError",
    "PrioritizedBulletinVersionError",
]
