from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest

from sentinela.real_signals.acled import AcledCollector, possible_cross_source_matches
from sentinela.real_signals.collectors import CollectionResult, _event
from sentinela.real_signals.config import RealSignalSettings
from sentinela.real_signals.orchestrator import _pipeline_with_eligibility, run_real_signals

NOW = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)


def settings(**changes):
    values = {
        "acled_username": "user@example.test", "acled_password": "secret",
        "acled_lookback_days": 3, "acled_limit": 5000,
    }
    values.update(changes)
    return replace(RealSignalSettings.from_env(), **values)


def row(**changes):
    value = {
        "event_id_cnty": "ISR1", "event_date": "2026-08-09", "year": 2026,
        "disorder_type": "Political violence", "event_type": "Battles",
        "sub_event_type": "Armed clash", "actor1": "Military Forces of Israel",
        "assoc_actor_1": "", "actor2": "Hamas", "assoc_actor_2": "",
        "interaction": "State forces-Rebel group", "region": "Middle East",
        "country": "Israel", "admin1": "South District", "admin2": "",
        "admin3": "", "location": "Gaza Border", "latitude": "31.2",
        "longitude": "34.4", "geo_precision": "1", "source": "Source A",
        "source_scale": "National", "notes": "ACLED factual note.",
        "fatalities": "0", "timestamp": "1786291200",
    }
    value.update(changes)
    return value


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://acled.test")
            response = httpx.Response(self.status_code, request=request, text="secret external body")
            raise httpx.HTTPStatusError("external secret", request=request, response=response)

    def json(self):
        return self.payload


class Client:
    def __init__(self, *, posts=None, gets=None):
        self.posts = iter(posts or [])
        self.gets = iter(gets or [])
        self.post_calls = []
        self.get_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return next(self.posts)

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return next(self.gets)


def token(access="access-1", refresh="refresh-1"):
    return Response({"access_token": access, "refresh_token": refresh, "expires_in": 86400})


def data(rows, *, count=None, status=200):
    return Response({"status": 200, "success": True, "count": len(rows) if count is None else count, "data": rows}, status)


def collect(rows, **setting_changes):
    client = Client(posts=[token()], gets=[data(rows)])
    return AcledCollector(settings(**setting_changes), client).collect(NOW), client


def test_oauth_valido_e_token_somente_em_memoria():
    result, client = collect([row()])
    assert len(result.events) == 1
    assert client.post_calls[0][1]["data"]["grant_type"] == "password"
    assert client.get_calls[0][1]["headers"]["authorization"] == "Bearer access-1"
    assert "access-1" not in str(result.events[0].evidence)
    assert result.events[0].evidence[0]["raw_fields"]["source"] == "Source A"


def test_token_invalido_e_sanitizado():
    client = Client(posts=[Response({"refresh_token": "x"})])
    result = AcledCollector(settings(), client).collect(NOW)
    assert result.events == ()
    assert result.error == "ValueError: falha na consulta ACLED"
    assert "secret" not in result.error


def test_refresh_apos_401():
    client = Client(
        posts=[token(), token("access-2", "refresh-2")],
        gets=[data([], status=401), data([row()])],
    )
    result = AcledCollector(settings(), client).collect(NOW)
    assert len(result.events) == 1
    assert client.post_calls[1][1]["data"]["grant_type"] == "refresh_token"
    assert client.get_calls[1][1]["headers"]["authorization"] == "Bearer access-2"


@pytest.mark.parametrize(
    "original,category",
    [
        ("Battles", "acled_battle_event"),
        ("Explosions/Remote violence", "acled_explosion_remote_violence"),
        ("Violence against civilians", "acled_violence_against_civilians"),
        ("Protests", "acled_protest"),
        ("Riots", "acled_riot"),
        ("Strategic developments", "acled_strategic_development"),
    ],
)
def test_mapeia_tipos_sem_reduzir_tudo_a_conflito(original, category):
    result, _ = collect([row(event_type=original)])
    event = result.events[0]
    assert event.category == category
    assert event.evidence[0]["event_type"] == original
    assert event.evidence[0]["sub_event_type"] == "Armed clash"


def test_evento_sem_fatalidades_nao_menciona_fatalidades():
    result, _ = collect([row(fatalities="0")])
    assert "fatalidades" not in result.events[0].summary


def test_evento_com_fatalidades_usa_formula_factual():
    result, _ = collect([row(fatalities="3")])
    assert "ACLED registra 3 fatalidades associadas ao evento" in result.events[0].summary
    assert "mortos confirmados" not in result.events[0].summary


@pytest.mark.parametrize(
    "country,concept",
    [("Israel", "israel"), ("Iran", "iran"), ("Palestine", "palestine")],
)
def test_conceito_de_pais_somente_quando_sustentado(country, concept):
    result, _ = collect([row(country=country, event_id_cnty=country[:3].upper() + "1")])
    assert concept in result.events[0].keywords
    assert "abraham_accords" not in result.events[0].keywords


def test_evento_fora_do_foco_e_descartado():
    result, _ = collect([row(country="France")])
    assert result.events == ()
    assert result.discarded == 1


def test_atualizacao_do_event_id_mantem_identidade_e_usa_revisao_mais_nova():
    result, _ = collect([
        row(timestamp="100", notes="old"),
        row(timestamp="200", notes="new", fatalities="2"),
    ])
    assert len(result.events) == 1
    assert result.duplicates == 1
    assert result.events[0].evidence[0]["timestamp"] == "200"
    first, _ = collect([row(timestamp="100")])
    assert first.events[0].id == result.events[0].id
    assert first.events[0].primary_claim_id is None
    assert first.events[0].evidence[0]["canonical_group_id"] == result.events[0].evidence[0]["canonical_group_id"]


def test_paginacao():
    client = Client(
        posts=[token()],
        gets=[data([row(event_id_cnty="ISR1"), row(event_id_cnty="ISR2")], count=3), data([row(event_id_cnty="ISR3")], count=3)],
    )
    result = AcledCollector(settings(acled_limit=2), client).collect(NOW)
    assert result.received == 3
    assert len(result.events) == 3
    assert [call[1]["params"]["page"] for call in client.get_calls] == [1, 2]


def test_lote_vazio():
    result, _ = collect([])
    assert result.received == 0
    assert result.events == ()


def test_erro_http_sanitizado():
    client = Client(posts=[Response({}, 401)])
    result = AcledCollector(settings(), client).collect(NOW)
    assert result.error == "HTTP 401: falha na consulta ACLED"
    assert "external" not in result.error


def test_possible_cross_source_match_nao_funde_identidades():
    acled, _ = collect([row()])
    gdelt = _event(
        event_type="geopolitical_conflict_reported", source="GDELT 2.0",
        product="events", region="Israel", window="2026-08-09",
        title="Evento factual", summary="Evento factual", occurred_at=datetime(2026, 8, 9, 6, tzinfo=timezone.utc),
        evidence={"action_geo": "Gaza Border, Israel", "action_geo_country_code": "Israel"},
        keywords=["conflict", "middle_east"], entities=[{"name": "Hamas", "type": "actor"}],
        scientific_area="scientific_geopolitics", evidence_text="conflict",
    )
    matches = possible_cross_source_matches(acled.events, (gdelt,))
    assert matches[0]["kind"] == "possible_cross_source_match"
    assert matches[0]["acled_event_id"] != matches[0]["gdelt_event_id"]


def test_orquestrador_reporta_possible_cross_source_match():
    acled, _ = collect([row()])
    gdelt_event = _event(
        event_type="geopolitical_conflict_reported", source="GDELT 2.0",
        product="events", region="Israel", window="2026-08-09",
        title="Evento factual", summary="Evento factual", occurred_at=datetime(2026, 8, 9, 6, tzinfo=timezone.utc),
        evidence={"action_geo": "Gaza Border, Israel", "action_geo_country_code": "Israel"},
        keywords=["conflict"], entities=[{"name": "Hamas", "type": "actor"}],
        scientific_area="scientific_geopolitics", evidence_text="conflict",
    )

    class Fixed:
        def __init__(self, result):
            self.result = result

        def collect(self, now):
            return self.result

    run = run_real_signals(
        settings=settings(), sources=("acled", "gdelt"), now=NOW,
        collectors={
            "acled": Fixed(acled),
            "gdelt": Fixed(CollectionResult(source="gdelt", events=(gdelt_event,))),
        },
    )
    acled_result = run.collections[0]
    assert "possible_cross_source_matches=1" in acled_result.notice
    assert acled_result.details[-1]["kind"] == "possible_cross_source_match"


def test_gdelt_auxiliar_e_explicito_e_falha_torna_run_parcial():
    acled, _ = collect([row()])

    class Fixed:
        def __init__(self, result=None, error=None):
            self.result = result
            self.error = error

        def collect(self, now):
            if self.error:
                raise self.error
            return self.result

    run = run_real_signals(
        settings=settings(), sources=("acled",), now=NOW,
        collectors={
            "acled": Fixed(acled),
            "gdelt": Fixed(error=RuntimeError("offline")),
        },
    )

    assert run.result.status == "partial"
    assert run.result.requested_sources == ("acled",)
    assert run.result.consulted_sources == ("acled", "gdelt")
    assert run.result.supporting_sources == ("gdelt",)
    assert run.result.successful_sources == ("acled",)
    assert run.result.failed_sources == ("gdelt",)
    assert run.events[0].source == "ACLED"
    assert run.events[0].supporting_sources == ()
    assert run.signals[0].source == "ACLED"
    assert run.signals[0].supporting_sources == ()


def test_battle_tem_elegibilidade_tematica():
    result, _ = collect([row()])
    signals, _, eligible = _pipeline_with_eligibility(result.events, settings())
    assert signals[0].relevance_score > 0
    assert eligible == (signals[0].id,)


def test_estrategico_apenas_geografico_e_bloqueado():
    result, _ = collect([row(event_type="Strategic developments", sub_event_type="Other", notes="Administrative update")])
    signals, _, eligible = _pipeline_with_eligibility(result.events, settings())
    assert signals[0].relevance_score > 0
    assert eligible == ()


def test_falha_acled_nao_interrompe_outra_fonte():
    class Fixed:
        def __init__(self, result):
            self.result = result

        def collect(self, now):
            return self.result

    acled_failure = AcledCollector(replace(settings(), acled_username="", acled_password=""), Client()).collect(NOW)
    valid, _ = collect([row()])
    run = run_real_signals(
        settings=settings(), sources=("acled", "other"), now=NOW,
        collectors={"acled": Fixed(acled_failure), "other": Fixed(valid)},
    )
    assert run.collections[0].error == "credenciais ACLED ausentes"
    assert len(run.signals) == 1
