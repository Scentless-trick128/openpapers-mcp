# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_No public changes yet._

## [0.1.0] - 2026-07-18

### Added

- Initial release.
- Five MCP tools: `search_papers`, `get_paper`, `find_oa_pdf`, `download_pdf`,
  `research_topic`.
- OpenAlex, CrossRef, and Unpaywall integrations with polite-pool headers,
  retry-with-backoff, and HTTP-date `Retry-After` handling.
- 69 offline unit tests via `respx` (field mapping, security guards,
  retry/backoff, abstract reconstruction, OA resolution).
- Configuration via `.env` (`CONTACT_EMAIL`, `PDF_DIR`, `HTTP_*`, `PDF_MAX_BYTES`).
- `POLITE_POOL` env var: set to `0` to withhold the contact email from all
  upstream requests (privacy mode, at the cost of stricter rate limits).
- `LOG_LEVEL` env var to control logging verbosity.
- Security module with SSRF guards, path-traversal-safe filenames, and
  `%PDF-` magic-byte verification.
- Documentation for ZCode, Claude Desktop, and Cursor clients.
- CI matrix (Python 3.12 / 3.13 × ubuntu / macos / windows) with ruff, mypy
  strict, and offline pytest; optional `live-smoke` job on workflow dispatch.

### Changed

- `download_pdf` validates the URL scheme and resolved host (refuses private,
  loopback, link-local, CGNAT, and ULA networks) and verifies the downloaded
  bytes start with `%PDF-`.
- `download_pdf` writes to `<name>.pdf.part` and renames atomically on success
  — a failed or oversized download never leaves a partial file at the final
  path.
- `search_papers` uses OpenAlex's top-level `?search=` parameter instead of
  the deprecated `filter=fulltext.search:` form, restoring correct relevance
  scoring and removing comma-injection risk.
- `research_topic` enriches results concurrently (bounded) and no longer
  re-fetches works from OpenAlex just for their abstracts.
- `Paper.funder` (singular) is `Paper.funders` (it's a list). Funder lists
  from OpenAlex and CrossRef are merged and de-duplicated.
- Tool errors are surfaced as structured errors with sanitized messages
  rather than raw upstream response bodies.

### Fixed

- Path traversal via `download_pdf(filename=...)` — caller-supplied filenames
  are sanitized and the resolved destination is checked to stay inside
  `PDF_DIR`.
- Partial-file leak when a stream exceeded `PDF_MAX_BYTES` mid-download.
- OpenAlex `grants` field was read with the wrong key, so OpenAlex-derived
  funders were always empty.
- Ephemeral httpx client leak when the server lifespan context was missing —
  now raises a clear error instead.

### Security

- SSRF protection on `download_pdf` (scheme allowlist + IP classification).
- Path-traversal protection on caller-supplied filenames and destinations.
- `%PDF-` magic-byte verification of downloaded content.
- Atomic on-disk writes (`*.part` + `rename`) to prevent truncated files at
  the final path.

[Unreleased]: https://github.com/Kaago/openpapers-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Kaago/openpapers-mcp/releases/tag/v0.1.0
