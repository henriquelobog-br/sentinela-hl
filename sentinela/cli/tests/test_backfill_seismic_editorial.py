from __future__ import annotations

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
