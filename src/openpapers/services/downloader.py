"""PDF download service with safety guards.

Security properties enforced here:
  - The destination filename (whether derived from a DOI or supplied by the
    caller) is sanitized so the resolved path stays inside `PDF_DIR`.
  - The download URL is validated for scheme and resolved host before any
    bytes are fetched (see `openpapers.security`).
  - Content is verified to actually be a PDF via the `%PDF-` magic bytes,
    not just the (spoofable) Content-Type header.
  - Downloads are written to a `.part` file and renamed only on success, so
    a truncated/failed download never occupies the final filename.
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path

import httpx

from ..config import ensure_pdf_dir, get_settings
from ..http_client import download_to_file
from ..models import DownloadResult
from ..security import UnsafeUrlError, validate_url

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

# PDF magic bytes per the spec — every well-formed PDF starts with this.
PDF_MAGIC = b"%PDF-"


class UnsafeDownloadError(RuntimeError):
    """Raised when a download request is rejected on safety grounds."""


def sanitize_filename(name: str | None) -> str:
    """Turn any caller-supplied filename into a PDF-safe name.

    Strips path separators, collapses unsafe characters, removes leading
    dots/underscores, and ensures the result is a bare filename that cannot
    escape `PDF_DIR` via absolute paths or traversal.
    """
    if not name:
        base = "unknown"
    else:
        # Strip any directory components the caller may have included.
        base = Path(name).name
        base = _SAFE_CHARS.sub("_", base).strip("._") or "unknown"
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return base


def filename_for_doi(doi: str | None) -> str:
    """Turn a DOI into a filesystem-safe PDF filename."""
    if not doi:
        return sanitize_filename(None)
    return sanitize_filename(doi.replace("/", "_").replace("\\", "_"))


def safe_destination(out_dir: Path, name: str) -> Path:
    """Return the resolved destination, raising if it escapes `out_dir`."""
    base_dir = out_dir.resolve()
    dest = (base_dir / name).resolve()
    try:
        dest.relative_to(base_dir)
    except ValueError as e:
        raise UnsafeDownloadError(f"Refusing to write outside PDF_DIR: {name!r}") from e
    return dest


async def download(
    client: httpx.AsyncClient,
    url: str,
    *,
    doi: str | None = None,
    filename: str | None = None,
) -> DownloadResult:
    """Download a PDF to the configured PDF directory.

    Validates the URL for SSRF safety, the filename for path safety, and the
    downloaded content for the `%PDF-` magic bytes. See module docstring.
    """
    try:
        validated = validate_url(url)
    except UnsafeUrlError as e:
        raise UnsafeDownloadError(str(e)) from e

    settings = get_settings()
    out_dir = ensure_pdf_dir()
    name = sanitize_filename(filename) if filename else filename_for_doi(doi)
    dest = safe_destination(out_dir, name)
    tmp = dest.with_suffix(dest.suffix + ".part")

    try:
        bytes_written, content_type = await download_to_file(
            client,
            str(validated),
            tmp,
            max_bytes=settings.pdf_max_bytes,
            expected_content_type="application/pdf",
        )
    except BaseException:
        # Never leave a partial file behind under any name.
        _unlink_quietly(tmp)
        raise

    # Verify the bytes really are a PDF before promoting to the final name.
    try:
        with open(tmp, "rb") as f:
            magic = f.read(len(PDF_MAGIC))
    except OSError:
        _unlink_quietly(tmp)
        raise
    if magic != PDF_MAGIC:
        _unlink_quietly(tmp)
        raise UnsafeDownloadError(
            f"Downloaded content from {url!r} is not a PDF (magic bytes: {magic!r})."
        )

    # Atomic promotion: rename is atomic on POSIX within the same filesystem.
    tmp.replace(dest)

    return DownloadResult(
        url=str(validated),
        local_path=str(dest),
        doi=doi,
        bytes_written=bytes_written,
        content_type=content_type,
    )


def _unlink_quietly(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
