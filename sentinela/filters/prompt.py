"""
Sentinela HL — carregamento e montagem do prompt (Documento 113.4).

O SYSTEM é um artefato versionado em sentinela/prompts/<versão>.md — não é
mais string no código. O PromptLoader lê por importlib.resources (funciona
independente do CWD). RESPONSE_SCHEMA fica pronto para OpenRouter Structured
Outputs quando o modelo escolhido suportar (ver Ajuste 4).
"""

from __future__ import annotations

from importlib import resources

from sentinela.core.contract import FilterAgentInput

FILTER_KEYS = ("provenance", "epistemic_label", "calibration")
DEFAULT_PROMPT_VERSION = "filter_v1"

# JSON Schema da saída — usável via response_format (extra passthrough) quando
# o modelo suportar. Baseline continua sendo a instrução textual no .md.
RESPONSE_SCHEMA = {
    "name": "filter_verdicts",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": list(FILTER_KEYS),
        "properties": {
            k: {
                "type": "object",
                "additionalProperties": False,
                "required": ["result", "rationale"],
                "properties": {
                    "result": {"type": "string", "enum": ["pass", "flag", "fail"]},
                    "rationale": {"type": "string"},
                },
            }
            for k in FILTER_KEYS
        },
    },
}


class PromptLoader:
    """Carrega o SYSTEM versionado de sentinela/prompts/<versão>.md (com cache)."""
    _cache: dict[str, str] = {}

    @classmethod
    def load(cls, version: str = DEFAULT_PROMPT_VERSION) -> str:
        if version not in cls._cache:
            cls._cache[version] = (
                resources.files("sentinela.prompts")
                .joinpath(f"{version}.md")
                .read_text(encoding="utf-8")
                .strip()
            )
        return cls._cache[version]


def build_messages(inp: FilterAgentInput, *, version: str = DEFAULT_PROMPT_VERSION) -> tuple[str, str]:
    """Monta (system, user). O system vem do arquivo versionado; o user é a
    interpolação mecânica dos dados do caso."""
    system = PromptLoader.load(version)
    c, s = inp.claim, inp.source
    label = c.epistemic_status.value if c.epistemic_status else "ausente"
    conf = c.confidence_score if c.confidence_score is not None else "ausente"
    user = f"""claim a auditar
- afirmação: {c.statement}
- rótulo provisório (epistemic_status): {label}
- confiança provisória (confidence_score): {conf}
- confiabilidade declarada da fonte: {c.source_reliability.value}

fonte
- confiabilidade: {s.reliability.value}
- trecho: {s.excerpt}

devolva o JSON com os três vereditos."""
    return system, user
