"""Supertext AI file translation API v1. A later API version gets its own subpackage
(``supertext.v2``) next to this one, so integrations can move at their own pace.

    from supertext import v1

    client = v1.SupertextClient(api_key)
    target = v1.Languages.target(cms_locale, {"de": "de-CH"})
    texts = client.translate_texts({"title": "Hello", "body": v1.Segment("<p>Hi</p>", html=True)}, target)

No Supertext account yet? Create one at https://www.supertext.com/person/en/account/signin.
Generate your API key at https://www.supertext.com/en/integrations/api
(supertext.com → Integrations → API; requires the Admin role).
"""

from ..transport import HttpRequest, HttpResponse, Transport, UrllibTransport
from . import languages
from .api_key_check import KEY_CHECK_TIMEOUT, ApiKeyCheck, ApiKeyCheckStatus, api_key_fingerprint
from .client import (
    DEFAULT_MAX_CHARACTERS,
    LIVE_BASE_URL,
    FeatureSupport,
    Politeness,
    SupertextClient,
    auth_header,
    plan_batches,
    retry_delay_ms,
)
from .corrections import Correction
from .errors import API_KEY_URL, SIGNUP_URL, ErrorCode, SupertextError
from .html_document import HtmlDocument, Segment
from .languages import LanguageMapping, Languages, SourceLanguage, TargetLanguage

__all__ = [
    "API_KEY_URL",
    "DEFAULT_MAX_CHARACTERS",
    "KEY_CHECK_TIMEOUT",
    "LIVE_BASE_URL",
    "SIGNUP_URL",
    "ApiKeyCheck",
    "ApiKeyCheckStatus",
    "Correction",
    "ErrorCode",
    "FeatureSupport",
    "HtmlDocument",
    "HttpRequest",
    "HttpResponse",
    "LanguageMapping",
    "Languages",
    "Politeness",
    "Segment",
    "SourceLanguage",
    "SupertextClient",
    "SupertextError",
    "TargetLanguage",
    "Transport",
    "UrllibTransport",
    "api_key_fingerprint",
    "auth_header",
    "languages",
    "plan_batches",
    "retry_delay_ms",
]
