"""Corrections for the CMS (spec/corrections.json): the requests and answers of the review service's
two calls, without HTTP. :meth:`SupertextClient.pending_corrections` and
:meth:`SupertextClient.acknowledge_corrections` use them.

Reviewers correct translations on the website in Supertext Localization Review; its review service
(a drop-in proxy for the API) remembers where each segment sits by the integration's ``data-st-id``.
Only the review service answers these calls; Supertext's API answers 404 (``not_found``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal
from urllib.parse import quote

PAGE_SIZE: Final = 500
MAX_PAGES: Final = 100
ACKNOWLEDGE_BATCH_SIZE: Final = 1000

_VERSION = re.compile(r"[0-9a-f]{16}")
_DIGITS = re.compile(r"[0-9]+")


@dataclass(frozen=True)
class Correction:
    """A correction the integration hasn't written into the CMS yet."""

    id: str
    """The review service's id of this place (send back with ``acknowledge_corrections``)."""
    segment_id: str
    """The ``data-st-id`` the integration gave the segment (its own reference to the field)."""
    source_lang: str | None
    """``None``: the source language was detected."""
    target_lang: str
    politeness: Literal["default", "more", "less"]
    source_html: str
    previous_html: str
    """What the integration received for this place last: check the field still holds it before
    overwriting an editor's change."""
    html: str
    """The corrected translation: write this into the field."""
    status: str
    """``corrected``, ``approved``, …"""
    corrected_at: str
    """ISO time of the latest change."""
    version: str
    """Changes with every new correction: acknowledge the version you wrote."""


def corrections_path(
    target_lang: str | None, source_lang: str | None, politeness: str | None, after: str | None
) -> str:
    """The path of one page of pending corrections."""
    params = [
        ("target_lang", target_lang),
        ("source_lang", source_lang),
        ("politeness", politeness),
        ("after", after),
        ("limit", str(PAGE_SIZE)),
    ]
    query = "&".join(f"{name}={quote(value, safe='')}" for name, value in params if value is not None)
    return f"review/corrections?{query}"


def parse_corrections_page(body: str) -> tuple[list[Correction], str | None]:
    """One page: its valid corrections and the ``after`` for the next page (``None``: last page)."""
    try:
        data: Any = json.loads(body)
    except ValueError:
        return [], None
    if not isinstance(data, dict) or not isinstance(data.get("corrections"), list):
        return [], None
    out: list[Correction] = []
    for raw in data["corrections"]:
        if not isinstance(raw, dict):
            continue
        required = [raw.get("id"), raw.get("st_id"), raw.get("target_lang"), raw.get("html")]
        if not all(isinstance(v, str) and v != "" for v in required):
            continue
        version = raw.get("version")
        if not isinstance(version, str) or not _VERSION.fullmatch(version):
            continue
        source = raw.get("source_lang")
        politeness = raw.get("politeness")
        out.append(
            Correction(
                id=raw["id"],
                segment_id=raw["st_id"],
                source_lang=source if isinstance(source, str) and source != "" else None,
                target_lang=raw["target_lang"],
                politeness="more" if politeness == "more" else "less" if politeness == "less" else "default",
                source_html=_str(raw.get("source_html")),
                previous_html=_str(raw.get("previous_html")),
                html=raw["html"],
                status=_str(raw.get("status")),
                corrected_at=_str(raw.get("corrected_at")),
                version=version,
            )
        )
    nxt = data.get("next_after")
    return out, nxt if isinstance(nxt, str) and _DIGITS.fullmatch(nxt) else None


def acknowledge_body(corrections: Sequence[Correction]) -> str:
    """The acknowledge request body, byte-exact."""
    items = [{"id": c.id, "version": c.version} for c in corrections]
    return json.dumps({"corrections": items}, separators=(",", ":"), ensure_ascii=False)


def acknowledged_count(body: str) -> int:
    """The answer's ``acknowledged`` (0 when it isn't a non-negative integer)."""
    try:
        data: Any = json.loads(body)
    except ValueError:
        return 0
    n = data.get("acknowledged") if isinstance(data, dict) else None
    return n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else 0


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""
