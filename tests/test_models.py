"""The pure domain models: provider detection, preferences and app settings."""

from __future__ import annotations

import json

import pytest

from cleanyourmail_app.domain.models import AppSettings, Preferences
from cleanyourmail_app.domain.providers import PROVIDERS, detect_provider

SECRET_MARKERS = ("password", "secret", "token", "credential", "refresh")


# --- provider detection ----------------------------------------------------


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("me@gmail.com", "gmail"),
        ("me@googlemail.com", "gmail"),
        ("me@outlook.com", "outlook"),
        ("me@outlook.es", "outlook"),
        ("me@hotmail.com", "outlook"),
        ("me@hotmail.co.uk", "outlook"),
        ("me@live.com", "outlook"),
        ("me@live.es", "outlook"),
        ("me@msn.com", "outlook"),
        ("me@yahoo.com", "yahoo"),
        ("me@yahoo.es", "yahoo"),
        ("me@icloud.com", "icloud"),
        ("me@me.com", "icloud"),
        ("me@mac.com", "icloud"),
        ("me@fastmail.com", "fastmail"),
        ("me@fastmail.fm", "fastmail"),
        ("me@proton.me", "proton"),
        ("me@protonmail.com", "proton"),
        ("me@corp.example", "custom"),
        ("me@example.com", "custom"),
    ],
)
def test_detect_provider_by_domain(address, expected):
    assert detect_provider(address).id == expected


def test_detect_provider_ignores_case_and_padding():
    assert detect_provider("  Me@GMAIL.com ").id == "gmail"


@pytest.mark.parametrize("address", ["", "not-an-address", "@gmail.com", "me@", "me@gmail"])
def test_detect_provider_falls_back_to_custom(address):
    provider = detect_provider(address)
    assert provider.id == "custom"
    assert provider is not None


def test_detect_provider_does_not_match_subdomains():
    assert detect_provider("me@mail.gmail.com").id == "custom"


# --- provider catalog ------------------------------------------------------


def test_catalog_has_the_seven_providers_in_order():
    assert [provider.id for provider in PROVIDERS] == [
        "gmail", "outlook", "yahoo", "icloud", "fastmail", "proton", "custom",
    ]


def test_catalog_auth_kinds_and_statuses():
    expected = {
        "gmail": ("app_password", "pass"),
        "outlook": ("device_code", "partial"),
        "yahoo": ("app_password", "documented"),
        "icloud": ("app_password", "documented"),
        "fastmail": ("app_password", "documented"),
        "proton": ("bridge", "documented"),
        "custom": ("custom", "documented"),
    }
    for provider in PROVIDERS:
        assert (provider.auth_kind, provider.status) == expected[provider.id]


def test_catalog_help_urls_are_the_design_urls():
    urls = {provider.id: provider.help_url for provider in PROVIDERS}
    assert urls["gmail"] == "https://myaccount.google.com/security"
    assert urls["outlook"] == (
        "https://github.com/jparedesDS/cleanyourmail/blob/master/docs/MICROSOFT-OAUTH.md"
    )
    assert urls["yahoo"] == "https://login.yahoo.com/account/security"
    assert urls["icloud"] == "https://appleid.apple.com/"
    assert urls["fastmail"] == "https://app.fastmail.com/settings/security/apppasswords"
    assert urls["proton"] == "https://proton.me/mail/bridge"
    assert urls["custom"] == (
        "https://github.com/jparedesDS/cleanyourmail/blob/master/docs/PROVIDERS.md"
    )


def test_gmail_exposes_the_app_passwords_page_too():
    gmail = next(provider for provider in PROVIDERS if provider.id == "gmail")
    links = dict(gmail.help_links)
    assert links["app_passwords"] == "https://myaccount.google.com/apppasswords"


def test_catalog_labels_and_notes_are_present():
    for provider in PROVIDERS:
        assert provider.label
        assert provider.note
        assert provider.status in {"pass", "partial", "documented"}
        assert provider.auth_kind in {"app_password", "device_code", "bridge", "custom"}


def test_custom_has_no_domains():
    custom = next(provider for provider in PROVIDERS if provider.id == "custom")
    assert custom.domains == ()


# --- Preferences -----------------------------------------------------------


def test_preferences_defaults():
    preferences = Preferences()
    assert preferences.categories == [
        "newsletter", "promotion", "social", "notification", "cold", "spam",
    ]
    assert preferences.mode == "folders"
    assert preferences.protect_starred is True
    assert preferences.protect_answered is True
    assert preferences.min_age_days == 30
    assert preferences.max_moves == 50
    assert preferences.max_per_group == 100
    assert preferences.language == "en"


def test_preferences_round_trip_through_dict():
    preferences = Preferences(
        categories=["newsletter", "spam"],
        mode="archive",
        protect_starred=False,
        protect_answered=False,
        min_age_days=7,
        max_moves=200,
        max_per_group=25,
        language="es",
    )
    assert Preferences.from_dict(preferences.to_dict()) == preferences


def test_preferences_to_dict_returns_a_copy_of_the_categories():
    preferences = Preferences()
    payload = preferences.to_dict()
    payload["categories"].append("spam")
    assert preferences.categories == [
        "newsletter", "promotion", "social", "notification", "cold", "spam",
    ]


def test_preferences_from_dict_fills_defaults_and_ignores_unknown_keys():
    preferences = Preferences.from_dict({"mode": "archive", "password": "nope"})
    assert preferences.mode == "archive"
    assert preferences.min_age_days == 30
    assert "password" not in preferences.to_dict()


def test_preferences_from_dict_rejects_a_non_mapping():
    with pytest.raises(ValueError):
        Preferences.from_dict([])


@pytest.mark.parametrize(
    "payload",
    [
        {"categories": ["newsletter", "unknown"]},
        {"categories": "spam"},
        {"mode": "delete"},
        {"min_age_days": -1},
        {"max_moves": 0},
        {"max_moves": 5001},
        {"max_per_group": 0},
        {"max_per_group": 5001},
        {"language": ""},
        {"language": "fr"},
    ],
)
def test_preferences_validation_rejects_bad_values(payload):
    with pytest.raises(ValueError):
        Preferences.from_dict(payload)


def test_preferences_accepts_the_boundaries():
    preferences = Preferences(
        categories=[],
        min_age_days=0,
        max_moves=5000,
        max_per_group=1,
    )
    assert preferences.categories == []
    assert preferences.max_moves == 5000


def test_preferences_validation_rejects_bad_direct_construction():
    with pytest.raises(ValueError):
        Preferences(max_moves=0)


# --- AppSettings -----------------------------------------------------------


def test_app_settings_round_trip_preserves_everything():
    settings = AppSettings(
        provider="outlook",
        email="me@outlook.es",
        preferences=Preferences(mode="archive", language="es"),
        last_update_check=1_760_000_000,
    )
    restored = AppSettings.from_dict(settings.to_dict())
    assert restored == settings
    assert restored.provider == "outlook"
    assert restored.email == "me@outlook.es"
    assert restored.preferences.language == "es"
    assert restored.last_update_check == 1_760_000_000


def test_app_settings_last_update_check_defaults_to_zero():
    assert AppSettings().last_update_check == 0
    assert AppSettings.from_dict({}).last_update_check == 0


@pytest.mark.parametrize("value", [-1, True, False, "1760000000", 1.5, None])
def test_app_settings_rejects_a_bad_last_update_check(value):
    with pytest.raises(ValueError):
        AppSettings(last_update_check=value)


def test_app_settings_from_dict_rejects_a_bad_last_update_check():
    with pytest.raises(ValueError):
        AppSettings.from_dict({"provider": "gmail", "last_update_check": -5})


def test_app_settings_default_preferences():
    settings = AppSettings(provider="gmail", email="me@gmail.com")
    assert settings.preferences == Preferences()


def test_app_settings_payload_has_no_secret_key_at_any_depth():
    settings = AppSettings(
        provider="gmail",
        email="me@gmail.com",
        preferences=Preferences(),
    )
    serialized = json.dumps(settings.to_dict()).lower()
    for marker in SECRET_MARKERS:
        assert marker not in serialized


def test_app_settings_from_dict_ignores_secret_keys():
    restored = AppSettings.from_dict(
        {
            "provider": "gmail",
            "email": "me@gmail.com",
            "password": "hunter2",
            "preferences": {"mode": "folders", "app_password": "hunter2"},
        }
    )
    assert restored.provider == "gmail"
    assert "password" not in json.dumps(restored.to_dict()).lower()
    assert "hunter2" not in json.dumps(restored.to_dict())


def test_app_settings_from_dict_rejects_a_non_mapping():
    with pytest.raises(ValueError):
        AppSettings.from_dict("gmail")
