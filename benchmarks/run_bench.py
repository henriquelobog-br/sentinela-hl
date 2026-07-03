"""
Sentinela HL — benchmark runner (Ajuste 5, Doc 113).

Roda os fixtures contra um modelo real (via OpenRouter) e compara o veredito
com o bloco `_expected` de cada fixture. É o harness para calibrar o prompt
e comparar modelos (Claude / GPT / Gemini / DeepSeek / GLM...) sobre os mesmos
casos.

    OPENROUTER_API_KEY=... OPENROUTER_MODEL_PRIMARY=... \
        uv run python benchmarks/run_bench.py

Mede latência por caso. Tokens/custo ficam para quando houver instrumentação
real do provedor (deferido de propósito — ver Doc 113).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from sentinela.clients.base import LLMClient
from sentinela.clients.openrouter import OpenRouterClient
from sentinela.core.contract import FilterAgentInput
from sentinela.engines.agent import evaluate

FIXTURES = Path(__file__).resolve().parent.parent / "sentinela" / "fixtures"


def run(client: LLMClient, prompt_version: str = "filter_v1") -> int:
    cases = sorted(FIXTURES.glob("caso_*.json"))
    print(f"{'caso':22} {'esperado':10} {'obtido':10} {'ok':4} {'ms':>7}")
    print("-" * 58)
    all_ok = True
    for path in cases:
        raw = json.loads(path.read_text(encoding="utf-8"))
        expected = raw.pop("_expected")
        inp = FilterAgentInput.model_validate(raw)
        t0 = time.perf_counter()
        out = evaluate(inp, client, prompt_version=prompt_version)
        ms = round((time.perf_counter() - t0) * 1000)
        got = out.report.decision if out.ok else f"erro:{out.error.error.value}"
        ok = out.ok and got == expected["decision"]
        all_ok &= ok
        print(f"{path.name:22} {expected['decision']:10} {str(got):10} {'✅' if ok else '❌':4} {ms:>7}")
    print("-" * 58)
    print("RESULTADO:", "todos bateram ✅" if all_ok else "DIVERGÊNCIA — ajustar o prompt ❌")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(run(OpenRouterClient.from_env()))
