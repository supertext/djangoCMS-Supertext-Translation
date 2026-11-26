"""Client for the Supertext AI file translation API v1.

Protocol: POST an HTML file → poll its status → GET the translation → DELETE the file.
"""

from __future__ import annotations

import contextlib
import json
import random
import re
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import quote

from ..transport import HttpRequest, HttpResponse, Transport, UrllibTransport
from . import html_document
from .api_key_check import KEY_CHECK_TIMEOUT, ApiKeyCheck, api_key_check_from_error, api_key_fingerprint, iso_seconds
from .corrections import (
    ACKNOWLEDGE_BATCH_SIZE,
    MAX_PAGES,
    Correction,
    acknowledge_body,
    acknowledged_count,
    corrections_path,
    parse_corrections_page,
)
from .errors import ErrorCode, SupertextError, error_for_response
from .html_document import Segment

LIVE_BASE_URL: Final = "https://api.supertext.com/v1/"

DEFAULT_MAX_CHARACTERS: Final = 900_000
"""Characters per document in :meth:`SupertextClient.translate_texts`: well below the API's limit of 1,000,000."""

Politeness = Literal["default", "more", "less"]
"""``more`` = formal address (Sie, vous), ``less`` = informal (du, tu), ``default`` = let Supertext decide."""


@dataclass(frozen=True)
class FeatureSupport:
    """One language pair from ``GET features``."""

    source_lang: str
    target_lang: str
    features: tuple[str, ...]
    """E.g. ``supports_politeness``, ``supports_glossary``."""


_USER_AGENT: Final = "supertext-sdk-python"
_PREFIX = re.compile(r"^supertext-auth-key(?:\s+|$)", re.IGNORECASE)
_RETRY_AFTER = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def auth_header(api_key: str | None) -> str:
    """The ``Authorization`` value for a key as pasted by an administrator (spec/auth-header.json).

    Supertext shows the key with its ``Supertext-Auth-Key`` prefix, so a pasted prefix is stripped
    and exactly one is sent. A blank key raises ``SupertextError(missing_api_key)``.
    """
    key = _PREFIX.sub("", (api_key or "").strip()).strip()
    if not key:
        raise SupertextError(ErrorCode.MISSING_API_KEY)
    return f"Supertext-Auth-Key {key}"


def retry_delay_ms(attempt: int, retry_after: str | None = None, rand: Callable[[], float] = random.random) -> int:
    """Milliseconds to wait before retrying HTTP 429 number ``attempt`` (0-based; spec/retry-delay.json).

    A ``Retry-After`` in plain seconds wins; otherwise 1, 2, 4, 8, … s plus 0 to 249 ms jitter, so
    that several clients sharing a key don't retry in lockstep. Either way at most 30 s.
    """
    value = (retry_after or "").strip(" \t\n\r\f\v")
    if _RETRY_AFTER.fullmatch(value):
        delay = round(float(value) * 1000)
    else:
        delay = 1000 * (1 << attempt) + min(249, int(rand() * 250))
    return min(30_000, delay)


class SupertextClient:
    """Translates HTML documents and texts with Supertext.

    A blank API key doesn't fail here: the first request raises ``SupertextError(missing_api_key)``
    without sending anything, so integrations can build the client before the key is configured.
    Times are in seconds. ``transport``, ``sleep``, ``clock`` (monotonic, for timeouts) and ``now``
    (Unix time, for :attr:`ApiKeyCheck.checked_at`) are injectable for tests.
    """

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = LIVE_BASE_URL,
        poll_interval: float = 2.0,
        timeout: float = 180.0,
        request_timeout: float = 30.0,
        max_retries: int = 4,
        user_agent: str | None = None,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._api_key = api_key or ""
        self.base_url = (base_url or LIVE_BASE_URL).rstrip("/") + "/"
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.request_timeout = request_timeout
        self.max_retries = max_retries
        self.user_agent = f"{_USER_AGENT} {user_agent}" if user_agent else _USER_AGENT
        self._transport: Transport = transport or UrllibTransport()
        self._sleep = sleep
        self._clock = clock
        self._now = now

    def __repr__(self) -> str:
        # Never show the key.
        return f"SupertextClient(base_url={self.base_url!r})"

    # -- Single steps ------------------------------------------------------------------------

    def get_features(self) -> list[FeatureSupport]:
        """The language pairs the API offers right now, with their features (``supports_politeness``, …).

        The live version of :data:`Languages.SOURCES <supertext.v1.languages.SOURCES>` /
        :data:`TARGETS <supertext.v1.languages.TARGETS>`, e.g. for a settings page. Cost-free.
        Malformed entries are skipped.
        """
        try:
            data = json.loads(self._request("GET", "features").text)
        except ValueError:
            return []
        items = data.get("supported_features") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        result = []
        for item in items:
            entry = item if isinstance(item, dict) else {}
            source_lang, target_lang = entry.get("source_lang"), entry.get("target_lang")
            if not isinstance(source_lang, str) or not isinstance(target_lang, str):
                continue
            features = entry.get("features")
            names = tuple(f for f in features if isinstance(f, str)) if isinstance(features, list) else ()
            result.append(FeatureSupport(source_lang, target_lang, names))
        return result

    def validate_api_key(self) -> None:
        """Cost-free check that the key is accepted; raises :class:`SupertextError` otherwise."""
        self._request("GET", "features")

    def check_api_key(self) -> ApiKeyCheck:
        """The automatic API key check: ``GET features`` with at most 10 s timeout, as an :class:`ApiKeyCheck`.

        Status ``ok`` (2xx), ``invalid`` (401/403), ``unreachable`` (no answer, 5xx) or ``error``
        (anything else, e.g. 429 after the retries). Never raises. A blank key gives ``missing``
        without a request.
        """
        checked_at = iso_seconds(self._now())
        fingerprint = api_key_fingerprint(self._api_key)
        if not fingerprint:
            return ApiKeyCheck("missing", checked_at, None, None, fingerprint)
        try:
            response = self._request("GET", "features", timeout=min(KEY_CHECK_TIMEOUT, self.request_timeout))
        except Exception as error:
            return api_key_check_from_error(error, checked_at, fingerprint)
        return ApiKeyCheck("ok", checked_at, response.status, None, fingerprint)

    def submit(
        self, html: str, target_lang: str, source_lang: str | None = None, politeness: Politeness = "default"
    ) -> str:
        """Uploads an HTML document and returns its file id.

        The language codes are sent as given (trimmed): resolve CMS languages with
        :meth:`Languages.target() <supertext.v1.Languages.target>` / :meth:`Languages.source()
        <supertext.v1.Languages.source>` first. An empty ``target_lang`` raises
        ``SupertextError(unsupported_language)`` without a request. Without ``source_lang`` Supertext
        detects the language.
        """
        target = target_lang.strip()
        if not target:
            raise SupertextError(ErrorCode.UNSUPPORTED_LANGUAGE)
        fields = [("target_lang", target)]
        source = (source_lang or "").strip()
        if source:
            fields.append(("source_lang", source))
        if politeness in ("more", "less"):
            fields.append(("politeness", politeness))
        body, content_type = _multipart(fields, html)
        response = self._request("POST", "translate/ai/file", body=body, content_type=content_type)
        file_id = _json_field(response, "file_id")
        if not file_id:
            raise SupertextError(ErrorCode.NO_FILE_ID, status=response.status)
        return file_id

    def get_status(self, file_id: str) -> str:
        """The file's status: ``translating``, ``done``, ``error``, ``limit_exceeded``, ``deleted`` (or others)."""
        return _json_field(self._request("GET", f"translate/ai/file/{quote(file_id, safe='')}/status"), "status")

    def wait_until_done(self, file_id: str) -> None:
        """Polls until the file is ``done``; raises on ``error``/``limit_exceeded``/``deleted`` or after ``timeout``."""
        started = self._clock()
        while True:
            status = self.get_status(file_id)
            if status == "done":
                return
            if status == "error":
                raise SupertextError(ErrorCode.TRANSLATION_ERROR)
            if status == "limit_exceeded":
                raise SupertextError(ErrorCode.QUOTA_EXCEEDED)
            if status == "deleted":
                raise SupertextError(ErrorCode.FILE_DELETED)
            # Unknown statuses (e.g. "queued") mean "not yet": keep polling.
            if self._clock() + self.poll_interval - started > self.timeout:
                raise SupertextError(ErrorCode.TIMEOUT)
            self._sleep(self.poll_interval)

    def download(self, file_id: str) -> str:
        """The translated HTML document."""
        text = self._request("GET", f"translate/ai/file/{quote(file_id, safe='')}/translation").text
        if not text.strip():
            raise SupertextError(ErrorCode.INCOMPLETE_RESPONSE)
        return text

    def delete(self, file_id: str) -> None:
        """Deletes the file at Supertext. Never raises: files expire after 24 hours anyway."""
        # Cleanup must never hide the real result (or raise after a success).
        with contextlib.suppress(Exception):
            self._request("DELETE", f"translate/ai/file/{quote(file_id, safe='')}")

    # -- Whole translations ------------------------------------------------------------------

    def translate_html(
        self, html: str, target_lang: str, source_lang: str | None = None, politeness: Politeness = "default"
    ) -> str:
        """Translates a complete HTML document and returns the translated document."""
        file_id = self.submit(html, target_lang, source_lang, politeness)
        try:
            self.wait_until_done(file_id)
            return self.download(file_id)
        finally:
            self.delete(file_id)

    def translate_texts(
        self,
        segments: Mapping[str, Segment | str],
        target_lang: str,
        source_lang: str | None = None,
        politeness: Politeness = "default",
        max_characters: int = DEFAULT_MAX_CHARACTERS,
    ) -> dict[str, str]:
        """Translates texts by key and returns ``{key: translation}`` in input order.

        A value is a :class:`Segment` or a plain ``str`` (shorthand for ``Segment(text)``). Blank
        texts come back unchanged without being sent. Large inputs are split into several
        documents (``max_characters`` each), translated one after the other because the API
        limits requests per second.
        """
        items = {key: value if isinstance(value, Segment) else Segment(value) for key, value in segments.items()}
        result = {key: segment.text for key, segment in items.items()}
        for batch in plan_batches(items, max_characters):
            batch_segments = [items[key] for key in batch]
            translated = self.translate_html(html_document.build(batch_segments), target_lang, source_lang, politeness)
            texts = html_document.parse(translated, batch_segments)
            missing = [key for key, text in zip(batch, texts, strict=True) if text is None]
            if missing:
                raise SupertextError(ErrorCode.INCOMPLETE_RESPONSE, detail="missing: " + ", ".join(missing))
            for key, text in zip(batch, texts, strict=True):
                result[key] = text or ""
        return result

    # -- HTTP --------------------------------------------------------------------------------

    def pending_corrections(
        self,
        target_lang: str | None = None,
        source_lang: str | None = None,
        politeness: Politeness | None = None,
    ) -> list[Correction]:
        """Corrections reviewers made that the integration hasn't written into the CMS yet
        (Supertext Localization Review; spec/corrections.json). Only the review service answers
        this: against Supertext's API it raises ``not_found``. Follows all pages. ``segment_id``
        is the ``data-st-id`` the integration sent, so this is useful when the integration builds
        its documents with its own ids (:meth:`translate_html`)."""
        found: list[Correction] = []
        after: str | None = None
        for _ in range(MAX_PAGES):
            response = self._request("GET", corrections_path(target_lang, source_lang, politeness, after))
            corrections, nxt = parse_corrections_page(response.text)
            found.extend(corrections)
            if nxt is None or nxt == after:
                break
            after = nxt
        return found

    def acknowledge_corrections(self, corrections: Sequence[Correction]) -> int:
        """Tells the review service these corrections are in the CMS now; returns how many it
        accepted. Only the fetched ``version`` counts: a newer correction stays pending."""
        total = 0
        for i in range(0, len(corrections), ACKNOWLEDGE_BATCH_SIZE):
            body = acknowledge_body(corrections[i : i + ACKNOWLEDGE_BATCH_SIZE]).encode("utf-8")
            response = self._request(
                "POST", "review/corrections/acknowledge", body=body, content_type="application/json"
            )
            total += acknowledged_count(response.text)
        return total

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        authorization = auth_header(self._api_key)
        headers = {
            "Authorization": authorization,
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if content_type:
            headers["Content-Type"] = content_type
        request_timeout = self.request_timeout if timeout is None else timeout
        request = HttpRequest(method, self.base_url + path, headers, body, request_timeout)
        attempt = 0
        while True:
            try:
                response = self._transport(request)
            except OSError as error:
                detail = _scrub(str(error) or type(error).__name__, authorization)
                raise SupertextError(ErrorCode.TRANSPORT_ERROR, detail=detail) from None
            if response.status != 429 or attempt >= self.max_retries:
                break
            # The API limits requests per second per key; several languages at once hit it.
            self._sleep(retry_delay_ms(attempt, response.header("Retry-After")) / 1000)
            attempt += 1
        if 200 <= response.status < 300:
            return response
        failure = error_for_response(response.status, response.text)
        if failure.detail:
            failure.detail = _scrub(failure.detail, authorization)
        raise failure


def _scrub(text: str, authorization: str) -> str:
    # A misbehaving proxy or server could echo the key back; it must not end up in logs.
    key = authorization.split(" ", 1)[1]
    return text.replace(key, "***")


def plan_batches(segments: Mapping[str, Segment], max_characters: int = DEFAULT_MAX_CHARACTERS) -> list[list[str]]:
    """Splits segments into documents (spec/batching.json): lists of keys, in input order.

    Blank segments are skipped. A segment longer than ``max_characters`` goes alone.
    """
    batches: list[list[str]] = []
    current: list[str] = []
    size = 0
    for key, segment in segments.items():
        if not segment.text.strip(" \t\r\n\f"):
            continue
        length = len(html_document.pack(segment))
        if current and size + length > max_characters:
            batches.append(current)
            current, size = [], 0
        current.append(key)
        size += length
    if current:
        batches.append(current)
    return batches


def _json_field(response: HttpResponse, name: str) -> str:
    try:
        data = json.loads(response.text)
    except ValueError:
        return ""
    value = data.get(name) if isinstance(data, dict) else None
    return str(value) if value is not None else ""


def _multipart(fields: list[tuple[str, str]], html: str) -> tuple[bytes, str]:
    # Built by hand: the file part's Content-Type must be exactly "text/html" (no charset), or the
    # API answers 415. Fields go in the documented order: target_lang, source_lang, politeness, file.
    boundary = "supertext-" + uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields
    ]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="content.html"\r\n'
        "Content-Type: text/html\r\n\r\n".encode()
        + html.encode("utf-8")
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
