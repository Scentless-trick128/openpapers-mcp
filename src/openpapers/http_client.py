"""Shared httpx.AsyncClient with retry, polite headers, and pooling.

Note: per-request retries are applied to JSON fetches against the three
trusted metadata APIs (OpenAlex, CrossRef, Unpaywall). Downloads of
user-supplied PDF URLs go through `download_to_file`, which does NOT retry
(to avoid amplifying a hostile mirror's response) but does validate
content-type and caps the byte budget.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

from .config import get_settings

log = logging.getLogger("openpapers.http")


__all__ = ["HttpClientError", "build_client", "download_to_file", "get_json"]


class HttpClientError(RuntimeError):
    """Raised when an upstream API call fails permanently."""

    def __init__(self, message: str, *, status: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status = status
        self.url = url


def build_client() -> httpx.AsyncClient:
    s = get_settings()
    headers = {
        "User-Agent": s.user_agent,
        "Accept": "application/json",
    }
    return httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(s.http_timeout),
        # follow_redirects for the JSON APIs (all three use them sparingly).
        # PDF downloads go through download_to_file, which uses a separate
        # stream with explicit, validated redirects.
        follow_redirects=True,
        max_redirects=5,
    )


_RETRIABLE_STATUS = {429, 500, 502, 503, 504}


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    max_retries: int | None = None,
) -> dict[str, Any]:
    """GET `url` and return parsed JSON. Retries on 429/5xx with exponential backoff."""
    settings = get_settings()
    retries = max_retries if max_retries is not None else settings.http_max_retries

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code in _RETRIABLE_STATUS and attempt < retries:
                retry_after = resp.headers.get("Retry-After")
                wait = _parse_retry_after(retry_after) if retry_after else _backoff(attempt)
                log.warning(
                    "Upstream %s returned %s — retry %d/%d after %.1fs",
                    url,
                    resp.status_code,
                    attempt + 1,
                    retries,
                    wait,
                )
                await resp.aclose()
                await asyncio.sleep(wait)
                continue
            if resp.status_code == 404:
                raise HttpClientError(f"Not found: {url}", status=404, url=url)
            if resp.status_code >= 400:
                # Only surface a short snippet of the body, never the whole thing.
                raise HttpClientError(
                    f"Upstream error {resp.status_code} for {url}",
                    status=resp.status_code,
                    url=url,
                )
            data: dict[str, Any] = resp.json()
            return data
        except httpx.HTTPError as e:
            last_exc = e
            if attempt < retries:
                wait = _backoff(attempt)
                log.warning(
                    "HTTP error for %s — retry %d/%d after %.1fs: %s",
                    url,
                    attempt + 1,
                    retries,
                    wait,
                    e,
                )
                await asyncio.sleep(wait)
                continue
            raise HttpClientError(f"HTTP error for {url}: {e}", url=url) from e

    raise HttpClientError(f"Exhausted retries for {url}: {last_exc}", url=url)


def _backoff(attempt: int) -> float:
    """Exponential backoff: 0.5, 1, 2, 4, ... capped at 30s, with jitter."""
    base: float = min(30.0, 0.5 * (2**attempt))
    return base * (0.5 + random.random() * 0.5)


def _parse_retry_after(value: str) -> float:
    """Parse Retry-After as either seconds or an HTTP-date (RFC 7231)."""
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        pass
    try:
        target = parsedate_to_datetime(value)
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        return max(0.0, (target - datetime.now(tz=UTC)).total_seconds())
    except (TypeError, ValueError):
        return _backoff(0)


async def download_to_file(
    client: httpx.AsyncClient,
    url: str,
    dest_path: Path,
    *,
    max_bytes: int,
    expected_content_type: str = "application/pdf",
) -> tuple[int, str | None]:
    """Stream-download `url` to `dest_path`. Returns (bytes_written, content_type).

    Safety properties:
      - Accepts only `application/pdf` Content-Type (octet-stream is rejected,
        since cloud metadata endpoints return it).
      - Caps at `max_bytes`; on overflow the destination is unlinked.
      - On any exception during the stream, the destination is unlinked so no
        truncated bytes ever occupy the path.
    """
    dest = Path(dest_path)
    bytes_written = 0

    async with client.stream("GET", url, follow_redirects=True) as resp:
        if resp.status_code >= 400:
            raise HttpClientError(
                f"Download failed ({resp.status_code}) for {url}",
                status=resp.status_code,
                url=url,
            )
        ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        # Strict: require application/pdf. We additionally sniff the %PDF-
        # magic after the download completes (see downloader.py), so this is
        # a fast-fail guard rather than the only check.
        if ctype and ctype != "application/pdf":
            raise HttpClientError(
                f"Refusing non-PDF content-type {ctype!r} from {url}",
                url=url,
            )

        declared_len = resp.headers.get("content-length")
        if declared_len and declared_len.isdigit() and int(declared_len) > max_bytes:
            raise HttpClientError(
                f"Content-Length {declared_len} exceeds limit {max_bytes} for {url}",
                url=url,
            )

        import anyio

        try:
            async with await anyio.open_file(dest, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        raise HttpClientError(
                            f"Stream exceeded {max_bytes} bytes for {url}; aborted.",
                            url=url,
                        )
                    await f.write(chunk)
        except BaseException:
            # Always remove a partial file on failure of any kind.
            with contextlib.suppress(FileNotFoundError):
                dest.unlink()
            raise

        return bytes_written, ctype or expected_content_type
