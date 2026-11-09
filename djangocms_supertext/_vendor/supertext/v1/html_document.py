"""Packing texts into the HTML document sent to Supertext, and reading them back (spec/html-document.json).

Each segment becomes one ``<div data-st-id="N">``. Supertext translates every such element on
its own, so a whole text (paragraph, field) must be one segment with its formatting as inline
tags: splitting at formatting breaks sentences apart.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

_HEAD = '<!DOCTYPE html>\n<html><head><meta charset="utf-8"></head><body>\n'
_TAIL = "</body></html>\n"

# Start tag of any element carrying data-st-id (double, single or no quotes). Digits are spelled
# [0-9] because Python's \d also matches non-ASCII digits.
_START = re.compile(
    r"""<([a-zA-Z][a-zA-Z0-9]*)(?=[\s>/])[^>]*?\sdata-st-id\s*=\s*(?:"([0-9]+)"|'([0-9]+)'|([0-9]+))[^>]*>"""
)
_ENTITY = re.compile(r"&(#[xX][0-9a-fA-F]+|#[0-9]+|amp|lt|gt|quot|apos|nbsp);")
_NAMED = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": "\u00a0"}
_ASCII_SPACE = " \t\n\r\f"


@dataclass(frozen=True)
class Segment:
    """One text to translate. ``html=True``: the text is HTML and goes as it is; otherwise it is escaped."""

    text: str
    html: bool = False


def pack(segment: Segment) -> str:
    """The content that goes between ``<div data-st-id>`` and ``</div>`` for one segment."""
    if segment.html:
        return segment.text
    text = segment.text.replace("\r\n", "\n").replace("\r", "\n")
    text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
    return text.replace("\n", "<br>")


def build(segments: Sequence[Segment]) -> str:
    """The HTML document for the segments; ids are the positions in the list."""
    body = "".join(f'<div data-st-id="{index}">{pack(segment)}</div>\n' for index, segment in enumerate(segments))
    return _HEAD + body + _TAIL


def decode_entities(text: str) -> str:
    """Decodes the entities Supertext writes (numeric, amp, lt, gt, quot, apos, nbsp); others stay as they are."""
    return _ENTITY.sub(_decode_entity, text)


def _decode_entity(match: re.Match[str]) -> str:
    entity = match.group(1)
    if entity[0] != "#":
        return _NAMED[entity]
    hexadecimal = entity[1] in "xX"
    digits = entity[2:] if hexadecimal else entity[1:]
    # More than 7 significant digits is always out of range (and keeps int() fast and within limits).
    if len(digits.lstrip("0")) > 7:
        return match.group(0)
    number = int(digits, 16) if hexadecimal else int(digits)
    # Surrogates can't be encoded as UTF-8, so they are left as they are, like out-of-range numbers.
    if 0 < number <= 0x10FFFF and not 0xD800 <= number <= 0xDFFF:
        return chr(number)
    return match.group(0)


def to_plain_text(inner: str) -> str:
    """A segment's inner HTML as plain text: tags removed, ``<br>`` as line breaks, entities decoded."""
    text = re.sub(r"<br\s*/?>", "\x1e", inner, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"[ \t\n\r\f]+", " ", text)
    text = re.sub(r" ?\x1e ?", "\n", text)
    text = text.strip(" ")
    return decode_entities(text)


def parse(html: str, segments: Sequence[Segment]) -> list[str | None]:
    """Reads the segments back from a translated document: one result per segment, ``None`` if missing.

    Only ``segments[i].html`` is used, to decide whether segment ``i`` comes back as HTML (inner
    markup, outer whitespace trimmed) or as plain text (tags removed, entities decoded).
    """
    found = parse_positions(html, {index: segment.html for index, segment in enumerate(segments)})
    return [found.get(index) for index in range(len(segments))]


def parse_positions(html: str, wanted: Mapping[int, bool]) -> dict[int, str]:
    """:func:`parse` for selected ids only (SDK-internal): ``wanted`` maps an id to its ``html`` flag."""
    out: dict[int, str] = {}
    position = 0
    while True:
        start = _START.search(html, position)
        if start is None:
            return out
        tag = start.group(1)
        digits = start.group(2) or start.group(3) or start.group(4)
        # An absurdly long id can't be a segment (and int() refuses very long digit strings).
        index = int(digits) if len(digits.lstrip("0")) <= 18 else -1
        content_start = start.end()
        # Translations may nest elements of the same name inside a segment, so count depth.
        same = re.compile(rf"<(/?){re.escape(tag)}(?=[\s>/])[^>]*?(/?)>", re.IGNORECASE)
        depth, end, after = 1, -1, -1
        for tag_match in same.finditer(html, content_start):
            if tag_match.group(1):
                depth -= 1
            elif not tag_match.group(2):
                depth += 1
            if depth == 0:
                end, after = tag_match.start(), tag_match.end()
                break
        if end < 0:
            # No closing tag: skip this start tag and look for the next one.
            position = content_start
            continue
        if index in wanted and index not in out:
            inner = html[content_start:end]
            out[index] = inner.strip(_ASCII_SPACE) if wanted[index] else to_plain_text(inner)
        position = after


class HtmlDocument:
    """Namespace mirroring the other Supertext SDKs: ``HtmlDocument.build`` / ``HtmlDocument.parse``."""

    build = staticmethod(build)
    parse = staticmethod(parse)
