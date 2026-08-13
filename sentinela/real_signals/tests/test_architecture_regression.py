from __future__ import annotations

import hashlib
import json

import pytest

from sentinela.fingerprint import ConceptFingerprintEngine
from sentinela.real_signals.collectors import CamsCollector, _event
from sentinela.real_signals.firms import FirmsCollector
from sentinela.real_signals.multithematic import UsgsCollector
from sentinela.real_signals.orchestrator import (
    ROOT,
    _configs,
    _pipeline_with_eligibility,
)
from sentinela.real_signals.tests.test_firms import (
    MODIS_HEADER,
    VIIRS_HEADER,
    Client as FirmsClient,
    Response as FirmsResponse,
    csv_text,
    settings as firms_settings,
    viirs,
)
from sentinela.real_signals.tests.test_firms import NOW as FIRMS_NOW
from sentinela.real_signals.tests.test_multithematic import (
    Client as MultithematicClient,
    donki_result,
    hourly_payload,
    marine_payload,
    marine_result,
    settings,
    usgs_feature,
    weather_result,
)
from sentinela.real_signals.tests.test_multithematic import NOW as MULTITHEMATIC_NOW
from sentinela.real_signals.tests.test_real_signals import (
    cams_row,
    settings as real_signal_settings,
)
from sentinela.real_signals.tests.test_real_signals import NOW as REAL_SIGNALS_NOW
from sentinela.real_signals.tests.test_volcano_geopolitics import (
    detail,
    elevated,
    gdelt_result,
    gdelt_row,
    section,
    volcano_result,
)
from sentinela.taxonomy.loader import load_taxonomy
from sentinela.taxonomy.taxonomy import TaxonomyIndex


def _great_sitkin():
    item = elevated(alert="WATCH", color="ORANGE") | {
        "volcano_name": "Great Sitkin",
        "vnum": "311120",
        "notice_identifier": "notice-311120",
        "notice_url": "https://notice/311120",
        "notice_data": "https://detail/311120",
    }
    return volcano_result(
        [item],
        detail_rows=[detail(section("311120", "Great Sitkin", "WATCH", "ORANGE"))],
    ).events[0]


def _firms_kilauea():
    volcano = {
        "volcano_name": "Kilauea",
        "volcano_number": "332010",
        "latitude": 19.421,
        "longitude": -155.287,
        "alert_level": "ADVISORY",
        "aviation_color_code": "YELLOW",
    }
    responses = [
        FirmsResponse(csv_text(VIIRS_HEADER, viirs(lat=19.42, lon=-155.29))),
        FirmsResponse(csv_text(VIIRS_HEADER)),
        FirmsResponse(csv_text(MODIS_HEADER)),
    ]
    return FirmsCollector(
        firms_settings(),
        FirmsClient(responses),
        monitored_volcanoes=[volcano],
        regions={"hawaii": ("Hawaii", (-156.0, 19.0, -154.5, 20.0))},
    ).collect(FIRMS_NOW).events[0]


def _donki(endpoint: str):
    overrides = {
        name: []
        for name in ("CME", "FLR", "GST", "SEP", "IPS")
        if name != endpoint
    }
    return donki_result(overrides)[0].events[0]


def _marine(category: str, **variables):
    return next(
        event
        for event in marine_result(marine_payload(**variables)).events
        if event.category == category
    )


def _earthquake():
    return UsgsCollector(
        settings(),
        MultithematicClient([{"features": [usgs_feature()]}]),
    ).collect(MULTITHEMATIC_NOW).events[0]


def _regional_only():
    return _event(
        event_type="generic_regional_observation",
        source="Fonte",
        product="generic",
        region="south_atlantic",
        window="2026-08-11",
        title="Observacao regional",
        summary="Observacao no South Atlantic.",
        occurred_at=MULTITHEMATIC_NOW,
        evidence={"region": "south_atlantic"},
        keywords=["south_atlantic"],
        entities=[{"name": "South Atlantic", "type": "region"}],
        scientific_area="geology",
        evidence_text="south_atlantic",
    )


def _dust_cams():
    return CamsCollector(
        real_signal_settings(),
        records_loader=lambda now, regions: [cams_row()],
    ).collect(REAL_SIGNALS_NOW).events[0]


CASES = {
    "gdelt_diplomacy": (
        lambda: gdelt_result(
            gdelt_row(actor1="ISRAEL", actor2="IRAN", root="05")
        ).events[0],
        "2176bd9a-6d98-4fb7-8963-eb737034fd4c",
        "e3cb7b00019b3bf1fe98cb03b3700e99334bcc9e9dc97e47db37f58fe13d4f16",
        0.903141,
        0.0,
        0.677356,
        "high",
        True,
        "51bc319d0fc8067d69adb30fba57ea7ffce27fbe267e0390dcbe7065d2d9a12f",
    ),
    "gdelt_conflict": (
        lambda: gdelt_result(
            gdelt_row(actor1="ISRAEL", actor2="IRAN", root="19")
        ).events[0],
        "31bedc00-2498-42cf-b684-b34a396eb46c",
        "0d6d732b5fbe42148283e10e0c9936f85bc3744c5f1716fd27b5efc14bd11a6d",
        1.0,
        0.0,
        0.75,
        "urgent",
        True,
        "de96dfc18fa7afeb1d250c9b6410bfccb8b27eaa1e78415a049e1f5bc30faba3",
    ),
    "great_sitkin": (
        _great_sitkin,
        "ce56a796-d9f8-46db-8261-5a33454d8dab",
        "55268f300fa561ef47eb772dcc2a7af555e7f58af903c79371bccc2d308a8c67",
        0.249094,
        0.0,
        0.186821,
        "low",
        True,
        "0735fb121551104cd55c7da2e43a494f01ad820ad9c7cb4c715f3b8673d12be9",
    ),
    "firms_kilauea": (
        _firms_kilauea,
        "da2cb379-398d-4ba3-974e-581e8242b17e",
        "28ae22cf39edb9243eb3274f784663c36221927649be3af5d58c7bcb8ac1cae4",
        0.232111,
        0.0,
        0.174083,
        "low",
        True,
        "f4b894067909f80c1efb7652d1f4cfd0967b8337d4fdd2a3da5cf9889b353300",
    ),
    "donki_cme": (
        lambda: _donki("CME"),
        "e7b687c3-5a62-4749-aacd-82d12f4eb35a",
        "f87a4f9fd80c31fd080a9aed1ede96f0b777df5f9ef1168832fd8115732e3f02",
        0.214985,
        0.0,
        0.161239,
        "low",
        True,
        "066c7399dec42c98c188d2e3131392de8ee99123b433035002503671b753803b",
    ),
    "donki_gst": (
        lambda: _donki("GST"),
        "1ab556f0-3b83-4e80-aedc-41d55bdd0015",
        "b2e3ca1b8740c042463de38114cb311a2d3e934b025cb8f76f67d9fc81f39171",
        0.593081,
        0.0,
        0.444811,
        "moderate",
        True,
        "fa39bb24a1da5a34bdce2dc074b2245f61865f7418a326de045e975a0dbcc205",
    ),
    "marine_wave_height": (
        lambda: _marine(
            "marine_high_waves_forecast", wave_height=[3.5] + [1.0] * 11
        ),
        "e30325f7-96f5-47d5-80c2-8a91765c0ae7",
        "31df421efbfc4328f6a3fd5b420b23a00e7c7f65a999621d7bed0ecc3e7afca8",
        1.0,
        0.0,
        0.75,
        "urgent",
        True,
        "7538fa6dde732341482ecd39bbde88773eb82b2a6010ff781210781ddfbeea5e",
    ),
    "marine_swell": (
        lambda: _marine(
            "marine_high_swell_forecast", swell_wave_height=[2.8] + [1.0] * 11
        ),
        "4f7d9bb9-33d4-4a30-99ce-ff314d5028d0",
        "f2f5f4c7c2efbd15e53af5f6a285670f681998bc36d79e507eab9b2b0c89bfd2",
        1.0,
        0.0,
        0.75,
        "urgent",
        True,
        "da93cac69709706c9631d9c202c2d92344738b4aed4b67e57fd88fbb7030ae5a",
    ),
    "usgs_earthquake": (
        _earthquake,
        "97b9230e-dcb0-460e-bec9-7a7ddf696dd5",
        "025b4722acf8673a1748856f0a30d5fe8a2b5b0afb1e48d1a75e16f5744cb172",
        0.0,
        0.0,
        0.0,
        "low",
        False,
        "f71e3be700119314967c98bcc8e746a107cec9a9411a6018136e808dffed52de",
    ),
    # low_visibility has an explicit research-line concept in profile v6.
    "weather_low_visibility": (
        lambda: next(
            event
            for event in weather_result(
                hourly_payload(visibility=[2500.0] + [10000.0] * 11)
            ).events
            if event.category == "weather_low_visibility_forecast"
        ),
        "259b2c61-01ca-43c3-90d8-fb5eb8ff8bfd",
        "6deebef9e3024de9a128acf67fd8793130691fb83ad1d084f6ee5abe9bf93c5c",
        0.0476,
        0.0,
        0.0357,
        "low",
        True,
        "b92d6eb5165b610e2a1d5357bf5cd0ba6976d79ca110ae7c2a0312e8df649c5e",
    ),
    "regional_only": (
        _regional_only,
        "035f08db-609a-45fd-93a9-3c1c98db50b8",
        "1d05893b4c0dc50d6f8eee255ab8e4e6808cd30955a6a7ecab258301b442e0b6",
        1.0,
        0.0,
        0.75,
        "urgent",
        False,
        "0c99552ffaa3dc95e62972a40c3f35a214e514a6654b3d3541331f9d26c21048",
    ),
    "dust_cams": (
        _dust_cams,
        "978abdec-90e4-45c4-8d01-710bbd8b51c1",
        "40bc280b9f2a03ce292817682d59ac633c425c38df4e2bf114be10d6d86dd757",
        1.0,
        0.87057,
        0.967642,
        "urgent",
        True,
        "501d4928845fd86777e02e1a004032824a9fcf5cd4088b1ad7f483f11ff01ba5",
    ),
}


@pytest.mark.parametrize("case_name", CASES)
def test_scientific_architecture_regression_baseline(case_name):
    (
        event_factory,
        event_id,
        fingerprint_digest,
        relevance_score,
        significance_score,
        priority_score,
        priority_level,
        eligible,
        signal_id,
    ) = CASES[case_name]
    event = event_factory()

    taxonomy = load_taxonomy(ROOT / "taxonomy")
    fingerprint = ConceptFingerprintEngine(
        TaxonomyIndex(taxonomy), _configs(taxonomy.version)[0]
    ).build(event)
    fingerprint_payload = fingerprint.model_dump(
        mode="json", exclude={"generated_at"}
    )
    canonical_fingerprint = json.dumps(
        fingerprint_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )

    signals, _, eligible_ids = _pipeline_with_eligibility((event,), settings())
    signal = signals[0]

    assert str(event.id) == event_id
    assert str(fingerprint.event_id) == event_id
    assert hashlib.sha256(canonical_fingerprint.encode()).hexdigest() == fingerprint_digest
    assert signal.relevance_score == relevance_score
    assert signal.significance_score == significance_score
    assert signal.priority_score == priority_score
    assert signal.priority_level.value == priority_level
    assert (signal.id in eligible_ids) is eligible
    assert signal.id == signal_id
    assert signal.representative_event_id == event_id
