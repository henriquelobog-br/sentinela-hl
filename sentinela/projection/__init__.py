"""Projection — projeções estáveis e serializáveis para consumo externo."""

from .models import ResearcherSignal
from .researcher_signal import project_researcher_signals

__all__ = [
    "ResearcherSignal",
    "project_researcher_signals",
]
