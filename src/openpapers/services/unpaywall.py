"""Unpaywall client — finds legal Open Access PDFs.

Docs: https://unpaywall.org/products/api
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import get_settings
from ..http_client import HttpClientError, get_json
from ..models import OALocation, OAResult

log = logging.getLogger("openpapers.unpaywall")


async def lookup(client: httpx.AsyncClient, doi: str) -> OAResult | None:
    """Look up OA status for a bare DOI. Returns None on 404 (no record)."""
    url = f"{get_settings().unpaywall_base}/v2/{doi}"
    params = {"email": get_settings().effective_contact_email}
    try:
        data = await get_json(client, url, params=params)
    except HttpClientError as e:
        if e.status == 404:
            return None
        log.debug("Unpaywall lookup failed for %s: %s", doi, e)
        return None
    return _to_result(data)


def _to_location(loc: dict[str, Any] | None) -> OALocation | None:
    if not loc:
        return None
    return OALocation(
        url_for_pdf=loc.get("url_for_pdf"),
        url_for_landing_page=loc.get("url_for_landing_page"),
        version=loc.get("version"),
        host_type=loc.get("host_type"),
        license=loc.get("license"),
        repository_institution=loc.get("repository_institution"),
        is_best=bool(loc.get("is_best")),
    )


def _to_result(data: dict[str, Any]) -> OAResult:
    best = _to_location(data.get("best_oa_location"))
    locations = [
        loc
        for loc in (_to_location(item) for item in (data.get("oa_locations") or []))
        if loc is not None
    ]
    if best is None and locations:
        best = locations[0]
    pdf_url = best.url_for_pdf if best else None
    return OAResult(
        doi=data.get("doi"),
        is_oa=bool(data.get("is_oa")),
        oa_status=data.get("oa_status"),
        journal_is_oa=bool(data.get("journal_is_oa")),
        journal_is_in_doaj=bool(data.get("journal_is_in_doaj")),
        genre=data.get("genre"),
        journal_name=data.get("journal_name"),
        best_oa_location=best,
        oa_locations=locations,
        pdf_url=pdf_url,
    )
