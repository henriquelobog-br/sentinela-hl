"""Research Profile — Documento 112.7B."""

from .loader import ProfileLoadError, load_research_profile
from .models import (
    PreferredSource,
    ResearchConcept,
    ResearchDomain,
    ResearchIdentity,
    ResearchInstrument,
    ResearchLine,
    ResearchProfile,
    ResearchRegion,
    ResolutionRecord,
)

__all__ = [
    "PreferredSource",
    "ProfileLoadError",
    "ResearchConcept",
    "ResearchDomain",
    "ResearchIdentity",
    "ResearchInstrument",
    "ResearchLine",
    "ResearchProfile",
    "ResearchRegion",
    "ResolutionRecord",
    "load_research_profile",
]
