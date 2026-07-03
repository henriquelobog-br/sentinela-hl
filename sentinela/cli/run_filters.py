"""
Sentinela HL — CLI do agente de filtros (Documento 113.6).

    uv run python -m sentinela.cli.run_filters sentinela/fixtures/caso_pass.json

Lê o JSON de entrada, monta o FilterAgentInput, constrói o LLMClient
(OpenRouter, por env) e imprime o FilterAgentOutput em stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from sentinela.clients.base import LLMClient
from sentinela.clients.openrouter import OpenRouterClient
from sentinela.core.contract import (
    FilterAgentError,
    FilterAgentInput,
    FilterAgentOutput,
    FilterErrorCode,
)
from sentinela.engines.agent import evaluate


def load_input(path: Path) -> FilterAgentInput:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("_expected", None)  # metadado de teste — não faz parte do contrato
    return FilterAgentInput.model_validate(raw)


def build_client() -> LLMClient:
    # separado para facilitar troca/monkeypatch em teste
    return OpenRouterClient.from_env()


def _emit(out: FilterAgentOutput) -> int:
    print(json.dumps(out.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if out.ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run_filters", description="Agente de filtros do Sentinela HL")
    ap.add_argument("fixture", help="caminho do JSON de entrada (FilterAgentInput)")
    args = ap.parse_args(argv)

    path = Path(args.fixture)
    if not path.exists():
        return _emit(_err(FilterErrorCode.MALFORMED_CLAIM, f"arquivo não encontrado: {path}"))
    try:
        inp = load_input(path)
    except json.JSONDecodeError as e:
        return _emit(_err(FilterErrorCode.INVALID_JSON, str(e)))
    except ValidationError as e:
        return _emit(_err(FilterErrorCode.MALFORMED_CLAIM, str(e)))

    out = evaluate(inp, build_client())
    return _emit(out)


def _err(code: FilterErrorCode, message: str) -> FilterAgentOutput:
    return FilterAgentOutput(ok=False, error=FilterAgentError(error=code, message=message))


if __name__ == "__main__":
    sys.exit(main())
