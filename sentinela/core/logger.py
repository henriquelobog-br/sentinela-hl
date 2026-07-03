"""
Sentinela HL — logging estruturado (JSON), sem dependência externa.

Cada linha é um JSON com timestamp, nível, módulo e campos extras. Facilita
depuração do pipeline e casa com a natureza auditável do projeto.

Uso:
    from shared.logger import get_logger
    log = get_logger(__name__)
    log.info("item coletado", extra={"source": "namib-feed", "count": 12})
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from shared.config import get_settings

_RESERVED = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime", "taskName"}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # anexa qualquer campo passado via extra=
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured = False


def _configure_root() -> None:
    global _configured
    if _configured:
        return
    level = get_settings().log_level.upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Retorna um logger já configurado com saída JSON."""
    _configure_root()
    return logging.getLogger(name)
