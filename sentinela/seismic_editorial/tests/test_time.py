from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import time

from sentinela.seismic_editorial import SeismicEditorialEngine

from .conftest import seismic_event


def test_datetime_aware_e_convertido_explicitamente_para_utc():
    event = seismic_event(
        occurred_at=datetime(
            2026,
            8,
            13,
            15,
            39,
            tzinfo=timezone(timedelta(hours=-3)),
        )
    )

    content = SeismicEditorialEngine().build(event)

    assert "13 de agosto de 2026, às 18h39 UTC" in content.editorial_summary


def test_conversao_utc_preserva_mudanca_de_data_no_seo():
    event = seismic_event(
        occurred_at=datetime(
            2026,
            8,
            13,
            23,
            30,
            tzinfo=timezone(timedelta(hours=-3)),
        )
    )

    content = SeismicEditorialEngine().build(event)

    assert "14 de agosto de 2026, às 02h30 UTC" in content.editorial_summary
    assert "14 de agosto de 2026" in content.seo_description


def test_occurred_at_da_evidencia_tambem_e_normalizado_para_utc():
    event = seismic_event(occurred_at=None)
    event.evidence[0]["occurred_at"] = "2026-08-13T15:39:00-03:00"

    content = SeismicEditorialEngine().build(event)

    assert "13 de agosto de 2026, às 18h39 UTC" in content.editorial_summary


def test_datetime_sem_timezone_nao_e_rotulado_como_utc():
    event = seismic_event(occurred_at=datetime(2026, 8, 13, 15, 39))

    content = SeismicEditorialEngine().build(event)

    assert "UTC" not in content.editorial_summary
    assert "13 de agosto de 2026" not in content.seo_description


def test_saida_e_independente_do_timezone_local():
    event = seismic_event(
        occurred_at=datetime(
            2026,
            8,
            13,
            15,
            39,
            tzinfo=timezone(timedelta(hours=-3)),
        )
    )
    original_tz = os.environ.get("TZ")
    outputs = []
    try:
        for local_tz in ("UTC", "America/Sao_Paulo"):
            os.environ["TZ"] = local_tz
            time.tzset()
            outputs.append(SeismicEditorialEngine().build(event))
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()

    assert outputs[0] == outputs[1]
    assert "13 de agosto de 2026, às 18h39 UTC" in outputs[0].editorial_summary
