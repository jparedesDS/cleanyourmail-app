"""Bilingual copy for every visible string in the app.

English and Spanish are first-class. Import ``Translator`` from here; the JSON
catalogs are package data, not Python modules.
"""

from __future__ import annotations

from cleanyourmail_app.i18n.translator import (
    AVAILABLE_LANGUAGES,
    DEFAULT_LANGUAGE,
    Translator,
    normalise_language,
)

__all__ = ["AVAILABLE_LANGUAGES", "DEFAULT_LANGUAGE", "Translator", "normalise_language"]
