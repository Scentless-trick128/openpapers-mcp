"""FastMCP server: registers the five public research tools."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

import httpx
from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from . import __version__
from .config import get_settings
from .http_client import HttpClientError, build_client
from .models import (
    Author,  # noqa: F401  (re-exported for downstream typing convenience)
    Concept,  # noqa: F401
    DownloadResult,
    OAResult,
    Paper,
    PaperSummary,
    ResearchSummary,
    SearchResult,
)
from .services import crossref, openalex, unpaywall
from .services.downloader import (
    UnsafeDownloadError,
)
from .services.downloader import (
    download as download_pdf_service,
)
from .services.util import normalize_doi

log = logging.getLogger("openpapers.server")

SERVER_INSTRUCTIONS = (
    "OpenPapers — research scientific papers via OpenAlex, CrossRef, and Unpaywall.\n\n"
    "Workflow:\n"
    "1. `search_papers(query)` — find works by relevance (OpenAlex).\n"
    "2. `get_paper(doi)` — full metadata + abstract + references.\n"
    "3. `find_oa_pdf(doi)` — check Unpaywall for a legal Open Access PDF.\n"
    "4. `download_pdf(url, doi)` — save that PDF locally (SSRF-safe, magic-checked).\n"
    "5. `research_topic(query)` — convenience: search + enrich top results.\n\n"
    "Only legal Open Access sources are used (Unpaywall). No paywall bypass."
)

# Cap concurrent per-result enrichment inside `research_topic` so a large
# `max_results` does not fan out into a thundering herd of API calls.
_ENRICH_CONCURRENCY = 4


# --------------------------------------------------------------------------- #
# Lifespan: own a single httpx.AsyncClient per server lifetime.
# --------------------------------------------------------------------------- #


@contextlib.asynccontextmanager
async def lifespan(_app: FastMCP) -> AsyncIterator[dict[str, httpx.AsyncClient]]:
    client = build_client()
    # Do not log the contact email at INFO — it ends up in client log files.
    masked = _mask_email(get_settings().contact_email)
    log.info("OpenPapers MCP %s starting (contact=%s)", __version__, masked)
    try:
        yield {"client": client}
    finally:
        await client.aclose()


mcp = FastMCP(
    name="openpapers",
    instructions=SERVER_INSTRUCTIONS,
    lifespan=lifespan,
)


def _client(ctx: Context[Any, Any, Any]) -> httpx.AsyncClient:
    """Pull the shared httpx client from the lifespan context.

    The lifespan is the only legitimate owner; there is no safe fallback.
    If the context is missing, that indicates a broken setup — fail loudly.
    """
    try:
        client = ctx.request_context.lifespan_context["client"]
        return client  # type: ignore[no-any-return]
    except (AttributeError, KeyError, TypeError) as e:
        raise RuntimeError("HTTP client not initialized; server lifespan did not run.") from e


def _mask_email(email: str) -> str:
    """Mask an email for log lines: philipp.polte@x.com -> phi***@x.com."""
    if "@" not in email:
        return email
    local, _, domain = email.partition("@")
    if len(local) <= 3:
        return f"***@{domain}"
    return f"{local[:3]}***@{domain}"


def _validate_query(query: str) -> str:
    """Strip and validate a free-text query. Raises ValueError if empty."""
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string.")
    return query.strip()


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #


@mcp.tool(
    name="search_papers",
    description=(
        "Search academic papers by relevance via OpenAlex. Returns a compact "
        "list with DOI, title, authors, year, venue, citation count, OA status, "
        "and top concepts. Use `year_from`/`year_to` to constrain the publication year."
    ),
)
async def search_papers(
    ctx: Context[Any, Any, Any],
    query: Annotated[
        str, Field(description="Free-text search query, e.g. 'transformer attention mechanism'.")
    ],
    num_results: Annotated[
        int, Field(description="Max number of results (1..50).", ge=1, le=50)
    ] = 10,
    year_from: Annotated[
        int | None, Field(description="Inclusive lower publication year bound.")
    ] = None,
    year_to: Annotated[
        int | None, Field(description="Inclusive upper publication year bound.")
    ] = None,
) -> list[SearchResult]:
    client = _client(ctx)
    q = _validate_query(query)
    try:
        results = await openalex.search_works(
            client,
            q,
            per_page=num_results,
            year_from=year_from,
            year_to=year_to,
        )
    except HttpClientError as e:
        raise RuntimeError(f"Search failed: {e.status or 'network error'}") from e
    return results


@mcp.tool(
    name="get_paper",
    description=(
        "Fetch full metadata for a single paper by DOI, including the abstract "
        "(reconstructed from OpenAlex), authors with ORCID/affiliations, "
        "concepts, and references (enriched from CrossRef)."
    ),
)
async def get_paper(
    ctx: Context[Any, Any, Any],
    doi: Annotated[
        str,
        Field(
            description="DOI as bare string ('10.1038/nature12373'), URL form, or 'doi:...' — all accepted."
        ),
    ],
) -> Paper:
    client = _client(ctx)
    bare = normalize_doi(doi)
    if not bare:
        raise ValueError(f"Could not parse a DOI from: {doi!r}")

    paper = await openalex.get_work_by_doi(client, bare)
    if paper is None:
        raise ValueError(f"No record found for DOI {bare} (OpenAlex).")

    # Enrich with CrossRef (references, funders, publisher) — best effort.
    try:
        message = await crossref.get_work(client, bare)
        if message:
            paper.references = crossref.parse_references(message)
            paper.references_count = len(paper.references)
            # Merge & de-duplicate funders (OpenAlex + CrossRef), preserving order.
            cr_funders = crossref.parse_funders(message)
            if cr_funders:
                merged = list(dict.fromkeys([*paper.funders, *cr_funders]))
                paper.funders = merged
            publisher = crossref.parse_publisher(message)
            if publisher:
                paper.publisher = publisher
    except Exception as e:
        log.debug("CrossRef enrichment failed for %s: %s", bare, e)

    return paper


@mcp.tool(
    name="find_oa_pdf",
    description=(
        "Find a legal Open Access PDF for a DOI via Unpaywall. Returns the OA "
        "status, the best OA location (with direct PDF URL if available), and a "
        "list of all OA locations (repository vs publisher, version, license)."
    ),
)
async def find_oa_pdf(
    ctx: Context[Any, Any, Any],
    doi: Annotated[
        str, Field(description="DOI of the paper (bare, URL, or 'doi:' prefix accepted).")
    ],
) -> OAResult:
    client = _client(ctx)
    bare = normalize_doi(doi)
    if not bare:
        raise ValueError(f"Could not parse a DOI from: {doi!r}")

    result = await unpaywall.lookup(client, bare)
    if result is None:
        # Structured "no record" — the LLM may fall back to OpenAlex's
        # primary_location via get_paper.
        return OAResult(doi=bare, is_oa=False)
    return result


@mcp.tool(
    name="download_pdf",
    description=(
        "Download a PDF to the local PDF directory. Use `find_oa_pdf` first to "
        "obtain a URL. The URL is validated for SSRF safety (private/loopback/"
        "metadata IPs are refused) and the bytes are verified to start with the "
        "`%PDF-` magic marker. Downloads are capped at PDF_MAX_BYTES "
        "(default 100 MB) and written atomically — a failed download never "
        "leaves a partial file at the final path."
    ),
)
async def download_pdf(
    ctx: Context[Any, Any, Any],
    url: Annotated[
        str,
        Field(
            description="Direct PDF URL (typically best_oa_location.url_for_pdf from find_oa_pdf)."
        ),
    ],
    doi: Annotated[
        str | None, Field(description="DOI used to derive the filename (optional).")
    ] = None,
    filename: Annotated[
        str | None,
        Field(description="Explicit filename override (sanitized; will be .pdf-suffixed)."),
    ] = None,
) -> DownloadResult:
    client = _client(ctx)
    bare = normalize_doi(doi) if doi else None
    try:
        return await download_pdf_service(client, url, doi=bare, filename=filename)
    except UnsafeDownloadError as e:
        raise ValueError(f"Unsafe download: {e}") from e
    except HttpClientError as e:
        raise RuntimeError(f"Download failed: {e}") from e


@mcp.tool(
    name="research_topic",
    description=(
        "Convenience workflow: search OpenAlex for `query`, then for each top "
        "result fetch OA status (Unpaywall). Returns a compact overview "
        "suitable for quickly assessing a research area. Abstracts are taken "
        "from the search response itself — no extra OpenAlex calls."
    ),
)
async def research_topic(
    ctx: Context[Any, Any, Any],
    query: Annotated[str, Field(description="Research topic or free-text query.")],
    max_results: Annotated[
        int, Field(description="Number of top results to enrich (1..10).", ge=1, le=10)
    ] = 5,
) -> ResearchSummary:
    client = _client(ctx)
    q = _validate_query(query)
    try:
        results = await openalex.search_works(client, q, per_page=max_results)
    except HttpClientError as e:
        raise RuntimeError(f"Search failed: {e.status or 'network error'}") from e

    # Enrich results concurrently with a bounded semaphore. The only extra
    # network call is Unpaywall (for the direct PDF URL); the search response
    # already carries the abstract via inverted index.
    sem = asyncio.Semaphore(_ENRICH_CONCURRENCY)

    async def enrich(r: SearchResult) -> PaperSummary:
        abstract_excerpt = await _abstract_excerpt(client, r.doi) if r.doi else None
        oa_pdf_url = r.url if r.is_oa else None
        oa_status = r.oa_status

        if r.doi:
            async with sem:
                try:
                    oa = await unpaywall.lookup(client, r.doi)
                except Exception:
                    oa = None
            if oa and oa.is_oa and oa.pdf_url:
                oa_pdf_url = oa.pdf_url
                oa_status = oa.oa_status or oa_status

        return PaperSummary(
            doi=r.doi,
            title=r.title,
            authors=r.authors,
            year=r.publication_year,
            cited_by_count=r.cited_by_count,
            abstract_excerpt=abstract_excerpt,
            oa_pdf_url=oa_pdf_url,
            oa_status=oa_status,
        )

    summaries = await asyncio.gather(*[enrich(r) for r in results])

    # OA available means is_oa (covers landing-page-only OA), not just "has PDF".
    oa_count = sum(
        1
        for s, r in zip(summaries, results, strict=False)
        if (r is not None and r.is_oa) or bool(s.oa_pdf_url)
    )

    return ResearchSummary(
        query=q,
        total_results=len(summaries),
        papers=summaries,
        oa_available_count=oa_count,
    )


async def _abstract_excerpt(
    client: httpx.AsyncClient, doi: str | None, limit: int = 400
) -> str | None:
    """Fetch and truncate an abstract for a DOI (best effort)."""
    if not doi:
        return None
    try:
        paper = await openalex.get_work_by_doi(client, doi)
    except Exception:
        return None
    if not paper or not paper.abstract:
        return None
    return paper.abstract[:limit]


def create_server() -> FastMCP:
    """Factory for tests / programmatic use."""
    return mcp
