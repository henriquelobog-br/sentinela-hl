"""Coletores reais para vulcanologia e geopolítica estruturada."""

from __future__ import annotations

import csv
import html
import io
import re
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from sentinela.core.models import EventStatus

from .collectors import CollectionResult, _dt, _event, _six_hour_window, _uuid
from .config import RealSignalSettings

HANS_ELEVATED = "https://volcanoes.usgs.gov/hans-public/api/volcano/getElevatedVolcanoes"
HANS_RECENT = "https://volcanoes.usgs.gov/hans-public/api/notice/getRecentNotices"
HANS_VONAS = "https://volcanoes.usgs.gov/vsc/api/hansApi/vonas"
GVP_WFS = "https://webservices.volcano.si.edu/geoserver/GVP-VOTW/wfs"
GVP_VOLCANO_LAYER = "GVP-VOTW:Smithsonian_VOTW_Holocene_Volcanoes"
GVP_ERUPTION_LAYER = "GVP-VOTW:Smithsonian_VOTW_Holocene_Eruptions"
GDELT_LASTUPDATE = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"


def _plain(value: Any, limit: int = 600) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(value)))
    text = " ".join(text.split())
    return text[:limit] if text else None


def _notice_time(item: dict[str, Any]) -> datetime | None:
    if item.get("sent_unixtime") is not None:
        return datetime.fromtimestamp(float(item["sent_unixtime"]), tz=timezone.utc)
    if item.get("sentUtc"):
        return _dt(str(item["sentUtc"]))
    identifier = str(item.get("noticeId") or item.get("notice_identifier") or "")
    match = re.search(r"(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00)", identifier)
    return _dt(match.group(1)) if match else None


class UsgsVolcanoCollector:
    def __init__(self, settings: RealSignalSettings, client: Any | None = None, gvp_features: list[dict[str, Any]] | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds)
        self.gvp_features = gvp_features

    def collect(self, now: datetime) -> CollectionResult:
        try:
            elevated = self._get(HANS_ELEVATED)
            recent = self._get(HANS_RECENT)
            vonas = self._get(HANS_VONAS)
        except Exception as exc:
            return CollectionResult(
                source="usgs_volcano",
                error=f"{type(exc).__name__}: falha na consulta USGS HANS",
            )
        cutoff = now - timedelta(hours=self.settings.volcano_lookback_hours)
        gvp_features, gvp_warning = self._gvp_features()
        gvp_by_number = {
            str((feature.get("properties") or {}).get("Volcano_Number")): feature.get("properties") or {}
            for feature in gvp_features
        }
        detail_cache: dict[str, dict[str, Any]] = {}
        events = []
        details = []
        discarded = 0

        for item in elevated:
            alert = str(item.get("alert_level") or "").upper()
            color = str(item.get("color_code") or "").upper()
            if alert not in {"ADVISORY", "WATCH", "WARNING"}:
                discarded += 1
                continue
            notice_id = str(item.get("notice_identifier") or "")
            volcano_number = str(item.get("vnum") or "")
            if not notice_id or not volcano_number:
                discarded += 1
                continue
            sent_at = _notice_time(item) or now
            section = self._section(item.get("notice_data"), volcano_number, detail_cache)
            event = self._volcano_event(
                now=now, item=item, section=section,
                event_type="volcano_alert_elevated",
                volcano_name=str(item.get("volcano_name") or section.get("vName") or "vulcão não informado"),
                volcano_number=volcano_number, notice_id=notice_id,
                sent_at=sent_at, alert=alert, color=color,
                gvp=gvp_by_number.get(volcano_number, {}),
                title=f"Alerta vulcânico atualizado para {item.get('volcano_name') or section.get('vName') or volcano_number}",
            )
            events.append(event)
            details.append(self._detail(event))

        for item in recent:
            sent_at = _notice_time(item)
            if (
                sent_at is None or sent_at < cutoff
                or item.get("notice_category") == "Scheduled Update"
                or item.get("notice_type_cd") == "VV"
            ):
                discarded += 1
                continue
            notice_id = str(item.get("notice_identifier") or "")
            detail = self._detail_payload(item.get("notice_data"), detail_cache)
            sections = detail.get("notice_sections") or []
            if not notice_id or not sections:
                discarded += 1
                continue
            for section in sections:
                volcano_number = str(section.get("vnum") or "")
                volcano_name = str(section.get("vName") or "")
                if not volcano_number or not volcano_name:
                    discarded += 1
                    continue
                alert = str(section.get("alertLevel") or detail.get("highest_alert_level") or "").upper()
                color = str(section.get("colorCode") or detail.get("highest_color_code") or "").upper()
                if (alert == "NORMAL" or color == "GREEN") and not self._material_normal_notice(item, section):
                    discarded += 1
                    continue
                event = self._volcano_event(
                    now=now, item=item, section=section,
                    event_type="volcano_notice_published",
                    volcano_name=volcano_name, volcano_number=volcano_number,
                    notice_id=notice_id, sent_at=sent_at,
                    alert=alert, color=color,
                    gvp=gvp_by_number.get(volcano_number, {}),
                    title=f"Nova notificação vulcânica publicada para {volcano_name}",
                )
                events.append(event)
                details.append(self._detail(event))

        for item in vonas:
            sent_at = _notice_time(item)
            volcano_number = str(item.get("vnum") or "")
            volcano_name = str(item.get("vName") or "")
            notice_id = str(item.get("noticeId") or "")
            if sent_at is None or sent_at < cutoff or not all((volcano_number, volcano_name, notice_id)):
                discarded += 1
                continue
            alert = str(item.get("alertLevel") or "").upper()
            color = str(item.get("colorCode") or "").upper()
            if (alert == "NORMAL" or color == "GREEN") and not self._material_normal_notice(item, {"synopsis": item.get("noticeSynopsis")}):
                discarded += 1
                continue
            event = self._volcano_event(
                now=now, item=item, section={"synopsis": item.get("noticeSynopsis")},
                event_type="volcano_vona_published", volcano_name=volcano_name,
                volcano_number=volcano_number, notice_id=notice_id,
                sent_at=sent_at, alert=alert, color=color,
                gvp=gvp_by_number.get(volcano_number, {}),
                title=f"Novo aviso VONA emitido para {volcano_name}",
            )
            events.append(event)
            details.append(self._detail(event))

        unique = {event.id: event for event in events}
        notice_count = sum(event.category == "volcano_notice_published" for event in unique.values())
        vona_count = sum(event.category == "volcano_vona_published" for event in unique.values())
        enriched_count = sum(bool(event.evidence[0].get("gvp_enriched")) for event in unique.values())
        metrics_notice = (
            f"elevados={len(elevated)}; notices_novas={notice_count}; "
            f"vonas_novas={vona_count}; eventos_enriquecidos_gvp={enriched_count}"
        )
        if gvp_warning:
            metrics_notice += f"; {gvp_warning}"
        return CollectionResult(
            source="usgs_volcano",
            received=len(elevated) + len(recent) + len(vonas),
            discarded=discarded,
            duplicates=len(events) - len(unique),
            events=tuple(unique.values()), details=tuple(details), notice=metrics_notice,
        )

    def _get(self, url: str) -> list[dict[str, Any]]:
        response = self.client.get(url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("resposta USGS HANS inválida")
        return payload

    def _gvp_features(self) -> tuple[list[dict[str, Any]], str | None]:
        if self.gvp_features is not None:
            return self.gvp_features, None
        try:
            response = self.client.get(GVP_WFS, params={
                "service": "WFS", "version": "2.0.0", "request": "GetFeature",
                "typeNames": GVP_VOLCANO_LAYER, "outputFormat": "application/json",
                "count": self.settings.gvp_feature_count,
            })
            response.raise_for_status()
            payload = response.json()
            return list(payload.get("features", [])), None
        except Exception as exc:
            return [], f"enriquecimento GVP indisponível: {type(exc).__name__}"

    def _detail_payload(self, url: Any, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
        if not url:
            return {}
        key = str(url)
        if key not in cache:
            try:
                response = self.client.get(key)
                response.raise_for_status()
                payload = response.json()
                cache[key] = payload if isinstance(payload, dict) else {}
            except Exception:
                cache[key] = {}
        return cache[key]

    def _section(self, url: Any, volcano_number: str, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
        detail = self._detail_payload(url, cache)
        return next(
            (section for section in detail.get("notice_sections", []) if str(section.get("vnum")) == volcano_number),
            {},
        )

    @staticmethod
    def _material_normal_notice(item: dict[str, Any], section: dict[str, Any]) -> bool:
        text = " ".join(filter(None, (
            _plain(section.get("synopsis"), 2000),
            _plain(section.get("summary"), 2000),
            _plain(item.get("noticeSynopsis"), 2000),
        ))).lower()
        patterns = (
            r"\b(?:lowered|returned|changed|returning)\b.{0,80}\bnormal\b",
            r"\b(?:lowered|returned|changed|returning)\b.{0,80}\bgreen\b",
            r"\b(?:activity|eruption|unrest)\b.{0,40}\b(?:ended|ceased|declined)\b",
            r"\balert level\b.{0,40}\bbeing lowered\b",
            r"\baviation color code\b.{0,40}\bbeing lowered\b",
        )
        return any(re.search(pattern, text) for pattern in patterns)

    def _volcano_event(
        self, *, now: datetime, item: dict[str, Any], section: dict[str, Any],
        event_type: str, volcano_name: str, volcano_number: str,
        notice_id: str, sent_at: datetime, alert: str, color: str, title: str,
        gvp: dict[str, Any],
    ):
        synopsis = _plain(section.get("synopsis") or item.get("noticeSynopsis"))
        notice_type = item.get("notice_type_title") or item.get("notice_type_cd") or item.get("notice_type") or "notificação"
        summary = (
            f"O USGS publicou {notice_type} para {volcano_name} em "
            f"{sent_at.isoformat()}, com nível de alerta {alert or 'não informado'} "
            f"e código de aviação {color or 'não informado'}."
        )
        if synopsis:
            summary += f" Resumo oficial: {synopsis}"
        source_url = item.get("notice_url") or item.get("noticeUrl")
        evidence = {
            "source": "USGS HANS", "product": "HANS/VONA",
            "volcano_name": volcano_name, "volcano_number": volcano_number,
            "latitude": section.get("lat") or gvp.get("Latitude"),
            "longitude": section.get("lng") or gvp.get("Longitude"),
            "alert_level": alert or None, "aviation_color_code": color or None,
            "observatory": item.get("obs_fullname") or item.get("obs"),
            "notice_type": notice_type, "notice_identifier": notice_id,
            "sent_at": sent_at.isoformat(), "source_url": source_url,
            "official_summary": synopsis, "retrieved_at": now.isoformat(),
            "country": gvp.get("Country"), "gvp_region": gvp.get("Region"),
            "volcano_type": gvp.get("Primary_Volcano_Type"),
            "last_known_eruption": gvp.get("Last_Eruption_Year"),
            "historical_context": _plain(gvp.get("Geological_Summary"), 1000),
            "gvp_enriched": bool(gvp), "region": volcano_name,
        }
        concept = "volcanic_alert" if event_type == "volcano_alert_elevated" else "volcanic_activity"
        return _event(
            event_type=event_type, source="USGS HANS", product="volcano-notices",
            region=volcano_number, window=notice_id,
            group=f"usgs-volcano:{volcano_number}:{event_type}",
            title=title, summary=summary, occurred_at=sent_at,
            evidence=evidence, keywords=["volcano", concept],
            entities=[{"name": volcano_name, "type": "volcano"}, {"name": "USGS", "type": "source"}],
            scientific_area="volcanology", evidence_text=concept,
            event_status=EventStatus.OFFICIAL_ALERT,
        )

    @staticmethod
    def _detail(event: Any) -> dict[str, Any]:
        evidence = event.evidence[0]
        return {
            "source": "USGS HANS", "region": evidence["volcano_name"],
            "variable": "alert_level", "value": evidence.get("alert_level"),
            "unit": evidence.get("aviation_color_code"),
        }


class GvpCollector:
    def __init__(self, settings: RealSignalSettings, client: Any | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds)

    def collect(self, now: datetime) -> CollectionResult:
        try:
            response = self.client.get(GVP_WFS, params={
                "service": "WFS", "version": "2.0.0", "request": "GetFeature",
                "typeNames": GVP_VOLCANO_LAYER, "outputFormat": "application/json",
                "count": self.settings.gvp_feature_count,
            })
            response.raise_for_status()
            payload = response.json()
            features = payload.get("features", [])
            eruption_response = self.client.get(GVP_WFS, params={
                "service": "WFS", "version": "2.0.0", "request": "GetFeature",
                "typeNames": GVP_ERUPTION_LAYER, "outputFormat": "application/json",
                "count": 100,
                "CQL_FILTER": f"StartDateYear >= {now.year - 1}",
            })
            eruption_response.raise_for_status()
            eruption_features = eruption_response.json().get("features", [])
        except Exception as exc:
            return CollectionResult(
                source="gvp", error=f"{type(exc).__name__}: falha na consulta GVP WFS"
            )
        valid = [feature for feature in features if (feature.get("properties") or {}).get("Volcano_Number")]
        confirmed_recent = [
            feature for feature in eruption_features
            if (feature.get("properties") or {}).get("Activity_Type") == "Confirmed Eruption"
        ]
        return CollectionResult(
            source="gvp", received=len(features) + len(eruption_features),
            discarded=len(features) - len(valid),
            notice=(
                f"{len(valid)} vulcões disponíveis para enriquecimento; "
                f"{len(confirmed_recent)} registros recentes de erupção confirmada reportados apenas como contexto; "
                "nenhum evento em tempo real criado"
            ),
        )

    @staticmethod
    def find_volcano(features: list[dict[str, Any]], volcano_number: str) -> dict[str, Any] | None:
        return next(
            (feature for feature in features if str((feature.get("properties") or {}).get("Volcano_Number")) == str(volcano_number)),
            None,
        )


_GDELT_INDEX = {
    "id": 0, "sqldate": 1,
    "actor1_name": 6, "actor1_country": 7,
    "actor2_name": 16, "actor2_country": 17,
    "event_code": 26, "base_code": 27, "root_code": 28,
    "quad_class": 29, "goldstein": 30, "mentions": 31,
    "sources": 32, "articles": 33, "tone": 34,
    "actor1_geo": 36, "actor1_geo_country": 37,
    "actor2_geo": 44, "actor2_geo_country": 45,
    "action_geo": 52, "action_country": 53,
    "date_added": 59, "url": 60,
}

_MONITORED_CODES = {
    "ISR", "IS", "PSE", "PS", "LBN", "LE", "IRN", "IR", "SYR", "SY",
    "JOR", "JO", "EGY", "EG", "SAU", "SA", "UAE", "AE", "BHR", "BA",
    "MAR", "MO", "YEM", "YM",
}
_MONITORED_TERMS = {
    "ISRAEL", "PALESTIN", "GAZA", "WEST BANK", "LEBAN", "IRAN", "SYRIA",
    "JORDAN", "EGYPT", "SAUDI", "EMIRAT", "BAHRAIN", "MOROCC", "YEMEN",
    "HAMAS", "HEZBOLLAH", "HOUTHI", "IRGC", "RED SEA", "SUEZ", "HORMUZ",
}
_ABRAHAM_PARTNERS = {"UAE", "EMIRAT", "BAHRAIN", "MOROCC", "SAUDI"}


class GdeltCollector:
    def __init__(self, settings: RealSignalSettings, client: Any | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds, follow_redirects=True)

    def collect(self, now: datetime) -> CollectionResult:
        try:
            response = self.client.get(GDELT_LASTUPDATE)
            response.raise_for_status()
            latest_url = next(
                line.split()[-1] for line in response.text.splitlines()
                if line.endswith("export.CSV.zip")
            )
        except Exception as exc:
            return CollectionResult(source="gdelt", error=f"{type(exc).__name__}: falha ao localizar atualização GDELT")
        urls = self._window_urls(latest_url)
        raw_rows = []
        failures = []
        for url in urls:
            try:
                response = self.client.get(url)
                response.raise_for_status()
                raw_rows.extend(self._read_zip(response.content))
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                failures.append(f"HTTP {status}" if status else type(exc).__name__)
        cutoff = now - timedelta(minutes=self.settings.gdelt_lookback_minutes)
        candidates = []
        discarded = 0
        for row in raw_rows:
            item = self._parse(row)
            if item is None or item["occurred_at"] < cutoff or not self._eligible(item):
                discarded += 1
                continue
            candidates.append(item)
        groups: dict[tuple[str, str, str, str, str, datetime], list[dict[str, Any]]] = {}
        for item in candidates:
            window_start, _ = _six_hour_window(item["occurred_at"])
            actors = sorted((self._normalize(item["actor1"]), self._normalize(item["actor2"])))
            key = (
                item["root_code"], actors[0], actors[1], item["action_country"],
                self._normalize(item["action_geo"]), window_start,
            )
            groups.setdefault(key, []).append(item)
        events = []
        details = []
        ranked_groups = sorted(
            groups.items(),
            key=lambda pair: (
                sum(item["sources"] for item in pair[1]),
                sum(item["mentions"] for item in pair[1]),
                max(item["occurred_at"] for item in pair[1]),
            ),
            reverse=True,
        )
        for key, members in ranked_groups[:self.settings.gdelt_max_groups]:
            root, actor1, actor2, country, action_geo, window_start = key
            members.sort(key=lambda item: (item["occurred_at"], item["id"]))
            window_end = window_start + timedelta(hours=6)
            category = self._category(root, actor1, actor2, members)
            title = self._title(category, actor1, actor2, members[0]["action_geo"])
            mentions = sum(item["mentions"] for item in members)
            sources = sum(item["sources"] for item in members)
            actors = " e ".join(value for value in (actor1, actor2) if value) or "atores não informados"
            location = members[0]["action_geo"] or country or "local não informado"
            summary = (
                f"O GDELT registrou {mentions} menções em {sources} fontes para "
                f"um evento classificado como {category}, envolvendo {actors}, em "
                f"{location}, na janela {window_start.isoformat()}-{window_end.isoformat()}. "
                "Este sinal reflete cobertura mediática estruturada pelo GDELT e "
                "não constitui confirmação independente do fato."
            )
            member_ids = [str(_uuid(f"gdelt-member|{item['id']}")) for item in members]
            goldstein = [item["goldstein"] for item in members if item["goldstein"] is not None]
            evidence = {
                "source": "GDELT 2.0", "product": "Event Database",
                "event_root_code": root, "actor1": actor1, "actor2": actor2,
                "action_geo_country_code": country, "action_geo": location,
                "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
                "earliest_occurred_at": members[0]["occurred_at"].isoformat(),
                "latest_occurred_at": members[-1]["occurred_at"].isoformat(),
                "member_event_ids": member_ids,
                "global_event_ids": [item["id"] for item in members],
                "source_urls": sorted({item["url"] for item in members}),
                "total_mentions": mentions, "total_sources": sources,
                "total_articles": sum(item["articles"] for item in members),
                "goldstein_mean": sum(goldstein) / len(goldstein) if goldstein else None,
                "goldstein_range": [min(goldstein), max(goldstein)] if goldstein else None,
                "quad_classes": sorted({item["quad_class"] for item in members}),
                "avg_tone_values": [item["tone"] for item in members],
                "members": members, "category": category,
                "abraham_accords_basis": (
                    "CAMEO EventRootCode 05: diplomatic cooperation between Israel and an eligible normalization partner"
                    if category == "Acordos de Abraão" else None
                ),
                "retrieved_at": now.isoformat(),
            }
            event_type = {
                "conflito material": "geopolitical_conflict_reported",
                "protesto": "geopolitical_protest_reported",
                "diplomacia": "geopolitical_diplomacy_reported",
                "Acordos de Abraão": "abraham_accords_activity_reported",
                "segurança/coerção": "geopolitical_security_reported",
            }[category]
            concept = {
                "conflito material": "conflict", "protesto": "protest",
                "diplomacia": "diplomacy", "Acordos de Abraão": "abraham_accords",
                "segurança/coerção": "military_action",
            }[category]
            events.append(_event(
                event_type=event_type, source="GDELT 2.0",
                product=f"events:{root}:{actor1}:{actor2}:{action_geo}",
                region=country or location, window=window_start.isoformat(),
                group=f"gdelt:{root}:{actor1}:{actor2}:{country}:{action_geo}",
                title=title, summary=summary, occurred_at=members[-1]["occurred_at"],
                evidence=evidence, keywords=[concept, "middle_east"],
                entities=[{"name": actor, "type": "actor"} for actor in (actor1, actor2) if actor],
                scientific_area="scientific_geopolitics", evidence_text=concept,
                event_status=EventStatus.REPORTED_EVENT,
            ))
            details.append({
                "source": "GDELT 2.0", "region": location,
                "variable": category, "value": mentions,
                "threshold": self.settings.gdelt_min_mentions,
                "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
            })
        notice = (
            f"candidatos_apos_filtro={len(candidates)}; grupos_formados={len(groups)}; "
            f"grupos_selecionados={len(events)}"
        )
        if failures:
            notice += "; arquivos parciais indisponíveis: " + ", ".join(failures)
        return CollectionResult(
            source="gdelt", received=len(raw_rows), discarded=discarded,
            events=tuple(events), notice=notice, details=tuple(details),
        )

    def _window_urls(self, latest_url: str) -> list[str]:
        match = re.search(r"(\d{14})\.export\.CSV\.zip", latest_url)
        if not match:
            return [latest_url]
        latest = datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        count = max(1, (self.settings.gdelt_lookback_minutes + 14) // 15)
        return [
            re.sub(r"\d{14}(?=\.export\.CSV\.zip)", (latest - timedelta(minutes=15 * index)).strftime("%Y%m%d%H%M%S"), latest_url)
            for index in range(count)
        ]

    @staticmethod
    def _read_zip(content: bytes) -> list[list[str]]:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            name = archive.namelist()[0]
            text = archive.read(name).decode("utf-8", errors="replace")
        return list(csv.reader(io.StringIO(text), delimiter="\t"))

    @staticmethod
    def _parse(row: list[str]) -> dict[str, Any] | None:
        if len(row) <= 60:
            return None
        try:
            occurred = datetime.strptime(row[_GDELT_INDEX["date_added"]], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            return {
                "id": row[0], "sql_date": row[1],
                "actor1": row[6], "actor1_country": row[7],
                "actor2": row[16], "actor2_country": row[17],
                "event_code": row[26], "base_code": row[27], "root_code": row[28],
                "quad_class": row[29], "goldstein": float(row[30]) if row[30] else None,
                "mentions": int(row[31]), "sources": int(row[32]),
                "articles": int(row[33]), "tone": float(row[34]) if row[34] else None,
                "actor1_geo": row[36], "actor1_geo_country": row[37],
                "actor2_geo": row[44], "actor2_geo_country": row[45],
                "action_geo": row[52], "action_country": row[53],
                "occurred_at": occurred, "url": row[60],
            }
        except (TypeError, ValueError):
            return None

    def _eligible(self, item: dict[str, Any]) -> bool:
        searchable = " ".join(str(item.get(key) or "").upper() for key in (
            "actor1", "actor2", "action_geo"
        ))
        codes = {str(item.get(key) or "").upper() for key in (
            "actor1_country", "actor2_country", "action_country",
        )}
        monitored = bool(codes & _MONITORED_CODES) or any(term in searchable for term in _MONITORED_TERMS)
        quality = item["sources"] >= self.settings.gdelt_min_sources or item["mentions"] >= self.settings.gdelt_min_mentions
        relevant = item["root_code"] in {
            "03", "04", "05", "06", "07", "08", "10",
            "13", "14", "15", "16", "17", "18", "19", "20",
        }
        return monitored and quality and relevant and bool(item["id"] and item["url"])

    @staticmethod
    def _normalize(value: Any) -> str:
        return " ".join(str(value or "").upper().split())

    @staticmethod
    def _category(root: str, actor1: str, actor2: str, members: list[dict[str, Any]]) -> str:
        pair = f"{actor1} {actor2}"
        diplomatic_cooperation = root == "05" and any(
            str(item.get("event_code") or "").startswith("05")
            for item in members
        )
        if "ISRAEL" in pair and any(partner in pair for partner in _ABRAHAM_PARTNERS) and diplomatic_cooperation:
            return "Acordos de Abraão"
        value = int(root)
        if value == 14:
            return "protesto"
        if value >= 18:
            return "conflito material"
        if value in {10, 13, 15, 16, 17}:
            return "segurança/coerção"
        return "diplomacia"

    @staticmethod
    def _title(category: str, actor1: str, actor2: str, location: str) -> str:
        actors = " e ".join(value for value in (actor1, actor2) if value) or "atores não informados"
        if category == "conflito material":
            return f"Evento de conflito reportado envolvendo {actors}"
        if category == "protesto":
            return f"Protestos reportados em {location or 'local não informado'}"
        if category == "Acordos de Abraão":
            return f"Atividade diplomática relacionada aos Acordos de Abraão envolvendo {actors}"
        if category == "segurança/coerção":
            return f"Evento de segurança reportado envolvendo {actors}"
        return f"Nova atividade diplomática envolvendo {actors}"


__all__ = ["GdeltCollector", "GvpCollector", "UsgsVolcanoCollector"]
