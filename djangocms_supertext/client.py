"""
The plugin's access to the Supertext AI file translation API (v1), built on the shared
Supertext Python SDK (``djangocms_supertext/_vendor/supertext``, copied by
``scripts/vendor-sdk.sh``; sites install nothing else). The SDK does the protocol:

1. ``POST translate/ai/file``                 multipart HTML upload -> ``{"file_id": …}``
2. ``GET translate/ai/file/{id}/status``      poll until ``done``
3. ``GET translate/ai/file/{id}/translation`` the translated HTML
4. ``DELETE translate/ai/file/{id}``          cleanup, also after errors

plus the ``Authorization: Supertext-Auth-Key <key>`` header (a pasted prefix is stripped),
HTTP 429 retries and packing many strings into one document. Language codes are resolved
before (``conf.Options.target_code``, the SDK's ``Languages``); the SDK sends them as given. Requests go
through ``requests`` (the plugin's HTTP library: proxies, certificates). SDK errors come out
as this module's :class:`SupertextError`, whose message template is translated in the admin.

No Django imports here: tested on its own.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path

import requests

from ._vendor.supertext import v1 as sdk
from ._vendor.supertext.v1 import ApiKeyCheck, ErrorCode, HttpRequest, HttpResponse, Languages, Segment, html_document, plan_batches

LIVE = sdk.LIVE_BASE_URL
ENVIRONMENTS = {
    "live": LIVE,
    "staging": "https://api.staging.supertext.com/v1/",
    "testing": "https://api.testing.supertext.com/v1/",
}
#: Supertext's review service (translation proxy of Supertext Localization Review). It speaks the
#: same API v1 and forwards to the live Supertext API with the plugin's key, keeping every
#: translation so reviewers can correct them on the website. Used for languages with *Translation review* on.
REVIEW_URL = "https://localizationreview-production.up.railway.app/v1/"
#: The plugin's name in the User-Agent and in version reports (the repository's name).
PLUGIN_NAME = "djangoCMS-Supertext-Translation"
SIGNUP_URL = "https://www.supertext.com/person/en/account/signin"
#: supertext.com → Integrations → API (requires the Admin role).
API_KEY_URL = "https://www.supertext.com/en/integrations/api"

#: Stay well below the API's 1,000,000 character limit per document.
MAX_DOCUMENT_CHARACTERS = sdk.DEFAULT_MAX_CHARACTERS

#: Version of the vendored SDK (the copy isn't an installed distribution).
SDK_VERSION = (Path(__file__).parent / "_vendor" / "supertext" / "VERSION").read_text(encoding="utf-8").strip()


def gettext_noop(message: str) -> str:
    """Marks a message for translation (makemessages) without importing Django."""
    return message


_KEY_LINKS = {"signup_url": SIGNUP_URL, "api_key_url": API_KEY_URL}

#: Message (translated in the admin) per SDK error code.
MESSAGES: dict[str, str] = {
    ErrorCode.MISSING_API_KEY: gettext_noop(
        "No Supertext API key is configured. No Supertext account yet? Create one at %(signup_url)s. "
        "Generate your API key at %(api_key_url)s (supertext.com → Integrations → API, requires the Admin role)."
    ),
    ErrorCode.AUTHENTICATION_FAILURE: gettext_noop(
        "Authentication failed. Please check the Supertext API key. No Supertext account yet? Create one at %(signup_url)s. "
        "Generate a new API key at %(api_key_url)s (requires the Admin role)."
    ),
    ErrorCode.INVALID_LANGUAGE_PAIR: gettext_noop(
        "Supertext does not support this language pair (%(source)s → %(target)s). Check the Supertext languages "
        "under Supertext → Supertext translations → Settings and connection → Languages."
    ),
    ErrorCode.UNSUPPORTED_LANGUAGE: gettext_noop(
        "The language %(language)s has no Supertext language yet. Ask your administrator to choose one "
        "under Supertext → Supertext translations → Settings and connection → Languages."
    ),
    ErrorCode.UNSUPPORTED_FEATURE: gettext_noop(
        "Supertext offers no formal or informal tone for this language (%(target)s). "
        "Set its form of address to the default under Supertext → Supertext translations → Settings and connection → Languages."
    ),
    ErrorCode.NOT_FOUND: gettext_noop("The requested Supertext resource was not found."),
    ErrorCode.PAYLOAD_TOO_LARGE: gettext_noop("The content is too large for Supertext to translate in one go."),
    ErrorCode.TOO_MANY_REQUESTS: gettext_noop("Too many requests to Supertext. Please try again shortly."),
    ErrorCode.SERVICE_UNAVAILABLE: gettext_noop("The Supertext service is currently unavailable."),
    ErrorCode.UNEXPECTED_STATUS: gettext_noop("Supertext answered with HTTP %(code)s."),
    ErrorCode.TRANSPORT_ERROR: gettext_noop("Could not reach Supertext: %(error)s"),
    ErrorCode.NO_FILE_ID: gettext_noop("Supertext did not return a file id."),
    ErrorCode.TRANSLATION_ERROR: gettext_noop("Supertext could not translate the document."),
    ErrorCode.QUOTA_EXCEEDED: gettext_noop("Your Supertext translation limit is exceeded. Please upgrade your subscription."),
    ErrorCode.FILE_DELETED: gettext_noop("The document was deleted at Supertext before it could be downloaded."),
    ErrorCode.TIMEOUT: gettext_noop("Timed out waiting for the Supertext translation."),
    ErrorCode.INCOMPLETE_RESPONSE: gettext_noop("The translated document was empty."),
}


class SupertextError(Exception):
    """A Supertext error. ``code`` is the SDK's error code.

    ``str(error)`` is the English message. ``template`` and ``params`` let the Django layer
    show it in the admin language; ``detail`` is the API's own text (never translated).
    """

    def __init__(self, message: str, status: int | None = None, *, params: dict | None = None, detail: str = "", code: str = ""):
        self.template = message
        self.params = params or {}
        self.status = status
        self.detail = detail
        self.code = code
        text = message % self.params if self.params else message
        super().__init__(f"{text} ({detail})" if detail else text)

    @classmethod
    def from_sdk(cls, error: sdk.SupertextError) -> SupertextError:
        params: dict = {}
        detail = error.detail or ""
        if error.code in (ErrorCode.MISSING_API_KEY, ErrorCode.AUTHENTICATION_FAILURE):
            params = dict(_KEY_LINKS)
        elif error.code == ErrorCode.UNEXPECTED_STATUS:
            params = {"code": error.status}
        elif error.code == ErrorCode.TRANSPORT_ERROR:
            params, detail = {"error": detail or "?"}, ""
        elif error.code == ErrorCode.INVALID_LANGUAGE_PAIR:
            params = {"source": error.source_lang or "?", "target": error.target_lang or "?"}
        elif error.code == ErrorCode.UNSUPPORTED_LANGUAGE:
            params = {"language": error.target_lang or error.source_lang or "?"}
        elif error.code == ErrorCode.UNSUPPORTED_FEATURE:
            params = {"target": error.target_lang or "?"}
        message = MESSAGES.get(error.code, error.message)
        return cls(message, error.status, params=params, detail=detail, code=error.code)


def normalize_key(key: str | None) -> str:
    """Strips whitespace and a pasted ``Supertext-Auth-Key `` prefix."""
    key = (key or "").strip()
    return key[len("Supertext-Auth-Key ") :].strip() if key.lower().startswith("supertext-auth-key ") else key


def base_url_for(environment: str = "live", endpoint: str = "") -> str:
    url = (endpoint or "").strip() or ENVIRONMENTS.get((environment or "live").lower(), LIVE)
    return url.rstrip("/") + "/"


class RequestsTransport:
    """Sends the SDK's requests with ``requests`` (honours proxies and certificate settings)."""

    def __init__(self, session: requests.Session):
        self.session = session

    def __call__(self, request: HttpRequest) -> HttpResponse:
        try:
            response = self.session.request(
                request.method, request.url, headers=dict(request.headers), data=request.body, timeout=request.timeout
            )
        except requests.RequestException as error:
            raise OSError(str(error)) from error
        headers = {name.lower(): value for name, value in response.headers.items()}
        return HttpResponse(response.status_code, response.content or b"", headers)


class SupertextClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = LIVE,
        *,
        poll_timeout: float = 180,
        poll_interval: float = 2,
        request_timeout: float = 30,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        review_url: str = "",
    ):
        from . import __version__

        self.api_key = normalize_key(api_key)
        self.base_url = (base_url or LIVE).rstrip("/") + "/"
        # The plugin's version too, so Supertext and the review service see which release calls.
        self.user_agent = f"{PLUGIN_NAME}/{__version__}"
        self.transport = RequestsTransport(session or requests.Session())
        review_url = (review_url or "").strip()
        self.review_url = review_url.rstrip("/") + "/" if review_url and review_url.rstrip("/") != self.base_url.rstrip("/") else ""
        self._review_client: SupertextClient | None = None
        self._settings = {"poll_timeout": poll_timeout, "poll_interval": poll_interval, "request_timeout": request_timeout, "sleep": sleep}
        self.sdk = sdk.SupertextClient(
            self.api_key,
            base_url=self.base_url,
            poll_interval=poll_interval,
            timeout=poll_timeout,
            request_timeout=request_timeout,
            user_agent=self.user_agent,
            transport=self.transport,
            sleep=sleep,
        )

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def for_review(self, review: bool) -> SupertextClient:
        """The client for a target language: the review service when its *Translation review* is on
        (same key, timeouts, session and User-Agent; created once), else this one. Without a review
        URL (``""`` or the same as the API's), always this one. Each document is uploaded, polled,
        downloaded and deleted by the client that submitted it."""
        if not review or not self.review_url:
            return self
        if self._review_client is None:
            self._review_client = SupertextClient(self.api_key, self.review_url, session=self.transport.session, **self._settings)
        return self._review_client

    def translate_document(self, html: str, target_language: str, source_language: str = "", politeness: str = "default") -> str:
        """Translates a complete HTML document and returns the translated HTML.

        The codes are sent as given: Supertext codes (``de-CH``, ``es``; see ``Languages.TARGETS``) for
        the target, a bare language for the source (empty: auto-detect); ``politeness`` is default,
        more or less. Formal/informal for a target that doesn't offer it is refused before sending
        (``unsupported_feature``), so a setting is never silently dropped.
        """
        if politeness in ("more", "less") and Languages.supports_politeness(target_language) is False:
            raise SupertextError.from_sdk(sdk.SupertextError(ErrorCode.UNSUPPORTED_FEATURE, target_lang=target_language, feature="politeness"))
        try:
            return self.sdk.translate_html(html, target_language, source_language or None, politeness)  # type: ignore[arg-type]
        except sdk.SupertextError as error:
            raise SupertextError.from_sdk(error) from error

    def translate_segments(
        self, segments: Sequence[Segment], target_language: str, source_language: str = "", politeness: str = "default"
    ) -> dict[int, str]:
        """Translates segments (plain text or HTML, one ``data-st-id`` element each) in as few documents as possible.

        Returns ``{index: translation}``; blank segments and those Supertext returned nothing for are left out.
        """
        keyed = {str(i): segment for i, segment in enumerate(segments)}
        out: dict[int, str] = {}
        for batch in plan_batches(keyed, MAX_DOCUMENT_CHARACTERS):
            batch_segments = [keyed[key] for key in batch]
            translated = self.translate_document(html_document.build(batch_segments), target_language, source_language, politeness)
            for key, text in zip(batch, html_document.parse(translated, batch_segments), strict=True):
                if text is not None:
                    out[int(key)] = text
        return out

    def check_api_key(self) -> ApiKeyCheck:
        """The automatic key check (``ok``, ``invalid``, ``missing``, ``unreachable``, ``error``). Never raises."""
        return self.sdk.check_api_key()

    def validate_api_key(self) -> None:
        """Cost-free check that the key is accepted."""
        try:
            self.sdk.validate_api_key()
        except sdk.SupertextError as error:
            raise SupertextError.from_sdk(error) from error
