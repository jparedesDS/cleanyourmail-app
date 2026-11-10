"""The opt-in feedback HTTP client.

This module is reached only after the person presses Send in the feedback
dialog and accepts the privacy line. It never runs at import or startup, never
sends on its own, and never logs the payload or the response body.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request

from cleanyourmail_app.domain.feedback import (
    FEEDBACK_ENDPOINT,
    FeedbackPayload,
)

_MAX_RESPONSE_BYTES = 4096


class FeedbackError(RuntimeError):
    """A user-facing feedback failure, identified by an i18n key."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def send_feedback(
    payload: FeedbackPayload,
    *,
    endpoint: str = FEEDBACK_ENDPOINT,
    timeout: int = 20,
) -> None:
    """POST one payload to the Worker; raise FeedbackError on failure."""
    if not isinstance(payload, FeedbackPayload):
        raise TypeError("payload must be a FeedbackPayload")
    target = (endpoint or "").strip()
    if not target:
        raise FeedbackError("feedback.not_configured")

    body = json.dumps(
        payload.as_dict(),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        target,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "CleanYourMail-feedback/1",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(_MAX_RESPONSE_BYTES)
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 429:
            raise FeedbackError("feedback.rate_limited") from error
        if error.code == 503:
            raise FeedbackError("feedback.not_configured") from error
        raise FeedbackError("feedback.failed") from error
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
        http.client.HTTPException,
    ) as error:
        raise FeedbackError("feedback.failed") from error

    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FeedbackError("feedback.failed") from error
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        raise FeedbackError("feedback.failed")


__all__ = ["FeedbackError", "send_feedback"]
