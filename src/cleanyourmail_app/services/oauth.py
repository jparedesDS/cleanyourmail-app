"""The Outlook device-code flow, owned entirely by the sidecar.

The app never calls Microsoft, never sees an access token and never touches the
refresh token: it runs ``connect outlook --no-wait`` to get the URL and code,
shows them, and later runs ``connect outlook --wait`` (which saves the refresh
token in the sidecar's own store) and ``doctor``. ``--json`` is appended by
``services.cli.CliClient``, so this module never passes it.

Known Azure failures are turned into three reasons the UI can translate. The
sidecar's stderr is only read for classification and is never returned to the
page, logged or rendered, so a response body cannot leak a token into a label.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DeviceCode:
    """The URL and user code Microsoft's device login asks for.

    ``expires_in`` is informational: the sidecar owns the expiry check, but a
    page may show it. ``pending`` is the sidecar's device-file path; the app
    never reads that file and never handles the token it leads to.
    """

    verification_uri: str
    user_code: str
    pending: str
    expires_in: int = 0


#: Failure reasons the Connect page maps to catalog keys.
REASON_CONSENT = "consent"
REASON_EXPIRED = "expired"
REASON_FAILED = "failed"

#: The device code is valid for about 15 minutes. The client waits a little
#: longer than that so the sidecar's own expiry message, not a local timeout,
#: is what the person sees.
WAIT_TIMEOUT = 960

#: ``--no-wait`` is one HTTP request plus local file work.
START_TIMEOUT = 120

#: Lower-case fragments that identify a blocked consent. AADSTS65001 is the
#: tenant admin-consent gate; AADSTS50020 is a personal/foreign account the
#: tenant does not accept; both are explained by the same Outlook copy.
_CONSENT_MARKERS = (
    "admin consent",
    "consent_required",
    "aadsts65001",
    "verified publisher",
    "aadsts50020",
)

#: A dead device flow: the code expired, the person declined it, or a saved
#: grant was revoked.
_EXPIRED_MARKERS = (
    "invalid_grant",
    "expired",
    "declined",
    "revoked",
)


class OAuthError(RuntimeError):
    """The sidecar could not start or finish a Microsoft sign-in.

    ``reason`` is one of ``REASON_CONSENT``, ``REASON_EXPIRED`` or
    ``REASON_FAILED``. The message is for developers only; pages show catalog
    copy, never this text.
    """

    def __init__(self, message: str, reason: str = REASON_FAILED) -> None:
        super().__init__(message)
        self.reason = reason


def outlook_failure_reason(source: object) -> str:
    """Classify a sidecar result (or plain text) for the Connect page.

    Accepts the dict ``CliClient.run`` returns, an exception's text, or a
    string. Unknown content is ``REASON_FAILED`` so the page still shows a
    clear retry message instead of raw output.
    """
    text = _failure_text(source).lower()
    if any(marker in text for marker in _CONSENT_MARKERS):
        return REASON_CONSENT
    if any(marker in text for marker in _EXPIRED_MARKERS):
        return REASON_EXPIRED
    return REASON_FAILED


def _failure_text(source: object) -> str:
    """Join the diagnostic fields of a result; never used for display."""
    if isinstance(source, dict):
        parts: list[str] = []
        for key in ("stderr", "stdout", "error", "message"):
            value = source.get(key)
            if value:
                parts.append(str(value))
        data = source.get("data")
        if isinstance(data, dict):
            for key in ("error", "error_description", "message", "detail"):
                value = data.get(key)
                if value:
                    parts.append(str(value))
        return " ".join(parts)
    if isinstance(source, BaseException):
        return str(source)
    return str(source or "")


class OutlookConnect:
    """Run the two sidecar commands that make up Microsoft's device flow.

    ``config_path`` is the TOML the sidecar must read (it needs
    ``oauth = "microsoft"``). Passing ``None`` lets the sidecar use its default
    config, which is useful for a manual smoke test.
    """

    def __init__(self, cli: object, config_path: object) -> None:
        self._cli = cli
        self._config_path = Path(config_path) if config_path is not None else None
        self._cancelled = threading.Event()

    def start(self) -> DeviceCode:
        """Ask Microsoft for a code and return the URL, code and pending path.

        Raises ``OAuthError`` when the sidecar refuses the request or answers
        without a usable URL/code; no token is ever part of the returned value.
        A new start clears the previous Cancel, so the same service can be
        reused for a retry.
        """
        self._cancelled.clear()
        result = self._cli.run(  # type: ignore[attr-defined]
            ["connect", "outlook", "--no-wait"],
            config_path=self._config_path,
            timeout=START_TIMEOUT,
        )
        data = result.get("data") if isinstance(result, dict) else None
        data = data if isinstance(data, dict) else {}
        verification_uri = str(data.get("verification_uri") or "").strip()
        user_code = str(data.get("user_code") or "").strip()
        pending = str(data.get("pending") or "").strip()

        if (
            not isinstance(result, dict)
            or not result.get("ok")
            or not verification_uri
            or not user_code
        ):
            raise OAuthError(
                "Microsoft sign-in did not return a usable device code.",
                outlook_failure_reason(result),
            )

        try:
            expires_in = int(data.get("expires_in") or 0)
        except (TypeError, ValueError):
            expires_in = 0
        return DeviceCode(verification_uri, user_code, pending, max(0, expires_in))

    def cancel(self) -> None:
        """Ask a running ``--wait`` to stop the sidecar instead of ignoring it."""
        self._cancelled.set()

    def wait(self) -> dict[str, Any]:
        """Finish a pending sign-in and return the sidecar's result untouched.

        The sidecar saves the refresh token in its own store. A non-zero exit is
        a result with ``ok=False``, not an exception, so the page can classify
        the reason; ``CliError`` is still raised when the sidecar cannot be
        started or does not answer at all. If Cancel was requested, the child
        is terminated and a normalized ``{ok: False, cancelled: True}`` result
        is returned without reading or using any token.
        """
        result = self._cli.run(  # type: ignore[attr-defined]
            ["connect", "outlook", "--wait"],
            config_path=self._config_path,
            timeout=WAIT_TIMEOUT,
            cancel_event=self._cancelled,
        )
        if self._cancelled.is_set() or (
            isinstance(result, dict) and result.get("cancelled")
        ):
            return {
                "ok": False,
                "cancelled": True,
                "exit_code": -1,
                "data": {},
                "stdout": "",
                "stderr": "",
            }
        return result
