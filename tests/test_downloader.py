"""Tests for the PDF downloader with mocked HTTP.

All filesystem-touching tests are isolated via the `isolated_pdf_dir`
fixture (see conftest.py) so nothing ever lands in the real `pdfs/`
directory on the developer's machine.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from openpapers.http_client import HttpClientError, build_client, download_to_file
from openpapers.services.downloader import (
    UnsafeDownloadError,
    download,
    filename_for_doi,
    safe_destination,
    sanitize_filename,
)

# --------------------------------------------------------------------------- #
# Filename sanitization
# --------------------------------------------------------------------------- #


def test_sanitize_filename_bare():
    assert sanitize_filename("paper") == "paper.pdf"


def test_sanitize_filename_strips_absolute_path():
    # A caller-supplied absolute path must collapse to a bare filename.
    name = sanitize_filename("/etc/cron.d/evil")
    assert name == "evil.pdf"
    assert "/" not in name


def test_sanitize_filename_strips_traversal():
    name = sanitize_filename("../../etc/passwd")
    assert name == "passwd.pdf"
    assert "/" not in name
    assert ".." not in name


def test_sanitize_filename_strips_unsafe_chars():
    assert sanitize_filename("a b:c*d?e|f") == "a_b_c_d_e_f.pdf"


def test_sanitize_filename_handles_none():
    assert sanitize_filename(None) == "unknown.pdf"
    assert sanitize_filename("") == "unknown.pdf"


def test_filename_for_doi_replaces_slashes():
    assert filename_for_doi("10.1038/nature12373") == "10.1038_nature12373.pdf"


def test_safe_destination_rejects_traversal(tmp_path: Path):
    # Even if a caller smuggled "../" past sanitize_filename, safe_destination
    # catches it at the path-resolution level.
    with pytest.raises(UnsafeDownloadError, match="outside PDF_DIR"):
        # We bypass sanitize_filename here to exercise the second layer.
        safe_destination(tmp_path, "../escape.pdf")


def test_safe_destination_accepts_clean_name(tmp_path: Path):
    dest = safe_destination(tmp_path, "clean.pdf")
    assert dest == (tmp_path / "clean.pdf").resolve()


# --------------------------------------------------------------------------- #
# Successful download + magic-byte verification
# --------------------------------------------------------------------------- #

PDF_BYTES = b"%PDF-1.5\n%fake pdf content for testing\n%%EOF"


@pytest.mark.asyncio
@respx.mock
async def test_download_writes_pdf(isolated_pdf_dir: Path):
    respx.get("https://example.org/paper.pdf").mock(
        return_value=httpx.Response(
            200, content=PDF_BYTES, headers={"content-type": "application/pdf"}
        )
    )
    async with build_client() as client:
        result = await download(
            client,
            "https://example.org/paper.pdf",
            doi="10.1038/nature12373",
            filename="custom.pdf",
        )
    assert result.bytes_written == len(PDF_BYTES)
    assert result.content_type == "application/pdf"
    assert Path(result.local_path).read_bytes() == PDF_BYTES
    assert result.local_path.endswith("custom.pdf")
    # No .part file should remain.
    assert not any(p.suffix == ".part" for p in isolated_pdf_dir.iterdir())


@pytest.mark.asyncio
@respx.mock
async def test_download_rejects_html_content_type(isolated_pdf_dir: Path):
    respx.get("https://example.org/trap").mock(
        return_value=httpx.Response(
            200,
            content=b"<html><body>login page</body></html>",
            headers={"content-type": "text/html"},
        )
    )
    async with build_client() as client:
        with pytest.raises(HttpClientError, match="non-PDF"):
            await download(client, "https://example.org/trap", doi="10.1/x")
    # No file should have been created.
    assert list(isolated_pdf_dir.iterdir()) == []


@pytest.mark.asyncio
@respx.mock
async def test_download_rejects_octet_stream_from_metadata_like_url(
    isolated_pdf_dir: Path,
):
    # application/octet-stream must be refused even though AWS metadata and
    # many other endpoints return it.
    respx.get("https://example.org/data").mock(
        return_value=httpx.Response(
            200,
            content=b"%PDF-1.5 fake",
            headers={"content-type": "application/octet-stream"},
        )
    )
    async with build_client() as client:
        with pytest.raises(HttpClientError, match="non-PDF"):
            await download(client, "https://example.org/data", doi="10.1/x")


@pytest.mark.asyncio
@respx.mock
async def test_download_rejects_non_pdf_bytes_with_pdf_content_type(
    isolated_pdf_dir: Path,
):
    # A malicious mirror could serve HTML with the right Content-Type to bypass
    # the header check. The %PDF- magic check must catch it.
    respx.get("https://example.org/fake.pdf").mock(
        return_value=httpx.Response(
            200,
            content=b"<html>not actually a pdf</html>",
            headers={"content-type": "application/pdf"},
        )
    )
    async with build_client() as client:
        with pytest.raises(UnsafeDownloadError, match="not a PDF"):
            await download(client, "https://example.org/fake.pdf", doi="10.1/x")
    # Partial bytes must not be promoted to the final name.
    assert list(isolated_pdf_dir.iterdir()) == []


# --------------------------------------------------------------------------- #
# Size limits & partial-file cleanup
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@respx.mock
async def test_download_aborts_on_declared_size_exceed(isolated_pdf_dir: Path):
    respx.get("https://example.org/big").mock(
        return_value=httpx.Response(
            200,
            content=b"%PDF-1.5 small",
            headers={"content-type": "application/pdf", "content-length": "999999999999"},
        )
    )
    async with build_client() as client:
        with pytest.raises(HttpClientError, match="exceeds limit"):
            await download_to_file(
                client,
                "https://example.org/big",
                isolated_pdf_dir / "out.pdf",
                max_bytes=100,
            )
    assert not (isolated_pdf_dir / "out.pdf").exists()


@pytest.mark.asyncio
@respx.mock
async def test_streaming_abort_removes_partial_file(isolated_pdf_dir: Path):
    """Mid-stream overflow must not leave a truncated file behind.

    To exercise the streaming-abort path (not the Content-Length pre-check),
    we use a chunked streaming body with no declared length, larger than
    `max_bytes`.
    """

    async def byte_stream():
        # First chunk is the PDF magic; subsequent chunks blow past the cap.
        yield b"%PDF-1.5\n"
        for _ in range(20):
            yield b"x" * 500

    respx.get("https://example.org/huge.pdf").mock(
        return_value=httpx.Response(
            200,
            stream=byte_stream(),
            headers={"content-type": "application/pdf"},
        )
    )
    target = isolated_pdf_dir / "huge.pdf"
    async with build_client() as client:
        with pytest.raises(HttpClientError, match="exceeded"):
            await download_to_file(client, "https://example.org/huge.pdf", target, max_bytes=100)
    # Critical assertion: no partial file may survive the abort.
    assert not target.exists()


# --------------------------------------------------------------------------- #
# SSRF guards
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_download_refuses_loopback_url(isolated_pdf_dir: Path):
    async with build_client() as client:
        with pytest.raises((UnsafeDownloadError, ValueError), match=r"blocked|unsafe|loopback"):
            await download(client, "http://127.0.0.1:6379/x", doi="10.1/x")


@pytest.mark.asyncio
async def test_download_refuses_link_local_metadata_url(isolated_pdf_dir: Path):
    # 169.254.169.254 is the AWS IMDS endpoint — classic SSRF target.
    async with build_client() as client:
        with pytest.raises((UnsafeDownloadError, ValueError), match=r"blocked|unsafe|link"):
            await download(
                client,
                "http://169.254.169.254/latest/meta-data/",
                doi="10.1/x",
            )


@pytest.mark.asyncio
async def test_download_refuses_rfc1918_url(isolated_pdf_dir: Path):
    async with build_client() as client:
        with pytest.raises((UnsafeDownloadError, ValueError), match=r"blocked|unsafe|private"):
            await download(client, "http://192.168.1.1/admin", doi="10.1/x")


@pytest.mark.asyncio
async def test_download_refuses_file_scheme(isolated_pdf_dir: Path):
    async with build_client() as client:
        with pytest.raises((UnsafeDownloadError, ValueError), match=r"scheme|unsafe"):
            await download(client, "file:///etc/passwd", doi="10.1/x")


@pytest.mark.asyncio
@respx.mock
async def test_download_allows_public_host(isolated_pdf_dir: Path):
    # example.org resolves to public IPs; respx intercepts so no real network.
    respx.get("https://example.org/ok.pdf").mock(
        return_value=httpx.Response(
            200, content=PDF_BYTES, headers={"content-type": "application/pdf"}
        )
    )
    async with build_client() as client:
        result = await download(client, "https://example.org/ok.pdf", doi="10.1/x")
    assert result.bytes_written == len(PDF_BYTES)


@pytest.mark.asyncio
async def test_download_refuses_unresolvable_host(isolated_pdf_dir: Path):
    async with build_client() as client:
        with pytest.raises((UnsafeDownloadError, ValueError), match=r"resolve|unsafe"):
            await download(
                client,
                "https://this-host-definitely-does-not-exist.invalid/x.pdf",
                doi="10.1/x",
            )


# --------------------------------------------------------------------------- #
# Path-traversal via the filename parameter (the C1 from the security audit)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@respx.mock
async def test_download_filename_traversal_collapsed(isolated_pdf_dir: Path):
    """Even a malicious filename must resolve inside PDF_DIR."""
    respx.get("https://example.org/p.pdf").mock(
        return_value=httpx.Response(
            200, content=PDF_BYTES, headers={"content-type": "application/pdf"}
        )
    )
    async with build_client() as client:
        result = await download(
            client,
            "https://example.org/p.pdf",
            doi="10.1/x",
            filename="../../etc/cron.d/evil",
        )
    # Resolved path must be inside isolated_pdf_dir, and the on-disk file
    # only contains the sanitized basename.
    dest = Path(result.local_path)
    assert dest.resolve().is_relative_to(isolated_pdf_dir.resolve())
    assert dest.name == "evil.pdf"
