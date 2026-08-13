"""Coletor oficial ACLED com OAuth em memória e eventos factuais."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timedelta, timezone
from typing import Any

import httpx

from sentinela.core.models import EpistemicStatus, Event, EventStatus

from .collectors import CollectionResult, _uuid
from .config import RealSignalSettings

ACLED_API_URL = "https://acleddata.com/api/acled/read"
ACLED_TOKEN_URL = "https://acleddata.com/oauth/token"
ACLED_COUNTRIES = (
    "Israel", "Palestine", "Lebanon", "Iran", "Syria", "Jordan", "Egypt",
    "Yemen", "Saudi Arabia", "United Arab Emirates", "Bahrain", "Morocco",
)
ACLED_FIELDS = (
    "event_id_cnty", "event_date", "year", "disorder_type", "event_type",
    "sub_event_type", "actor1", "assoc_actor_1", "actor2", "assoc_actor_2",
    "interaction", "region", "country", "admin1", "admin2", "admin3",
    "location", "latitude", "longitude", "geo_precision", "source",
    "source_scale", "notes", "fatalities", "timestamp",
)

_TYPE_MAP = {
    "Battles": ("acled_battle_event", "Evento de conflito", ("conflict", "military_action")),
    "Explosions/Remote violence": ("acled_explosion_remote_violence", "Explosão ou violência remota", ("conflict", "military_action")),
    "Violence against civilians": ("acled_violence_against_civilians", "Violência contra civis", ("conflict",)),
    "Protests": ("acled_protest", "Protesto", ("protest",)),
    "Riots": ("acled_riot", "Distúrbio", ("protest", "conflict")),
    "Strategic developments": ("acled_strategic_development", "Desenvolvimento estratégico", ()),
}
_COUNTRY_CONCEPT = {"Israel": "israel", "Palestine": "palestine", "Iran": "iran"}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _event_date(value: str) -> datetime:
    parsed = datetime.strptime(value, "%Y-%m-%d").date()
    return datetime.combine(parsed, time.min, tzinfo=timezone.utc)


def _strategic_concepts(row: dict[str, Any]) -> tuple[str, ...]:
    factual = " ".join((_clean(row.get("sub_event_type")), _clean(row.get("notes")))).lower()
    concepts = []
    if "ceasefire" in factual or "cease-fire" in factual or "truce" in factual:
        concepts.append("ceasefire")
    if "peace agreement" in factual or "peace process" in factual:
        concepts.append("peace")
    if "diplomatic" in factual or "diplomacy" in factual:
        concepts.append("diplomacy")
    return tuple(concepts)


class AcledCollector:
    def __init__(self, settings: RealSignalSettings, client: Any | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds)
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    def collect(self, now: datetime) -> CollectionResult:
        if not self.settings.acled_username or not self.settings.acled_password:
            return CollectionResult(source="acled", error="credenciais ACLED ausentes")
        try:
            self._authenticate()
            rows = self._pages(now)
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f"HTTP {status}" if status else type(exc).__name__
            return CollectionResult(source="acled", error=f"{detail}: falha na consulta ACLED")

        start = now.astimezone(timezone.utc).date() - timedelta(days=self.settings.acled_lookback_days)
        allowed = set(ACLED_COUNTRIES)
        latest: dict[str, dict[str, Any]] = {}
        discarded = 0
        duplicates = 0
        for row in rows:
            identifier = _clean(row.get("event_id_cnty"))
            try:
                occurred = _event_date(_clean(row.get("event_date")))
            except ValueError:
                discarded += 1
                continue
            if not identifier or row.get("country") not in allowed or not start <= occurred.date() <= now.date():
                discarded += 1
                continue
            previous = latest.get(identifier)
            if previous is not None:
                duplicates += 1
                if _integer(row.get("timestamp")) <= _integer(previous.get("timestamp")):
                    continue
            latest[identifier] = row

        events = tuple(self._to_event(row, now) for row in sorted(
            latest.values(), key=lambda item: (_clean(item.get("event_date")), _clean(item.get("event_id_cnty")))
        ) if _clean(row.get("event_type")) in _TYPE_MAP)
        type_counts = Counter(event.evidence[0]["event_type"] for event in events)
        country_counts = Counter(event.country for event in events)
        fatalities = sum(event.evidence[0]["fatalities"] for event in events)
        notice = "; ".join((
            "countries=" + ",".join(f"{key}:{value}" for key, value in sorted(country_counts.items())),
            "event_types=" + ",".join(f"{key}:{value}" for key, value in sorted(type_counts.items())),
            f"fatalities_reported={fatalities}",
        ))
        details = tuple({
            "source": "ACLED", "region": event.country,
            "variable": event.evidence[0]["event_type"],
            "value": event.evidence[0]["fatalities"],
            "unit": "fatalities_reported",
            "sub_event_type": event.evidence[0]["sub_event_type"],
        } for event in events)
        return CollectionResult(
            source="acled", received=len(rows), discarded=discarded,
            duplicates=duplicates, events=events, notice=notice, details=details,
        )

    def _authenticate(self) -> None:
        response = self.client.post(ACLED_TOKEN_URL, data={
            "username": self.settings.acled_username,
            "password": self.settings.acled_password,
            "grant_type": "password", "client_id": "acled", "scope": "authenticated",
        }, headers={"content-type": "application/x-www-form-urlencoded"})
        response.raise_for_status()
        self._set_tokens(response.json())

    def _refresh(self) -> None:
        if not self._refresh_token:
            raise RuntimeError("refresh token ACLED ausente")
        response = self.client.post(ACLED_TOKEN_URL, data={
            "refresh_token": self._refresh_token,
            "grant_type": "refresh_token", "client_id": "acled",
        }, headers={"content-type": "application/x-www-form-urlencoded"})
        response.raise_for_status()
        self._set_tokens(response.json())

    def _set_tokens(self, payload: dict[str, Any]) -> None:
        access_token = _clean(payload.get("access_token"))
        if not access_token:
            raise ValueError("token ACLED inválido")
        self._access_token = access_token
        self._refresh_token = _clean(payload.get("refresh_token")) or self._refresh_token

    def _pages(self, now: datetime) -> list[dict[str, Any]]:
        start = now.astimezone(timezone.utc).date() - timedelta(days=self.settings.acled_lookback_days)
        page = 1
        rows: list[dict[str, Any]] = []
        while True:
            params = {
                "_format": "json", "country": "|".join(ACLED_COUNTRIES),
                "event_date": f"{start.isoformat()}|{now.date().isoformat()}",
                "event_date_where": "BETWEEN", "fields": "|".join(ACLED_FIELDS),
                "limit": self.settings.acled_limit, "page": page, "with_total": "true",
            }
            response = self.client.get(ACLED_API_URL, params=params, headers={
                "authorization": f"Bearer {self._access_token}", "accept": "application/json",
            })
            if response.status_code == 401 and self._refresh_token:
                self._refresh()
                response = self.client.get(ACLED_API_URL, params=params, headers={
                    "authorization": f"Bearer {self._access_token}", "accept": "application/json",
                })
            response.raise_for_status()
            payload = response.json()
            if payload.get("success") is False or _integer(payload.get("status"), 200) != 200:
                raise ValueError("resposta ACLED inválida")
            batch = payload.get("data")
            if not isinstance(batch, list):
                raise ValueError("dados ACLED inválidos")
            rows.extend(item for item in batch if isinstance(item, dict))
            total = _integer(payload.get("count"), len(rows))
            if not batch or len(rows) >= total or len(batch) < self.settings.acled_limit:
                return rows
            page += 1

    def _to_event(self, row: dict[str, Any], now: datetime) -> Event:
        event_type = _clean(row["event_type"])
        category, title_prefix, base_concepts = _TYPE_MAP[event_type]
        country = _clean(row.get("country"))
        location = _clean(row.get("location")) or "local não informado"
        occurred = _event_date(_clean(row["event_date"]))
        actor1 = _clean(row.get("actor1"))
        actor2 = _clean(row.get("actor2"))
        actors = " e ".join(value for value in (actor1, actor2) if value) or "não informados"
        fatalities = max(0, _integer(row.get("fatalities")))
        summary = (
            f"A ACLED registrou um evento classificado como {event_type}/"
            f"{_clean(row.get('sub_event_type')) or 'subtipo não informado'} em "
            f"{location}, {country}, em {occurred.date().isoformat()}. "
            f"Atores reportados: {actors}."
        )
        if fatalities:
            summary += f" ACLED registra {fatalities} fatalidades associadas ao evento."
        concepts = list(base_concepts)
        if event_type == "Strategic developments":
            concepts.extend(_strategic_concepts(row))
        if country in _COUNTRY_CONCEPT:
            concepts.append(_COUNTRY_CONCEPT[country])
        if _clean(row.get("region")) == "Middle East":
            concepts.append("middle_east")
        identifier = _clean(row["event_id_cnty"])
        raw_fields = {field: row.get(field) for field in ACLED_FIELDS}
        evidence = dict(raw_fields)
        evidence.update({
            "source": "ACLED", "product": "ACLED event dataset",
            "acled_source": raw_fields["source"], "raw_fields": raw_fields,
            "raw_identifiers": {"event_id_cnty": identifier, "timestamp": row.get("timestamp")},
            "retrieved_at": now.isoformat(), "fatalities": fatalities,
            "latitude": _float(row.get("latitude")), "longitude": _float(row.get("longitude")),
        })
        entities = [
            {"name": value, "type": kind}
            for value, kind in ((actor1, "actor"), (actor2, "actor"), (location, "place")) if value
        ]
        stable_id = _uuid(f"acled-event|{identifier}")
        return Event(
            id=stable_id, primary_claim_id=stable_id,
            title=f"{title_prefix} registrado em {location}, {country}", summary=summary,
            epistemic_status=EpistemicStatus.CONFIRMED_FACT, category=category,
            event_status=EventStatus.REPORTED_EVENT,
            source="ACLED",
            country=country, scientific_area="scientific_geopolitics",
            entities=entities, keywords=list(dict.fromkeys(concepts)),
            evidence=[{"text": base_concepts[0] if base_concepts else (concepts[0] if concepts else "strategic_development"), **evidence}],
            occurred_at=occurred, validated_at=occurred,
        )


def possible_cross_source_matches(
    acled_events: tuple[Event, ...], gdelt_events: tuple[Event, ...],
) -> tuple[dict[str, str], ...]:
    matches = []
    for acled in acled_events:
        a_evidence = acled.evidence[0]
        a_location = " ".join((str(a_evidence.get("location") or ""), acled.country or "")).lower()
        a_actors = {word.lower() for entity in acled.entities if entity.get("type") == "actor" for word in str(entity.get("name", "")).split() if len(word) >= 4}
        a_categories = set(acled.keywords) & {"conflict", "military_action", "protest", "ceasefire", "peace", "diplomacy"}
        for gdelt in gdelt_events:
            if not acled.occurred_at or not gdelt.occurred_at or abs((acled.occurred_at - gdelt.occurred_at).total_seconds()) > 86400:
                continue
            g_evidence = gdelt.evidence[0]
            g_location = " ".join((str(g_evidence.get("action_geo") or ""), str(g_evidence.get("action_geo_country_code") or ""))).lower()
            g_actors = {word.lower() for entity in gdelt.entities if entity.get("type") == "actor" for word in str(entity.get("name", "")).split() if len(word) >= 4}
            g_categories = set(gdelt.keywords) & {"conflict", "military_action", "protest", "ceasefire", "peace", "diplomacy"}
            same_place = bool(acled.country and acled.country.lower() in g_location) or any(part in g_location for part in a_location.split() if len(part) >= 5)
            if same_place and a_actors & g_actors and a_categories & g_categories:
                matches.append({
                    "kind": "possible_cross_source_match",
                    "acled_event_id": str(acled.id), "gdelt_event_id": str(gdelt.id),
                })
    return tuple(matches)


__all__ = ["ACLED_COUNTRIES", "AcledCollector", "possible_cross_source_matches"]
