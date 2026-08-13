"""Ingestao operacional de sinais atmosfericos reais."""

from .config import RealSignalSettings
from .orchestrator import RealSignalRun, RunResult, run_real_signals

__all__ = ["RealSignalRun", "RealSignalSettings", "RunResult", "run_real_signals"]
