"""Build the opt-in feedback checklist and validate a message.

Nothing in this module sends data. The app only calls it after the person
presses Send in the feedback dialog. The checklist is deliberately narrow:
version, Windows build, provider label, mode, category names and language.
Account addresses, config paths, subjects, senders, message IDs, passwords,
tokens and logs never enter it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

FEEDBACK_ENDPOINT = "https://cleanyourmail-feedback.subtitleme.workers.dev"
FEEDBACK_KINDS = ("feedback", "bug")
MAX_MESSAGE = 4000
MAX_CHECKLIST = 6000
MAX_CONTACT = 200

_UNKNOWN = "(unknown)"


@dataclass(frozen=True)
class FeedbackPayload:
    """The exact JSON body the Worker accepts. ``website`` is a honeypot."""

    kind: str
    message: str
    checklist: str
    contact: str = ""
    app_version: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "message": self.message,
            "checklist": self.checklist,
            "contact": self.contact,
            "app_version": self.app_version,
            "website": "",
        }


def _shown(value: str) -> str:
    """Return a trimmed value, or a placeholder when it is missing."""
    if not isinstance(value, str):
        return _UNKNOWN
    return value.strip() or _UNKNOWN


def build_checklist(
    app_version: str,
    sidecar_version: str,
    provider: str,
    mode: str,
    categories: Iterable[str],
    language: str,
    windows_version: str,
) -> str:
    """Return a plain-text checklist with no account or message data."""
    selected: list[str] = []
    for category in categories:
        if not isinstance(category, str):
            continue
        name = category.strip()
        if name and name not in selected:
            selected.append(name)

    lines = [
        f"CleanYourMail app {_shown(app_version)}",
        f"Sidecar: {_shown(sidecar_version)}",
        f"Windows: {_shown(windows_version)}",
        f"Provider: {_shown(provider)}",
        f"Mode: {_shown(mode)}",
        "Categories: " + (", ".join(selected) if selected else "(none)"),
        f"Language: {_shown(language)}",
    ]
    return "\n".join(lines)


def _normalized_kind(kind: str) -> str:
    return kind.strip().lower() if isinstance(kind, str) else ""


def validate_feedback(
    *,
    kind: str,
    message: str,
    checklist: str,
    contact: str,
) -> str | None:
    """Return an i18n key for the first problem, or ``None`` when valid."""
    if _normalized_kind(kind) not in FEEDBACK_KINDS:
        return "feedback.invalid_kind"
    if not isinstance(message, str) or not isinstance(checklist, str):
        return "feedback.invalid"
    if not isinstance(contact, str):
        return "feedback.invalid"
    if not message.strip() and not checklist.strip():
        return "feedback.empty"
    if len(message) > MAX_MESSAGE:
        return "feedback.message_too_long"
    if len(checklist) > MAX_CHECKLIST:
        return "feedback.checklist_too_long"
    if len(contact) > MAX_CONTACT:
        return "feedback.contact_too_long"
    return None


def feedback_payload(
    *,
    kind: str,
    message: str,
    checklist: str,
    contact: str = "",
    app_version: str = "",
) -> FeedbackPayload:
    """Build a payload after the caller has validated it."""
    return FeedbackPayload(
        kind=_normalized_kind(kind),
        message=message.strip(),
        checklist=checklist.strip(),
        contact=contact.strip(),
        app_version=app_version.strip(),
    )


__all__ = [
    "FEEDBACK_ENDPOINT",
    "FEEDBACK_KINDS",
    "MAX_CHECKLIST",
    "MAX_CONTACT",
    "MAX_MESSAGE",
    "FeedbackPayload",
    "build_checklist",
    "feedback_payload",
    "validate_feedback",
]
