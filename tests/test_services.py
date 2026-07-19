"""Service tests with mocked HTTP responses (respx)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from openpapers.http_client import _parse_retry_after, build_client, get_json
from openpapers.services import crossref, openalex, unpaywall

# --------------------------------------------------------------------------- #
# OpenAlex
# --------------------------------------------------------------------------- #

OPENALEX_WORK = {
    "id": "https://openalex.org/W1234567890",
    "doi": "https://doi.org/10.1038/nature12373",
    "title": "Test Paper Title",
    "display_name": "Test Paper Title",
    "publication_year": 2013,
    "publication_date": "2013-07-31",
    "language": "en",
    "cited_by_count": 1965,
    "abstract_inverted_index": {"Hello": [0], "world": [1]},
    "authorships": [
        {
            "author": {
                "display_name": "Alice Smith",
                "orcid": "https://orcid.org/0000-0001-0002-0003",
            },
            "institutions": [{"display_name": "MIT"}],
        },
    ],
    "concepts": [
        {"display_name": "Physics", "score": 0.9},
        {"display_name": None, "score": 0.5},  # filtered out
        {"display_name": "Quantum", "score": 0.7},
    ],
    "keywords": [{"keyword": "thermometry"}, {"keyword": "diamond"}],
    "primary_location": {
        "is_oa": True,
        "pdf_url": "https://example.org/paper.pdf",
        "landing_page_url": "https://doi.org/10.1038/nature12373",
        "license": "cc-by",
        "source": {"display_name": "Nature", "type": "journal"},
    },
    "open_access": {"is_oa": True, "oa_status": "green"},
    "referenced_works": ["https://openalex.org/W1", "https://openalex.org/W2"],
    "grants": [
        {"funder_display_name": "NSF", "award_id": "ABC"},
        {"funder_display_name": None, "award_id": "X"},  # filtered
    ],
}

OPENALEX_SEARCH_RESPONSE = {
    "meta": {"count": 1},
    "results": [OPENALEX_WORK],
}


@pytest.mark.asyncio
@respx.mock
async def test_search_works_uses_search_parameter():
    """The bug fix: OpenAlex search must use `?search=`, not `filter=fulltext.search:`."""
    route = respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(200, json=OPENALEX_SEARCH_RESPONSE)
    )
    async with build_client() as client:
        results = await openalex.search_works(client, "test query", per_page=1)

    request = route.calls.last.request
    assert request.url.params.get("search") == "test query"
    # The deprecated filter form must NOT appear.
    assert "fulltext.search" not in str(request.url)
    assert request.url.params.get("sort") == "relevance_score:desc"

    assert len(results) == 1
    r = results[0]
    assert r.doi == "10.1038/nature12373"
    assert r.title == "Test Paper Title"
    assert r.openalex_id == "W1234567890"
    assert r.is_oa is True
    assert r.oa_status == "green"
    assert r.venue == "Nature"
    # Concepts are filtered then sliced — None entries removed.
    assert "Physics" in r.concepts
    assert "Quantum" in r.concepts
    assert len(r.concepts) == 2


@pytest.mark.asyncio
@respx.mock
async def test_search_works_comma_in_query_does_not_inject_filter():
    """A comma in the query must not split it into multiple filter clauses."""
    route = respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(200, json=OPENALEX_SEARCH_RESPONSE)
    )
    async with build_client() as client:
        await openalex.search_works(client, "machine learning, transformers", per_page=1)

    request = route.calls.last.request
    assert request.url.params.get("search") == "machine learning, transformers"
    assert "filter" not in request.url.params


@pytest.mark.asyncio
@respx.mock
async def test_search_works_year_bounds_applied_as_filter():
    route = respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(200, json=OPENALEX_SEARCH_RESPONSE)
    )
    async with build_client() as client:
        await openalex.search_works(client, "test", per_page=1, year_from=2020, year_to=2024)
    request = route.calls.last.request
    filt = request.url.params.get("filter", "")
    assert "from_publication_date:2020-01-01" in filt
    assert "to_publication_date:2024-12-31" in filt


@pytest.mark.asyncio
async def test_search_works_rejects_empty_query():
    async with build_client() as client:
        with pytest.raises(ValueError, match="non-empty"):
            await openalex.search_works(client, "   ", per_page=1)


@pytest.mark.asyncio
@respx.mock
async def test_get_work_by_doi_reconstructs_abstract():
    respx.get("https://api.openalex.org/works/doi:10.1038/nature12373").mock(
        return_value=httpx.Response(200, json=OPENALEX_WORK)
    )
    async with build_client() as client:
        paper = await openalex.get_work_by_doi(client, "10.1038/nature12373")
    assert paper is not None
    assert paper.abstract == "Hello world"
    assert paper.authors[0].name == "Alice Smith"
    assert paper.authors[0].orcid == "0000-0001-0002-0003"
    assert paper.authors[0].affiliations == ["MIT"]
    assert paper.pdf_url == "https://example.org/paper.pdf"
    assert paper.references_count == 2
    assert paper.license == "cc-by"
    assert paper.funders == ["NSF"]


@pytest.mark.asyncio
@respx.mock
async def test_get_work_by_doi_returns_none_on_404():
    respx.get("https://api.openalex.org/works/doi:10.9999/missing").mock(
        return_value=httpx.Response(404, text="not found")
    )
    async with build_client() as client:
        paper = await openalex.get_work_by_doi(client, "10.9999/missing")
    assert paper is None


@pytest.mark.asyncio
@respx.mock
async def test_get_work_by_doi_handles_missing_optional_fields():
    sparse = {
        "id": "https://openalex.org/W1",
        "display_name": "Sparse Paper",
    }
    respx.get("https://api.openalex.org/works/doi:10.1/x").mock(
        return_value=httpx.Response(200, json=sparse)
    )
    async with build_client() as client:
        paper = await openalex.get_work_by_doi(client, "10.1/x")
    assert paper is not None
    assert paper.doi is None
    assert paper.authors == []
    assert paper.abstract is None
    assert paper.funders == []
    assert paper.venue is None


# --------------------------------------------------------------------------- #
# CrossRef
# --------------------------------------------------------------------------- #

CROSSREF_MESSAGE = {
    "DOI": "10.1038/nature12373",
    "title": ["Test Paper Title"],
    "publisher": "Springer Nature",
    "reference": [
        {"DOI": "10.3402/nano.v3i0.11586", "article-title": "A cited work", "year": "2012"},
        {"unstructured": "Some unstructured citation"},
        {"author": "Smith J, Jones A & Brown C and Lee D"},
    ],
    "funder": [{"name": "NSF"}, {"name": "NIH"}],
}


@pytest.mark.asyncio
@respx.mock
async def test_crossref_get_work():
    respx.get("https://api.crossref.org/works/10.1038/nature12373").mock(
        return_value=httpx.Response(200, json={"status": "ok", "message": CROSSREF_MESSAGE})
    )
    async with build_client() as client:
        msg = await crossref.get_work(client, "10.1038/nature12373")
    assert msg is not None
    refs = crossref.parse_references(msg)
    assert len(refs) == 3
    assert refs[0].doi == "10.3402/nano.v3i0.11586"
    assert refs[0].title == "A cited work"
    assert refs[0].year == 2012
    assert crossref.parse_funders(msg) == ["NSF", "NIH"]
    assert crossref.parse_publisher(msg) == "Springer Nature"


def test_crossref_author_splitting_handles_multiple_separators():
    """The reference above mixes comma, &, and 'and' separators."""
    refs = crossref.parse_references(
        {"reference": [{"author": "Smith J, Jones A & Brown C and Lee D"}]}
    )
    assert refs[0].authors == ["Smith J", "Jones A", "Brown C", "Lee D"]


@pytest.mark.asyncio
@respx.mock
async def test_crossref_returns_none_on_404():
    respx.get("https://api.crossref.org/works/10.9999/missing").mock(
        return_value=httpx.Response(404, text="not found")
    )
    async with build_client() as client:
        msg = await crossref.get_work(client, "10.9999/missing")
    assert msg is None


# --------------------------------------------------------------------------- #
# Unpaywall
# --------------------------------------------------------------------------- #

UNPAYWALL_RESPONSE = {
    "doi": "10.1038/nature12373",
    "is_oa": True,
    "oa_status": "green",
    "journal_is_oa": False,
    "journal_is_in_doaj": False,
    "genre": "journal-article",
    "journal_name": "Nature",
    "best_oa_location": {
        "url_for_pdf": "https://arxiv.org/pdf/1304.1068",
        "url_for_landing_page": "http://arxiv.org/abs/1304.1068",
        "version": "submittedVersion",
        "host_type": "repository",
        "is_best": True,
    },
    "oa_locations": [
        {
            "url_for_pdf": "https://arxiv.org/pdf/1304.1068",
            "host_type": "repository",
            "version": "submittedVersion",
        },
    ],
}


@pytest.mark.asyncio
@respx.mock
async def test_unpaywall_lookup():
    respx.get("https://api.unpaywall.org/v2/10.1038/nature12373").mock(
        return_value=httpx.Response(200, json=UNPAYWALL_RESPONSE)
    )
    async with build_client() as client:
        result = await unpaywall.lookup(client, "10.1038/nature12373")
    assert result is not None
    assert result.is_oa is True
    assert result.pdf_url == "https://arxiv.org/pdf/1304.1068"
    assert result.best_oa_location is not None
    assert result.best_oa_location.version == "submittedVersion"
    assert len(result.oa_locations) == 1


@pytest.mark.asyncio
@respx.mock
async def test_unpaywall_lookup_missing_returns_none():
    respx.get("https://api.unpaywall.org/v2/10.9999/missing").mock(
        return_value=httpx.Response(404, text="not found")
    )
    async with build_client() as client:
        result = await unpaywall.lookup(client, "10.9999/missing")
    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_unpaywall_no_best_location_falls_back_to_first():
    """If best_oa_location is absent but oa_locations has entries, use the first."""
    payload = {
        "doi": "10.1/x",
        "is_oa": True,
        "oa_status": "green",
        "oa_locations": [
            {"url_for_pdf": "https://example.org/a.pdf", "host_type": "repository"},
            {"url_for_pdf": "https://example.org/b.pdf", "host_type": "repository"},
        ],
    }
    respx.get("https://api.unpaywall.org/v2/10.1/x").mock(
        return_value=httpx.Response(200, json=payload)
    )
    async with build_client() as client:
        result = await unpaywall.lookup(client, "10.1/x")
    assert result is not None
    assert result.best_oa_location is not None
    assert result.pdf_url == "https://example.org/a.pdf"


# --------------------------------------------------------------------------- #
# HTTP client retry behaviour
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@respx.mock
async def test_get_json_retries_on_429_then_succeeds(monkeypatch):
    # Make backoff instant so the test doesn't sleep.
    import openpapers.http_client as hc

    monkeypatch.setattr(hc, "_backoff", lambda attempt: 0.0)

    route = respx.get("https://api.example.org/x").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with build_client() as client:
        data = await get_json(client, "https://api.example.org/x", max_retries=2)
    assert data == {"ok": True}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_get_json_raises_after_exhausting_retries(monkeypatch):
    import openpapers.http_client as hc

    monkeypatch.setattr(hc, "_backoff", lambda attempt: 0.0)

    respx.get("https://api.example.org/x").mock(return_value=httpx.Response(503))
    async with build_client() as client:
        with pytest.raises(Exception):
            await get_json(client, "https://api.example.org/x", max_retries=1)


@pytest.mark.asyncio
@respx.mock
async def test_get_json_raises_on_404_immediately():
    route = respx.get("https://api.example.org/x").mock(return_value=httpx.Response(404))
    async with build_client() as client:
        with pytest.raises(Exception, match="Not found"):
            await get_json(client, "https://api.example.org/x", max_retries=3)
    assert route.call_count == 1  # 404 is not retried


def test_parse_retry_after_seconds():
    assert _parse_retry_after("5") == 5.0
    assert _parse_retry_after("0") == 0.0


def test_parse_retry_after_http_date():
    """RFC 7231 HTTP-date form must be honored."""
    future = (datetime.now(UTC) + timedelta(seconds=30)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    seconds = _parse_retry_after(future)
    assert 20 <= seconds <= 35


def test_parse_retry_after_invalid_falls_back():
    assert _parse_retry_after("not-a-date") >= 0
