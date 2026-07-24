from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from sentinela.interest.loader import (
    ProfileLoadError,
    load_research_profile,
)
from sentinela.interest.profile import canonical_concept_ids


@dataclass(frozen=True)
class FakeConcept:
    concept_id: str
    domain: str
    synonyms: tuple[str, ...] = ()


class FakeTaxonomy:
    def __init__(self):
        concepts = [
            FakeConcept(
                "mineral_dust",
                "atmospheric_science",
                ("desert dust",),
            ),
            FakeConcept(
                "atmospheric_transport",
                "atmospheric_science",
                ("transport",),
            ),
            FakeConcept(
                "south_atlantic",
                "regions",
                ("atlântico sul",),
            ),
            FakeConcept(
                "southern_africa",
                "regions",
                ("namibia", "angola"),
            ),
            FakeConcept(
                "southeast_brazil",
                "regions",
                ("espírito santo",),
            ),
            FakeConcept(
                "satellite_instruments",
                "remote_sensing",
                ("calipso", "modis"),
            ),
            FakeConcept(
                "reanalysis",
                "remote_sensing",
                ("merra-2",),
            ),
        ]

        self.concepts = {
            item.concept_id: item
            for item in concepts
        }

        self.domains = {
            "atmospheric_science": object(),
            "regions": object(),
            "remote_sensing": object(),
        }

    def find_by_term(self, term: str):
        folded = term.casefold()

        return [
            concept
            for concept in self.concepts.values()
            if concept.concept_id.casefold() == folded
            or folded in {
                synonym.casefold()
                for synonym in concept.synonyms
            }
        ]


def write_profile(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_resolve_sinonimos_e_guarda_ids_canonicos(tmp_path):
    path = write_profile(
        tmp_path,
        """
researcher:
  id: hl
  name: Henrique Lobo
  version: 1

domains:
  atmospheric_science: 1.0

regions:
  namibia: 0.9

instruments:
  calipso: 1.0

concepts:
  desert dust:
    weight: 0.8

excluded_topics:
  - Celebrity
  - "  celebrity  "
  - Sports

research_lines:
  - id: dust_transport
    title: Transporte de poeira
    question: Existe transporte da África Austral ao Brasil?
    concepts:
      - mineral_dust
      - atmospheric_transport
    regions:
      - south_atlantic
    instruments:
      - modis
""",
    )

    profile = load_research_profile(
        path,
        FakeTaxonomy(),
    )

    assert profile.regions[0].concept_id == "southern_africa"
    assert profile.instruments[0].concept_id == "satellite_instruments"
    assert profile.concepts[0].concept_id == "mineral_dust"
    assert profile.excluded_topics == ("celebrity", "sports")
    assert profile.research_lines[0].question
    assert "satellite_instruments" in canonical_concept_ids(profile)
    assert len(profile.resolution_log) >= 4


def test_colisao_com_pesos_diferentes_falha(tmp_path):
    path = write_profile(
        tmp_path,
        """
researcher:
  id: hl
  name: Henrique Lobo
  version: 1

instruments:
  calipso: 1.0
  modis: 0.8
""",
    )

    with pytest.raises(
        ProfileLoadError,
        match="pesos conflitantes",
    ):
        load_research_profile(path, FakeTaxonomy())


def test_regiao_precisa_ser_regions(tmp_path):
    path = write_profile(
        tmp_path,
        """
researcher:
  id: hl
  name: Henrique Lobo
  version: 1

regions:
  - mineral_dust
""",
    )

    with pytest.raises(
        ProfileLoadError,
        match="esperado: regions",
    ):
        load_research_profile(path, FakeTaxonomy())


def test_instrumento_precisa_ser_remote_sensing(tmp_path):
    path = write_profile(
        tmp_path,
        """
researcher:
  id: hl
  name: Henrique Lobo
  version: 1

instruments:
  - mineral_dust
""",
    )

    with pytest.raises(
        ProfileLoadError,
        match="remote_sensing",
    ):
        load_research_profile(path, FakeTaxonomy())


def test_termo_inexistente_falha(tmp_path):
    path = write_profile(
        tmp_path,
        """
researcher:
  id: hl
  name: Henrique Lobo
  version: 1

concepts:
  - nao_existe
""",
    )

    with pytest.raises(
        ProfileLoadError,
        match="não resolvido",
    ):
        load_research_profile(path, FakeTaxonomy())


def test_deterministico(tmp_path):
    path = write_profile(
        tmp_path,
        """
researcher:
  id: hl
  name: Henrique Lobo
  version: 1

concepts:
  - desert dust
  - atmospheric_transport

regions:
  - namibia
""",
    )

    taxonomy = FakeTaxonomy()

    first = load_research_profile(path, taxonomy)
    second = load_research_profile(path, taxonomy)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_sem_llm_sem_banco():
    base = Path(__file__).parents[1]

    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in base.glob("*.py")
    ).casefold()

    assert "openrouter" not in source
    assert "psycopg" not in source
    assert "llmclient" not in source
