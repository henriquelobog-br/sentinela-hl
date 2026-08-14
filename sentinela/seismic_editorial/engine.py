"""Editorial Sismologia v1: Event canonico -> conteudo editorial.

Deterministica e read-only: usa somente metadados do Event e evidencias
estruturadas, sem rede, banco, LLM ou conhecimento tectonico externo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any

from sentinela.core.models import Event

from .models import SeismicEditorialContent

_MONTHS = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)
_COUNTRIES = {
    "Indonesia": ("na Indonésia", "Indonésia"),
    "Papua New Guinea": ("em Papua-Nova Guiné", "Papua-Nova Guiné"),
    "Philippines": ("nas Filipinas", "Filipinas"),
    "Russia": ("na Rússia", "Rússia"),
}
_ALERTS = {"green": "verde"}
_RELATIVE_PLACE = re.compile(
    r"^(?P<distance>\d+(?:\.\d+)?) km (?P<direction>S|ESE|SSW|ENE) of "
    r"(?P<locality>[^,]+?)(?:, (?P<country>.+))?$"
)
_KNOWN_EVIDENCE_FIELDS = (
    "magnitude",
    "magnitude_type",
    "place",
    "depth_km",
    "latitude",
    "longitude",
    "alert",
    "occurred_at",
    "source",
)


@dataclass(frozen=True)
class _Location:
    kind: str
    title_phrase: str
    precise_phrase: str
    seo_phrase: str
    keywords: tuple[str, ...]
    precise_in_title: bool = False


@dataclass(frozen=True)
class _Facts:
    magnitude: Decimal | None
    magnitude_type: str | None
    location: _Location | None
    depth_km: Decimal | None
    latitude: Decimal | None
    longitude: Decimal | None
    alert: str | None
    occurred_at: datetime | None
    source: str | None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _number_pt(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return (rendered or "0").replace(".", ",")


def _magnitude(value: Decimal | None) -> str | None:
    return _number_pt(value) if value is not None else None


def _depth(value: Decimal | None) -> tuple[str, bool] | None:
    if value is None:
        return None
    rounded = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if rounded == rounded.to_integral():
        rounded = rounded.to_integral()
    return _number_pt(rounded), rounded != value


def _country(country: str | None) -> tuple[str, str]:
    if not country:
        return "", ""
    article, keyword = _COUNTRIES.get(country, (f"em {country}", country))
    return f", {article}", keyword


def _location(place: str | None) -> _Location | None:
    if not place:
        return None
    if place == "west of Macquarie Island":
        return _Location(
            kind="west",
            title_phrase="na região da Ilha Macquarie",
            precise_phrase="a oeste da Ilha Macquarie",
            seo_phrase="na região da Ilha Macquarie",
            keywords=("Ilha Macquarie",),
        )
    if place == "Kermadec Islands region":
        return _Location(
            kind="region",
            title_phrase="na região das Ilhas Kermadec",
            precise_phrase="na região das Ilhas Kermadec",
            seo_phrase="nas Ilhas Kermadec",
            keywords=("Ilhas Kermadec",),
            precise_in_title=True,
        )

    match = _RELATIVE_PLACE.fullmatch(place)
    if match:
        distance = _number_pt(Decimal(match.group("distance")))
        direction = match.group("direction")
        locality = match.group("locality")
        country_suffix, country_keyword = _country(match.group("country"))
        keywords = tuple(
            item for item in (locality, country_keyword) if item
        )
        directions = {
            "S": ("south", "ao sul de"),
            "ESE": ("east_southeast", "a leste-sudeste de"),
            "SSW": ("south_southwest", "ao sul-sudoeste de"),
            "ENE": ("east_northeast", "a leste-nordeste de"),
        }
        kind, direction_phrase = directions[direction]
        phrase = f"{direction_phrase} {locality}{country_suffix}"
        if direction == "S":
            return _Location(
                kind=kind,
                title_phrase=phrase,
                precise_phrase=f"cerca de {distance} km {phrase}",
                seo_phrase=f"{direction_phrase} {locality}",
                keywords=keywords,
                precise_in_title=True,
            )
        if direction == "SSW" and Decimal(match.group("distance")) >= 100:
            return _Location(
                kind=kind,
                title_phrase=phrase,
                precise_phrase=f"cerca de {distance} km {phrase}",
                seo_phrase=f"{direction_phrase} {locality}",
                keywords=keywords,
                precise_in_title=True,
            )
        return _Location(
            kind=kind,
            title_phrase=f"próximo a {locality}{country_suffix}",
            precise_phrase=(
                f"cerca de {distance} km {direction_phrase} "
                f"{locality}{country_suffix}"
            ),
            seo_phrase=f"próximo a {locality}",
            keywords=keywords,
        )

    return _Location(
        kind="literal",
        title_phrase=f'com localização informada como "{place}"',
        precise_phrase=f'com localização informada como "{place}"',
        seo_phrase=f'com localização informada como "{place}"',
        keywords=(),
        precise_in_title=True,
    )


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _utc_datetime(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _date_pt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (
        f"{value.day} de {_MONTHS[value.month - 1]} de {value.year}, "
        f"às {value:%Hh%M} UTC"
    )


def _evidence(event: Event) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for item in event.evidence:
        if not isinstance(item, dict):
            continue
        for field in _KNOWN_EVIDENCE_FIELDS:
            if field not in facts and item.get(field) is not None:
                facts[field] = item[field]
    return facts


def _facts(event: Event) -> _Facts:
    evidence = _evidence(event)
    return _Facts(
        magnitude=_decimal(evidence.get("magnitude")),
        magnitude_type=_text(evidence.get("magnitude_type")),
        location=_location(_text(evidence.get("place"))),
        depth_km=_decimal(evidence.get("depth_km")),
        latitude=_decimal(evidence.get("latitude")),
        longitude=_decimal(evidence.get("longitude")),
        alert=_text(evidence.get("alert")),
        occurred_at=_utc_datetime(
            event.occurred_at or _datetime(evidence.get("occurred_at"))
        ),
        source=_text(event.source) or _text(evidence.get("source")),
    )


def _depth_phrase(depth_km: Decimal | None) -> str | None:
    depth = _depth(depth_km)
    if depth is None:
        return None
    value, approximate = depth
    qualifier = "aproximadamente " if approximate else ""
    return f"a {qualifier}{value} km de profundidade"


def _depth_measure(depth_km: Decimal | None) -> str | None:
    depth = _depth(depth_km)
    if depth is None:
        return None
    value, approximate = depth
    qualifier = "aproximadamente " if approximate else ""
    return f"{qualifier}{value} km"


def _title(facts: _Facts) -> str:
    magnitude = _magnitude(facts.magnitude)
    magnitude_phrase = f" de magnitude {magnitude}" if magnitude else ""
    location = facts.location
    if location and location.kind == "region":
        region = location.title_phrase.removeprefix("na ")
        region = region[0].upper() + region[1:]
        return (
            f"{region} registra terremoto{magnitude_phrase}"
        )
    if location and location.kind in {"west", "east_northeast"} and facts.source:
        return (
            f"{facts.source} registra terremoto{magnitude_phrase} "
            f"{location.title_phrase}"
        )
    if location and (
        location.kind == "east_southeast"
        or (location.kind == "south_southwest" and not location.precise_in_title)
    ):
        return (
            f"Terremoto{magnitude_phrase} ocorre {location.title_phrase}"
        )
    title = f"Terremoto{magnitude_phrase} é registrado"
    if location:
        title += f" {location.title_phrase}"
    return title


def _subtitle(facts: _Facts) -> str:
    location = facts.location
    depth = _depth_phrase(facts.depth_km)
    if location and location.kind == "west":
        suffix = f", {depth}" if depth else ""
        return f"O evento foi localizado {location.precise_phrase}{suffix}."
    if location and location.kind in {"east_southeast", "east_northeast"}:
        return f"A localização indicada fica {location.precise_phrase}."
    if location and location.kind == "south_southwest":
        return f"O registro situa o evento {location.precise_phrase}."
    coordinates = _coordinates(facts)
    if not location and coordinates:
        return f"A localização foi informada pelas coordenadas {coordinates}."
    if depth:
        return f"O evento ocorreu {depth}."
    if facts.alert:
        alert = _ALERTS.get(facts.alert.lower(), facts.alert)
        return f"O registro oficial apresenta alerta {alert}."
    if (
        facts.magnitude_type
        and not facts.occurred_at
        and not facts.source
    ):
        return f"A magnitude foi classificada como {facts.magnitude_type}."
    return ""


def _coordinates(facts: _Facts) -> str | None:
    if facts.latitude is None or facts.longitude is None:
        return None
    return (
        f"latitude {_number_pt(facts.latitude)} e "
        f"longitude {_number_pt(facts.longitude)}"
    )


def _summary(facts: _Facts) -> str:
    date = _date_pt(facts.occurred_at)
    source = facts.source
    location = facts.location
    depth = _depth_phrase(facts.depth_km)
    depth_measure = _depth_measure(facts.depth_km)
    paragraphs: list[str] = []

    if location and location.kind == "south":
        lead = f"O {source} registrou a ocorrência" if source else "A ocorrência foi registrada"
        if date:
            lead += f" em {date}"
        lead += f", {location.precise_phrase}."
        paragraphs.append(lead)
    elif location and location.kind == "west":
        lead = "A ocorrência foi registrada"
        if date:
            lead += f" em {date}"
        paragraphs.append(lead + ".")
    elif location and location.kind == "region":
        lead = f"Segundo o registro do {source}, o terremoto ocorreu" if source else "O terremoto ocorreu"
        if date:
            lead += f" em {date}"
        paragraphs.append(lead + ".")
    elif location and location.kind == "east_southeast":
        lead = f"Com profundidade de {depth_measure}, o evento foi registrado" if depth_measure else "O evento foi registrado"
        if source:
            lead += f" pelo {source}"
        if date:
            lead += f" em {date}"
        paragraphs.append(lead + ".")
    elif location and location.kind == "east_northeast":
        lead = "A ocorrência foi registrada"
        if date:
            lead += f" em {date}"
        if depth_measure:
            lead += f", com profundidade de {depth_measure}"
        paragraphs.append(lead + ".")
    elif location and location.kind == "south_southwest":
        if location.precise_in_title:
            lead = f"O evento consta no registro do {source}" if source else "O evento foi registrado"
            if date:
                lead += f" em {date}"
            if depth_measure:
                lead += f", com profundidade de {depth_measure}"
        else:
            lead = f"Segundo o registro do {source}, o evento ocorreu" if source else "O evento ocorreu"
            if date:
                lead += f" em {date}"
            if depth:
                lead += f", {depth}"
        paragraphs.append(lead + ".")
    else:
        lead = "A ocorrência foi registrada"
        if date:
            lead += f" em {date}"
        if source:
            lead += f" pelo {source}"
        if depth:
            lead += f", {depth}"
        if not date and not source:
            lead = ""
        if lead:
            paragraphs.append(lead + ".")

    if facts.alert:
        alert = _ALERTS.get(facts.alert.lower(), facts.alert)
        paragraphs.append(f"O registro apresenta alerta {alert}.")

    return "\n\n".join(paragraphs[:2])


def _seo_title(facts: _Facts) -> str:
    magnitude = _magnitude(facts.magnitude)
    title = "Terremoto"
    if magnitude:
        title += f" de magnitude {magnitude}"
    if facts.location and facts.location.kind != "literal":
        title += f" {facts.location.seo_phrase}"
    return title


def _seo_description(facts: _Facts) -> str:
    magnitude = _magnitude(facts.magnitude)
    text = "Terremoto"
    if magnitude:
        text += f" de magnitude {magnitude}"
    text += " foi registrado"
    if facts.location:
        location = (
            facts.location.precise_phrase
            if facts.location.kind in {
                "south",
                "east_southeast",
                "south_southwest",
                "east_northeast",
                "west",
            }
            else facts.location.seo_phrase
        )
        text += f" {location}"
    depth = _depth_phrase(facts.depth_km)
    if depth:
        text += f", {depth}"
    if facts.occurred_at:
        dated = (
            f"{text}, em {facts.occurred_at.day} de "
            f"{_MONTHS[facts.occurred_at.month - 1]} de "
            f"{facts.occurred_at.year}."
        )
        if len(dated) <= 180:
            return dated
    return text + "."


def _seo_keywords(facts: _Facts) -> tuple[str, ...]:
    values = ["terremoto"]
    magnitude = _magnitude(facts.magnitude)
    if magnitude:
        values.append(f"magnitude {magnitude}")
    if facts.location:
        values.extend(facts.location.keywords)
    if facts.source:
        values.append(facts.source)
    values.append("sismologia")
    return tuple(dict.fromkeys(values))[:8]


class SeismicEditorialEngine:
    """Constroi uma projecao editorial sem modificar o Event de entrada."""

    def build(self, event: Event) -> SeismicEditorialContent:
        if event.category not in (None, "earthquake_detected"):
            raise ValueError("Event não pertence à categoria sísmica suportada")
        if event.scientific_area not in (None, "seismology"):
            raise ValueError("Event não pertence à área sismológica suportada")

        facts = _facts(event)
        return SeismicEditorialContent(
            editorial_title=_title(facts),
            editorial_subtitle=_subtitle(facts),
            editorial_summary=_summary(facts),
            seo_title=_seo_title(facts),
            seo_description=_seo_description(facts),
            seo_keywords=_seo_keywords(facts),
        )


__all__ = ["SeismicEditorialEngine"]
