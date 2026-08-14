from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from sentinela.core.models import EpistemicStatus, Event, EventStatus


def seismic_event(
    *,
    event_id: str = "00000000-0000-0000-0000-000000000001",
    source_event_id: str = "us-test",
    magnitude: float | None = 5.0,
    magnitude_type: str | None = "mww",
    place: str | None = "local de teste",
    depth_km: float | None = 10.0,
    latitude: float | None = -20.0,
    longitude: float | None = -40.0,
    alert: str | None = None,
    occurred_at: datetime | None = datetime(2026, 8, 13, 12, tzinfo=timezone.utc),
    source: str | None = "USGS",
) -> Event:
    evidence = {
        "source_event_id": source_event_id,
        "magnitude": magnitude,
        "magnitude_type": magnitude_type,
        "place": place,
        "depth_km": depth_km,
        "latitude": latitude,
        "longitude": longitude,
        "alert": alert,
        "tsunami": 0,
        "source": source,
    }
    return Event(
        id=UUID(event_id),
        title="Texto legado não usado como fonte editorial",
        summary="Resumo legado não usado como fonte editorial",
        epistemic_status=EpistemicStatus.CONFIRMED_FACT,
        event_status=EventStatus.OBSERVED_FACT,
        category="earthquake_detected",
        source=source,
        scientific_area="seismology",
        occurred_at=occurred_at,
        validated_at=occurred_at,
        evidence=[evidence],
    )


@pytest.fixture
def sarangani_event() -> Event:
    return seismic_event(
        event_id="605eed2b-22da-4223-b7f5-25ccc8d4c6ca",
        source_event_id="us6000tkig",
        magnitude=5.3,
        magnitude_type="mww",
        place="11 km S of Sarangani, Philippines",
        depth_km=66.312,
        latitude=5.3002,
        longitude=125.4836,
        occurred_at=datetime(2026, 8, 13, 18, 39, 31, 327000, timezone.utc),
    )


@pytest.fixture
def macquarie_event() -> Event:
    return seismic_event(
        event_id="29fe63f5-c7b8-459d-8964-0d91d380e8d2",
        source_event_id="us6000tki8",
        magnitude=5.1,
        magnitude_type="mww",
        place="west of Macquarie Island",
        depth_km=10.0,
        latitude=-56.8562,
        longitude=147.2281,
        occurred_at=datetime(2026, 8, 13, 17, 39, 29, 650000, timezone.utc),
    )


@pytest.fixture
def kermadec_event() -> Event:
    return seismic_event(
        event_id="6995d5f0-2984-4b78-8bb6-e8b508f4d9a1",
        source_event_id="us6000tkhm",
        magnitude=5.6,
        magnitude_type="mww",
        place="Kermadec Islands region",
        depth_km=10.0,
        latitude=-28.6742,
        longitude=-176.3124,
        alert="green",
        occurred_at=datetime(2026, 8, 13, 16, 11, 45, 826000, timezone.utc),
    )


@pytest.fixture
def gambiran_event() -> Event:
    return seismic_event(
        event_id="614b7f87-0c17-46d2-ae20-807248ea6ef6",
        source_event_id="us6000tkg4",
        magnitude=4.6,
        magnitude_type="mb",
        place="3 km ESE of Gambiran Satu, Indonesia",
        depth_km=145.679,
        latitude=-8.4115,
        longitude=114.1762,
        occurred_at=datetime(2026, 8, 13, 10, 23, 19, 536000, timezone.utc),
    )


@pytest.fixture
def angoram_event() -> Event:
    return seismic_event(
        event_id="5b81c531-0f40-4e03-8a0b-3f58a1486b82",
        source_event_id="us6000tkgn",
        magnitude=5.0,
        magnitude_type="mb",
        place="45 km SSW of Angoram, Papua New Guinea",
        depth_km=134.025,
        latitude=-4.4318,
        longitude=143.8885,
        occurred_at=datetime(2026, 8, 13, 12, 44, 59, 102000, timezone.utc),
    )


@pytest.fixture
def lapuan_event() -> Event:
    return seismic_event(
        event_id="cc21eec7-9498-41ba-9e60-0fca0742963d",
        source_event_id="us6000tkfh",
        magnitude=5.1,
        magnitude_type="mww",
        place="22 km ENE of Lapuan, Philippines",
        depth_km=91.206,
        latitude=6.2479,
        longitude=125.8789,
        occurred_at=datetime(2026, 8, 13, 9, 22, 58, 999000, timezone.utc),
    )


@pytest.fixture
def severo_kurilsk_event() -> Event:
    return seismic_event(
        event_id="e2e0a73c-49b3-48e8-9f1f-d8fe5d074b9e",
        source_event_id="us6000tkeb",
        magnitude=4.5,
        magnitude_type="mb",
        place="222 km SSW of Severo-Kuril’sk, Russia",
        depth_km=35.0,
        latitude=48.738,
        longitude=155.3646,
        occurred_at=datetime(2026, 8, 13, 7, 9, 24, 608000, timezone.utc),
    )
