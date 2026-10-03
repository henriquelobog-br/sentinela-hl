"""RPC-backed canonical persistence with provenance and recovery metadata."""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

import httpx

from sentinela.canonical_provenance import (
    CanonicalEventAcceptance,
    CanonicalSignalRecord,
)
from sentinela.canonical_provenance.models import (
    CanonicalEventPersistenceResult,
    CanonicalPersistenceItemResult,
    CanonicalSignalPersistenceResult,
    PersistenceDisposition,
    RunManifestFinal,
)

from .errors import CanonicalFailureKind, CanonicalProvenanceStoreError

_DEFAULT_TIMEOUT_SECONDS = 10.0
_SUCCESSFUL_SIGNAL_DISPOSITIONS = frozenset({
    PersistenceDisposition.INSERTED,
    PersistenceDisposition.UPDATED,
    PersistenceDisposition.OBSERVED_EXISTING,
})
_MAX_ERROR_FIELD_LENGTH = 256
_SECRET_PATTERN = re.compile(
    r"(?i)(authorization|api[-_ ]?key|service[-_ ]?role|password|token)"
    r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]+|bearer\s+[^\s,;]+"
)


@runtime_checkable
class CanonicalProvenanceStore(Protocol):
    """Persistence boundary for canonical facts, linked signals and manifests."""

    def persist_events(
        self, run_id: str, acceptance: CanonicalEventAcceptance
    ) -> CanonicalEventPersistenceResult:
        ...

    def persist_signals(
        self, run_id: str, records: tuple[CanonicalSignalRecord, ...]
    ) -> CanonicalSignalPersistenceResult:
        ...

    def finalize_manifest(self, manifest: RunManifestFinal) -> None:
        ...


def _headers(service_key: str) -> dict[str, str]:
    headers = {"apikey": service_key, "content-type": "application/json"}
    if not service_key.startswith("sb_secret_"):
        headers["authorization"] = f"Bearer {service_key}"
    return headers


class SupabaseCanonicalProvenanceStore:
    """Supabase RPC adapter; no scientific acceptance rules live here."""

    def __init__(
        self,
        *,
        url: str | None = None,
        service_key: str | None = None,
        client: Any | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if url is None or service_key is None:
            from sentinela.core.config import get_settings

            settings = get_settings()
            url = url if url is not None else settings.supabase_url
            service_key = (
                service_key if service_key is not None else settings.supabase_service_key
            )
        self._url = url.rstrip("/")
        self._service_key = service_key
        self._client = client if client is not None else httpx.Client(timeout=timeout)

    def persist_events(
        self, run_id: str, acceptance: CanonicalEventAcceptance
    ) -> CanonicalEventPersistenceResult:
        canonical_run_id = str(UUID(run_id))
        self._rpc(
            "begin_canonical_run_manifest",
            {"p_run_id": canonical_run_id},
            expect_rows=False,
            run_id=canonical_run_id,
            operation="canonical_manifest_begin",
        )
        rows = self._rpc(
            "persist_canonical_event_batch",
            {
                "p_run_id": canonical_run_id,
                "p_accepted": [item.to_rpc_item() for item in acceptance.accepted],
                "p_rejected": [item.to_rpc_item() for item in acceptance.rejected],
            },
            run_id=canonical_run_id,
            operation="canonical_event_persistence",
        )
        items = tuple(self._item(row) for row in rows)
        return CanonicalEventPersistenceResult(
            received=len(acceptance.accepted) + len(acceptance.rejected),
            accepted=len(acceptance.accepted),
            rejected=len(acceptance.rejected),
            items=items,
        )

    def persist_signals(
        self, run_id: str, records: tuple[CanonicalSignalRecord, ...]
    ) -> CanonicalSignalPersistenceResult:
        if not records:
            return CanonicalSignalPersistenceResult(received=0, persisted=0, items=())
        rows = self._rpc(
            "persist_canonical_signal_batch",
            {
                "p_run_id": str(UUID(run_id)),
                "p_signals": [item.to_rpc_item() for item in records],
            },
            run_id=str(UUID(run_id)),
            operation="canonical_signal_persistence",
        )
        items = tuple(self._item(row) for row in rows)
        persisted = sum(
            1 for item in items
            if item.disposition in _SUCCESSFUL_SIGNAL_DISPOSITIONS
        )
        return CanonicalSignalPersistenceResult(
            received=len(records), persisted=persisted, items=items
        )

    def finalize_manifest(self, manifest: RunManifestFinal) -> None:
        self._rpc(
            "finalize_canonical_run_manifest",
            {
                "p_run_id": str(manifest.run_id),
                "p_stage": manifest.stage,
                "p_accepted_events": manifest.accepted_events,
                "p_rejected_events": manifest.rejected_events,
                "p_persisted_signals": manifest.persisted_signals,
                "p_versions": manifest.versions,
                "p_commit_state": (
                    "ambiguous" if manifest.commit_ambiguous else "known"
                ),
                "p_error_type": manifest.error_type,
                "p_error_message": manifest.error_message,
            },
            expect_rows=False,
            run_id=str(manifest.run_id),
            operation="canonical_manifest_finalization",
        )

    def _rpc(
        self,
        rpc: str,
        payload: dict[str, Any],
        *,
        expect_rows: bool = True,
        run_id: str | None = None,
        operation: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            response = self._client.post(
                f"{self._url}/rest/v1/rpc/{rpc}",
                json=payload,
                headers=_headers(self._service_key),
            )
            response.raise_for_status()
            if not expect_rows:
                return []
            body = response.json()
            if not isinstance(body, list):
                raise TypeError("RPC response must be a list")
            return body
        except httpx.HTTPStatusError as exc:
            response = exc.response
            status = response.status_code
            fields = self._postgrest_error_fields(response)
            kind = (
                CanonicalFailureKind.DEFINITIVE_REJECTION
                if 400 <= status < 500
                else CanonicalFailureKind.COMMIT_AMBIGUOUS
            )
            parts = [f"canonical provenance RPC failed: HTTP {status}", f"rpc={rpc}"]
            if run_id is not None:
                parts.append(f"run_id={run_id}")
            if operation is not None:
                parts.append(f"operation={operation}")
            for label, value in fields.items():
                if value is not None:
                    parts.append(f"{label}={value}")
            raise CanonicalProvenanceStoreError(
                "; ".join(parts),
                failure_kind=kind,
                status_code=status,
                postgrest_code=fields["code"],
                postgrest_message=fields["message"],
                details=fields["details"],
                hint=fields["hint"],
                rpc=rpc,
                run_id=run_id,
                operation=operation,
            ) from None
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise CanonicalProvenanceStoreError(
                f"canonical provenance RPC not sent: {type(exc).__name__}; rpc={rpc}",
                failure_kind=CanonicalFailureKind.NOT_COMMITTED,
                rpc=rpc,
                run_id=run_id,
                operation=operation,
            ) from None
        except httpx.HTTPError as exc:
            raise CanonicalProvenanceStoreError(
                f"canonical provenance RPC outcome unknown: {type(exc).__name__}; rpc={rpc}",
                failure_kind=CanonicalFailureKind.COMMIT_AMBIGUOUS,
                rpc=rpc,
                run_id=run_id,
                operation=operation,
            ) from None
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise CanonicalProvenanceStoreError(
                f"canonical provenance RPC response invalid: {type(exc).__name__}; rpc={rpc}",
                failure_kind=CanonicalFailureKind.COMMIT_AMBIGUOUS,
                rpc=rpc,
                run_id=run_id,
                operation=operation,
            ) from None

    def _postgrest_error_fields(self, response: Any) -> dict[str, str | None]:
        try:
            body = response.json()
        except (ValueError, TypeError, AttributeError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        return {
            field: self._sanitize_error_field(body.get(field))
            for field in ("code", "message", "details", "hint")
        }

    def _sanitize_error_field(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        sanitized = value
        if self._service_key:
            sanitized = sanitized.replace(self._service_key, "<redacted>")
        sanitized = _SECRET_PATTERN.sub(
            lambda match: f"{match.group(1) or 'credential'}=<redacted>",
            sanitized,
        )
        sanitized = " ".join(sanitized.split())
        return sanitized[:_MAX_ERROR_FIELD_LENGTH] or None

    @staticmethod
    def _item(row: dict[str, Any]) -> CanonicalPersistenceItemResult:
        return CanonicalPersistenceItemResult(
            artifact_id=str(row["artifact_id"]),
            disposition=PersistenceDisposition(str(row["disposition"])),
            content_hash=(
                str(row["content_hash"])
                if row.get("content_hash") is not None else None
            ),
            revision_id=row.get("revision_id"),
        )


__all__ = ["CanonicalProvenanceStore", "SupabaseCanonicalProvenanceStore"]
