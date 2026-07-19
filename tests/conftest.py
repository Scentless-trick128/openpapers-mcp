"""Shared pytest fixtures.

Tests must never touch the developer's real `pdfs/` directory. Because
`Settings` is a frozen dataclass, we swap the whole `get_settings()` return
value for a temp-dir-backed clone during filesystem-touching tests.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import openpapers.config as cfg


@pytest.fixture
def isolated_pdf_dir(tmp_path: Path):
    """Redirect all PDF downloads to a per-test temp directory.

    Replaces `get_settings()` with a fresh instance whose `pdf_dir` points
    at `tmp_path/pdfs`, and makes `ensure_pdf_dir()` return that path. The
    frozen production `SETTINGS` is untouched.
    """
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()

    # Build a non-frozen stand-in by reading the production settings and
    # overriding only the PDF path. dataclasses.replace works on frozen
    # dataclasses and produces a new frozen instance.
    import dataclasses

    base = cfg.get_settings()
    test_settings = dataclasses.replace(base, pdf_dir=pdf_dir)

    def fake_ensure():
        return pdf_dir

    with (
        patch.object(cfg, "SETTINGS", test_settings),
        patch.object(cfg, "get_settings", return_value=test_settings),
        patch.object(cfg, "ensure_pdf_dir", side_effect=fake_ensure),
    ):
        # Also patch the names bound into modules that did `from .config import ...`.
        import openpapers.http_client as hc
        import openpapers.services.downloader as dl

        with (
            patch.object(hc, "get_settings", return_value=test_settings),
            patch.object(dl, "ensure_pdf_dir", side_effect=fake_ensure),
            patch.object(dl, "get_settings", return_value=test_settings),
        ):
            yield pdf_dir
