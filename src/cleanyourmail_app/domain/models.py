"""Pure domain models for the wizard.

Nothing in this package touches Qt, the network, the filesystem or the sidecar:
``Preferences`` and ``AppSettings`` are plain data with validation, so they can
be tested and reused without a running application.

The local settings file stores *choices*, never credentials. A secret field is
therefore not part of any model here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

#: Message categories the person can choose to clean, in display order.
CATEGORIES: tuple[str, ...] = (
    "newsletter",
    "promotion",
    "social",
    "notification",
    "cold",
    "spam",
)

#: ``folders`` moves mail, ``archive`` removes the Inbox label.
MODES: tuple[str, ...] = ("folders", "archive")

#: Languages with a full translation. Spanish is first-class, not a fallback.
LANGUAGES: tuple[str, ...] = ("en", "es")


def _mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{what} must be a JSON object")
    return value


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false")
    return value


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _choice(value: Any, name: str, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in allowed:
        joined = ", ".join(allowed)
        raise ValueError(f"{name} must be one of: {joined}")
    return value


def _categories(value: Any) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ValueError("categories must be a list")
    result: list[str] = []
    for category in value:
        if not isinstance(category, str) or category not in CATEGORIES:
            joined = ", ".join(CATEGORIES)
            raise ValueError(f"categories must be a subset of: {joined}")
        result.append(category)
    return result


@dataclass
class Preferences:
    """What to clean, how, and what to protect.

    The defaults are the safe ones: all six categories selected, a reversible
    move into folders, starred and answered mail protected, and conservative
    limits.
    """

    categories: list[str] = field(default_factory=lambda: list(CATEGORIES))
    mode: str = "folders"
    protect_starred: bool = True
    protect_answered: bool = True
    min_age_days: int = 30
    max_moves: int = 50
    max_per_group: int = 100
    language: str = "en"

    def __post_init__(self) -> None:
        self.categories = _categories(self.categories)
        self.mode = _choice(self.mode, "mode", MODES)
        self.protect_starred = _boolean(self.protect_starred, "protect_starred")
        self.protect_answered = _boolean(self.protect_answered, "protect_answered")
        self.min_age_days = _integer(self.min_age_days, "min_age_days", 0, 36500)
        self.max_moves = _integer(self.max_moves, "max_moves", 1, 5000)
        self.max_per_group = _integer(self.max_per_group, "max_per_group", 1, 5000)
        self.language = _choice(self.language, "language", LANGUAGES)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready copy; the category list is never aliased."""
        return {
            "categories": list(self.categories),
            "mode": self.mode,
            "protect_starred": self.protect_starred,
            "protect_answered": self.protect_answered,
            "min_age_days": self.min_age_days,
            "max_moves": self.max_moves,
            "max_per_group": self.max_per_group,
            "language": self.language,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Preferences:
        """Rebuild preferences from JSON.

        Missing keys take their defaults and unknown keys are dropped, so a
        settings file written by an older or newer build still loads. Invalid
        values raise ``ValueError``; the caller decides whether to reset.
        """
        payload = _mapping(data, "preferences")
        return cls(
            categories=payload.get("categories", list(CATEGORIES)),
            mode=payload.get("mode", "folders"),
            protect_starred=payload.get("protect_starred", True),
            protect_answered=payload.get("protect_answered", True),
            min_age_days=payload.get("min_age_days", 30),
            max_moves=payload.get("max_moves", 50),
            max_per_group=payload.get("max_per_group", 100),
            language=payload.get("language", "en"),
        )


@dataclass
class AppSettings:
    """The non-secret state the app remembers between runs.

    The provider id and the email address live here, not inside
    ``Preferences``: they belong to the account step, while ``Preferences`` is
    what the person chose to clean.
    """

    provider: str = "custom"
    email: str = ""
    preferences: Preferences = field(default_factory=Preferences)

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("provider must be a non-empty string")
        self.provider = self.provider.strip()
        if not isinstance(self.email, str):
            raise ValueError("email must be a string")
        self.email = self.email.strip()
        if not isinstance(self.preferences, Preferences):
            raise ValueError("preferences must be a Preferences value")

    def to_dict(self) -> dict[str, Any]:
        """Return only the stored fields; a secret key cannot slip in."""
        return {
            "provider": self.provider,
            "email": self.email,
            "preferences": self.preferences.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Any) -> AppSettings:
        payload = _mapping(data, "settings")
        return cls(
            provider=payload.get("provider", "custom"),
            email=payload.get("email", ""),
            preferences=Preferences.from_dict(payload.get("preferences", {})),
        )
