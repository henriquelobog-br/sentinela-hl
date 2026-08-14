from __future__ import annotations

from copy import deepcopy
from datetime import datetime

import pytest
from pydantic import ValidationError

from sentinela.volcanic_editorial import (
    VolcanicEditorialEngine,
    group_volcanic_events,
)

from .conftest import volcanic_event


def all_text(content) -> str:
    return " ".join(
        (
            content.editorial_title,
            content.editorial_subtitle,
            content.editorial_summary,
            content.seo_title,
            content.seo_description,
            *content.seo_keywords,
        )
    )


def contents(real_volcanic_events):
    engine = VolcanicEditorialEngine()
    return [
        (unit, engine.build(unit))
        for unit in group_volcanic_events(real_volcanic_events)
    ]


def test_baselines_reais_preservam_diferencas(real_volcanic_events):
    by_volcano_category = {
        (unit.volcano_name, unit.category): content
        for unit, content in contents(real_volcanic_events)
    }

    assert "sismo sob Kama'ehuakanaloa" in by_volcano_category[
        ("Kama'ehuakanaloa", "volcano_notice_published")
    ].editorial_title
    assert "eventos sísmicos e de infrassom" in by_volcano_category[
        ("Shishaldin", "volcano_alert_elevated")
    ].editorial_title
    assert "extrusão lenta de lava" in by_volcano_category[
        ("Great Sitkin", "volcano_alert_elevated")
    ].editorial_title
    assert "atividade sísmica de baixo nível" in by_volcano_category[
        ("Kupreanof", "volcano_alert_elevated")
    ].editorial_title
    assert "não apresenta sinais de agitação" in by_volcano_category[
        ("Ahyi Seamount", "volcano_alert_elevated")
    ].editorial_title


def test_kilauea_produz_quatro_conteudos_distintos(real_volcanic_events):
    items = [item for item in contents(real_volcanic_events) if item[0].volcano_name == "Kilauea"]
    by_category = {unit.category: content for unit, content in items}

    assert len(items) == 4
    assert "Sequência VONA" in by_category["volcano_vona_published"].editorial_title
    assert "4 avisos VONA" in by_category["volcano_vona_published"].editorial_summary
    assert "encerramento" in by_category["volcano_notice_published"].editorial_title
    assert "informa pausa" in by_category["volcano_alert_elevated"].editorial_title
    assert "anomalia térmica" in by_category[
        "volcanic_thermal_anomaly_candidate"
    ].editorial_title
    assert "não confirma causa ou atividade vulcânica" in by_category[
        "volcanic_thermal_anomaly_candidate"
    ].editorial_summary


def test_campos_opcionais_ausentes_nao_sao_fabricados():
    event = volcanic_event(
        alert_level=None,
        aviation_color=None,
        occurred_at=None,
        observatory=None,
        gvp_enriched=False,
        official_summary="Activity observations are unchanged.",
    )
    unit = group_volcanic_events((event,))[0]
    text = all_text(VolcanicEditorialEngine().build(unit))

    assert "ADVISORY" not in text
    assert "YELLOW" not in text
    assert "UTC" not in text
    assert "GVP" not in text


def test_gvp_permanece_disponivel_mas_nao_entra_no_resumo_padrao():
    event = volcanic_event(
        gvp_enriched=True,
        volcano_type="Stratovolcano",
        last_known_eruption=1999,
        official_summary="Activity observations are unchanged.",
    )
    content = VolcanicEditorialEngine().build(group_volcanic_events((event,))[0])

    assert event.evidence[0]["gvp_enriched"] is True
    assert event.evidence[0]["volcano_type"] == "Stratovolcano"
    assert event.evidence[0]["last_known_eruption"] == 1999
    assert "GVP" not in all_text(content)
    assert "Stratovolcano" not in all_text(content)
    assert "1999" not in all_text(content)
    assert "erupção" not in all_text(content).lower()


def test_firms_isolado_nao_confirma_causa_vulcanica():
    event = volcanic_event(
        category="volcanic_thermal_anomaly_candidate",
        source="NASA FIRMS",
        event_status="observed_fact",
        alert_level=None,
        aviation_color=None,
        observatory=None,
        notice_type=None,
        official_summary=None,
        extra_evidence={
            "hotspot_count": 3,
            "distance_to_volcano_km": 4.2,
            "sensors": ["VIIRS_SNPP_NRT"],
        },
    )
    content = VolcanicEditorialEngine().build(group_volcanic_events((event,))[0])
    text = all_text(content).lower()

    assert "associação é espacial" in text
    assert "não confirma causa ou atividade vulcânica" in text
    assert "erupção" not in text


def test_ids_urls_danos_risco_e_evacuacao_nao_aparecem(real_volcanic_events):
    forbidden = (
        "source_event_id",
        "technical-source-id",
        "https://",
        "uuid",
        "dano",
        "vítima",
        "risco",
        "evacuação",
        "impacto aéreo",
        "direção de cinzas",
        " unassigned ",
        " du ",
        " wu ",
    )
    event_ids = {str(event.id) for event in real_volcanic_events}

    for _, content in contents(real_volcanic_events):
        text = all_text(content)
        lowered = f" {text.lower()} "
        assert all(value not in text for value in event_ids)
        assert all(value not in lowered for value in forbidden)


def test_ausencia_de_erupcao_explicita_nao_gera_erupcao():
    event = volcanic_event(official_summary="Activity observations are unchanged.")
    content = VolcanicEditorialEngine().build(group_volcanic_events((event,))[0])

    assert "erupção" not in all_text(content).lower()


def test_saida_deterministica_e_events_inalterados(real_volcanic_events):
    before = deepcopy([event.model_dump(mode="python") for event in real_volcanic_events])
    units = group_volcanic_events(real_volcanic_events)
    engine = VolcanicEditorialEngine()

    first = [engine.build(unit) for unit in units]
    second = [engine.build(unit) for unit in units]

    assert first == second
    assert [event.model_dump(mode="python") for event in real_volcanic_events] == before


def test_conteudo_e_imutavel(real_volcanic_events):
    content = contents(real_volcanic_events)[0][1]

    with pytest.raises(ValidationError):
        content.editorial_title = "alterado"


def test_limites_e_variacao_editorial(real_volcanic_events):
    generated = [content for _, content in contents(real_volcanic_events)]
    titles = [content.editorial_title for content in generated]
    subtitles = [content.editorial_subtitle for content in generated]
    leads = [content.editorial_summary.split("\n\n")[0] for content in generated]

    assert len(titles) == len(set(titles)) == 9
    assert len(subtitles) == len(set(subtitles)) == 9
    assert len(leads) == len(set(leads)) == 9
    for content in generated:
        assert len(content.editorial_title) <= 120
        assert len(content.editorial_subtitle) <= 180
        assert len(content.editorial_summary) <= 800
        assert len(content.seo_title) <= 70
        assert len(content.seo_description) <= 180
        assert len(content.seo_keywords) <= 8
        assert len(content.editorial_summary.split("\n\n")) == 1


def test_eruptivo_no_titulo_vona_e_sustentado_por_official_summary(
    real_volcanic_events,
):
    unit, content = next(
        item
        for item in contents(real_volcanic_events)
        if item[0].category == "volcano_vona_published"
    )

    summaries = [event.evidence[0]["official_summary"].lower() for event in unit.member_events]
    assert any("eruptive" in value or "eruption" in value for value in summaries)
    assert "episódio eruptivo" in content.editorial_title
