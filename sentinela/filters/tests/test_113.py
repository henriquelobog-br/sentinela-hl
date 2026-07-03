"""
Sentinela HL — testes do Documento 113.

Rodam offline: o LLMClient é substituído por um FakeLLMClient (dublê),
provando o pipeline sem gastar token nem depender de rede. A qualidade do
prompt real só é verificável contra um modelo de verdade — ver nota no doc.
"""

from __future__ import annotations

import json
from pathlib import Path

from sentinela.clients.fake import FakeLLMClient
from sentinela.core.contract import FilterAgentInput, FilterErrorCode
from sentinela.core.models import Classification, FilterResult
from sentinela.engines.agent import evaluate
from sentinela.engines.decision import DecisionEngine

FIX = Path(__file__).resolve().parent / "fixtures"


def _fake_llm_response(expected_classifications: list[dict]) -> str:
    """Simula a saída de um LLM perfeito a partir do bloco _expected do fixture."""
    key_out = {"provenance": {}, "epistemic_label": {}, "calibration": {}}
    keymap = {"provenance": "provenance", "epistemic_label": "epistemic_label", "calibration": "calibration"}
    body = {}
    for c in expected_classifications:
        body[keymap[c["filter"]]] = {"result": c["result"], "rationale": "simulado"}
    # o LLM só devolve os filtros presentes; para reject só há provenance,
    # então completamos os demais como pass (não afetam a decisão de reject)
    for k in ("provenance", "epistemic_label", "calibration"):
        body.setdefault(k, {"result": "pass", "rationale": "simulado"})
    return json.dumps(body)


def _load(name: str):
    raw = json.loads((FIX / name).read_text(encoding="utf-8"))
    expected = raw.pop("_expected")
    return FilterAgentInput.model_validate(raw), expected


def test_decision_engine_pure():
    def cls(*pairs):
        return [Classification(filter=f, result=r) for f, r in pairs]
    assert DecisionEngine.decide(cls(("provenance", "pass"), ("epistemic_label", "pass"), ("calibration", "pass"))) == ("pass", False)
    assert DecisionEngine.decide(cls(("provenance", "pass"), ("epistemic_label", "flag"), ("calibration", "pass"))) == ("escalate", True)
    assert DecisionEngine.decide(cls(("provenance", "fail"))) == ("reject", False)
    # fail tem prioridade sobre flag
    assert DecisionEngine.decide(cls(("provenance", "fail"), ("epistemic_label", "flag"))) == ("reject", False)


def test_pipeline_fixtures():
    for name in ("caso_pass.json", "caso_escalate.json", "caso_reject.json"):
        inp, expected = _load(name)
        fake = FakeLLMClient(_fake_llm_response(expected["classifications"]))
        out = evaluate(inp, fake)
        assert out.ok, f"{name} deveria ter ok=True"
        assert out.report.decision == expected["decision"], f"{name}: {out.report.decision} != {expected['decision']}"
        assert out.report.requires_human_review == expected["requires_human_review"]
        assert out.run_id, 'run_id ausente'
        for c in out.report.classifications:
            assert c.prompt_version == 'filter_v1'


def test_error_missing_source():
    inp, _ = _load("caso_pass.json")
    inp.source.excerpt = "   "
    out = evaluate(inp, FakeLLMClient("{}"))
    assert not out.ok and out.error.error == FilterErrorCode.MISSING_SOURCE


def test_error_invalid_json():
    inp, _ = _load("caso_pass.json")
    out = evaluate(inp, FakeLLMClient("isto não é json"))
    assert not out.ok and out.error.error == FilterErrorCode.INVALID_JSON


def test_error_llm_timeout():
    inp, _ = _load("caso_pass.json")
    out = evaluate(inp, FakeLLMClient(raise_timeout=True))
    assert not out.ok and out.error.error == FilterErrorCode.LLM_TIMEOUT
