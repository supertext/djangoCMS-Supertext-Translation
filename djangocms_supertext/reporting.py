"""
Version reports to the Supertext Commando Center, the automatic API key check and the callback
ping (Commando-Center-Supertext-Translation → docs/DEVELOPER.md → Report protocol).

The protocol is Supertext Plugin Health's (``_vendor/plugin_health``: ``InstallationReporter``,
``ping_response``, ``reports_enabled``), the key check the Supertext SDK's (``check_api_key``); this
module only gives them what django CMS knows: the site URL, the django CMS and package versions, the
ping URL, and a place for the reporter's state (the ``State`` row ``reporter``).

The settings live in Django's settings file, so there is no "settings saved": the key check runs
when the key differs from the one last checked (fingerprint), on *Test connection*, in
``supertext_check`` and after a 401/403 from Supertext. Back-end requests (settings page, translate
dialog) report after the response has been sent. Nothing here ever raises into a request or command.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from django.utils import translation
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe
from django.utils.translation import gettext as _

from . import __version__, conf
from ._vendor.plugin_health import (
    CallableKeyChecker,
    HttpRequest,
    HttpResponse,
    InstallationReporter,
    KeyCheck,
    NameVersion,
    PingResponse,
    ReporterResult,
    ReporterState,
    ping_response,
    reporter_state,
)
from ._vendor.supertext import SDK_VERSION
from ._vendor.supertext import v1 as sdk
from .client import PLUGIN_NAME, SupertextClient

logger = logging.getLogger(__name__)

#: PLUGIN_NAME (from .client): the GitHub repository name (the center reads the latest release from it).
STATE_KEY = "reporter"

#: For tests: extra options for the Plugin Health reporter (transport, report_url, now, key_checker).
REPORTER_OVERRIDES: dict = {}


def django_cms_version() -> str | None:
    try:
        import cms

        return str(cms.__version__)
    except Exception:  # noqa: BLE001
        return None


def ping_path() -> str:
    """The ping route: ``/supertext/ping`` when the site includes ``djangocms_supertext.urls``, else the admin's."""
    from django.urls import NoReverseMatch, reverse
    from django.conf import settings

    with translation.override(getattr(settings, "LANGUAGE_CODE", None) or "en"):
        for name in ("djangocms_supertext_ping", "admin:djangocms_supertext_ping"):
            try:
                return reverse(name)
            except NoReverseMatch:
                continue
    return ""


def site_url(options: conf.Options, request=None) -> str | None:
    """The site's base URL: ``SUPERTEXT["SITE_URL"]``, else the request's scheme and host, else the
    current Django site's domain (https), unless it is still Django's ``example.com``."""
    if options.site_url.startswith(("http://", "https://")):
        return options.site_url
    if request is not None:
        try:
            return request.build_absolute_uri("/").rstrip("/")
        except Exception:  # noqa: BLE001 - e.g. a disallowed host
            return None
    try:
        from django.contrib.sites.models import Site

        domain = Site.objects.get_current().domain.strip().rstrip("/")
    except Exception:  # noqa: BLE001
        return None
    if not domain or domain == "example.com":
        return None
    return domain if domain.startswith(("http://", "https://")) else f"https://{domain}"


def load_state() -> ReporterState:
    from .models import State

    row = State.objects.filter(key=STATE_KEY).first()
    return reporter_state(row.value if row else None)


def save_state(state: ReporterState) -> None:
    from .models import State

    State.objects.update_or_create(key=STATE_KEY, defaults={"value": state.to_json()})


def last_check() -> KeyCheck | None:
    try:
        return load_state().key_check
    except Exception:  # noqa: BLE001 - the table may not be migrated yet
        return None


def reporter(options: conf.Options, url: str | None) -> InstallationReporter:
    """The Plugin Health reporter. Without a site URL it only checks the key (reports need the URL).

    Reports and key checks go through the plugin's ``requests`` transport (proxies, certificates); the
    key check is the SDK's ``check_api_key`` against the configured API URL."""
    client = options.client()

    def send(request: HttpRequest) -> HttpResponse:
        answer = client.transport(sdk.HttpRequest(request.method, request.url, dict(request.headers), request.body, request.timeout))
        return HttpResponse(answer.status, answer.body)

    def check(api_key: str) -> object:
        return SupertextClient(api_key, options.base_url, session=client.transport.session).check_api_key()

    path = ping_path()
    kwargs = {
        "enabled": options.reports_enabled and bool(url),
        "site_url": url or "",
        "plugin": NameVersion(PLUGIN_NAME, __version__),
        "system": NameVersion("django CMS", django_cms_version()),
        "sdk_version": SDK_VERSION,
        "callback_url": url + path if url and path else None,
        "transport": send,
        "key_checker": CallableKeyChecker(check=check, fingerprint=sdk.api_key_fingerprint),
    }
    kwargs.update(REPORTER_OVERRIDES)
    return InstallationReporter(**kwargs)


def ping(challenge) -> PingResponse:
    """The ping route's answer (404 while version reports are off)."""
    return ping_response(challenge if isinstance(challenge, str) else None, PLUGIN_NAME, conf.load().reports_enabled)


def run(action: str, options: conf.Options | None = None, request=None, http_status: int = 401) -> ReporterResult | None:
    """Runs one reporter action (``on_request``, ``test_connection``, ``authentication_failed``,
    ``report_check``) with the stored state and stores the result. Never raises; None if skipped."""
    try:
        options = options or conf.load()
        url = site_url(options, request)
        if not url:
            logger.debug("[supertext] version report skipped: no site URL (set SITE_URL in the SUPERTEXT setting)")
        rep = reporter(options, url)
        state = load_state()
        if action == "authentication_failed":
            result = rep.authentication_failed(state, options.api_key, http_status)
        elif action == "test_connection":
            result = rep.test_connection(state, options.api_key)
        elif action == "report_check":
            result = rep.report_check(state)
        else:
            result = rep.on_request(state, options.api_key)
        save_state(result.state)
        if result.event:
            logger.debug("[supertext] version report %s: %s", result.event, "sent" if result.sent else "not sent")
        return result
    except Exception as error:  # noqa: BLE001 - reporting never breaks the admin
        logger.debug("[supertext] version report skipped: %s", error)
        return None


def after_response(response, task: Callable[[], object]) -> None:
    """Runs ``task`` once the response has been sent (Django calls the response's closers then);
    right away if the response can't take it."""
    closers = getattr(response, "_resource_closers", None)
    if isinstance(closers, list):
        closers.append(task)
    else:
        task()


def report_translation(results, options: conf.Options | None = None, request=None, response=None) -> None:
    """After translating: ``authentication_failed`` if Supertext rejected the key, else ``on_request``."""
    rejected = next((r for r in results or [] if getattr(r, "code", "") == "authentication_failure"), None)
    if rejected is not None:
        task = lambda: run("authentication_failed", options, request, rejected.http_status or 401)  # noqa: E731
    else:
        task = lambda: run("on_request", options, request)  # noqa: E731
    if response is None:
        task()
    else:
        after_response(response, task)


# -- Key check messages (Commando Center's table, in the admin language) -----------------------


def check_message(check: KeyCheck | None) -> str:
    """The plain text of a key check result."""
    if check is None:
        return _("Not checked yet.")
    if check.status == "ok":
        return _("API key checked: the connection to Supertext works.")
    if check.status == "invalid":
        return _(
            "Supertext rejected the API key. Check that you copied the whole key, or generate a new one at supertext.com → Integrations → API (requires the Admin role). No Supertext account yet? Create one at supertext.com."
        )
    if check.status == "missing":
        return _(
            "No API key is set yet. No Supertext account yet? Create one at supertext.com. Generate your API key at supertext.com → Integrations → API (requires the Admin role)."
        )
    if check.status == "unreachable":
        return _("The API key couldn't be checked because Supertext can't be reached. The settings are saved; check again later.")
    return _("The API key couldn't be checked: Supertext answered with an error (%(status)s). The settings are saved; check again later.") % {
        "status": check.http_status or check.error_code or "?"
    }


_API_PAGE = "supertext.com → Integrations → API"


def check_html(check: KeyCheck | None) -> SafeString:
    """The message with *supertext.com* and *supertext.com → Integrations → API* as links (new tab)."""
    text = str(escape(check_message(check)))
    if check is not None and check.status in ("invalid", "missing"):
        token = "\x00api\x00"
        text = text.replace(_API_PAGE, token).replace(
            "supertext.com", f'<a href="{conf.SIGNUP_URL}" target="_blank" rel="noopener">supertext.com</a>'
        )
        text = text.replace(token, f'<a href="{conf.API_KEY_URL}" target="_blank" rel="noopener">{_API_PAGE}</a>')
    return mark_safe(text)  # noqa: S308 - escaped above, only our own links added
