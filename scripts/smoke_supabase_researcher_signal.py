"""Smoke test real de persistência: ResearcherSignal → Supabase → leitura.

Fluxo:

    Walking Skeleton (determinístico, sem rede)
    → ResearcherSignal
    → Supabase real (upsert idempotente por id)
    → leitura de confirmação via PostgREST

Regras operacionais:

- nunca imprime service key, headers ou payload completo;
- timeout HTTP explícito em todas as chamadas;
- falha sanitizada com exit code != 0;
- operação idempotente (reexecutar produz o mesmo id);
- sem dados aleatórios e sem relógio não controlado: o Event é o
  sintético determinístico do walking skeleton e os únicos timestamps
  criados em runtime (created_at/updated_at do banco) não participam
  da comparação.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# permite `uv run python scripts/...` a partir da raiz do repositório
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from sentinela.persistence import (
    ResearcherSignalStoreError,
    SupabaseResearcherSignalStore,
)
from sentinela.persistence.supabase_store import _build_headers
from sentinela.pipeline.tests.test_walking_skeleton import (
    build_bulletin_config,
    build_event,
    build_fingerprint_config,
    build_interest_config,
    build_profile,
    build_radar_config,
    build_taxonomy,
)
from sentinela.pipeline.walking_skeleton import run_walking_skeleton
from sentinela.projection import project_researcher_signals

_TIMEOUT_SECONDS = 10.0
_DATETIME_FIELDS = ("occurred_at", "validated_at")


def _sanitize(message: str, secret: str) -> str:
    """Garante que a credencial nunca aparece em uma mensagem de erro."""
    if secret:
        return message.replace(secret, "***")
    return message


def main() -> int:
    from sentinela.core.config import get_settings

    settings = get_settings()
    url = settings.supabase_url.rstrip("/")
    service_key = settings.supabase_service_key

    if not url or not service_key:
        print(
            "erro: SENTINELA_SUPABASE_URL e/ou "
            "SENTINELA_SUPABASE_SERVICE_KEY ausentes no ambiente"
        )
        return 1

    # 1-3. pipeline completo + projeção (determinístico, sem rede)
    bulletin = run_walking_skeleton(
        event=build_event(),
        taxonomy=build_taxonomy(),
        profile=build_profile(),
        fingerprint_config=build_fingerprint_config(),
        radar_config=build_radar_config(),
        interest_config=build_interest_config(),
        bulletin_config=build_bulletin_config(),
    )
    signals = project_researcher_signals(bulletin)
    if len(signals) != 1:
        print(f"erro: esperado 1 sinal, obtido {len(signals)}")
        return 1
    signal = signals[0]

    # 4. persistência idempotente pela camada já implementada
    try:
        store = SupabaseResearcherSignalStore(timeout=_TIMEOUT_SECONDS)
        result = store.upsert_many(signals)
    except ResearcherSignalStoreError as exc:
        print(f"erro de persistência: {_sanitize(str(exc), service_key)}")
        return 1

    if result.persisted != 1 or result.persisted_ids != (signal.id,):
        print("erro: persistência não confirmada pelo adapter")
        return 1

    # 5. leitura de confirmação por id via PostgREST
    try:
        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            response = client.get(
                f"{url}/rest/v1/researcher_signals",
                params={"id": f"eq.{signal.id}", "select": "*"},
                headers=_build_headers(service_key),
            )
            response.raise_for_status()
            rows = response.json()
    except httpx.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        detail = f"HTTP {status}" if status else type(exc).__name__
        print(f"erro de leitura: {_sanitize(detail, service_key)}")
        return 1
    except ValueError:
        print("erro de leitura: resposta não é JSON válido")
        return 1

    if len(rows) != 1:
        print(f"erro: leitura retornou {len(rows)} registro(s)")
        return 1

    # 6. o registro retornado deve corresponder ao sinal projetado
    row = rows[0]
    expected = signal.model_dump(mode="json")
    mismatches = sorted(
        field
        for field, value in expected.items()
        if field in row and field not in _DATETIME_FIELDS and row[field] != value
    )
    for field in _DATETIME_FIELDS:
        if field in row and row[field] is not None:
            # banco devolve timestamptz com offset; comparação por instante
            if datetime.fromisoformat(row[field]) != datetime.fromisoformat(
                expected[field]
            ):
                mismatches.append(field)
    if mismatches:
        print(f"erro: campos divergentes: {mismatches}")
        return 1

    print(f"id: {signal.id}")
    print(f"researcher_id: {signal.researcher_id}")
    print(f"priority_level: {signal.priority_level.value}")
    print("persisted = true")
    print("verified = true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
