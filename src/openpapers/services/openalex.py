"""OpenAlex client — primary search & metadata source.

Docs: https://docs.openalex.org/

Uses the top-level `?search=` parameter (the documented, relevance-scored
full-text search) rather than the deprecated `filter=fulltext.search:...`
form. Year bounds are applied as a filter, which composes safely with
`?search=` because filters use `,` as a separator and `search` is its own
parameter — there is no way for a user query to inject filter clauses.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import get_settings
from ..http_client import HttpClientError, get_json
from ..models import Author, Concept, Paper, SearchResult
from .util import first_truthy, join_names, normalize_doi, reconstruct_abstract

log = logging.getLogger("openpapers.openalex")


def _polite_params(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"mailto": get_settings().effective_contact_email}
    if extra:
        params.update(extra)
    return params


async def search_works(
    client: httpx.AsyncClient,
    query: str,
    *,
    per_page: int = 10,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[SearchResult]:
    """Search OpenAlex works by relevance using the top-level `?search=` param.

    `sort=relevance_score:desc` is implicit when `search` is set; we set it
    explicitly for stability across API changes.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")

    params = _polite_params(
        {
            "search": query,
            "per-page": per_page,
            "sort": "relevance_score:desc",
        }
    )

    # Year bounds are applied as a *filter* (independent parameter, no
    # injection risk from the user query which lives in `search`).
    if year_from is not None or year_to is not None:
        lo = year_from if year_from is not None else 1000
        hi = year_to if year_to is not None else 9999
        params["filter"] = f"from_publication_date:{lo}-01-01,to_publication_date:{hi}-12-31"

    data = await get_json(client, f"{get_settings().openalex_base}/works", params=params)
    results = data.get("results", []) or []
    return [_to_search_result(w) for w in results]


async def get_work_by_doi(client: httpx.AsyncClient, doi: str) -> Paper | None:
    """Fetch a single work by bare DOI. Returns None on 404 (not found)."""
    url = f"{get_settings().openalex_base}/works/doi:{doi}"
    try:
        data = await get_json(client, url, params=_polite_params())
    except HttpClientError as e:
        if e.status == 404:
            return None
        log.debug("OpenAlex get_work_by_doi failed for %s: %s", doi, e)
        return None
    return _to_paper(data)


async def get_work_by_id(client: httpx.AsyncClient, openalex_id: str) -> Paper | None:
    """Fetch a single work by its OpenAlex ID (e.g. 'W3138516171')."""
    oid = openalex_id.strip()
    if not oid.startswith("W"):
        oid = f"W{oid}"
    if not oid.startswith("https://openalex.org/"):
        oid = f"https://openalex.org/{oid}"
    url = f"{get_settings().openalex_base}/works/{oid}"
    try:
        data = await get_json(client, url, params=_polite_params())
    except HttpClientError as e:
        if e.status == 404:
            return None
        log.debug("OpenAlex get_work_by_id failed for %s: %s", openalex_id, e)
        return None
    return _to_paper(data)


def _to_search_result(w: dict[str, Any]) -> SearchResult:
    doi = normalize_doi(w.get("doi"))

    primary = w.get("primary_location") or {}
    source = primary.get("source") or {}
    oa = w.get("open_access") or {}

    landing = first_truthy(
        primary.get("landing_page_url"),
        w.get("id"),
        w.get("doi"),
    )

    # Filter then slice so we always return up to N valid concepts.
    concepts = [c.get("display_name") for c in (w.get("concepts") or []) if c.get("display_name")][
        :8
    ]

    return SearchResult(
        openalex_id=_short_id(w.get("id")),
        doi=doi,
        title=w.get("display_name") or w.get("title") or "(untitled)",
        authors=join_names(w.get("authorships")),
        publication_year=w.get("publication_year"),
        venue=source.get("display_name"),
        cited_by_count=int(w.get("cited_by_count") or 0),
        is_oa=bool(oa.get("is_oa")),
        oa_status=oa.get("oa_status"),
        concepts=concepts,
        url=landing,
    )


def _to_paper(w: dict[str, Any]) -> Paper:
    doi = normalize_doi(w.get("doi"))

    primary = w.get("primary_location") or {}
    source = primary.get("source") or {}
    oa = w.get("open_access") or {}

    authors: list[Author] = []
    for a in w.get("authorships") or []:
        author = a.get("author") or {}
        institutions = [
            i.get("display_name") for i in (a.get("institutions") or []) if i.get("display_name")
        ]
        orcid = (author.get("orcid") or "").replace("https://orcid.org/", "") or None
        name = author.get("display_name") or a.get("raw_author_name")
        if name:
            authors.append(Author(name=name, orcid=orcid, affiliations=institutions))

    concepts = [
        Concept(name=c.get("display_name"), score=c.get("score"))
        for c in (w.get("concepts") or [])[:15]
        if c.get("display_name")
    ]

    keywords = [k.get("keyword") for k in (w.get("keywords") or []) if k.get("keyword")]

    ref_count = w.get("referenced_works_count")
    if ref_count is None:
        ref_count = len(w.get("referenced_works") or [])

    return Paper(
        doi=doi,
        openalex_id=_short_id(w.get("id")),
        title=w.get("display_name") or w.get("title") or "(untitled)",
        authors=authors,
        publication_year=w.get("publication_year"),
        publication_date=w.get("publication_date"),
        venue=source.get("display_name"),
        venue_type=source.get("type"),
        # OpenAlex does not expose a reliable publisher field; get_paper
        # enriches this from CrossRef where available.
        publisher=None,
        language=w.get("language"),
        abstract=reconstruct_abstract(w.get("abstract_inverted_index")),
        concepts=concepts,
        keywords=keywords,
        cited_by_count=int(w.get("cited_by_count") or 0),
        references_count=int(ref_count),
        references=[],  # populated via crossref enrichment in service layer
        is_oa=bool(oa.get("is_oa")),
        oa_status=oa.get("oa_status"),
        license=primary.get("license"),
        pdf_url=primary.get("pdf_url"),
        landing_page_url=first_truthy(primary.get("landing_page_url"), w.get("id"), w.get("doi")),
        # OpenAlex grants objects use `funder_display_name`, not `name`.
        funders=[
            g.get("funder_display_name")
            for g in (w.get("grants") or [])
            if g.get("funder_display_name")
        ],
    )


def _short_id(url: str | None) -> str | None:
    if not url:
        return None
    return url.rsplit("/", 1)[-1] or None
