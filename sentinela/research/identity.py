from __future__ import annotations

import re

OPENALEX_SOURCE = "openalex"

_W_ID = re.compile(r"^W\d+$")
_DOI = re.compile(r"^10\.\d{4,9}/\S+$")
_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
)


class OpenAlexIdError(ValueError):
    pass


class DoiError(ValueError):
    pass


def normalize_openalex_work_id(value: object) -> str:
    if not isinstance(value, str):
        raise OpenAlexIdError("OpenAlex work id must be a string")
    text = value.strip()
    if not text:
        raise OpenAlexIdError("OpenAlex work id is empty")
    lowered = text.lower()
    for prefix in ("https://openalex.org/", "http://openalex.org/"):
        if lowered.startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.strip().split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if text.startswith("openalex.org/"):
        text = text.split("/", 1)[1]
    if not _W_ID.match(text):
        raise OpenAlexIdError("OpenAlex work id is malformed")
    return text


def normalize_doi(value: object | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DoiError("DOI must be a string")
    text = value.strip()
    if not text:
        return None
    lowered = text.lower()
    for prefix in _DOI_PREFIXES:
        if lowered.startswith(prefix):
            text = text[len(prefix) :]
            lowered = text.lower()
            break
    text = text.strip().rstrip("/")
    if not text:
        raise DoiError("DOI resolver has no identifier")
    canonical = text.lower()
    if not _DOI.match(canonical):
        raise DoiError("DOI is malformed")
    return canonical
