from __future__ import annotations

import pytest

from sentinela.research.identity import (
    DoiError,
    OpenAlexIdError,
    normalize_doi,
    normalize_openalex_work_id,
)


def test_compact_w_id_is_unchanged():
    assert normalize_openalex_work_id("W1234567890") == "W1234567890"


def test_openalex_uri_compacts_to_w_id():
    assert normalize_openalex_work_id("https://openalex.org/W1234567890") == "W1234567890"


@pytest.mark.parametrize(
    "value",
    [
        "https://openalex.org/W1234567890/",
        "https://openalex.org/W1234567890?foo=1",
        "https://openalex.org/W1234567890#frag",
        "http://openalex.org/W1234567890",
    ],
)
def test_openalex_uri_noise_is_stripped(value: str):
    assert normalize_openalex_work_id(value) == "W1234567890"


@pytest.mark.parametrize("value", ["w123", "", "S123", "A123", "W", "openalex.org/Wabc"])
def test_malformed_openalex_ids_raise(value: str):
    with pytest.raises(OpenAlexIdError):
        normalize_openalex_work_id(value)


@pytest.mark.parametrize("value", [None, 1234567890, True, ["W1"]])
def test_non_string_openalex_ids_raise(value: object):
    with pytest.raises(OpenAlexIdError):
        normalize_openalex_work_id(value)


def test_doi_stays_lowercase_without_resolver():
    assert normalize_doi("10.1038/s41586-023-00001-1") == "10.1038/s41586-023-00001-1"


def test_doi_resolver_and_case_are_normalized():
    assert normalize_doi("https://doi.org/10.1038/S41586-023-00001-1") == "10.1038/s41586-023-00001-1"


def test_doi_prefix_is_stripped():
    assert normalize_doi("doi:10.1038/s41586-023-00001-1") == "10.1038/s41586-023-00001-1"


@pytest.mark.parametrize("value", [None, ""])
def test_empty_doi_is_none(value: object):
    assert normalize_doi(value) is None


@pytest.mark.parametrize("value", ["not-a-doi", "10.", "10.1038", "https://doi.org/"])
def test_malformed_doi_raises(value: str):
    with pytest.raises(DoiError):
        normalize_doi(value)


def test_identity_module_never_collapses_two_w_ids_with_same_doi():
    first = normalize_openalex_work_id("W111")
    second = normalize_openalex_work_id("W222")
    doi = normalize_doi("10.1000/xyz.1")
    assert first != second
    assert doi == "10.1000/xyz.1"
    assert (first, doi) != (second, doi)
