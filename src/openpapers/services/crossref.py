"""CrossRef client — DOI metadata & reference enrichment.

Docs: https://api.crossref.org/swagger-ui/
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from ..config import get_settings
from ..http_client import HttpClientError, get_json
from ..models import Reference

log = logging.getLogger("openpapers.crossref")


# CrossRef reference.author is free-form text. Real separators include
# commas, semicolons, " & ", and " and ".
_AUTHORS_SPLIT = re.compile(r"\s*[,;]\s*|\s+&\s+|\s+\band\b\s+", re.IGNORECASE)


def _headers() -> dict[str, str]:
    return {"User-Agent": get_settings().user_agent}


def _params(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"mailto": get_settings().effective_contact_email}
    if extra:
        params.update(extra)
    return params


async def get_work(client: httpx.AsyncClient, doi: str) -> dict[str, Any] | None:
    """Return the raw CrossRef message item for a DOI, or None if missing."""
    url = f"{get_settings().crossref_base}/works/{doi}"
    try:
        data = await get_json(client, url, params=_params(), headers=_headers())
    except HttpClientError as e:
        if e.status == 404:
            return None
        log.debug("CrossRef get_work failed for %s: %s", doi, e)
        return None
    return data.get("message")


def parse_references(message: dict[str, Any]) -> list[Reference]:
    refs: list[Reference] = []
    for r in message.get("reference") or []:
        doi = r.get("DOI") or None
        title = None
        if r.get("article-title"):
            title = r["article-title"]
        elif r.get("unstructured"):
            title = r["unstructured"][:200]
        year = None
        if r.get("year"):
            try:
                year = int(r["year"])
            except (ValueError, TypeError):
                year = None
        journal = r.get("journal-title") or r.get("source")
        authors = _parse_authors(r.get("author"))
        refs.append(Reference(doi=doi, title=title, year=year, journal=journal, authors=authors))
    return refs


def _parse_authors(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [a.strip() for a in _AUTHORS_SPLIT.split(raw) if a.strip()][:10]


def parse_funders(message: dict[str, Any]) -> list[str]:
    return [f.get("name") for f in (message.get("funder") or []) if f.get("name")]


def parse_publisher(message: dict[str, Any]) -> str | None:
    return message.get("publisher")
