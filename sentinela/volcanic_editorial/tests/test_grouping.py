from __future__ import annotations

import pytest

from sentinela.volcanic_editorial import group_volcanic_events

from .conftest import volcanic_event


def test_doze_events_reais_formam_nove_grupos(real_volcanic_events):
    units = group_volcanic_events(real_volcanic_events)

    assert len(units) == 9
    assert sum(len(unit.member_events) for unit in units) == 12
    assert len({unit.editorial_group_id for unit in units}) == 9


def test_editorial_group_ids_aprovados_permanecem_inalterados(real_volcanic_events):
    assert {unit.editorial_group_id for unit in group_volcanic_events(real_volcanic_events)} == {
        "327831eee036483273df3fa49595cde50b56a9dfd8b5a4a89d41e85db0f111f7",
        "c100ec5696adad2633b4cf67ea05e5ed34eb56d38bd0fe13d1709bce69853da2",
        "97951f40c20fbdac407f7763cf00213352f13dae8f52a0263cf021f5cf394d28",
        "68ceb025caf691be8b4d4d8c6bd17d5d883118dd78b19110b2d607b8d06975c0",
        "43d8bf35ba32e9eabb44e1b9a1bd4fd20ba5ca08526e428990a7ecc7ce6cfeb3",
        "70180eb3d45b8cd2c44a761558a8ce6f0297d3df719dd6f3fd79ae62ef2d28b5",
        "6e0ba833e3d827a5a1b0eace0f568d1c76666cff153c135f92ff8bf30d9c763f",
        "7b1e3eba61d255debbda6cc2f26068ccf8801d398c38db6d3d09649506d733ca",
        "bf2c7eaadb56693dd157ced84cfdca46f715ced1e91ffd83fb76d462f8b5d276",
    }


def test_quatro_vonas_do_mesmo_grupo_formam_uma_unidade(real_volcanic_events):
    units = group_volcanic_events(real_volcanic_events)
    vona = next(unit for unit in units if unit.category == "volcano_vona_published")

    assert len(vona.member_events) == 4
    assert vona.grouping_reason == "shared_vona_canonical_group"
    assert vona.representative_event_id == "f687fd9e-afd8-4dd8-a6dc-bc96d54977db"
    assert set(vona.member_event_ids) == {
        "850ef73c-1889-465a-a4a8-153bfd11aa11",
        "144e7612-9138-4c5f-b821-b73804c5b29b",
        "87ec6cad-8330-4b6c-93ad-28b2af9bbf32",
        "f687fd9e-afd8-4dd8-a6dc-bc96d54977db",
    }


def test_notice_elevated_e_firms_de_kilauea_ficam_separados(real_volcanic_events):
    units = group_volcanic_events(real_volcanic_events)
    kilauea = [unit for unit in units if unit.volcano_number == "332010"]

    assert len(kilauea) == 4
    assert sorted(len(unit.member_events) for unit in kilauea) == [1, 1, 1, 4]
    assert {unit.category for unit in kilauea} == {
        "volcano_vona_published",
        "volcano_notice_published",
        "volcano_alert_elevated",
        "volcanic_thermal_anomaly_candidate",
    }


def test_vonas_de_grupos_diferentes_nao_agrupam():
    first = volcanic_event(category="volcano_vona_published")
    second = volcanic_event(
        event_id="00000000-0000-0000-0000-000000000002",
        category="volcano_vona_published",
        canonical_group_id="20000000-0000-0000-0000-000000000002",
    )

    assert len(group_volcanic_events((first, second))) == 2


def test_vulcoes_diferentes_nunca_agrupam_mesmo_com_group_id_igual():
    first = volcanic_event(category="volcano_vona_published")
    second = volcanic_event(
        event_id="00000000-0000-0000-0000-000000000002",
        volcano_name="Outro Vulcão",
        volcano_number="888888",
        category="volcano_vona_published",
    )

    assert len(group_volcanic_events((first, second))) == 2


def test_firms_nao_vulcanico_e_rejeitado():
    event = volcanic_event(
        category="wildfire_hotspot_cluster",
        scientific_area="environmental_monitoring",
        source="NASA FIRMS",
    )

    with pytest.raises(ValueError, match="Vulcanologia"):
        group_volcanic_events((event,))


def test_ordem_de_entrada_nao_muda_grupos(real_volcanic_events):
    first = group_volcanic_events(real_volcanic_events)
    second = group_volcanic_events(tuple(reversed(real_volcanic_events)))

    assert [unit.editorial_group_id for unit in first] == [
        unit.editorial_group_id for unit in second
    ]
    assert [unit.member_event_ids for unit in first] == [
        unit.member_event_ids for unit in second
    ]
