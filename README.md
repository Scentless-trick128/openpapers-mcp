# OpenPapers MCP

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/Kaago/openpapers-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Kaago/openpapers-mcp/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](#development)

A local [Model Context Protocol](https://modelcontextprotocol.io) server for
scientific paper research — search, metadata, abstracts, and **legal** Open
Access PDF downloads. Runs entirely on your machine over stdio. Works with
Claude Desktop, ZCode, Cursor, and any other MCP client.

**Why use this instead of hitting the APIs directly?** It abstracts three
open scholarly APIs into five LLM-callable tools, reconstructs abstracts
from OpenAlex's inverted index, finds legal OA copies via Unpaywall, and
safely downloads PDFs (SSRF-safe, magic-byte-verified, atomic). No
Sci-Hub, no paywall bypass, no institutional license required.

## Backed by three free, open APIs

| API | Role | Auth |
|---|---|---|
| [OpenAlex](https://openalex.org) | Search, metadata, abstracts (inverted index), concepts, citations | `mailto` (polite pool) |
| [CrossRef](https://crossref.org) | DOI lookup, reference list, funders, publisher | `mailto` + User-Agent |
| [Unpaywall](https://unpaywall.org) | Legal Open Access PDFs from repositories & publishers | `email` |

> **What this is *not*:** No Sci-Hub, no paywall bypass, no EBSCO (which
> needs an institutional license). Only legitimately OA sources via Unpaywall.

---

## Quick start

```bash
git clone https://github.com/Kaago/openpapers-mcp.git
cd OpenPapers
cp .env.example .env        # then edit CONTACT_EMAIL
uv sync                     # install deps
uv run pytest               # 69 offline tests (+ 3 live tests gated on OPENPAPERS_LIVE=1)
uv run openpapers           # start the stdio MCP server
```

Requirements: Python ≥ 3.12 and [`uv`](https://docs.astral.sh/uv/).

---

## Tools

| Tool | Description |
|---|---|
| `search_papers(query, num_results=10, year_from?, year_to?)` | OpenAlex relevance search. Returns DOI, title, authors, year, venue, citations, OA status, concepts. |
| `get_paper(doi)` | Full metadata + abstract (reconstructed) + references (CrossRef-enriched) + authors with ORCID/affiliations + funders + publisher. |
| `find_oa_pdf(doi)` | Unpaywall lookup. Returns `is_oa`, best OA location with direct PDF URL, all OA locations (version, license, host type). |
| `download_pdf(url, doi?, filename?)` | Streams the PDF to `$PDF_DIR`. **SSRF-safe** (private/loopback/metadata IPs refused), **magic-byte-verified** (`%PDF-`), capped at `PDF_MAX_BYTES`, written **atomically** (no partial files). |
| `research_topic(query, max_results=5)` | Convenience: searches + enriches top results with OA status concurrently. Compact overview for scoping an area. |

### Typical workflow

```
search_papers("transformer attention")              → list of candidates
  └─ get_paper("10.48550/arXiv.1706.03762")         → full record + abstract
  └─ find_oa_pdf("10.48550/arXiv.1706.03762")       → OA URL
       └─ download_pdf("<url>", "10.48550/arXiv.1706.03762")  → local file
```

---

## Configuration

All configuration lives in `.env` (git-ignored). See [`.env.example`](./.env.example):

```dotenv
# Your email — sent only as mailto=/User-Agent to the three APIs.
# Set POLITE_POOL=0 to withhold it entirely (privacy mode).
CONTACT_EMAIL=your-email@example.com
POLITE_POOL=1

# Where downloaded PDFs land.
PDF_DIR=./pdfs

# HTTP tuning
HTTP_TIMEOUT=30
HTTP_MAX_RETRIES=3
PDF_MAX_BYTES=104857600   # 100 MB

# Logging
LOG_LEVEL=INFO
```

If `CONTACT_EMAIL` is unset, a neutral placeholder is used — the server still
works, just with potentially stricter rate limits.

---

## Privacy

- **Your email** is sent only in `mailto=` query params / `User-Agent` headers
  to OpenAlex, CrossRef, and Unpaywall — never to any other party. It is
  **not** logged at INFO level (only a masked form, e.g. `you***@x.com`).
  Set `POLITE_POOL=0` to withhold it entirely.
- **Search queries and DOIs** are sent to those three APIs as part of normal
  operation. Stderr logs may include them at WARNING level on errors. The
  stderr stream is captured by your MCP client into a local log file.
- **Downloaded PDFs** persist on disk under `PDF_DIR` and reveal your
  research interests. The directory is git-ignored.

---

## Connect your MCP client

The server is a standard stdio MCP server. Add it to your client's config,
replacing `/path/to/OpenPapers` with your checkout path.

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "openpapers": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/OpenPapers", "openpapers"]
    }
  }
}
```

### ZCode

`~/.zcode/config.toml` (or workspace `.zcode/config.toml`):

```toml
[[mcp_servers]]
name = "openpapers"
transport = "stdio"

[mcp_servers.stdio]
command = "uv"
args = ["run", "--directory", "/path/to/OpenPapers", "openpapers"]
```

### Cursor

`.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "openpapers": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/OpenPapers", "openpapers"]
    }
  }
}
```

After editing, restart the client. The five `openpapers` tools should appear.

---

## Development

```bash
# Tests (offline — uses respx mocks, no network needed)
uv run pytest

# Lint & format
uv run ruff check .
uv run ruff format --check .

# Type check
uv run mypy

# Optional: live smoke test against the real APIs
OPENPAPERS_LIVE=1 uv run pytest -m live
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full developer guide,
including the **offline-tests-only** convention.

### Project layout

```
src/openpapers/
├── __main__.py        # entry point: `uv run openpapers`
├── server.py          # FastMCP + 5 tool registrations
├── config.py          # .env loading, paths, constants, version source-of-truth
├── http_client.py     # httpx client w/ retry, polite headers, safe download
├── security.py        # SSRF & path-traversal guards
├── models.py          # Pydantic models (public tool contract)
└── services/
    ├── openalex.py    # search, get_by_doi, abstract reconstruction
    ├── crossref.py    # DOI metadata, references, funders, publisher
    ├── unpaywall.py   # OA lookup
    ├── downloader.py  # PDF download with atomic writes & magic-byte check
    └── util.py        # DOI normalization, abstract rebuild, name parsing
tests/                 # 69 offline tests via respx + 3 live smoke tests
```

### Design notes

- **Polite by default.** `mailto`/`User-Agent` headers are set on every
  request, with a `POLITE_POOL=0` escape hatch for privacy mode.
- **Abstract reconstruction.** OpenAlex stores abstracts as
  `{word: [positions]}` to avoid redistributing full text; the original is
  rebuilt losslessly.
- **PDF safety.** Content-type must be `application/pdf` **and** bytes must
  start with `%PDF-`. URLs are validated for scheme and resolved host
  (loopback, RFC1918, link-local `169.254/16`, CGNAT, ULA all refused).
  Filenames are sanitized and paths must stay inside `PDF_DIR`. Downloads
  write to `<name>.pdf.part` and rename atomically on success.
- **DOI normalization.** Accepts bare DOIs, `doi:...`, `https://doi.org/...`,
  or DOIs embedded in surrounding text. The regex excludes URL-significant
  chars (`?#&[]`) to prevent API-URL injection.
- **CrossRef enrichment is best-effort.** If CrossRef is down or has no
  record, `get_paper` still returns the OpenAlex record with empty references.
- **Single source of truth for version.** `__version__` lives in
  `config.py`; `pyproject.toml` mirrors it.

---

## Limitations & alternatives

- **No paywalled full text.** If a paper isn't OA, you'll get metadata +
  abstract but no PDF. For paywalled content, use your institution's VPN /
  library proxy, or an EBSCO Discovery Service integration (requires license).
- **Abstract coverage.** OpenAlex has abstracts for most recent papers, but
  older works (pre-~2000, some publishers) may have `abstract: null`.
- **Rate limits.** The three APIs are generous but not unlimited. On 429/5xx
  the server retries with exponential backoff, honoring `Retry-After` (both
  seconds and HTTP-date forms). For bulk work, throttle your calls or
  self-host OpenAlex snapshots.

---

## Data licensing & attribution

This server is a thin client over three upstream APIs. Each has its own terms:

- **OpenAlex** — metadata is CC0; they request attribution. See
  [openalex.org](https://openalex.org).
- **CrossRef** — metadata is CC0; the REST API has [terms of use](https://www.crossref.org/documentation/retrieve-metadata/rest-api/).
- **Unpaywall** — see [their terms](https://unpaywall.org/products/api).

PDFs you download come from the publishers/repositories that Unpaywall
identifies; each has its own license (CC-BY, paywalled-but-OA-copy, etc.).
Respect the individual paper's license.

---

## Getting help

- 🐛 **Bugs & feature requests:** [open an issue](https://github.com/Kaago/openpapers-mcp/issues/new/choose)
- 🔒 **Security issues:** see [SECURITY.md](./SECURITY.md) — **do not** open a public issue
- 💬 **Discussion:** GitHub Discussions (if enabled) or the issue tracker

---

## License

[MIT](./LICENSE) © Philipp Polte. See [CONTRIBUTING.md](./CONTRIBUTING.md) for
the contribution agreement and [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) for
community standards.
