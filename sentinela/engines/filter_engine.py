"""
Sentinela HL — FilterEngine (Documento 113.5).

Monta o prompt, chama o LLM e converte a resposta em Classification[], já
carimbando model + prompt_version (auditoria). NENHUMA política de decisão.
"""

from __future__ import annotations

import json

from sentinela.clients.base import LLMClient
from sentinela.core.contract import FilterAgentInput
from sentinela.core.models import Classification, FilterKey, FilterResult
from sentinela.filters.prompt import DEFAULT_PROMPT_VERSION, FILTER_KEYS, build_messages

_KEY_MAP = {
    "provenance": FilterKey.PROVENANCE,
    "epistemic_label": FilterKey.EPISTEMIC_LABEL,
    "calibration": FilterKey.CALIBRATION,
}


class FilterParseError(ValueError):
    """A saída do LLM não é o JSON esperado."""


class FilterEngine:
    def __init__(self, llm: LLMClient, *, prompt_version: str = DEFAULT_PROMPT_VERSION,
                 model_label: str = "openrouter", extra: dict | None = None) -> None:
        self.llm = llm
        self.prompt_version = prompt_version
        self.model_label = model_label
        self.extra = extra

    def run(self, inp: FilterAgentInput) -> list[Classification]:
        system, user = build_messages(inp, version=self.prompt_version)
        raw = self.llm.complete(system=system, user=user, temperature=0.0, extra=self.extra)
        data = self._parse(raw)
        out: list[Classification] = []
        for key in FILTER_KEYS:
            node = data[key]
            out.append(Classification(
                claim_id=inp.claim.id,
                filter=_KEY_MAP[key],
                result=FilterResult(node["result"]),
                rationale=node.get("rationale"),
                automated=True,
                model=self.model_label,
                prompt_version=self.prompt_version,
            ))
        return out

    @staticmethod
    def _parse(raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text[:4].lower() == "json":
                text = text[4:]
            text = text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise FilterParseError(f"resposta do LLM não é JSON válido: {e}") from e
        if not isinstance(data, dict):
            raise FilterParseError("resposta do LLM não é um objeto JSON")
        for key in FILTER_KEYS:
            if key not in data or not isinstance(data[key], dict) or "result" not in data[key]:
                raise FilterParseError(f"faltou o veredito de '{key}' na resposta do LLM")
        return data
