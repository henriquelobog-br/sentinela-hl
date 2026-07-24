"""Testes da Scientific Taxonomy (112.7A) — determinístico, sem rede/LLM/banco."""
from __future__ import annotations

import textwrap

import pytest

from sentinela.taxonomy.loader import TaxonomyLoadError, load_domain_file, load_taxonomy
from sentinela.taxonomy.models import Concept, Domain, Taxonomy, normalize_term
from sentinela.taxonomy.taxonomy import TaxonomyIndex
from sentinela.taxonomy.validator import TaxonomyValidationError, validate_taxonomy

TAXDIR = "taxonomy"


# ---------------- modelos ----------------
def test_concept_id_snake_case():
    with pytest.raises(ValueError):
        Concept(id="Mineral Dust", name="x", domain="atmospheric_science")


def test_synonyms_dedup_case_insensitive():
    c = Concept(id="a", name="A", domain="d",
                synonyms=["Desert Dust", "desert dust", "DESERT  DUST", "aeolian dust"])
    assert len(c.synonyms) == 2                     # dedup normalizado


def test_normalize_term():
    assert normalize_term("  Poeira   MINERAL ") == "poeira mineral"
    assert normalize_term("Erupção") == "erupcao"    # sem acento


# ---------------- validator ----------------
def _mini(concepts_a, concepts_b=()):
    return Taxonomy(domains=[
        Domain(id="da", name="A", concepts=list(concepts_a)),
        Domain(id="db", name="B", concepts=list(concepts_b)),
    ])


def test_validator_parent_inexistente():
    t = _mini([Concept(id="x", name="X", domain="da", parent="nao_existe")])
    with pytest.raises(TaxonomyValidationError, match="parent inexistente"):
        validate_taxonomy(t)


def test_validator_related_inexistente():
    t = _mini([Concept(id="x", name="X", domain="da", related=["fantasma"])])
    with pytest.raises(TaxonomyValidationError, match="related inexistente"):
        validate_taxonomy(t)


def test_validator_conceito_duplicado_entre_dominios():
    t = _mini([Concept(id="x", name="X", domain="da")],
              [Concept(id="x", name="X2", domain="db")])
    with pytest.raises(TaxonomyValidationError, match="duplicado"):
        validate_taxonomy(t)


def test_validator_ciclo_na_hierarquia():
    t = _mini([Concept(id="a", name="A", domain="da", parent="b"),
               Concept(id="b", name="B", domain="da", parent="a")])
    with pytest.raises(TaxonomyValidationError, match="ciclo"):
        validate_taxonomy(t)


def test_validator_termo_ambiguo():
    t = _mini([Concept(id="a", name="Dust", domain="da"),
               Concept(id="b", name="Poeira", domain="da", synonyms=["dust"])])
    with pytest.raises(TaxonomyValidationError, match="ambíguo"):
        validate_taxonomy(t)


def test_validator_domain_divergente():
    t = _mini([Concept(id="a", name="A", domain="OUTRO".lower())])
    with pytest.raises(TaxonomyValidationError, match="declara domain"):
        validate_taxonomy(t)


# ---------------- loader ----------------
def test_loader_yaml_invalido(tmp_path):
    f = tmp_path / "broken.yaml"
    f.write_text("id: x\nname: [não fech", encoding="utf-8")
    with pytest.raises(TaxonomyLoadError, match="YAML inválido"):
        load_domain_file(f)


def test_loader_estrutura_invalida(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text(textwrap.dedent("""
        id: dominio_x
        name: X
        concepts:
          - id: c1
            name: C1
            domain: dominio_x
            synonyms: "não é lista"
    """), encoding="utf-8")
    with pytest.raises(TaxonomyLoadError, match="estrutura inválida"):
        load_domain_file(f)


def test_loader_diretorio_vazio(tmp_path):
    with pytest.raises(TaxonomyLoadError, match="nenhum arquivo"):
        load_taxonomy(tmp_path)


# ---------------- taxonomia real do repositório ----------------
def test_taxonomia_real_carrega_e_valida():
    tax = load_taxonomy(TAXDIR)
    assert len(tax.domains) >= 10
    assert len(tax.concepts) >= 50


def test_dominios_minimos_presentes():
    tax = load_taxonomy(TAXDIR)
    ids = {d.id for d in tax.domains}
    exigidos = {"astronomy", "atmospheric_science", "climate_science", "oceanography",
                "geology", "seismology", "volcanology", "remote_sensing",
                "geopolitics", "space_weather"}
    assert exigidos.issubset(ids)


def test_lookup_por_sinonimo_case_insensitive():
    idx = TaxonomyIndex(load_taxonomy(TAXDIR))
    assert idx.find_by_term("AEOLIAN DUST").id == "mineral_dust"
    assert idx.find_by_term("Desert  Dust").id == "mineral_dust"
    assert idx.find_by_term("merra-2").id == "reanalysis"
    assert idx.find_by_term("850 hPa").id == "pressure_levels"
    assert idx.find_by_term("termo que não existe") is None


def test_hierarquia_ancestors():
    idx = TaxonomyIndex(load_taxonomy(TAXDIR))
    anc = [c.id for c in idx.ancestors("namib_dust")]
    assert anc == ["mineral_dust", "aerosols"]       # namib → mineral dust → aerosols


def test_hierarquia_descendants():
    idx = TaxonomyIndex(load_taxonomy(TAXDIR))
    desc = {c.id for c in idx.descendants("aerosols")}
    assert {"mineral_dust", "saharan_dust", "namib_dust", "volcanic_ash"}.issubset(desc)


def test_related_simetrico():
    idx = TaxonomyIndex(load_taxonomy(TAXDIR))
    # ocean_fertilization declara mineral_dust; a consulta inversa também enxerga
    rel_of_dust = {c.id for c in idx.related("mineral_dust")}
    assert "ocean_fertilization" in rel_of_dust


def test_caso_cientifico_namibia_para_brasil():
    """O caso real: um texto sobre 'aeolian dust' no 'South Atlantic' precisa
    resolver para conceitos conectados à linha de pesquisa Namíbia→ES."""
    idx = TaxonomyIndex(load_taxonomy(TAXDIR))
    dust = idx.find_by_term("aeolian dust")
    assert dust is not None
    vizinhos = {c.id for c in idx.related(dust.id)}
    assert "atmospheric_transport" in vizinhos and "trade_winds" in vizinhos
    atlantico = idx.find_by_term("atlantico sul")
    assert atlantico is not None and atlantico.id == "south_atlantic"
    # namib_dust conecta a região de origem e a de destino
    namib = idx.get("namib_dust")
    assert {"south_atlantic", "southeast_brazil", "southern_africa"}.issubset(set(namib.related))


def test_deterministico():
    a = TaxonomyIndex(load_taxonomy(TAXDIR)).stats()
    b = TaxonomyIndex(load_taxonomy(TAXDIR)).stats()
    assert a == b


def test_sem_llm_sem_banco():
    import inspect
    import sentinela.taxonomy.loader as l
    import sentinela.taxonomy.taxonomy as t
    import sentinela.taxonomy.validator as v
    src = inspect.getsource(l) + inspect.getsource(t) + inspect.getsource(v)
    assert "psycopg" not in src and "LLM" not in src and "openrouter" not in src.lower()
    assert "httpx" not in src and "requests" not in src
