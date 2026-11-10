"""Pure domain layer: provider catalog, preferences and app settings.

Import from here in UI code so a module move stays a one-file change.
"""

from cleanyourmail_app.domain.models import (
    CATEGORIES,
    LANGUAGES,
    MODES,
    AppSettings,
    Preferences,
)
from cleanyourmail_app.domain.providers import (
    CUSTOM,
    PROVIDERS,
    PROVIDERS_BY_ID,
    Provider,
    detect_provider,
    provider_by_id,
)

__all__ = [
    "CATEGORIES",
    "CUSTOM",
    "LANGUAGES",
    "MODES",
    "PROVIDERS",
    "PROVIDERS_BY_ID",
    "AppSettings",
    "Preferences",
    "Provider",
    "detect_provider",
    "provider_by_id",
]
