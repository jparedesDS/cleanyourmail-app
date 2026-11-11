"""Bilingual copy: English and Spanish are first-class, and nothing raises.

The catalogs are read as JSON, not through the translator, so a key that is
missing on one side cannot hide behind a runtime fallback: the parity test fails
before a person ever sees a raw key in the wizard.

Task 5 also ships the theme and the brand files; the last two tests keep those
assets from drifting without turning into screenshot tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cleanyourmail_app import i18n as i18n_package
from cleanyourmail_app.domain.models import LANGUAGES
from cleanyourmail_app.i18n import Translator

CATALOGS = ("en", "es")
CATALOG_DIR = Path(i18n_package.__file__).parent
PACKAGE_DIR = CATALOG_DIR.parent
THEME_PATH = PACKAGE_DIR / "ui" / "theme.qss"
RESOURCES_DIR = PACKAGE_DIR / "ui" / "resources"

#: Mojibake tokens that have appeared when a Spanish string was written through
#: a non-UTF-8 console. They are not valid Spanish words; a question mark at the
#: end of a question is fine, but these are not.
LOST_SPANISH_TOKENS = (
    "versi?n",
    "sesi?n",
    "cancel?",
    "aprob?",
    "usar?",
    "contrase?a",
    "contrase?as",
    "l?nea",
    "configuraci?n",
    "conexi?n",
    "reemplazar?a",
    "est?",
    "a?n",
    "env?a",
    "que s? se",
)

PROVIDER_IDS = ("gmail", "outlook", "yahoo", "icloud", "fastmail", "proton", "custom")
PAGE_PREFIXES = (
    "app",
    "common",
    "progress",
    "language",
    "provider",
    "connect",
    "preferences",
    "review",
    "apply",
    "errors",
    "installer",
)
KNOWN_KEYS = (
    "provider.gmail.label",
    "provider.outlook.label",
    "provider.proton.note",
    "connect.gmail.title",
    "connect.outlook.blocked.body",
    "preferences.title",
    "preferences.category.spam.help",
    "review.plan.title",
    "errors.generic",
    "installer.smartscreen.body",
)


def _load(language: str) -> dict[str, Any]:
    return json.loads((CATALOG_DIR / f"{language}.json").read_text(encoding="utf-8"))


def _flatten(payload: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Turn nested JSON into ``dotted.keys``; a list of strings is a leaf."""
    flat: dict[str, str] = {}
    for key, value in payload.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, dotted))
        else:
            flat[dotted] = value
    return flat


def _keys(language: str) -> set[str]:
    return set(_flatten(_load(language)))


def test_english_and_spanish_have_identical_keys():
    english = _keys("en")
    spanish = _keys("es")

    assert english, "the English catalog is empty"
    assert not sorted(english - spanish), f"missing in Spanish: {sorted(english - spanish)}"
    assert not sorted(spanish - english), f"missing in English: {sorted(spanish - english)}"


def test_spanish_copy_has_no_console_mojibake_tokens():
    raw = (CATALOG_DIR / "es.json").read_text(encoding="utf-8")

    for token in LOST_SPANISH_TOKENS:
        assert token not in raw, f"lost Spanish accent: {token!r}"


@pytest.mark.parametrize("language", CATALOGS)
def test_every_catalog_value_is_a_non_empty_string(language):
    for key, value in _flatten(_load(language)).items():
        assert isinstance(value, str), f"{language}:{key} is not a string"
        assert value.strip(), f"{language}:{key} is empty"


@pytest.mark.parametrize("language", CATALOGS)
@pytest.mark.parametrize("key", KNOWN_KEYS)
def test_known_strings_are_present(language, key):
    value = Translator(language).t(key)
    assert value
    assert value != key


@pytest.mark.parametrize("language", CATALOGS)
def test_every_provider_has_a_label_and_a_note(language):
    translator = Translator(language)
    for provider_id in PROVIDER_IDS:
        for field in ("label", "note"):
            key = f"provider.{provider_id}.{field}"
            assert translator.t(key) != key, key


@pytest.mark.parametrize("language", CATALOGS)
def test_both_catalogs_cover_every_page(language):
    keys = _keys(language)
    for prefix in PAGE_PREFIXES:
        assert any(key == prefix or key.startswith(f"{prefix}.") for key in keys), prefix


@pytest.mark.parametrize("language", CATALOGS)
def test_a_missing_key_falls_back_to_the_key_text(language):
    translator = Translator(language)
    assert translator.t("provider.does_not_exist.label") == "provider.does_not_exist.label"


def test_a_missing_key_with_arguments_still_does_not_raise():
    translator = Translator("es")
    assert translator.t("nope.{value}", value=1) == "nope.{value}"


def test_switching_language_changes_a_known_string():
    translator = Translator("en")
    english = translator.t("preferences.title")

    translator.set_language("es")
    spanish = translator.t("preferences.title")

    assert translator.language == "es"
    assert spanish != english
    assert spanish


def test_constructing_with_spanish_starts_in_spanish():
    assert Translator("es").language == "es"


def test_available_languages_are_english_and_spanish():
    assert Translator("en").available_languages == ("en", "es")


def test_translator_languages_match_the_domain_whitelist():
    assert set(Translator("en").available_languages) == set(LANGUAGES)


@pytest.mark.parametrize("language", ["", "fr", "de-DE", " EN ", "eng", None, 7])
def test_unknown_languages_fall_back_to_english(language):
    translator = Translator(language)
    assert translator.language == "en"
    assert translator.t("preferences.title") == Translator("en").t("preferences.title")


@pytest.mark.parametrize("language", ["es-MX", "ES", " es ", "es_ES"])
def test_regional_language_tags_normalise_to_their_base_language(language):
    assert Translator(language).language == "es"


@pytest.mark.parametrize("language", CATALOGS)
def test_named_placeholders_are_filled(language):
    text = Translator(language).t("review.summary", messages=12, groups=3)
    assert "12" in text
    assert "3" in text
    assert "{" not in text


@pytest.mark.parametrize("language", CATALOGS)
def test_incomplete_placeholders_do_not_raise(language):
    text = Translator(language).t("review.summary", messages=12)
    assert isinstance(text, str)
    assert text


@pytest.mark.parametrize(
    ("language", "sentence"),
    [
        ("en", "No feedback is sent automatically"),
        ("es", "Ningún comentario se envía automáticamente"),
    ],
)
def test_feedback_copy_only_claims_feedback_is_not_automatic(language, sentence):
    body = _load(language)["feedback"]["body"]
    assert sentence in body
    assert "Nothing is sent automatically" not in body
    assert "No se envía nada automáticamente" not in body


@pytest.mark.parametrize("language", CATALOGS)
def test_download_failure_copy_covers_download_or_verification(language):
    text = _load(language)["update"]["download_failed"].lower()
    assert "download" in text or "descarg" in text
    assert "verif" in text or "verific" in text


def test_the_theme_styles_the_secondary_open_github_action():
    qss = THEME_PATH.read_text(encoding="utf-8").lower()
    assert "qpushbutton#updategithubbutton" in qss


def test_the_theme_uses_the_spectrum_palette_and_soft_radii():
    qss = THEME_PATH.read_text(encoding="utf-8").lower()
    for colour in ("#121316", "#2a2c31", "#f3f1ec", "#a19e96", "#ffb38a", "#a8e6cf", "#ffe08a"):
        assert colour in qss, colour
    assert "border-radius: 12px" in qss
    assert "border-radius: 16px" in qss
    assert ":focus" in qss, "the theme needs a visible focus ring"
    assert "@font-face" not in qss, "no web fonts"
    assert "http" not in qss


def test_the_brand_mark_and_app_icon_are_shipped():
    for name in ("logo.svg", "app-icon.svg"):
        path = RESOURCES_DIR / name
        assert path.is_file(), name
        assert "<svg" in path.read_text(encoding="utf-8"), name
