"""The translator: plain Python, no Qt import.

The catalogs are JSON files that sit next to this module, nested by page
(``provider.gmail.label`` is ``{"provider": {"gmail": {"label": ...}}}``). They
are flattened once and cached for the life of the process.

Two rules matter for the wizard:

* English and Spanish must carry exactly the same keys. A parity test enforces
  it, because a missing translation returns the key text, which is visible to
  the person but never fatal.
* ``t`` never raises. A missing key returns the key itself; a template whose
  placeholders were not all supplied returns the template unchanged.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_LANGUAGE = "en"

#: Languages with a full catalog, in display order. Pinned to
#: ``domain.models.LANGUAGES`` by a test.
AVAILABLE_LANGUAGES: tuple[str, ...] = ("en", "es")


def normalise_language(language: object) -> str:
    """Return a supported language code, or English for anything unknown.

    ``es-MX``, ``ES`` and ``es_ES`` all mean Spanish: the base tag is what the
    catalog is keyed by, and a regional variant must not silently fall back.
    """
    if not isinstance(language, str):
        return DEFAULT_LANGUAGE
    base = language.strip().lower().replace("_", "-").split("-", 1)[0]
    return base if base in AVAILABLE_LANGUAGES else DEFAULT_LANGUAGE


@lru_cache(maxsize=None)
def _catalog(language: str) -> dict[str, str]:
    """Load and flatten one JSON catalog. Cached: the files never change."""
    path = Path(__file__).with_name(f"{language}.json")
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return _flatten(payload)


def _flatten(payload: dict[str, Any], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in payload.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, dotted))
        elif isinstance(value, str):
            flat[dotted] = value
        else:
            raise ValueError(f"{dotted} must be a string")
    return flat


class Translator:
    """Look up visible copy for one language.

    ``Translator(language)`` accepts a full tag (``es-MX``); an unsupported or
    malformed value starts in English instead of failing the wizard.
    """

    def __init__(self, language: str = DEFAULT_LANGUAGE) -> None:
        self._language = normalise_language(language)
        # Load both catalogs now: a packaging error surfaces at startup, not
        # halfway through the wizard, and the active catalog is a plain dict.
        self._catalogs = {code: _catalog(code) for code in AVAILABLE_LANGUAGES}

    @property
    def language(self) -> str:
        """The active language code."""
        return self._language

    @property
    def available_languages(self) -> tuple[str, ...]:
        """Every language with a full catalog, in display order."""
        return AVAILABLE_LANGUAGES

    def set_language(self, language: str) -> None:
        """Switch language in place; unknown values fall back to English."""
        self._language = normalise_language(language)

    def t(self, key: str, **kwargs: object) -> str:
        """Return the copy for ``key``, optionally formatted with ``kwargs``.

        A missing key returns the key text. A template with an unfilled
        placeholder returns the template, so a bad call can never crash a page.
        """
        template = self._catalogs[self._language].get(key)
        if template is None:
            return key
        if not kwargs:
            return template
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return template
