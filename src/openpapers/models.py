"""Pydantic models exposed to MCP clients.

These are the public contract between the server and the LLM. Fields are
nullable where the underlying API may legitimately omit them (e.g. abstracts
are frequently missing).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Author(BaseModel):
    name: str
    orcid: str | None = None
    affiliations: list[str] = Field(default_factory=list)


class Concept(BaseModel):
    name: str
    score: float | None = None  # 0..1 relevance, OpenAlex-specific


class SearchResult(BaseModel):
    """Compact record returned by `search_papers`."""

    openalex_id: str | None = None
    doi: str | None = None  # bare DOI, e.g. "10.1038/nature12373"
    title: str
    authors: list[str] = Field(default_factory=list)
    publication_year: int | None = None
    venue: str | None = None
    cited_by_count: int = 0
    is_oa: bool = False
    oa_status: str | None = None  # gold | green | hybrid | bronze | closed
    concepts: list[str] = Field(default_factory=list)
    url: str | None = None  # landing page


class Reference(BaseModel):
    doi: str | None = None
    title: str | None = None
    year: int | None = None
    journal: str | None = None
    authors: list[str] = Field(default_factory=list)


class Paper(BaseModel):
    """Full record returned by `get_paper`."""

    doi: str | None = None
    openalex_id: str | None = None
    title: str
    authors: list[Author] = Field(default_factory=list)
    publication_year: int | None = None
    publication_date: str | None = None
    venue: str | None = None
    venue_type: str | None = None  # journal | conference | repository | ...
    publisher: str | None = None
    language: str | None = None
    abstract: str | None = None
    concepts: list[Concept] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    cited_by_count: int = 0
    references_count: int = 0
    references: list[Reference] = Field(default_factory=list)
    is_oa: bool = False
    oa_status: str | None = None
    license: str | None = None
    pdf_url: str | None = None  # best known OA PDF URL (OpenAlex primary_location)
    landing_page_url: str | None = None
    funders: list[str] = Field(default_factory=list)


class OALocation(BaseModel):
    url_for_pdf: str | None = None
    url_for_landing_page: str | None = None
    version: str | None = None  # submittedVersion | acceptedVersion | publishedVersion
    host_type: str | None = None  # publisher | repository
    license: str | None = None
    repository_institution: str | None = None
    is_best: bool = False


class OAResult(BaseModel):
    """Result of `find_oa_pdf`."""

    doi: str | None = None
    is_oa: bool
    oa_status: str | None = None
    journal_is_oa: bool = False
    journal_is_in_doaj: bool = False
    genre: str | None = None
    journal_name: str | None = None
    best_oa_location: OALocation | None = None
    oa_locations: list[OALocation] = Field(default_factory=list)
    pdf_url: str | None = None  # convenience: best_oa_location.url_for_pdf

    @property
    def summary(self) -> str:
        if not self.is_oa:
            return f"No Open Access PDF found for {self.doi}."
        loc = self.best_oa_location.url_for_pdf if self.best_oa_location else None
        return f"OA PDF for {self.doi}: {loc or '(landing page only)'}"


class DownloadResult(BaseModel):
    """Result of `download_pdf`."""

    url: str
    local_path: str
    doi: str | None = None
    bytes_written: int
    content_type: str | None = None


class PaperSummary(BaseModel):
    """One entry in a `research_topic` overview."""

    doi: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    cited_by_count: int = 0
    abstract_excerpt: str | None = None  # first ~400 chars
    oa_pdf_url: str | None = None
    oa_status: str | None = None


class ResearchSummary(BaseModel):
    """Result of `research_topic`."""

    query: str
    total_results: int
    papers: list[PaperSummary] = Field(default_factory=list)
    oa_available_count: int = 0
