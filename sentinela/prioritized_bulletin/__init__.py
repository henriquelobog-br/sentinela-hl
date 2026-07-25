"""Prioritized Bulletin — Documento 112.7G.

Boletim personalizado priorizado: organização final dos InterestResults
em seções por prioridade. Não recalcula scores, não apresenta, não persiste.
"""

from .engine import (
    PrioritizedBulletinEngine,
    SUPPORTED_PRIORITIZED_BULLETIN_ALGORITHM_VERSION,
)
from .errors import (
    PrioritizedBulletinAssociationError,
    PrioritizedBulletinConfigError,
    PrioritizedBulletinContextMismatchError,
    PrioritizedBulletinDuplicateEntryError,
    PrioritizedBulletinError,
    PrioritizedBulletinInputError,
    PrioritizedBulletinLimitError,
    PrioritizedBulletinReviewMismatchError,
    PrioritizedBulletinVersionError,
)
from .models import (
    PrioritizedBulletin,
    PrioritizedBulletinConfig,
    PrioritizedBulletinContext,
    PrioritizedBulletinDeduplicationPolicy,
    PrioritizedBulletinEntry,
    PrioritizedBulletinGroupingPolicy,
    PrioritizedBulletinItem,
    PrioritizedBulletinMember,
    PrioritizedBulletinRequest,
    PrioritizedBulletinSection,
    PrioritizedBulletinSectionTitle,
    PrioritizedBulletinSectionType,
)

__all__ = [
    "PrioritizedBulletin",
    "PrioritizedBulletinAssociationError",
    "PrioritizedBulletinConfig",
    "PrioritizedBulletinConfigError",
    "PrioritizedBulletinContext",
    "PrioritizedBulletinContextMismatchError",
    "PrioritizedBulletinDeduplicationPolicy",
    "PrioritizedBulletinDuplicateEntryError",
    "PrioritizedBulletinEngine",
    "PrioritizedBulletinEntry",
    "PrioritizedBulletinError",
    "PrioritizedBulletinGroupingPolicy",
    "PrioritizedBulletinInputError",
    "PrioritizedBulletinItem",
    "PrioritizedBulletinLimitError",
    "PrioritizedBulletinMember",
    "PrioritizedBulletinRequest",
    "PrioritizedBulletinReviewMismatchError",
    "PrioritizedBulletinSection",
    "PrioritizedBulletinSectionTitle",
    "PrioritizedBulletinSectionType",
    "PrioritizedBulletinVersionError",
    "SUPPORTED_PRIORITIZED_BULLETIN_ALGORITHM_VERSION",
]
