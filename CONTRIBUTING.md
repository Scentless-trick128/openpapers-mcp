# Contributing to OpenPapers MCP

Thanks for considering a contribution! This is a small project — the bar is
"makes the project better for users" and "doesn't break existing behavior",
not perfection.

## Quick start

```bash
git clone https://github.com/Kaago/openpapers-mcp.git
cd OpenPapers
cp .env.example .env        # then edit CONTACT_EMAIL
uv sync                     # install deps (uses uv.lock)
uv run pytest               # all tests should pass — and they're 100% offline
uv run ruff check .         # lint
uv run ruff format --check .  # format check
```

Requirements: Python ≥ 3.12 and [`uv`](https://docs.astral.sh/uv/).

## Project layout

```
src/openpapers/
├── server.py          # the 5 MCP tools
├── services/          # OpenAlex, CrossRef, Unpaywall, downloader
├── http_client.py     # httpx wrapper with retry + safe download
├── security.py        # SSRF/path-traversal guards
├── models.py          # Pydantic models = public tool contract
└── config.py          # settings + version
tests/                 # respx-mocked, no network
```

The golden rule: **`server.py` is the public contract**. Don't change a tool's
name, parameter names, or return-type shape without bumping the major version
(or, pre-1.0, calling it out clearly in the PR).

## Tests stay offline

Every test must pass with the network unplugged. We use
[`respx`](https://github.com/lundberg/respx) to mock httpx. **Do not add tests
that hit live APIs** — they will fail in CI and on contributors' machines.

If you want to verify a change against the real APIs, do it manually:

```bash
uv run python -c "
import asyncio
from openpapers.http_client import build_client
from openpapers.services import openalex
async def main():
    async with build_client() as c:
        print(await openalex.search_works(c, 'your query', per_page=2))
asyncio.run(main())
"
```

…but don't commit that as a test.

## Code style

- [`ruff`](https://docs.astral.sh/ruff/) is the only linter/formatter. Run
  `uv run ruff check .` and `uv run ruff format .` before committing.
- Target Python 3.12+. Modern syntax (`str | None`, not `Optional[str]`).
- Type-hint everything that's public. `mypy --strict src/openpapers` should
  stay green (we're not there yet on every file — improvements welcome).
- Keep tool descriptions in `server.py` short and LLM-actionable: the model
  reads them to decide when to call the tool.

## Submitting changes

1. Fork → branch → commit. Small, focused PRs land faster.
2. Make sure `uv run pytest`, `uv run ruff check .`, and
   `uv run ruff format --check .` all pass.
3. If you changed user-visible behavior (a tool's inputs/outputs, the `.env`
   shape, default behavior), update `README.md` and `CHANGELOG.md`.
4. Open a PR with a clear "what & why" — the maintainer is human.

## Security issues

**Do not open a public issue for security problems.** See
[SECURITY.md](./SECURITY.md) for responsible disclosure.

## License

By contributing, you agree your contributions will be licensed under the
project's [MIT license](./LICENSE).
