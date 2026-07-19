"""Common helpers shared across services."""

from __future__ import annotations

import re
from typing import Any

# Match a DOI either bare, with "doi:" prefix, or as a full URL.
# The character class deliberately excludes URL-significant chars (`?#&[]{}|^\\`)
# so a "DOI" cannot inject a path/query/fragment into upstream API URLs.
_DOI_RE = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/|doi:)?(10\.\d{4,9}/[^\s\"<>?#\[\]{}|\\^]+)",
    re.IGNORECASE,
)


def normalize_doi(value: str | None) -> str | None:
    """Return a bare DOI (e.g. '10.1038/nature12373') or None.

    Strips URL prefixes, surrounding whitespace, and trailing punctuation
    that commonly sneaks in via copy-paste.
    """
    if not value:
        return None
    v = value.strip()
    m = _DOI_RE.search(v)
    if not m:
        return None
    doi = m.group(1).rstrip(".,);]")
    return doi


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    """Rebuild an OpenAlex abstract from its inverted index representation.

    OpenAlex stores abstracts as `{word: [positions]}` to avoid giving away
    full text; the reconstruction is deterministic and lossless.
    """
    if not inverted_index:
        return None
    pairs: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            pairs.append((pos, word))
    if not pairs:
        return None
    pairs.sort(key=lambda p: p[0])
    return " ".join(word for _, word in pairs)


def join_names(authorships: list[dict[str, Any]] | Any) -> list[str]:
    names: list[str] = []
    for a in authorships or []:
        author = a.get("author") or {}
        name = author.get("display_name") or a.get("raw_author_name")
        if name:
            names.append(name)
    return names


def first_truthy(*values: Any) -> Any:
    for v in values:
        if v:
            return v
    return None
