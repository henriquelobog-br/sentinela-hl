"""
Sentinela HL — carregamento da Taxonomia a partir de YAML (Documento 112.7A).

Um arquivo YAML por domínio científico. O loader carrega, valida com Pydantic
(estrutura) e com o validator (integridade referencial). Falha com mensagem
clara indicando ARQUIVO e problema — nunca silenciosamente.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from sentinela.taxonomy.models import Domain, Taxonomy
from sentinela.taxonomy.validator import validate_taxonomy


class TaxonomyLoadError(ValueError):
    """Erro de carregamento com o caminho do arquivo problemático."""


def load_domain_file(path: str | Path) -> Domain:
    p = Path(path)
    if not p.exists():
        raise TaxonomyLoadError(f"arquivo de taxonomia não encontrado: {p}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise TaxonomyLoadError(f"YAML inválido em {p.name}: {e}") from e
    if not isinstance(data, dict):
        raise TaxonomyLoadError(f"{p.name}: esperado um mapeamento de domínio no topo")
    try:
        return Domain.model_validate(data)
    except ValidationError as e:
        raise TaxonomyLoadError(f"{p.name}: estrutura inválida:\n{e}") from e


def load_taxonomy(directory: str | Path, *, version: str = "1") -> Taxonomy:
    """Carrega todos os .yaml do diretório (ordem alfabética = determinística),
    monta a Taxonomy e valida a integridade referencial do conjunto."""
    d = Path(directory)
    if not d.is_dir():
        raise TaxonomyLoadError(f"diretório de taxonomia não encontrado: {d}")
    files = sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml"))
    if not files:
        raise TaxonomyLoadError(f"nenhum arquivo .yaml em {d}")
    domains = [load_domain_file(f) for f in files]
    tax = Taxonomy(version=version, domains=domains)
    validate_taxonomy(tax)      # levanta TaxonomyValidationError com tudo listado
    return tax
