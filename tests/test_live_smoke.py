"""Live API smoke tests against OpenAlex, CrossRef, and Unpaywall.

These tests are **deselected by default** and only run when the environment
variable ``OPENPAPERS_LIVE=1`` is set. They exist to give the manual CI job
(``live-smoke``) something real to do: one ping per upstream, asserting the
contract we depend on (field names, status codes) still holds.

Run locally:

    OPENPAPERS_LIVE=1 uv run pytest -m live -v

These tests intentionally use well-known fixtures (a canonical arXiv DOI
that is open access and present in all three databases) so transient
network blips are the only realistic failure mode.
"""

from __future__ import annotations

import os

import httpx
import pytest

from openpapers.http_client import build_client
from openpapers.services.crossref import get_work as crossref_get_work
from openpapers.services.openalex import search_works as openalex_search_works
from openpapers.services.unpaywall import lookup as unpaywall_lookup

# A canonical Nature paper that is (a) registered in CrossRef, (b) known to
# Unpaywall as open access, and (c) indexed by OpenAlex. Using an arXiv-only
# DOI here would 404 on CrossRef and Unpaywall, since neither tracks arXiv
# preprints reliably. This DOI is stable and widely cached.
CANONICAL_OA_DOI = "10.1038/s41586-021-03819-2"

_LIVE_ENABLED = os.environ.get("OPENPAPERS_LIVE") == "1"

# Skip the whole module unless the live gate is set. Keeps `pytest -m live`
# collection instant and silent in offline runs.
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _LIVE_ENABLED,
        reason="OPENPAPERS_LIVE is not set; run `OPENPAPERS_LIVE=1 uv run pytest -m live`",
    ),
]


@pytest.fixture
def live_client() -> httpx.AsyncClient:
    """A polite async client for a single live call."""
    return build_client()


async def test_openalex_search_returns_relevant_hit(live_client: httpx.AsyncClient) -> None:
    """OpenAlex ?search= must return at least one work with a title."""
    results = await openalex_search_works(live_client, "attention is all you need", per_page=3)
    assert results, "OpenAlex returned zero results for a known query"
    top = results[0]
    assert top.title, "top result has no title"
    assert top.cited_by_count is not None


async def test_crossref_resolves_canonical_doi(live_client: httpx.AsyncClient) -> None:
    """CrossRef must resolve a canonical DOI to a message with a title."""
    message = await crossref_get_work(live_client, CANONICAL_OA_DOI)
    assert message is not None, f"CrossRef could not resolve {CANONICAL_OA_DOI}"
    titles = message.get("title", [])
    assert titles and titles[0], "CrossRef message has no title"


async def test_unpaywall_returns_oa_status(live_client: httpx.AsyncClient) -> None:
    """Unpaywall must report a known OA DOI as open access."""
    result = await unpaywall_lookup(live_client, CANONICAL_OA_DOI)
    assert result is not None, f"Unpaywall returned None for {CANONICAL_OA_DOI}"
    assert result.is_oa is True, "canonical OA DOI should be marked open access"
