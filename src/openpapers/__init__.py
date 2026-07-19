"""OpenPapers MCP — local server for scientific paper research.

Backed by OpenAlex (search + metadata), CrossRef (DOI + references),
and Unpaywall (legal Open Access PDFs).
"""

from .config import __version__
from .server import create_server

__all__ = ["__version__", "create_server"]
