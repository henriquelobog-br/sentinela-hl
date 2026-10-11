from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

DOCKERFILE = ROOT / "docker" / "operational" / "Dockerfile.runner"
DOCKERIGNORE = (
    ROOT
    / "docker"
    / "operational"
    / "Dockerfile.runner.dockerignore"
)


def test_operational_runner_packages_scientific_runtime_assets():
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert "COPY sentinela ./sentinela" in text
    assert "COPY taxonomy ./taxonomy" in text
    assert "COPY profiles ./profiles" in text


def test_operational_runner_build_context_includes_runtime_assets():
    text = DOCKERIGNORE.read_text(encoding="utf-8")

    required = {
        "!taxonomy/",
        "!taxonomy/**",
        "!profiles/",
        "!profiles/**",
    }

    lines = {
        line.strip()
        for line in text.splitlines()
        if line.strip()
    }

    assert required <= lines


def test_scientific_runtime_assets_exist_in_repository():
    taxonomy = ROOT / "taxonomy"
    profile = ROOT / "profiles" / "henrique_lobo.yaml"

    assert taxonomy.is_dir()
    assert any(taxonomy.glob("*.yaml")) or any(
        taxonomy.glob("*.yml")
    )
    assert profile.is_file()
