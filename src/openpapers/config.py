"""Configuration loading for OpenPapers MCP.

Reads from environment / .env file. No secrets are required — the only
personal value is a contact email used for the API "polite pool"
(OpenAlex / CrossRef / Unpaywall).
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Logging must go to stderr — stdout is the JSON-RPC transport for the MCP
# stdio protocol. Any stdout write corrupts the stream.
_STDERR = sys.stderr

# Load .env from CWD or project root (best effort).
for _candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"):
    if _candidate.is_file():
        load_dotenv(_candidate, override=False)
        break


PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Project repo URL. Surfaced in the User-Agent header (polite-pool etiquette
# expects a reachable project URL) and mirrored in [project.urls] in pyproject.toml.
REPO_URL = "https://github.com/Kaago/openpapers-mcp"

# Single source of truth for the version. pyproject.toml mirrors this; bump
# both together at release time.
__version__ = "0.1.0"


def _env_str(key: str, default: str) -> str:
    val = os.environ.get(key)
    return val.strip() if val and val.strip() else default


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if not raw or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Contact email — sent as `mailto=` (OpenAlex/Unpaywall) and in User-Agent
    # (CrossRef). Falls back to a neutral placeholder if unset.
    contact_email: str = field(
        default_factory=lambda: _env_str("CONTACT_EMAIL", "openpapers-mcp@localhost")
    )

    # Whether to send the contact email at all. Set `POLITE_POOL=0` to
    # withhold your email entirely (at the cost of stricter rate limits).
    polite_pool: bool = field(default_factory=lambda: _env_str("POLITE_POOL", "1") != "0")

    # Where downloaded PDFs land. Default: <project>/pdfs
    pdf_dir: Path = field(
        default_factory=lambda: Path(_env_str("PDF_DIR", str(PROJECT_ROOT / "pdfs"))).expanduser()
    )

    http_timeout: float = field(default_factory=lambda: float(_env_int("HTTP_TIMEOUT", 30)))
    http_max_retries: int = field(default_factory=lambda: _env_int("HTTP_MAX_RETRIES", 3))

    # Logging
    log_level: str = field(default_factory=lambda: _env_str("LOG_LEVEL", "INFO").upper())

    # PDF download guardrails
    pdf_max_bytes: int = field(
        default_factory=lambda: _env_int("PDF_MAX_BYTES", 104_857_600)
    )  # 100 MB

    # API base URLs (overridable for tests / self-hosters)
    openalex_base: str = field(
        default_factory=lambda: _env_str("OPENALEX_BASE", "https://api.openalex.org")
    )
    crossref_base: str = field(
        default_factory=lambda: _env_str("CROSSREF_BASE", "https://api.crossref.org")
    )
    unpaywall_base: str = field(
        default_factory=lambda: _env_str("UNPAYWALL_BASE", "https://api.unpaywall.org")
    )

    @property
    def effective_contact_email(self) -> str:
        """The email actually sent upstream, respecting `polite_pool`."""
        return self.contact_email if self.polite_pool else "openpapers-mcp@localhost"

    @property
    def user_agent(self) -> str:
        return f"OpenPapers-MCP/{__version__} (+{REPO_URL}; mailto:{self.effective_contact_email})"


def get_settings() -> Settings:
    """Return the (process-wide) settings instance."""
    return SETTINGS


def ensure_pdf_dir() -> Path:
    """Create the PDF output directory if needed and return it."""
    SETTINGS.pdf_dir.mkdir(parents=True, exist_ok=True)
    return SETTINGS.pdf_dir


def configure_logging() -> None:
    """Configure logging from settings. Call once at startup."""
    level = getattr(logging, SETTINGS.log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        stream=_STDERR,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )


SETTINGS = Settings()
