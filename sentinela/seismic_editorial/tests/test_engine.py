from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from sentinela.seismic_editorial import (
    SeismicEditorialContent,
    SeismicEditorialEngine,
)

from .conftest import seismic_event

FORBIDDEN = (
    "source_event_id",
    "vítima",
    "vitima",
    "dano",
    "placa tectônica",
    "placa tectonica",
    "falha geológica",
    "falha geologica",
    "mecanismo focal",
    "risco futuro",
    "forte terremoto",
    "ameaça",
)
ALL_EVENT_FIXTURES = (
    "sarangani_event",
    "macquarie_event",
    "kermadec_event",
    "gambiran_event",
    "angoram_event",
    "lapuan_event",
    "severo_kurilsk_event",
)


def all_text(content: SeismicEditorialContent) -> str:
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


@pytest.mark.parametrize(
    ("fixture_name", "title_parts", "subtitle_parts", "summary_parts"),
    (
        (
            "sarangani_event",
            ("Terremoto", "magnitude 5,3", "Sarangani", "Filipinas"),
            ("66,3 km", "profundidade"),
            ("USGS", "13 de agosto de 2026", "11 km ao sul"),
        ),
        (
            "macquarie_event",
            ("USGS registra", "magnitude 5,1", "Ilha Macquarie"),
            ("oeste da Ilha Macquarie", "10 km"),
            ("17h39",),
        ),
        (
            "kermadec_event",
            ("Região das Ilhas Kermadec", "magnitude 5,6"),
            ("10 km", "profundidade"),
            ("USGS", "16h11", "alerta", "verde"),
        ),
        (
            "gambiran_event",
            ("Terremoto", "magnitude 4,6", "ocorre", "Gambiran Satu", "Indonésia"),
            ("3 km", "leste-sudeste"),
            ("USGS", "10h23", "145,7 km"),
        ),
        (
            "angoram_event",
            ("Terremoto", "magnitude 5", "ocorre", "Angoram", "Papua-Nova Guiné"),
            ("45 km", "sul-sudoeste", "Papua-Nova Guiné"),
            ("USGS", "12h44", "134 km"),
        ),
        (
            "lapuan_event",
            ("USGS registra", "magnitude 5,1", "Lapuan", "Filipinas"),
            ("22 km", "leste-nordeste", "Filipinas"),
            ("09h22", "91,2 km"),
        ),
        (
            "severo_kurilsk_event",
            ("Terremoto", "magnitude 4,5", "sul-sudoeste", "Severo-Kuril’sk", "Rússia"),
            ("222 km", "sul-sudoeste", "Severo-Kuril’sk", "Rússia"),
            ("USGS", "07h09", "35 km"),
        ),
    ),
)
def test_quatro_baselines_editoriais(
    request,
    fixture_name,
    title_parts,
    subtitle_parts,
    summary_parts,
):
    event = request.getfixturevalue(fixture_name)
    content = SeismicEditorialEngine().build(event)

    for part in title_parts:
        assert part in content.editorial_title
    for part in subtitle_parts:
        assert part in content.editorial_subtitle
    for part in summary_parts:
        assert part in content.editorial_summary

    assert 1 <= len(content.editorial_summary.split("\n\n")) <= 2
    assert len(content.editorial_title) <= 120
    assert len(content.editorial_subtitle) <= 180
    assert len(content.editorial_summary) <= 800
    assert len(content.seo_title) <= 70
    assert len(content.seo_description) <= 180
    assert len(content.seo_keywords) <= 8

    text = all_text(content)
    assert str(event.id) not in text
    assert event.evidence[0]["source_event_id"] not in text
    for forbidden in FORBIDDEN:
        assert forbidden not in text.lower()


def test_seo_e_autonomo_factual_e_sem_keyword_stuffing(sarangani_event):
    content = SeismicEditorialEngine().build(sarangani_event)
    assert "Terremoto" in content.seo_title
    assert "5,3" in content.seo_title
    assert "Sarangani" in content.seo_description
    assert "66,3 km" in content.seo_description
    assert len(content.seo_keywords) == len(set(content.seo_keywords))
    assert content.seo_keywords.count("terremoto") == 1


@pytest.mark.parametrize(
    "fixture_name",
    ("angoram_event", "lapuan_event", "severo_kurilsk_event"),
)
def test_normalizacoes_novas_nao_deixam_fragmentos_em_ingles(
    request,
    fixture_name,
):
    content = SeismicEditorialEngine().build(
        request.getfixturevalue(fixture_name)
    )
    text = all_text(content)
    for forbidden in (
        "SSW of",
        "ENE of",
        "Papua New Guinea",
        "Philippines",
        "Russia",
    ):
        assert forbidden not in text


def test_severo_kurilsk_e_preservado_exatamente(severo_kurilsk_event):
    content = SeismicEditorialEngine().build(severo_kurilsk_event)
    assert "Severo-Kuril’sk" in all_text(content)


@pytest.mark.parametrize("fixture_name", ALL_EVENT_FIXTURES)
def test_informacao_tecnica_nivel_tres_nao_e_preenchimento_automatico(
    request,
    fixture_name,
):
    content = SeismicEditorialEngine().build(
        request.getfixturevalue(fixture_name)
    )
    text = all_text(content).lower()
    assert "latitude" not in text
    assert "longitude" not in text
    assert "mww" not in text
    assert " mb " not in f" {text} "


def test_event_sem_profundidade_nao_fabrica_profundidade():
    event = seismic_event(place="Kermadec Islands region", depth_km=None)
    content = SeismicEditorialEngine().build(event)
    assert "profundidade" not in all_text(content).lower()


def test_event_sem_alert_nao_fabrica_alerta():
    event = seismic_event(place="Kermadec Islands region", alert=None)
    event.evidence[0].pop("alert")
    content = SeismicEditorialEngine().build(event)
    assert "alerta" not in all_text(content).lower()


def test_event_sem_magnitude_type_nao_fabrica_tipo():
    event = seismic_event(
        place="west of Macquarie Island",
        magnitude_type=None,
    )
    content = SeismicEditorialEngine().build(event)
    assert "mww" not in all_text(content).lower()


def test_event_sem_coordenadas_nao_fabrica_coordenadas():
    event = seismic_event(
        place="west of Macquarie Island",
        latitude=None,
        longitude=None,
    )
    content = SeismicEditorialEngine().build(event)
    text = all_text(content).lower()
    assert "latitude" not in text
    assert "longitude" not in text


def test_coordenadas_so_localizam_quando_texto_geografico_esta_ausente():
    event = seismic_event(place=None, depth_km=12.4)
    content = SeismicEditorialEngine().build(event)
    assert "latitude -20" in content.editorial_subtitle
    assert "longitude -40" in content.editorial_subtitle


def test_event_com_campos_opcionais_ausentes_produz_menos_conteudo():
    event = seismic_event(
        magnitude=None,
        magnitude_type=None,
        place=None,
        depth_km=None,
        latitude=None,
        longitude=None,
        alert=None,
        occurred_at=None,
        source=None,
    )
    content = SeismicEditorialEngine().build(event)
    assert content.editorial_title == "Terremoto é registrado"
    assert content.editorial_subtitle == ""
    assert content.editorial_summary == ""
    assert content.seo_keywords == ("terremoto", "sismologia")


def test_alerta_e_preservado_sem_interpretacao(kermadec_event):
    content = SeismicEditorialEngine().build(kermadec_event)
    text = all_text(content).lower()
    assert "alerta verde" in text
    for interpretation in ("baixo risco", "seguro", "sem perigo", "gravidade"):
        assert interpretation not in text


def test_tsunami_nao_e_inferido_quando_ausente():
    event = seismic_event()
    event.evidence[0].pop("tsunami")
    content = SeismicEditorialEngine().build(event)
    assert "tsunami" not in all_text(content).lower()


def test_tsunami_estruturado_nao_recebe_inferencia_editorial():
    event = seismic_event()
    event.evidence[0]["tsunami"] = 1
    content = SeismicEditorialEngine().build(event)
    assert "tsunami" not in all_text(content).lower()


def test_vitimas_e_danos_nao_sao_mencionados_sem_evidencia():
    content = SeismicEditorialEngine().build(seismic_event())
    text = all_text(content).lower()
    assert "vítima" not in text
    assert "vitima" not in text
    assert "dano" not in text


def test_ids_tecnicos_nunca_entram_no_editorial(sarangani_event):
    content = SeismicEditorialEngine().build(sarangani_event)
    text = all_text(content)
    assert str(sarangani_event.id) not in text
    assert "us6000tkig" not in text
    assert "canonical_group_id" not in text


@pytest.mark.parametrize("fixture_name", ALL_EVENT_FIXTURES)
def test_event_original_permanece_inalterado_e_saida_e_deterministica(
    request,
    fixture_name,
):
    event = request.getfixturevalue(fixture_name)
    before = event.model_dump_json()
    structural_copy = deepcopy(event.model_dump(mode="python"))

    first = SeismicEditorialEngine().build(event)
    second = SeismicEditorialEngine().build(event)

    assert first == second
    assert event.model_dump_json() == before
    assert event.model_dump(mode="python") == structural_copy


def test_repeticao_estrutural_fica_limitada_a_familias_fechadas(request):
    contents = [
        SeismicEditorialEngine().build(request.getfixturevalue(name))
        for name in ALL_EVENT_FIXTURES
    ]

    title_families = {
        "a": sum(" é registrado" in item.editorial_title for item in contents),
        "b": sum(item.editorial_title.startswith("Região") for item in contents),
        "c": sum(" ocorre " in item.editorial_title for item in contents),
        "d": sum(item.editorial_title.startswith("USGS registra") for item in contents),
    }
    subtitle_families = {
        prefix: sum(item.editorial_subtitle.startswith(prefix) for item in contents)
        for prefix in (
            "O evento ocorreu",
            "O evento foi localizado",
            "A localização indicada",
            "O registro situa",
        )
    }
    lead_families = {
        prefix: sum(item.editorial_summary.startswith(prefix) for item in contents)
        for prefix in (
            "O USGS registrou",
            "A ocorrência foi registrada",
            "Segundo o registro do USGS",
            "Com profundidade",
            "O evento consta",
        )
    }

    assert title_families == {"a": 2, "b": 1, "c": 2, "d": 2}
    assert sorted(subtitle_families.values()) == [1, 2, 2, 2]
    assert sorted(lead_families.values()) == [1, 1, 1, 2, 2]
    assert max(title_families.values()) == 2
    assert max(subtitle_families.values()) == 2
    assert max(lead_families.values()) == 2
    assert [
        len(item.editorial_summary.split("\n\n")) for item in contents
    ] == [1, 1, 2, 1, 1, 1, 1]


def test_conteudo_editorial_e_imutavel(sarangani_event):
    content = SeismicEditorialEngine().build(sarangani_event)
    with pytest.raises(ValidationError):
        content.editorial_title = "alterado"


def test_event_de_outro_tema_e_rejeitado():
    event = seismic_event()
    event.category = "volcano_alert"
    with pytest.raises(ValueError, match="categoria sísmica"):
        SeismicEditorialEngine().build(event)


def test_title_e_summary_legados_nao_sao_fonte_factual():
    event = seismic_event(magnitude=None, place=None, depth_km=None)
    event.title = "Magnitude 9.9 em local inventado"
    event.summary = "Danos inventados e risco futuro"
    content = SeismicEditorialEngine().build(event)
    text = all_text(content).lower()
    assert "9,9" not in text
    assert "local inventado" not in text
    assert "danos inventados" not in text
    assert "risco futuro" not in text
