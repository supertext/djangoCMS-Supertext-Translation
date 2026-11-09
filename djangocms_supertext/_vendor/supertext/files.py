"""Translation files: export segments as XLIFF 1.2 or HTML, translate them outside the API (a CAT
tool, a translator, Supertext's web app), import them again (spec/translation-file.json,
integration guide → Translation files).

Not tied to an API version: nothing here talks to the API. The HTML file is the same document
:func:`supertext.v1.HtmlDocument.build` makes, plus metadata in its head.

Imported files are untrusted. :func:`read` refuses DTDs and files over :data:`MAX_FILE_CHARACTERS`;
:func:`import_translations` takes markup only from the integration's current source, never from
the file.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal, Protocol

from .v1.html_document import Segment, decode_entities, pack, parse_positions, to_plain_text

__all__ = [
    "MAX_FILE_CHARACTERS",
    "ErrorCode",
    "FileFormat",
    "FileJob",
    "FileSegment",
    "FileUnit",
    "ImportStatus",
    "ImportedSegment",
    "TranslationFile",
    "TranslationFileError",
    "checksum",
    "export_html",
    "export_xliff",
    "import_translations",
    "read",
]

FileFormat = Literal["xliff", "html"]

ImportStatus = Literal["ok", "source_changed", "untranslated", "invalid_markup", "missing"]
"""ok: translated, source unchanged. source_changed: translated, but the source changed since the
export (or the file has no checksum): the integration decides. untranslated: no translation in the
file. invalid_markup: the translation uses markup the current source doesn't have. missing: the
file has no such key."""

ErrorCode = Literal["invalid_job", "invalid_file", "missing_metadata", "too_large"]

MAX_FILE_CHARACTERS: Final = 10_000_000
"""Larger files are refused by :func:`read` (counted as ``len()`` of the string)."""


@dataclass(frozen=True)
class FileSegment:
    """One text of a job. ``key`` is the integration's own key (unique in the job), e.g. ``title`` or
    ``body.3``; ``text`` is the text, or an HTML fragment when ``html`` is true."""

    key: str
    text: str
    html: bool = False


@dataclass(frozen=True)
class FileJob:
    """One item to translate into one language.

    ``plugin`` is the integration's name (its repository name), e.g. ``Contao-Supertext-Translation``;
    ``reference`` is what the integration needs to find the item again, e.g. ``page:12`` (opaque to
    the SDK).
    """

    plugin: str
    reference: str
    source_language: str
    target_language: str
    segments: Sequence[FileSegment]


@dataclass(frozen=True)
class FileUnit:
    """A unit of a file read back: the key and the source's checksum at export time (``None`` when
    the file doesn't carry one)."""

    key: str
    checksum: str | None


@dataclass(frozen=True)
class _Code:
    code: Literal["bpt", "ept", "ph"]
    id: int
    raw: str = ""


class _Invalid:
    """A target element that isn't a usable inline code."""


_INVALID: Final = _Invalid()
_TargetPart = str | _Code | _Invalid


@dataclass(frozen=True)
class _UnitData:
    key: str
    checksum: str | None
    # XLIFF: the target's parts (None: no target). HTML: the segment's inner HTML (None: missing).
    target: tuple[_TargetPart, ...] | str | None


@dataclass(frozen=True)
class TranslationFile:
    """One job read back from a file (an XLIFF file can hold several). Pass it to
    :func:`import_translations`."""

    format: FileFormat
    plugin: str
    reference: str
    source_language: str
    target_language: str
    units: tuple[FileUnit, ...]
    _units: Mapping[str, _UnitData] | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class ImportedSegment:
    """The result for one current segment. ``text`` is the translation (plain text or HTML, like the
    segment) for ``ok`` and ``source_changed``, else ``None``."""

    key: str
    status: ImportStatus
    text: str | None


class TranslationFileError(Exception):
    """A job that can't be exported or a file that can't be read. ``code`` is one of
    ``invalid_job``, ``invalid_file``, ``missing_metadata``, ``too_large``; ``message`` is English."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code: ErrorCode = code
        self.message = message
        super().__init__(message)

    def __repr__(self) -> str:
        return f"TranslationFileError(code={self.code!r}, message={self.message!r})"


class _HasText(Protocol):
    @property
    def text(self) -> str: ...

    @property
    def html(self) -> bool: ...


# JavaScript's \s (and trim()), so the rules match the other SDKs exactly; Python's \s differs.
_WS_CHARS: Final = (
    "\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_W: Final = r"\t\n\x0b\x0c\r \xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_S: Final = "[" + _W + "]"

_BLANK: Final = re.compile(r"[ \t\r\n\f]*")


def _fail(code: ErrorCode, message: str) -> TranslationFileError:
    return TranslationFileError(code, message)


def _is_blank(text: str) -> bool:
    return _BLANK.fullmatch(text) is not None


def checksum(segment: FileSegment | Segment | _HasText) -> str:
    """FNV-1a (32 bit) of the packed segment's UTF-8 bytes, 8 lowercase hex digits. Detects changed
    sources; not a security check."""
    packed = pack(Segment(segment.text, segment.html))
    value = 0x811C9DC5
    # Lone surrogates can't be encoded; they count as U+FFFD, like in the other SDKs.
    for byte in re.sub("[\ud800-\udfff]", "\ufffd", packed).encode("utf-8"):
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return f"{value:08x}"


# ---------------------------------------------------------------------------
# HTML fragments: tokens and inline codes


@dataclass(frozen=True)
class _Text:
    text: str


@dataclass(frozen=True)
class _Start:
    name: str
    raw: str
    self_closing: bool
    attrs: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True)
class _End:
    name: str
    raw: str


@dataclass(frozen=True)
class _Comment:
    raw: str


_Token = _Text | _Start | _End | _Comment


def _js_regex(pattern: str) -> re.Pattern[str]:
    """Compiles a pattern written with JavaScript's whitespace: ``_S_`` is ``[\\s]``, ``_W_`` the inside of it."""
    return re.compile(pattern.replace("_S_", _S).replace("_W_", _W))


_TAG: Final = _js_regex(
    r"<(?:!--[\s\S]*?-->"  # a comment
    r"|/([a-zA-Z][a-zA-Z0-9:-]*)_S_*>"  # an end tag
    r"|([a-zA-Z][a-zA-Z0-9:-]*)"  # a start tag: name, attributes, self-closing slash
    r"((?:_S_+[^_W_\"'>/=]+(?:_S_*=_S_*(?:\"[^\"]*\"|'[^']*'|[^_W_\"'=<>`]+))?)*)_S_*(/?)>)"
)
_ATTR: Final = _js_regex(r"([^_W_\"'>/=]+)(?:_S_*=_S_*(?:\"([^\"]*)\"|'([^']*)'|([^_W_\"'=<>`]+)))?")
_VOID: Final = frozenset(
    ["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"]
)


def _attributes(source: str) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    for a in _ATTR.finditer(source):
        value = a.group(2) if a.group(2) is not None else a.group(3) if a.group(3) is not None else a.group(4)
        out.append((a.group(1).lower(), value))
    return out


def _tokenize(html: str) -> list[_Token]:
    tokens: list[_Token] = []
    last = 0
    for m in _TAG.finditer(html):
        if m.start() > last:
            tokens.append(_Text(html[last : m.start()]))
        raw = m.group(0)
        if raw.startswith("<!--"):
            tokens.append(_Comment(raw))
        elif m.group(1) is not None:
            tokens.append(_End(m.group(1).lower(), raw))
        else:
            attrs = tuple(_attributes(m.group(3) or ""))
            tokens.append(_Start(m.group(2).lower(), raw, m.group(4) == "/", attrs))
        last = m.end()
    if last < len(html):
        tokens.append(_Text(html[last:]))
    return tokens


_ENTITY: Final = re.compile(r"&(#[xX][0-9a-fA-F]+|#[0-9]+|[a-zA-Z][a-zA-Z0-9]*);")
_KNOWN_ENTITY: Final = re.compile(r"amp|lt|gt|quot|apos|nbsp|#[xX][0-9a-fA-F]+|#[0-9]+")


def _is_xml_char(cp: int) -> bool:
    return cp in (0x9, 0xA, 0xD) or 0x20 <= cp <= 0xD7FF or 0xE000 <= cp <= 0xFFFD or 0x10000 <= cp <= 0x10FFFF


def _segment_parts(html: str) -> list[str | _Code]:
    """The inline codes of an HTML segment: a start tag with its matching end tag becomes bpt/ept,
    everything else (void and self-closing tags, unmatched tags, comments, entities XML can't hold)
    a ph. Ids count from 1 in order of appearance; an ept has its bpt's id. Text has the known
    entities decoded."""
    tokens = _tokenize(html)
    end_of: dict[int, int] = {}
    start_of: dict[int, int] = {}
    stack: list[tuple[str, int]] = []
    for i, t in enumerate(tokens):
        if isinstance(t, _Start) and not t.self_closing and t.name not in _VOID:
            stack.append((t.name, i))
        elif isinstance(t, _End) and stack and stack[-1][0] == t.name:
            start = stack.pop()[1]
            end_of[start] = i
            start_of[i] = start
    parts: list[str | _Code] = []
    ids: dict[int, int] = {}
    next_id = 1

    def text(s: str) -> None:
        if parts and isinstance(parts[-1], str):
            parts[-1] += s
        else:
            parts.append(s)

    for i, t in enumerate(tokens):
        if isinstance(t, _Text):
            last = 0
            for m in _ENTITY.finditer(t.text):
                if m.start() > last:
                    text(t.text[last : m.start()])
                decoded = decode_entities(m.group(0)) if _KNOWN_ENTITY.fullmatch(m.group(1)) else m.group(0)
                if decoded != m.group(0) and _is_xml_char(ord(decoded[0])):
                    text(decoded)
                else:
                    parts.append(_Code("ph", next_id, m.group(0)))
                    next_id += 1
                last = m.end()
            if last < len(t.text):
                text(t.text[last:])
        elif isinstance(t, _Start) and i in end_of:
            ids[i] = next_id
            parts.append(_Code("bpt", next_id, t.raw))
            next_id += 1
        elif isinstance(t, _End) and i in start_of:
            parts.append(_Code("ept", ids[start_of[i]], t.raw))
        else:
            parts.append(_Code("ph", next_id, t.raw if not isinstance(t, _Text) else t.text))
            next_id += 1
    return parts


# ---------------------------------------------------------------------------
# Export

_INVALID_XML: Final = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff\ud800-\udfff]")
_CONTROL: Final = re.compile("[\x00-\x1f\x7f]")


def _xml_text(s: str) -> str:
    s = _INVALID_XML.sub("", s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\r", "&#13;")


def _xml_attr(s: str) -> str:
    return _xml_text(s).replace('"', "&quot;")


def _html_attr(s: str) -> str:
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")
    )


def _check_job(job: FileJob) -> list[FileSegment]:
    for name, value in (
        ("plugin", job.plugin),
        ("reference", job.reference),
        ("source_language", job.source_language),
        ("target_language", job.target_language),
    ):
        if not isinstance(value, str) or value.strip(_WS_CHARS) == "" or _CONTROL.search(value):
            raise _fail("invalid_job", f"{name} must be a non-empty string without control characters")
    keys: set[str] = set()
    for segment in job.segments:
        if not isinstance(segment.key, str) or segment.key == "" or _CONTROL.search(segment.key):
            raise _fail("invalid_job", "segment keys must be non-empty strings without control characters")
        if segment.key in keys:
            raise _fail("invalid_job", f"duplicate segment key {json.dumps(segment.key)}")
        keys.add(segment.key)
    segments = [s for s in job.segments if not _is_blank(s.text)]
    if not segments:
        raise _fail("invalid_job", "the job has nothing to translate (all segments blank)")
    return segments


def _xliff_source(segment: FileSegment) -> str:
    if not segment.html:
        return _xml_text(segment.text.replace("\r\n", "\n").replace("\r", "\n"))
    return "".join(
        _xml_text(p) if isinstance(p, str) else f'<{p.code} id="{p.id}">{_xml_text(p.raw)}</{p.code}>'
        for p in _segment_parts(segment.text)
    )


def export_xliff(jobs: Sequence[FileJob]) -> str:
    """One XLIFF 1.2 file with one ``<file>`` per job. Blank segments are left out; a job with only
    blank segments is refused (:class:`TranslationFileError` ``invalid_job``)."""
    if not jobs:
        raise _fail("invalid_job", "at least one job is needed")
    out = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">\n'
    )
    for job in jobs:
        segments = _check_job(job)
        out += (
            f'  <file original="{_xml_attr(job.reference)}" source-language="{_xml_attr(job.source_language)}"'
            f' target-language="{_xml_attr(job.target_language)}"'
            f' datatype="html" product-name="{_xml_attr(job.plugin)}" tool-id="supertext-sdk">\n'
            '    <header>\n      <tool tool-id="supertext-sdk" tool-name="Supertext SDK"/>\n    </header>\n    <body>\n'
        )
        for segment in segments:
            datatype = "" if segment.html else ' datatype="plaintext"'
            out += (
                f'      <trans-unit id="{_xml_attr(segment.key)}"{datatype} extradata="{checksum(segment)}"'
                ' xml:space="preserve">\n'
                f"        <source>{_xliff_source(segment)}</source>\n      </trans-unit>\n"
            )
        out += "    </body>\n  </file>\n"
    return out + "</xliff>\n"


def export_html(job: FileJob) -> str:
    """The HTML document for one job (what ``HtmlDocument.build`` makes) with the job's metadata in
    its head. Blank segments are left out; a job with only blank segments is refused."""
    segments = _check_job(job)
    out = (
        f'<!DOCTYPE html>\n<html lang="{_html_attr(job.source_language)}"><head><meta charset="utf-8">\n'
        f'<meta name="supertext:plugin" content="{_html_attr(job.plugin)}">\n'
        f'<meta name="supertext:reference" content="{_html_attr(job.reference)}">\n'
        f'<meta name="supertext:source-language" content="{_html_attr(job.source_language)}">\n'
        f'<meta name="supertext:target-language" content="{_html_attr(job.target_language)}">\n'
    )
    for i, segment in enumerate(segments):
        out += f'<meta name="supertext:segment" content="{i} {checksum(segment)} {_html_attr(segment.key)}">\n'
    out += "</head><body>\n"
    for i, segment in enumerate(segments):
        out += f'<div data-st-id="{i}">{pack(Segment(segment.text, segment.html))}</div>\n'
    return out + "</body></html>\n"


# ---------------------------------------------------------------------------
# Reading files


class _XElement:
    __slots__ = ("attrs", "children", "name")

    def __init__(self, name: str) -> None:
        self.name = name
        self.attrs: dict[str, str] = {}
        self.children: list[_XElement | str] = []


_XML_NAME: Final = re.compile(r"[A-Za-z_:][-A-Za-z0-9_:.]*")
_XML_REF: Final = re.compile(r"&(?:#x([0-9a-fA-F]+)|#([0-9]+)|(amp|lt|gt|quot|apos));")
_PREDEFINED: Final = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
_WS_RUN: Final = re.compile(_S + "*")
_EQ: Final = re.compile(_S + "*=" + _S + "*([\"'])")


def _local_name(name: str) -> str:
    return name[name.rfind(":") + 1 :]


def _decode_xml(text: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        amp = text.find("&", i)
        if amp < 0:
            out.append(text[i:])
            break
        out.append(text[i:amp])
        m = _XML_REF.match(text, amp, amp + 12)
        if m is None:
            raise _fail("invalid_file", "not a well-formed XML file (unknown entity)")
        if m.group(3):
            out.append(_PREDEFINED[m.group(3)])
        else:
            cp = int(m.group(1), 16) if m.group(1) else int(m.group(2))
            if not _is_xml_char(cp):
                raise _fail("invalid_file", "not a well-formed XML file (character reference)")
            out.append(chr(cp))
        i = m.end()
    return "".join(out)


def _parse_xml(source: str) -> _XElement:
    """A small XML parser: elements, attributes, text, CDATA; comments and processing instructions
    skipped; no DTD (any ``<!`` declaration is refused, so nothing is ever expanded)."""
    s = source.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")

    def bad(what: str) -> TranslationFileError:
        return _fail("invalid_file", f"not a well-formed XML file ({what})")

    i = 0
    root: _XElement | None = None
    stack: list[_XElement] = []
    while i < len(s):
        lt = s.find("<", i)
        text_end = len(s) if lt < 0 else lt
        if text_end > i:
            text = s[i:text_end]
            if stack:
                stack[-1].children.append(_decode_xml(text))
            elif not _is_blank(text):
                raise bad("text outside the root element")
            if "]]>" in text:
                raise bad("]]> in text")
        if lt < 0:
            break
        if s.startswith("<!--", lt):
            end = s.find("-->", lt + 4)
            if end < 0:
                raise bad("unclosed comment")
            i = end + 3
        elif s.startswith("<![CDATA[", lt):
            end = s.find("]]>", lt + 9)
            if end < 0 or not stack:
                raise bad("CDATA")
            stack[-1].children.append(s[lt + 9 : end])
            i = end + 3
        elif s.startswith("<?", lt):
            end = s.find("?>", lt + 2)
            if end < 0:
                raise bad("unclosed processing instruction")
            i = end + 2
        elif s.startswith("<!", lt):
            raise bad("declarations are not allowed")
        elif s.startswith("</", lt):
            name_match = _XML_NAME.match(s, lt + 2)
            end = s.find(">", lt)
            if name_match is None or end < 0 or s[name_match.end() : end].strip(_WS_CHARS) != "":
                raise bad("end tag")
            if not stack or stack.pop().name != name_match.group(0):
                raise bad("mismatched end tag")
            i = end + 1
        else:
            name_match = _XML_NAME.match(s, lt + 1)
            if name_match is None:
                raise bad("start tag")
            j = name_match.end()
            element = _XElement(name_match.group(0))
            seen: set[str] = set()
            while True:
                ws = _WS_RUN.match(s, j, j + 200)
                assert ws is not None
                j = ws.end()
                if s.startswith("/>", j) or s.startswith(">", j):
                    break
                if ws.end() == ws.start():
                    raise bad("attribute")
                attr_match = _XML_NAME.match(s, j, j + 200)
                if attr_match is None:
                    raise bad("attribute")
                attr = attr_match.group(0)
                j = attr_match.end()
                eq = _EQ.match(s, j, j + 200)
                if eq is None:
                    raise bad("attribute value")
                j = eq.end()
                close = s.find(eq.group(1), j)
                if close < 0:
                    raise bad("attribute value")
                raw = s[j:close]
                if "<" in raw:
                    raise bad("< in attribute value")
                if attr in seen:
                    raise bad("duplicate attribute")
                seen.add(attr)
                element.attrs[_local_name(attr)] = _decode_xml(raw.replace("\t", " ").replace("\n", " "))
                j = close + 1
            self_closing = s.startswith("/", j)
            i = j + (2 if self_closing else 1)
            if stack:
                stack[-1].children.append(element)
            elif root is not None:
                raise bad("more than one root element")
            else:
                root = element
            if not self_closing:
                stack.append(element)
    if root is None or stack:
        raise bad("unclosed element")
    return root


_CHECKSUM: Final = re.compile(r"[0-9a-f]{8}")
_CODE_ID: Final = re.compile(r"[1-9][0-9]{0,8}")


def _is_element(node: _XElement | str, name: str) -> bool:
    return not isinstance(node, str) and _local_name(node.name) == name


def _target_parts(nodes: list[_XElement | str]) -> tuple[_TargetPart, ...]:
    out: list[_TargetPart] = []
    # Iterative, so deeply nested <mrk> can't exhaust the stack.
    pending: list[Iterator[_XElement | str]] = [iter(nodes)]
    while pending:
        node = next(pending[-1], None)
        if node is None:
            pending.pop()
        elif isinstance(node, str):
            if out and isinstance(out[-1], str):
                out[-1] += node
            else:
                out.append(node)
        else:
            name = _local_name(node.name)
            node_id = node.attrs.get("id", "")
            if name == "mrk":
                pending.append(iter(node.children))
            elif name in ("bpt", "ept", "ph") and _CODE_ID.fullmatch(node_id):
                out.append(_Code("bpt" if name == "bpt" else "ept" if name == "ept" else "ph", int(node_id)))
            else:
                out.append(_INVALID)
    return tuple(out)


def _read_xliff(content: str) -> list[TranslationFile]:
    root = _parse_xml(content)
    if _local_name(root.name) != "xliff":
        raise _fail("invalid_file", "not an XLIFF file")
    files = [c for c in root.children if isinstance(c, _XElement) and _is_element(c, "file")]
    if not files:
        raise _fail("invalid_file", "the XLIFF file has no <file> element")
    result: list[TranslationFile] = []
    for file in files:
        original = file.attrs.get("original")
        source_language = file.attrs.get("source-language")
        target_language = file.attrs.get("target-language")
        plugin = file.attrs.get("product-name")
        if not original or not source_language or not target_language or not plugin:
            raise _fail(
                "missing_metadata",
                "the <file> element lacks original, source-language, target-language or product-name",
            )
        units: dict[str, _UnitData] = {}
        pending: list[Iterator[_XElement | str]] = [
            iter(body.children)
            for body in reversed(file.children)
            if isinstance(body, _XElement) and _is_element(body, "body")
        ]
        while pending:
            node = next(pending[-1], None)
            if node is None:
                pending.pop()
            elif isinstance(node, str):
                continue
            elif _is_element(node, "group"):
                pending.append(iter(node.children))
            elif _is_element(node, "trans-unit"):
                key = node.attrs.get("id")
                if not key or key in units:
                    continue
                target = next((c for c in node.children if isinstance(c, _XElement) and _is_element(c, "target")), None)
                extradata = node.attrs.get("extradata", "")
                units[key] = _UnitData(
                    key,
                    extradata if _CHECKSUM.fullmatch(extradata) else None,
                    _target_parts(target.children) if target is not None else None,
                )
        result.append(_register("xliff", plugin, original, source_language, target_language, units))
    return result


_META: Final = re.compile(r"""<meta\b((?:[^>"']|"[^"]*"|'[^']*')*)>""", re.IGNORECASE | re.ASCII)
_SEGMENT_META: Final = re.compile(r"([0-9]{1,9}) ([0-9a-f]{8}) ([\s\S]+)")


def _read_html(content: str) -> TranslationFile:
    meta: dict[str, str] = {}
    segments: list[tuple[int, str, str]] = []
    for m in _META.finditer(content):
        attrs: dict[str, str] = {}
        for name, value in _attributes(m.group(1)):
            if name not in attrs:
                attrs[name] = decode_entities(value or "")
        name = attrs.get("name", "").lower()
        if not name.startswith("supertext:") or "content" not in attrs:
            continue
        if name == "supertext:segment":
            s = _SEGMENT_META.fullmatch(attrs["content"])
            if s:
                segments.append((int(s.group(1)), s.group(2), s.group(3)))
        elif name not in meta:
            meta[name] = attrs["content"]
    plugin = meta.get("supertext:plugin")
    reference = meta.get("supertext:reference")
    source_language = meta.get("supertext:source-language")
    target_language = meta.get("supertext:target-language")
    if not plugin or not reference or not source_language or not target_language or not segments:
        raise _fail("missing_metadata", "the HTML file lacks the supertext:* metadata in its head")
    inner = parse_positions(content, {position: True for position, _, _ in segments})
    units: dict[str, _UnitData] = {}
    positions: set[int] = set()
    for position, sum_, key in sorted(segments, key=lambda s: s[0]):
        if key in units or position in positions:
            continue
        positions.add(position)
        units[key] = _UnitData(key, sum_, inner.get(position))
    return _register("html", plugin, reference, source_language, target_language, units)


def _register(
    format: FileFormat, plugin: str, reference: str, source: str, target: str, units: dict[str, _UnitData]
) -> TranslationFile:
    return TranslationFile(
        format,
        plugin,
        reference,
        source,
        target,
        tuple(FileUnit(u.key, u.checksum) for u in units.values()),
        units,
    )


_HTML_START: Final = re.compile("<html[" + _W + ">]")


def read(content: str) -> list[TranslationFile]:
    """Reads an exported file after translation: XLIFF (one result per ``<file>``) or HTML (one
    result). Raises :class:`TranslationFileError`: ``too_large``, ``invalid_file`` (not XLIFF or
    HTML, not well-formed, a DTD), ``missing_metadata``."""
    if len(content) > MAX_FILE_CHARACTERS:
        raise _fail("too_large", f"the file is larger than {MAX_FILE_CHARACTERS} characters")
    start = content.removeprefix("\ufeff").lstrip(_WS_CHARS)[:200].lower()
    if start.startswith(("<?xml", "<xliff")):
        return _read_xliff(content)
    if start.startswith("<!doctype html") or _HTML_START.match(start):
        return [_read_html(content)]
    raise _fail("invalid_file", "neither an XLIFF nor an HTML file")


# ---------------------------------------------------------------------------
# Importing


def _escape_html_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rebuild_html(parts: tuple[_TargetPart, ...], source: str) -> str | None:
    """An HTML segment from XLIFF target parts with the current source's codes; ``None`` if the
    target uses codes the source doesn't have or they don't pair and nest."""
    codes = {(p.code, p.id): p.raw for p in _segment_parts(source) if isinstance(p, _Code)}
    open_ids: list[int] = []
    used: set[int] = set()
    out: list[str] = []
    for p in parts:
        if isinstance(p, str):
            out.append(_escape_html_text(p))
            continue
        if isinstance(p, _Invalid):
            return None
        raw = codes.get((p.code, p.id))
        if raw is None:
            return None
        if p.code == "bpt":
            if p.id in used:
                return None
            used.add(p.id)
            open_ids.append(p.id)
        elif p.code == "ept" and (not open_ids or open_ids.pop() != p.id):
            return None
        out.append(raw)
    return "".join(out) if not open_ids else None


_URL_ATTRIBUTES: Final = frozenset(["href", "src", "action", "formaction", "poster", "cite", "xlink:href"])
_SAFE_SCHEMES: Final = frozenset(["http", "https", "mailto", "tel"])
_URL_IGNORED: Final = re.compile("[\x00-\x20\x7f]")
_URL_HEAD_END: Final = re.compile("[/?#]")
_WS_SPLIT: Final = re.compile(_S + "+")


def _safe_url(value: str) -> bool:
    v = _URL_IGNORED.sub("", decode_entities(value)).lower()
    head = _URL_HEAD_END.split(v, maxsplit=1)[0]
    if "&" in head:
        return False
    colon = head.find(":")
    return colon < 0 or head[:colon] in _SAFE_SCHEMES


def _safe_srcset(value: str) -> bool:
    return all(_safe_url(_WS_SPLIT.split(c.strip(_WS_CHARS))[0]) for c in value.split(","))


def _sanitize_html(inner: str, source: str) -> str | None:
    """A translated HTML segment from an HTML file, rebuilt; ``None`` if it has tags, attributes,
    comments or URLs the source doesn't allow."""
    allowed: dict[str, set[str]] = {}
    comments: set[str] = set()
    for t in _tokenize(source):
        if isinstance(t, _Comment):
            comments.add(t.raw)
        elif not isinstance(t, _Text):
            names = allowed.setdefault(t.name, set())
            if isinstance(t, _Start):
                names.update(name for name, _ in t.attrs)
    out: list[str] = []
    for t in _tokenize(inner):
        if isinstance(t, _Text):
            out.append(t.text.replace("<", "&lt;"))
        elif isinstance(t, _Comment):
            if t.raw not in comments:
                return None
            out.append(t.raw)
        else:
            allowed_names = allowed.get(t.name)
            if allowed_names is None:
                return None
            if isinstance(t, _Start):
                for name, value in t.attrs:
                    if name not in allowed_names:
                        return None
                    if value is not None and name in _URL_ATTRIBUTES and not _safe_url(value):
                        return None
                    if value is not None and name == "srcset" and not _safe_srcset(value):
                        return None
            out.append(t.raw)
    return "".join(out)


def import_translations(file: TranslationFile, current: Sequence[FileSegment]) -> list[ImportedSegment]:
    """The translations for the integration's current segments (collected again from the item the
    file's ``reference`` names), one per non-blank segment in their order.

    Markup comes from the current source only: XLIFF codes are replaced by the source's tags; HTML
    translations may only use the source's tags, attributes and comments, and safe URLs.
    """
    units = file._units
    if units is None:
        raise _fail("invalid_file", "not a file returned by read()")
    out: list[ImportedSegment] = []
    for segment in current:
        if _is_blank(segment.text):
            continue
        unit = units.get(segment.key)
        if unit is None:
            out.append(ImportedSegment(segment.key, "missing", None))
            continue
        untranslated = False
        text: str | None = None
        target = unit.target
        if target is None:
            untranslated = True
        elif isinstance(target, str):
            if segment.html:
                if _is_blank(target):
                    untranslated = True
                else:
                    text = _sanitize_html(target, segment.text)
            else:
                plain = to_plain_text(target)
                untranslated = plain == ""
                text = plain or None
        else:
            has_code = any(not isinstance(p, str) for p in target)
            if not has_code and all(_is_blank(p) for p in target if isinstance(p, str)):
                untranslated = True
            elif segment.html:
                text = _rebuild_html(target, segment.text)
            else:
                text = None if has_code else "".join(p for p in target if isinstance(p, str))
        if untranslated:
            out.append(ImportedSegment(segment.key, "untranslated", None))
        elif text is None:
            out.append(ImportedSegment(segment.key, "invalid_markup", None))
        else:
            status: ImportStatus = "ok" if unit.checksum == checksum(segment) else "source_changed"
            out.append(ImportedSegment(segment.key, status, text))
    return out
