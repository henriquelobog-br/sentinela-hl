"""Editorial Vulcanologia v1: Events estruturados -> conteudo editorial."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
from typing import Any

from sentinela.core.models import Event

from .models import VolcanicEditorialContent, VolcanicEditorialUnit

_SUPPORTED_CATEGORIES = {
    "volcano_alert_elevated",
    "volcano_notice_published",
    "volcano_vona_published",
    "volcanic_thermal_anomaly_candidate",
}
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


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _number_pt(value: Decimal, places: int = 2) -> str:
    quantum = Decimal(1).scaleb(-places)
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    rendered = format(rounded, "f").rstrip("0").rstrip(".")
    return (rendered or "0").replace(".", ",")


def _evidence(event: Event) -> dict[str, Any]:
    return event.evidence[0] if event.evidence and isinstance(event.evidence[0], dict) else {}


def _utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _date_pt(value: datetime | None) -> str | None:
    value = _utc(value)
    if value is None:
        return None
    return (
        f"{value.day} de {_MONTHS[value.month - 1]} de {value.year}, "
        f"às {value:%Hh%M} UTC"
    )


def _date_text_pt(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _date_pt(parsed)


def _event_key(event: Event) -> tuple[datetime, str, str]:
    evidence = _evidence(event)
    occurred_at = _utc(event.occurred_at) or datetime.min.replace(tzinfo=timezone.utc)
    return (
        occurred_at,
        _text(evidence.get("notice_identifier")) or "",
        str(event.id),
    )


def _validate_event(event: Event) -> tuple[str, str, str]:
    if event.id is None:
        raise ValueError("Event.id e obrigatorio para agrupamento editorial")
    if event.scientific_area != "volcanology":
        raise ValueError("Event nao pertence a Vulcanologia")
    if event.category not in _SUPPORTED_CATEGORIES:
        raise ValueError("categoria vulcanologica nao suportada")
    evidence = _evidence(event)
    volcano_name = _text(evidence.get("volcano_name"))
    volcano_number = _text(evidence.get("volcano_number"))
    canonical_group_id = _text(evidence.get("canonical_group_id"))
    if not volcano_name or not volcano_number or not canonical_group_id:
        raise ValueError("Event vulcanologico sem identidade estruturada suficiente")
    return volcano_name, volcano_number, canonical_group_id


def _group_id(parts: tuple[str, ...]) -> str:
    return hashlib.sha256("|".join(("volcanic-editorial-v1", *parts)).encode()).hexdigest()


def group_volcanic_events(events: tuple[Event, ...]) -> tuple[VolcanicEditorialUnit, ...]:
    """Agrupa somente sequencias VONA; demais Events ficam isolados."""
    seen: dict[str, str] = {}
    grouped: dict[tuple[str, ...], list[Event]] = {}
    metadata: dict[tuple[str, ...], tuple[str, str, str]] = {}

    for event in events:
        volcano_name, volcano_number, canonical_group_id = _validate_event(event)
        event_id = str(event.id)
        serialized = event.model_dump_json()
        if event_id in seen:
            if seen[event_id] != serialized:
                raise ValueError("Event.id duplicado com payload divergente")
            continue
        seen[event_id] = serialized

        if event.category == "volcano_vona_published":
            key = ("vona", volcano_number, canonical_group_id)
            reason = "shared_vona_canonical_group"
        else:
            key = ("event", event_id)
            reason = "singleton_category_boundary"
        grouped.setdefault(key, []).append(event)
        metadata[key] = (volcano_name, volcano_number, reason)

    units = []
    for key, members in grouped.items():
        ordered = tuple(sorted(members, key=_event_key))
        volcano_name, volcano_number, reason = metadata[key]
        if any(_evidence(event).get("volcano_number") != volcano_number for event in ordered):
            raise ValueError("Events de vulcoes diferentes nao podem ser agrupados")
        representative = max(ordered, key=_event_key)
        units.append(
            VolcanicEditorialUnit(
                editorial_group_id=_group_id(key),
                volcano_name=volcano_name,
                volcano_number=volcano_number,
                category=str(representative.category),
                member_events=ordered,
                representative_event=representative,
                grouping_reason=reason,
            )
        )
    return tuple(sorted(units, key=lambda unit: (_event_key(unit.representative_event), unit.editorial_group_id)))


def _material_kind(summary: str | None) -> str | None:
    value = (summary or "").casefold()
    checks = (
        ("magnitude-5.2 earthquake", "submarine_earthquake"),
        ("seismic and infrasound events continue", "seismic_infrasound"),
        ("slow eruption of lava", "slow_lava"),
        ("low-level seismic activity continued", "low_seismicity"),
        ("no signs of unrest", "no_unrest_week"),
        ("is not erupting", "paused_episode"),
        ("ended abruptly", "episode_ended"),
        ("ended at", "episode_ended"),
        ("began at", "episode_began"),
        ("eruption continues", "episode_continues"),
        ("eruptive activity", "precursory_activity"),
    )
    return next((kind for phrase, kind in checks if phrase in value), None)


def _material_sentence(kind: str | None, volcano_name: str) -> str | None:
    values = {
        "submarine_earthquake": (
            f"O informe registra um sismo de magnitude 5,2 sob {volcano_name}, "
            "sem atribuir causa vulcânica ao evento."
        ),
        "seismic_infrasound": (
            "O comunicado relata a continuidade de eventos sísmicos e de infrassom."
        ),
        "slow_lava": (
            "O comunicado relata extrusão lenta de lava no interior da cratera do cume."
        ),
        "low_seismicity": (
            "O comunicado registra a continuidade de atividade sísmica de baixo nível."
        ),
        "no_unrest_week": (
            "O comunicado informa ausência de sinais de agitação nos dados de satélite "
            "e geofísicos distantes durante a última semana."
        ),
        "paused_episode": (
            "O comunicado informa que o vulcão não estava em erupção e que o episódio "
            "no cume estava em pausa."
        ),
        "episode_ended": "O comunicado registra o encerramento do episódio observado.",
        "episode_began": "O comunicado registra o início do episódio observado.",
        "episode_continues": "O comunicado registra a continuidade do episódio observado.",
        "precursory_activity": "O comunicado registra atividade precursora no episódio observado.",
    }
    return values.get(kind)


def _status_phrase(evidence: dict[str, Any]) -> str | None:
    alert = _text(evidence.get("alert_level"))
    color = _text(evidence.get("aviation_color_code"))
    alert = None if alert and alert.upper() == "UNASSIGNED" else alert
    color = None if color and color.upper() == "UNASSIGNED" else color
    if alert and color:
        return f"nível de alerta {alert} e código de aviação {color}"
    if alert:
        return f"nível de alerta {alert}"
    if color:
        return f"código de aviação {color}"
    return None


def _observatory(evidence: dict[str, Any]) -> str | None:
    observatory = _text(evidence.get("observatory"))
    if observatory and " " not in observatory and len(observatory) <= 5:
        return observatory.upper()
    return observatory


def _source_time_sentence(event: Event, evidence: dict[str, Any], noun: str) -> str:
    observatory = _observatory(evidence)
    source = observatory or _text(event.source) or "A fonte oficial"
    date = _date_pt(event.occurred_at)
    sentence = f"{source} publicou {noun}"
    if date:
        sentence += f" em {date}"
    return sentence + "."


def _status_sentence(evidence: dict[str, Any]) -> str | None:
    status = _status_phrase(evidence)
    return f"O registro informa {status}." if status else None


def _phenomenon_keywords(kind: str | None) -> tuple[str, ...]:
    values = {
        "submarine_earthquake": ("sismo",),
        "seismic_infrasound": ("eventos sísmicos", "infrassom"),
        "slow_lava": ("extrusão de lava",),
        "low_seismicity": ("atividade sísmica",),
        "no_unrest_week": ("monitoramento vulcânico",),
        "paused_episode": ("episódio vulcânico",),
        "episode_ended": ("episódio vulcânico",),
    }
    return values.get(kind, ("alerta vulcânico",))


def _compact_time_span(evidence: dict[str, Any]) -> str | None:
    start = _date_text_pt(evidence.get("earliest_acquisition"))
    end = _date_text_pt(evidence.get("latest_acquisition"))
    if start and end:
        return f"entre {start} e {end}"
    return start or end


def _vona_content(unit: VolcanicEditorialUnit) -> VolcanicEditorialContent:
    representative = unit.representative_event
    evidence = _evidence(representative)
    summaries = [_text(_evidence(event).get("official_summary")) for event in unit.member_events]
    kinds = tuple(dict.fromkeys(filter(None, (_material_kind(value) for value in summaries))))
    explicit_episode = any(kind in {"precursory_activity", "episode_began", "episode_continues", "episode_ended"} for kind in kinds)
    count = len(unit.member_events)
    count_text = "Quatro" if count == 4 else str(count)
    title = (
        f"Sequência VONA acompanha episódio eruptivo no {unit.volcano_name}"
        if explicit_episode
        else f"Sequência VONA reúne avisos operacionais sobre {unit.volcano_name}"
    )
    first_date = _date_pt(unit.member_events[0].occurred_at)
    last_date = _date_pt(representative.occurred_at)
    lead = f"A sequência reúne {count} avisos VONA"
    if first_date and last_date:
        lead += f" entre {first_date} e {last_date}"
    lead += "."
    phase_names = {
        "precursory_activity": "atividade precursora",
        "episode_began": "início",
        "episode_continues": "continuidade",
        "episode_ended": "encerramento",
    }
    phases = [phase_names[kind] for kind in kinds if kind in phase_names]
    phase_sentence = (
        f"Os comunicados descrevem {', '.join(phases[:-1])} e {phases[-1]} do episódio observado."
        if len(phases) > 1
        else (_material_sentence(kinds[0], unit.volcano_name) if kinds else None)
    )
    subtitle = phase_sentence or f"{count_text} avisos preservam a sequência operacional."
    source = _observatory(evidence) or "A fonte oficial"
    summary = lead
    status = _status_phrase(evidence)
    if status:
        summary += f" O aviso mais recente, emitido por {source}, apresenta {status}."
    seo_title = f"Avisos VONA sobre {unit.volcano_name}"
    seo_description = f"Sequência de {count} avisos VONA sobre {unit.volcano_name}"
    if status:
        seo_description += f", com {status} no registro mais recente"
    return VolcanicEditorialContent(
        editorial_title=title,
        editorial_subtitle=subtitle,
        editorial_summary=summary,
        seo_title=seo_title,
        seo_description=seo_description + ".",
        seo_keywords=tuple(dict.fromkeys(("vulcanologia", unit.volcano_name, "VONA", "alerta vulcânico"))),
    )


def _firms_content(unit: VolcanicEditorialUnit) -> VolcanicEditorialContent:
    event = unit.representative_event
    evidence = _evidence(event)
    count = evidence.get("hotspot_count")
    distance = _number(evidence.get("distance_to_volcano_km"))
    count_phrase = f"{count} hotspots" if count is not None else "hotspots"
    distance_phrase = (
        f" a cerca de {_number_pt(distance)} km do vulcão" if distance is not None else " próximo ao vulcão"
    )
    title = f"FIRMS identifica anomalia térmica próxima ao {unit.volcano_name}"
    time_span = _compact_time_span(evidence)
    subtitle = f"Cluster com {count_phrase}{distance_phrase}"
    if time_span:
        subtitle += f", {time_span}"
    subtitle += "."
    sensors = tuple(str(value) for value in evidence.get("sensors") or ())
    lead = f"A NASA FIRMS agrupou {count_phrase}"
    if time_span:
        lead += f" {time_span}"
    if sensors:
        lead += f", observados por {', '.join(sensors)}"
    lead += "."
    summary = (
        f"{lead} A associação é espacial e não confirma causa "
        "ou atividade vulcânica."
    )
    return VolcanicEditorialContent(
        editorial_title=title,
        editorial_subtitle=subtitle,
        editorial_summary=summary,
        seo_title=f"Anomalia térmica próxima ao {unit.volcano_name}",
        seo_description=(
            f"NASA FIRMS identifica {count_phrase}{distance_phrase}, sem confirmar atividade vulcânica."
        ),
        seo_keywords=("vulcanologia", unit.volcano_name, "NASA FIRMS", "anomalia térmica", "hotspots"),
    )


def _usgs_singleton_content(unit: VolcanicEditorialUnit) -> VolcanicEditorialContent:
    event = unit.representative_event
    evidence = _evidence(event)
    summary_value = _text(evidence.get("official_summary"))
    kind = _material_kind(summary_value)
    material = _material_sentence(kind, unit.volcano_name)
    notice_type = _text(evidence.get("notice_type"))

    if event.category == "volcano_notice_published":
        if kind == "submarine_earthquake":
            title = f"Informe oficial registra sismo sob {unit.volcano_name}"
            subtitle = (
                "O Information Statement registra magnitude 5,2 sem atribuir "
                "causa vulcânica ao evento."
            )
            noun = "o Information Statement"
        elif kind == "episode_ended":
            title = f"Relatório de status documenta encerramento de episódio no {unit.volcano_name}"
            subtitle = (
                "O Status Report reúne o início e o encerramento informados "
                "pela fonte oficial."
            )
            noun = "o Status Report"
        else:
            title = f"Comunicado vulcanológico publicado para {unit.volcano_name}"
            subtitle = material or "O comunicado preserva apenas os fatos estruturados pela fonte oficial."
            noun = "o comunicado"
        editorial_summary = " ".join(
            filter(None, (material, _source_time_sentence(event, evidence, noun)))
        )
        status_sentence = _status_sentence(evidence)
        if status_sentence:
            editorial_summary += f" {status_sentence}"
        seo_title = f"Comunicado sobre {unit.volcano_name}"
    else:
        elevated_titles = {
            "seismic_infrasound": "Shishaldin tem eventos sísmicos e de infrassom relatados",
            "slow_lava": "Great Sitkin tem extrusão lenta de lava relatada",
            "low_seismicity": "Kupreanof tem atividade sísmica de baixo nível relatada",
            "no_unrest_week": "Ahyi Seamount não apresenta sinais de agitação nos dados da última semana",
            "paused_episode": "Atualização oficial informa pausa no episódio do Kilauea",
        }
        title = elevated_titles.get(
            kind,
            f"Atualização oficial de alerta para {unit.volcano_name}",
        )
        subtitles = {
            "seismic_infrasound": "O estado oficial informado é ADVISORY, com código de aviação YELLOW.",
            "slow_lava": "O comunicado mantém WATCH e ORANGE como estados oficiais.",
            "low_seismicity": "O registro se limita à atividade observada e não apresenta tendência futura.",
            "no_unrest_week": "A observação se restringe a imagens de satélite e dados geofísicos distantes.",
            "paused_episode": "O comunicado afirma que o vulcão não estava em erupção no momento do registro.",
        }
        subtitle = subtitles.get(kind, _status_sentence(evidence) or "Atualização oficial sem interpretação adicional.")
        editorial_summary = " ".join(
            filter(None, (material, _source_time_sentence(event, evidence, "a atualização")))
        )
        status_sentence = _status_sentence(evidence)
        if status_sentence:
            editorial_summary += f" {status_sentence}"
        seo_title = f"Alerta vulcânico para {unit.volcano_name}"

    status = _status_phrase(evidence)
    seo_description = f"Atualização oficial sobre {unit.volcano_name}"
    if status:
        seo_description += f", com {status}"
    notice_keywords = (
        (notice_type,)
        if notice_type in {"Information Statement", "Status Report"}
        else ()
    )
    return VolcanicEditorialContent(
        editorial_title=title,
        editorial_subtitle=subtitle,
        editorial_summary=editorial_summary,
        seo_title=seo_title,
        seo_description=seo_description + ".",
        seo_keywords=tuple(
            dict.fromkeys(
                (
                    "vulcanologia",
                    unit.volcano_name,
                    *_phenomenon_keywords(kind),
                    *notice_keywords,
                    "USGS",
                )
            )
        )[:8],
    )


class VolcanicEditorialEngine:
    """Constroi conteudo sem modificar os Events da unidade editorial."""

    def build(self, unit: VolcanicEditorialUnit) -> VolcanicEditorialContent:
        if not unit.member_events:
            raise ValueError("unidade editorial vazia")
        for event in unit.member_events:
            _validate_event(event)
        if unit.category == "volcano_vona_published":
            return _vona_content(unit)
        if unit.category == "volcanic_thermal_anomaly_candidate":
            return _firms_content(unit)
        return _usgs_singleton_content(unit)


__all__ = ["VolcanicEditorialEngine", "group_volcanic_events"]
