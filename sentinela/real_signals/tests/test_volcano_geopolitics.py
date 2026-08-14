from __future__ import annotations

import io
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from sentinela.core.models import EventStatus
from sentinela.real_signals.config import RealSignalSettings
from sentinela.fingerprint import ConceptFingerprintEngine
from sentinela.interest import load_research_profile
from sentinela.real_signals.collectors import _event
from sentinela.real_signals.orchestrator import ROOT, _configs, _pipeline
from sentinela.real_signals.volcano_geopolitics import (
    GdeltCollector, GvpCollector, UsgsVolcanoCollector,
)
from sentinela.taxonomy.loader import load_taxonomy
from sentinela.taxonomy.taxonomy import TaxonomyIndex

NOW = datetime(2026, 8, 10, 21, 30, tzinfo=timezone.utc)


def settings(**changes):
    return replace(RealSignalSettings.from_env(), **changes)


class Response:
    def __init__(self, payload=None, status=200, text=None, content=None):
        self.payload = payload
        self.status_code = status
        self.text = text if text is not None else ""
        self.content = content if content is not None else b""

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://source.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("external", request=request, response=response)

    def json(self):
        return self.payload


class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, Response) else Response(response)


def section(vnum="332010", name="Kilauea", alert="ADVISORY", color="YELLOW"):
    return {
        "vnum": vnum, "vName": name, "lat": 19.421, "lng": -155.287,
        "alertLevel": alert, "colorCode": color,
        "synopsis": f"Resumo oficial para {name}.",
    }


def elevated(notice="notice-1", alert="ADVISORY", color="YELLOW"):
    return {
        "obs_fullname": "Hawaiian Volcano Observatory", "volcano_name": "Kilauea",
        "vnum": "332010", "notice_type_cd": "DU",
        "notice_identifier": notice, "sent_unixtime": 1786391994,
        "color_code": color, "alert_level": alert,
        "notice_url": f"https://volcanoes.usgs.gov/notice/{notice}",
        "notice_data": f"https://volcanoes.usgs.gov/api/{notice}",
    }


def detail(*sections):
    return {"notice_sections": list(sections), "highest_alert_level": "ADVISORY", "highest_color_code": "YELLOW"}


def volcano_result(elevated_rows=None, recent_rows=None, vona_rows=None, detail_rows=None):
    responses = [elevated_rows or [], recent_rows or [], vona_rows or []]
    responses.extend(detail_rows or [])
    return UsgsVolcanoCollector(settings(), Client(responses), gvp_features=[]).collect(NOW)


def test_volcano_elevated():
    result = volcano_result([elevated()], detail_rows=[detail(section())])
    assert len(result.events) == 1
    event = result.events[0]
    assert event.category == "volcano_alert_elevated"
    assert event.evidence[0]["volcano_number"] == "332010"
    assert event.evidence[0]["latitude"] == 19.421
    assert event.event_status is EventStatus.OFFICIAL_ALERT


def test_volcano_novo_vona():
    vona = {
        "vName": "Kilauea", "vnum": "332010", "noticeId": "DOI-USGS-HVO-2026-08-10T10:00:00+00:00",
        "sentUtc": "2026-08-10", "alertLevel": "ADVISORY", "colorCode": "YELLOW",
        "noticeSynopsis": "Atividade descrita no VONA.", "noticeUrl": "https://volcanoes.usgs.gov/vona/1",
        "obs": "hvo",
    }
    result = volcano_result(vona_rows=[vona])
    assert len(result.events) == 1
    assert result.events[0].category == "volcano_vona_published"
    assert result.events[0].title == "Novo aviso VONA emitido para Kilauea"


def test_volcano_notice_repetido_deduplica():
    notice = {
        "sent_unixtime": 1786391994, "notice_identifier": "same",
        "notice_type_title": "Information Statement", "notice_type_cd": "IS",
        "notice_category": "Event Response / Information Statement",
        "obs_fullname": "HVO", "notice_data": "https://detail/same",
    }
    result = volcano_result(recent_rows=[notice, notice], detail_rows=[detail(section())])
    assert len(result.events) == 1
    assert result.duplicates == 1


def test_volcano_alteracao_alerta_mantem_grupo():
    first = volcano_result([elevated("n1", "ADVISORY", "YELLOW")], detail_rows=[detail(section())])
    second = volcano_result([elevated("n2", "WATCH", "ORANGE")], detail_rows=[detail(section(alert="WATCH", color="ORANGE"))])
    assert first.events[0].id != second.events[0].id
    assert first.events[0].primary_claim_id is None
    assert first.events[0].evidence[0]["canonical_group_id"] == second.events[0].evidence[0]["canonical_group_id"]


def test_volcano_campos_ausentes():
    result = volcano_result([{"volcano_name": "Sem número", "alert_level": "WATCH"}])
    assert result.events == ()
    assert result.discarded == 1


def test_volcano_resposta_vazia():
    result = volcano_result()
    assert result.received == 0
    assert result.events == ()


def test_volcano_erro_http():
    result = UsgsVolcanoCollector(settings(), Client([Response(status=500)]), gvp_features=[]).collect(NOW)
    assert result.events == ()
    assert result.error == "HTTPStatusError: falha na consulta USGS HANS"


def test_volcano_normal_green_rotineiro_nao_gera_sinal():
    notice = {
        "sent_unixtime": 1786391994, "notice_identifier": "normal-routine",
        "notice_type_title": "Information Statement", "notice_type_cd": "IS",
        "notice_category": "Event Response / Information Statement",
        "obs_fullname": "HVO", "notice_data": "https://detail/normal-routine",
    }
    normal = section(alert="NORMAL", color="GREEN") | {"synopsis": "No volcanic activity was observed."}
    result = volcano_result(recent_rows=[notice], detail_rows=[detail(normal)])
    assert result.events == ()


def test_volcano_retorno_ao_normal_pode_gerar_sinal():
    notice = {
        "sent_unixtime": 1786391994, "notice_identifier": "return-normal",
        "notice_type_title": "Volcano Activity Notice", "notice_type_cd": "VV",
        "notice_category": "Event Response / Information Statement",
        "obs_fullname": "HVO", "notice_data": "https://detail/return-normal",
    }
    normal = section(alert="NORMAL", color="GREEN") | {
        "synopsis": "The USGS lowered the Volcano Alert Level from ADVISORY to NORMAL after unrest ended."
    }
    notice["notice_type_cd"] = "SR"
    result = volcano_result(recent_rows=[notice], detail_rows=[detail(normal)])
    assert len(result.events) == 1
    assert result.events[0].evidence[0]["alert_level"] == "NORMAL"


def gvp_feature(number=332010, name="Kilauea", optional=True):
    properties = {
        "Volcano_Number": number, "Volcano_Name": name,
        "Country": "United States", "Region": "Hawaii",
        "Latitude": 19.421, "Longitude": -155.287,
    }
    if optional:
        properties.update({"Primary_Volcano_Type": "Shield", "Last_Eruption_Year": 2026})
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-155.287, 19.421]}, "properties": properties}


def test_gvp_wfs_valido_geojson():
    result = GvpCollector(settings(), Client([
        {"type": "FeatureCollection", "features": [gvp_feature()]},
        {"type": "FeatureCollection", "features": []},
    ])).collect(NOW)
    assert result.received == 1
    assert result.events == ()
    assert "enriquecimento" in result.notice


def test_gvp_vulcao_encontrado():
    found = GvpCollector.find_volcano([gvp_feature()], "332010")
    assert found["properties"]["Volcano_Name"] == "Kilauea"


def test_gvp_vulcao_nao_encontrado():
    assert GvpCollector.find_volcano([gvp_feature()], "999999") is None


def test_gvp_campos_opcionais():
    found = GvpCollector.find_volcano([gvp_feature(optional=False)], "332010")
    assert "Primary_Volcano_Type" not in found["properties"]


def test_volcano_enriquecido_com_gvp():
    responses = [[elevated()], [], [], detail(section())]
    result = UsgsVolcanoCollector(settings(), Client(responses), gvp_features=[gvp_feature()]).collect(NOW)
    evidence = result.events[0].evidence[0]
    assert evidence["gvp_enriched"] is True
    assert evidence["volcano_type"] == "Shield"
    assert evidence["last_known_eruption"] == 2026


def gdelt_row(
    identifier="1", actor1="ISRAEL", actor2="IRAN", root="19",
    country="IS", mentions=4, sources=2, url="https://example.com/a",
    date_added="20260810211500", location="Israel",
):
    row = [""] * 61
    row[0] = identifier; row[1] = date_added[:8]
    row[6] = actor1; row[7] = "ISR" if "ISRAEL" in actor1 else ""
    row[16] = actor2; row[17] = "IRN" if "IRAN" in actor2 else ""
    row[26] = root + "0"; row[27] = root + "0"; row[28] = root
    row[29] = "4" if int(root) >= 18 else "1"; row[30] = "-7.0" if int(root) >= 18 else "4.0"
    row[31] = str(mentions); row[32] = str(sources); row[33] = str(mentions)
    row[34] = "-2.5"; row[36] = actor1; row[37] = country
    row[44] = actor2; row[45] = country; row[52] = location; row[53] = country
    row[59] = date_added; row[60] = url
    return row


def gdelt_zip(*rows):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        text = "\n".join("\t".join(row) for row in rows)
        archive.writestr("events.export.CSV", text)
    return output.getvalue()


def gdelt_result(*rows, configured=None, extra_responses=None):
    configured = configured or settings(gdelt_lookback_minutes=15)
    last = "100 hash http://data.gdeltproject.org/gdeltv2/20260810211500.export.CSV.zip\n"
    responses = [Response(text=last), Response(content=gdelt_zip(*rows))]
    responses.extend(extra_responses or [])
    return GdeltCollector(configured, Client(responses)).collect(NOW)


def test_gdelt_israel_conflito():
    result = gdelt_result(gdelt_row())
    assert len(result.events) == 1
    assert result.events[0].category == "geopolitical_conflict_reported"
    assert "conflito" in result.events[0].title.lower()


def test_gdelt_israel_diplomacia():
    result = gdelt_result(gdelt_row(actor2="JORDAN", root="05"))
    assert result.events[0].category == "geopolitical_diplomacy_reported"


def test_gdelt_abraham_accords():
    result = gdelt_result(gdelt_row(actor2="UNITED ARAB EMIRATES", root="05"))
    assert result.events[0].category == "abraham_accords_activity_reported"
    assert result.events[0].evidence[0]["abraham_accords_basis"]


def test_gdelt_israel_uae_sem_cooperacao_nao_declara_abraham_accords():
    result = gdelt_result(gdelt_row(actor2="UNITED ARAB EMIRATES", root="04"))
    assert result.events[0].category == "geopolitical_diplomacy_reported"
    assert result.events[0].evidence[0]["abraham_accords_basis"] is None


def test_gdelt_fora_regiao():
    result = gdelt_result(gdelt_row(actor1="BRAZIL", actor2="ARGENTINA", country="BR", location="Brazil"))
    assert result.events == ()


def test_gdelt_sources_insuficientes():
    result = gdelt_result(gdelt_row(mentions=1, sources=1))
    assert result.events == ()


def test_gdelt_agrupamento_seis_horas():
    result = gdelt_result(gdelt_row("1"), gdelt_row("2", url="https://example.com/b"))
    assert len(result.events) == 1
    evidence = result.events[0].evidence[0]
    assert len(evidence["member_event_ids"]) == 2
    assert evidence["total_mentions"] == 8


def test_gdelt_agrupa_atores_invertidos_no_mesmo_fato():
    result = gdelt_result(
        gdelt_row("1", actor1="ISRAEL", actor2="IRAN"),
        gdelt_row("2", actor1="IRAN", actor2="ISRAEL", url="https://example.com/b"),
    )
    assert len(result.events) == 1
    assert len(result.events[0].evidence[0]["member_event_ids"]) == 2


def test_gdelt_eventos_distintos():
    result = gdelt_result(gdelt_row("1"), gdelt_row("2", actor2="LEBANON", url="https://example.com/b"))
    assert len(result.events) == 2


def test_gdelt_idempotencia():
    first = gdelt_result(gdelt_row())
    second = gdelt_result(gdelt_row())
    assert first.events[0].id == second.events[0].id


def test_gdelt_sem_url():
    assert gdelt_result(gdelt_row(url="")).events == ()


def test_gdelt_erro_parcial():
    configured = settings(gdelt_lookback_minutes=30)
    last = "100 hash http://data.gdeltproject.org/gdeltv2/20260810211500.export.CSV.zip\n"
    client = Client([
        Response(text=last), Response(content=gdelt_zip(gdelt_row())), Response(status=404),
    ])
    result = GdeltCollector(configured, client).collect(NOW)
    assert len(result.events) == 1
    assert "arquivos parciais" in result.notice


def test_taxonomia_minima_reconhece_eventos_autorizados():
    index = TaxonomyIndex(load_taxonomy(Path("taxonomy")))
    expected = {
        "volcano": "volcano", "volcanic activity": "volcanic_activity",
        "conflict": "conflict", "military action": "military_action",
        "protest": "protest", "diplomacy": "diplomacy", "peace": "peace",
        "ceasefire": "ceasefire", "Israel": "israel", "Middle East": "middle_east",
        "Iran": "iran", "Palestine": "palestine", "Abraham Accords": "abraham_accords",
    }
    assert {term: index.find_by_term(term).id for term in expected} == expected


def test_gdelt_taxonomia_nao_forca_score_do_perfil():
    event = gdelt_result(gdelt_row(actor2="JORDAN", root="05")).events[0]
    signals, unmatched = _pipeline((event,), settings())
    assert unmatched == ()
    assert 0.0 < signals[0].relevance_score < 1.0
    assert abs(signals[0].priority_score - signals[0].relevance_score * 0.75) <= 0.000001


def test_perfil_geopolitico_reconhece_israel_e_preserva_atmosfera():
    taxonomy = load_taxonomy(Path("taxonomy"))
    profile = load_research_profile(Path("profiles/henrique_lobo.yaml"), TaxonomyIndex(taxonomy))
    lines = {line.id: line for line in profile.research_lines}
    geopolitical = lines["middle_east_geopolitics"]
    assert {item.concept_id for item in geopolitical.concepts} >= {"israel", "conflict", "diplomacy", "abraham_accords"}
    assert profile.researcher.id == "henrique_lobo"
    assert {item.domain_id: item.weight for item in profile.domains}["atmospheric_science"] == 1.0
    atmospheric = lines["transatlantic_mineral_dust"]
    assert atmospheric.priority == 1.0
    assert [(item.concept_id, item.weight) for item in atmospheric.concepts] == [("mineral_dust", 1.0)]
    assert [(item.concept_id, item.weight) for item in atmospheric.regions] == [("south_atlantic", 1.0)]


def test_conflito_e_diplomacia_com_israel_recebem_relevancia():
    conflict = gdelt_result(gdelt_row(actor1="ISRAEL", actor2="IRAN", root="19")).events[0]
    diplomacy = gdelt_result(gdelt_row(actor1="ISRAEL", actor2="IRAN", root="05")).events[0]
    conflict_signal = _pipeline((conflict,), settings())[0][0]
    diplomacy_signal = _pipeline((diplomacy,), settings())[0][0]
    assert conflict_signal.relevance_score > 0.0
    assert diplomacy_signal.relevance_score > 0.0


def test_abraham_accords_direto_somente_com_evidencia_compativel():
    compatible = gdelt_result(gdelt_row(actor1="ISRAEL", actor2="UNITED ARAB EMIRATES", root="05")).events[0]
    insufficient = gdelt_result(gdelt_row(actor1="ISRAEL", actor2="UNITED ARAB EMIRATES", root="04")).events[0]
    taxonomy = load_taxonomy(ROOT / "taxonomy")
    engine = ConceptFingerprintEngine(TaxonomyIndex(taxonomy), _configs(taxonomy.version)[0])
    compatible_direct = {concept.concept_id for concept in engine.build(compatible).concepts if concept.direct_weight > 0}
    insufficient_direct = {concept.concept_id for concept in engine.build(insufficient).concepts if concept.direct_weight > 0}
    assert "abraham_accords" in compatible_direct
    assert "abraham_accords" not in insufficient_direct
    assert _pipeline((compatible,), settings())[0][0].relevance_score > 0.0


def test_evento_fora_do_foco_continua_sem_relevancia():
    event = _event(
        event_type="unrelated_event", source="Test", product="offline",
        region="outside", window="2026-08-10", group="outside",
        title="Evento esportivo local", summary="Evento fora do foco de pesquisa.",
        occurred_at=NOW, evidence={"source": "Test", "product": "offline"},
        keywords=["sports"], entities=[], scientific_area="other",
        evidence_text="sports",
    )
    signal = _pipeline((event,), settings())[0][0]
    assert signal.relevance_score == 0.0
    assert signal.priority_score == 0.0


def test_perfil_vulcanologico_preserva_linhas_existentes():
    taxonomy = load_taxonomy(Path("taxonomy"))
    profile = load_research_profile(Path("profiles/henrique_lobo.yaml"), TaxonomyIndex(taxonomy))
    lines = {line.id: line for line in profile.research_lines}
    assert profile.researcher.id == "henrique_lobo"
    assert profile.researcher.version == 6
    assert [(item.concept_id, item.weight) for item in lines["transatlantic_mineral_dust"].concepts] == [("mineral_dust", 1.0)]
    assert [(item.concept_id, item.weight) for item in lines["middle_east_geopolitics"].concepts] == [
        ("abraham_accords", 0.25), ("ceasefire", 0.15), ("conflict", 0.25),
        ("diplomacy", 0.2), ("iran", 0.15), ("israel", 0.25),
        ("middle_east", 0.1), ("military_action", 0.25),
        ("palestine", 0.15), ("peace", 0.12),
    ]
    assert [(item.concept_id, item.weight) for item in lines["volcanology_monitoring"].concepts] == [
        ("volcanic_activity", 0.08), ("volcanic_alert", 0.18),
        ("volcanic_ash", 0.2), ("volcanic_eruption", 0.18),
        ("volcano", 0.02),
    ]


@pytest.mark.parametrize(
    ("name", "vnum", "alert", "color"),
    [
        ("Great Sitkin", "311120", "WATCH", "ORANGE"),
        ("Kilauea", "332010", "ADVISORY", "YELLOW"),
        ("Ahyi Seamount", "284141", "ADVISORY", "YELLOW"),
        ("Kupreanof", "312060", "ADVISORY", "YELLOW"),
        ("Shishaldin", "311360", "ADVISORY", "YELLOW"),
    ],
)
def test_vulcoes_elevados_recebem_relevancia_natural(name, vnum, alert, color):
    item = elevated(alert=alert, color=color) | {
        "volcano_name": name, "vnum": vnum,
        "notice_identifier": f"notice-{vnum}",
        "notice_url": f"https://notice/{vnum}",
        "notice_data": f"https://detail/{vnum}",
    }
    result = volcano_result([item], detail_rows=[detail(section(vnum, name, alert, color))])
    signal = _pipeline(result.events, settings())[0][0]
    assert signal.relevance_score > 0.0
    assert signal.priority_score > 0.0
    assert abs(signal.priority_score - signal.relevance_score * 0.75) <= 0.000001


def test_volcano_generico_sem_atividade_nao_recebe_relevancia_elevada():
    event = _event(
        event_type="volcano_catalogued", source="Test", product="catalogue",
        region="000000", window="catalogue", group="catalogue",
        title="Vulcão catalogado", summary="Registro conhecido sem mudança de atividade.",
        occurred_at=NOW, evidence={"source": "Test", "product": "catalogue"},
        keywords=["volcano"], entities=[], scientific_area="volcanology",
        evidence_text="volcano",
    )
    signal = _pipeline((event,), settings())[0][0]
    assert 0.0 < signal.relevance_score < 0.25
    assert signal.priority_level.value == "low"
