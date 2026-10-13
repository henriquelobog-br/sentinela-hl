from __future__ import annotations

from contextlib import nullcontext

from sentinela.cli import backfill_seismic_editorial


def test_backfill_requires_explicit_execute(monkeypatch, capsys):
    monkeypatch.setattr(
        backfill_seismic_editorial,
        "run_backfill",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    assert backfill_seismic_editorial.main([]) == 2
    output = capsys.readouterr().out
    assert "SEISMIC_EDITORIAL_BACKFILL_GATE=HOLD" in output
    assert "SEISMIC_EDITORIAL_BACKFILL_EXECUTED=NO" in output


def test_backfill_page_size_contract():
    assert backfill_seismic_editorial._page_size("1") == 1
    assert backfill_seismic_editorial._page_size("1000") == 1000


def test_backfill_drains_pending_pages_without_offset(monkeypatch):
    class _Store:
        def __init__(self):
            self.pages = [(object(), object()), (object(),)]
            self.limits = []

        def list_events(self, *, limit):
            self.limits.append(limit)
            return self.pages.pop(0)

    store = _Store()

    monkeypatch.setattr(
        backfill_seismic_editorial,
        "_load_backfill_environment",
        lambda path: {
            "SENTINELA_SUPABASE_URL": "https://example.supabase.co",
            "SENTINELA_SUPABASE_SERVICE_KEY": "sb_secret_test",
        },
    )
    monkeypatch.setattr(
        backfill_seismic_editorial,
        "_exclusive_local_lock",
        lambda path: nullcontext(),
    )
    monkeypatch.setattr(
        backfill_seismic_editorial,
        "_job_timeout",
        lambda seconds: nullcontext(),
    )

    def _generate(events, *, store, generated_at):
        count = len(events)
        return backfill_seismic_editorial.SeismicEditorialPersistenceResult(
            received=count,
            inserted=count,
            updated=0,
            unchanged=0,
        )

    monkeypatch.setattr(
        backfill_seismic_editorial,
        "generate_and_persist",
        _generate,
    )

    result = backfill_seismic_editorial.run_backfill(
        page_size=2,
        store_factory=lambda **kwargs: store,
        guard=lambda **kwargs: nullcontext(),
    )

    assert store.limits == [2, 2]
    assert result.received == 3
    assert result.inserted == 3
    assert result.updated == 0
    assert result.unchanged == 0
