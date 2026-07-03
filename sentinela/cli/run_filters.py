"""
Sentinela HL — CLI do agente de filtros (Documentos 113.6 / 112.1).

Lê um FilterAgentInput (de arquivo OU de stdin) e imprime o FilterAgentOutput
em stdout. A entrada por stdin é a interface para o n8n chamar o agente como
caixa-preta:

    uv run python -m sentinela.cli.run_filters caminho.json      # arquivo
    echo 'JSON' | uv run python -m sentinela.cli.run_filters -   # stdin
    cat input.json | uv run python -m sentinela.cli.run_filters -
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from sentinela.clients.base import LLMClient, LLMError
from sentinela.clients.openrouter import OpenRouterClient
from sentinela.core.contract import (
    FilterAgentError,
    FilterAgentInput,
    FilterAgentOutput,
    FilterErrorCode,
)
from sentinela.engines.agent import evaluate


def read_raw(source: str) -> dict:
    """Lê o JSON de um arquivo ou de stdin ('-')."""
    if source == "-":
        text = sys.stdin.read()
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(source)
        text = path.read_text(encoding="utf-8")
    raw = json.loads(text)
    if isinstance(raw, dict):
        raw.pop("_expected", None)  # metadado de teste — não faz parte do contrato
    return raw


def load_input(source: str) -> FilterAgentInput:
    return FilterAgentInput.model_validate(read_raw(source))


def build_client() -> LLMClient:
    # separado para facilitar troca/monkeypatch em teste
    return OpenRouterClient.from_env()


def _err(code: FilterErrorCode, message: str) -> FilterAgentOutput:
    return FilterAgentOutput(ok=False, error=FilterAgentError(error=code, message=message))


def _emit(out: FilterAgentOutput) -> int:
    print(json.dumps(out.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if out.ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run_filters", description="Agente de filtros do Sentinela HL")
    ap.add_argument("input", help="caminho do JSON de entrada, ou '-' para ler do stdin")
    args = ap.parse_args(argv)

    try:
        inp = load_input(args.input)
    except FileNotFoundError:
        return _emit(_err(FilterErrorCode.MALFORMED_CLAIM, f"arquivo não encontrado: {args.input}"))
    except json.JSONDecodeError as e:
        return _emit(_err(FilterErrorCode.INVALID_JSON, str(e)))
    except ValidationError as e:
        return _emit(_err(FilterErrorCode.MALFORMED_CLAIM, str(e)))

    try:
        llm = build_client()
    except LLMError as e:
        return _emit(_err(FilterErrorCode.LLM_ERROR, str(e)))

    out = evaluate(inp, llm)
    return _emit(out)


if __name__ == "__main__":
    sys.exit(main())
