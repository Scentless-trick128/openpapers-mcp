"""Entry point: `uv run openpapers` → stdio MCP server."""

from __future__ import annotations

from .config import configure_logging
from .server import mcp


def main() -> None:
    configure_logging()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
