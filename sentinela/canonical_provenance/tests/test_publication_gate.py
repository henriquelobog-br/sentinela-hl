from pathlib import Path


def test_bulletin_reader_requires_explicit_publication_approval():
    source = Path("sentinela/bulletin/postgres_reader.py").read_text(encoding="utf-8")
    assert "and publication_approved" in source
