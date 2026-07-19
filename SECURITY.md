# Security Policy

## Reporting a vulnerability

**Please do not open a public GitHub issue for security problems.**

Instead, use GitHub's private vulnerability reporting:
**Report a vulnerability** →
[github.com/Kaago/openpapers-mcp/security/advisories/new](https://github.com/Kaago/openpapers-mcp/security/advisories/new)

If you prefer, you can also email the maintainer directly at
`philipp.polte@gmail.com` with `[OpenPapers security]` in the subject.

Please include:

- A description of the issue and its impact.
- Steps to reproduce (a PoC is ideal).
- Affected versions, if known.

You should receive an acknowledgement within 7 days. We follow coordinated
disclosure and will credit reporters in the release notes unless you'd prefer
to remain anonymous.

## Supported versions

Only the latest release line receives security updates.

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅        |
| < 0.1   | ❌        |

## Trust model & security boundaries

OpenPapers MCP is a **local** server (stdio transport) that an MCP client
(Claude Desktop, ZCode, Cursor, etc.) runs on your machine. It is designed
under the following assumptions:

- **The MCP client is trusted.** Whatever the client sends, the server
  executes. Do not point this server at an untrusted MCP client.
- **Upstream APIs are trusted.** OpenAlex, CrossRef, and Unpaywall are
  contacted with the user's `CONTACT_EMAIL` for polite-pool participation.
- **PDF download URLs are NOT trusted.** They originate from Unpaywall or are
  supplied directly by the caller (often an LLM, which may have been
  prompt-injected). The `download_pdf` tool enforces:
  - URL scheme must be `http`/`https`.
  - The resolved host must be a public IP (loopback, RFC1918, link-local
    `169.254/16`, CGNAT `100.64/10`, ULA, multicast are all refused).
  - DNS answers are checked at fetch time (defense against DNS rebinding).
  - Response `Content-Type` must be `application/pdf`.
  - The downloaded bytes must start with the `%PDF-` magic marker.
  - Destination filenames are sanitized and resolved paths must stay inside
    `PDF_DIR` (no absolute-path or `../` traversal).
  - Downloads are capped at `PDF_MAX_BYTES` (default 100 MB) and written
    atomically — a failed/truncated download never occupies the final path.

If you find a bypass of any of these guards, that is a vulnerability — please
report it privately.
