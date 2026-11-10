"""The fixed provider catalog and the email-domain detector.

Each entry is honest about how far it is tested: ``pass`` means validated
against CleanYourMail 1.2.2, ``partial`` means a real limitation (Microsoft
consent), and ``documented`` means the app follows provider documentation but
has not smoke-tested that provider. The UI must show that status, never hide it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

GITHUB_DOCS = "https://github.com/jparedesDS/cleanyourmail/blob/master/docs"


@dataclass(frozen=True, slots=True)
class Provider:
    """One choice on the first page of the wizard.

    ``domains`` holds exact domains, or a ``*`` pattern meaning "the name and
    any TLD" (``hotmail.*``). ``help_url`` is the page the Connect page opens;
    ``help_links`` carries extra named pages (Gmail needs both the security
    checklist and the App Passwords page).
    """

    id: str
    label: str
    auth_kind: str
    domains: tuple[str, ...]
    help_url: str
    status: str
    note: str
    help_links: tuple[tuple[str, str], ...] = field(default=())

    def __post_init__(self) -> None:
        if not self.id or not self.label:
            raise ValueError("a provider needs an id and a label")
        if self.auth_kind not in {"app_password", "device_code", "bridge", "custom"}:
            raise ValueError(f"unknown auth_kind: {self.auth_kind}")
        if self.status not in {"pass", "partial", "documented"}:
            raise ValueError(f"unknown status: {self.status}")
        if not self.help_url.startswith("https://"):
            raise ValueError(f"provider {self.id} needs an https help URL")


CUSTOM = Provider(
    id="custom",
    label="Custom IMAP",
    auth_kind="custom",
    domains=(),
    help_url=f"{GITHUB_DOCS}/PROVIDERS.md",
    status="documented",
    note="Host only; port 993 with TLS.",
)

#: Display order on the provider page. Keep ``custom`` last.
PROVIDERS: tuple[Provider, ...] = (
    Provider(
        id="gmail",
        label="Gmail",
        auth_kind="app_password",
        domains=("gmail.com", "googlemail.com"),
        help_url="https://myaccount.google.com/security",
        status="pass",
        note="2-Step Verification + App Password.",
        help_links=(
            ("app_passwords", "https://myaccount.google.com/apppasswords"),
        ),
    ),
    Provider(
        id="outlook",
        label="Outlook / Microsoft 365",
        auth_kind="device_code",
        # The brief requires outlook.es to match; Microsoft uses country TLDs.
        domains=("outlook.*", "hotmail.*", "live.*", "msn.*"),
        help_url=f"{GITHUB_DOCS}/MICROSOFT-OAUTH.md",
        status="partial",
        note="Microsoft 365 admin consent; Outlook.com personal verified publisher.",
    ),
    Provider(
        id="yahoo",
        label="Yahoo",
        auth_kind="app_password",
        domains=("yahoo.*",),
        help_url="https://login.yahoo.com/account/security",
        status="documented",
        note="App password.",
    ),
    Provider(
        id="icloud",
        label="iCloud",
        auth_kind="app_password",
        domains=("icloud.com", "me.com", "mac.com"),
        help_url="https://appleid.apple.com/",
        status="documented",
        note="App password.",
    ),
    Provider(
        id="fastmail",
        label="Fastmail",
        auth_kind="app_password",
        domains=("fastmail.com", "fastmail.fm"),
        help_url="https://app.fastmail.com/settings/security/apppasswords",
        status="documented",
        note="App password.",
    ),
    Provider(
        id="proton",
        label="Proton Bridge",
        auth_kind="bridge",
        domains=("proton.me", "protonmail.com"),
        help_url="https://proton.me/mail/bridge",
        status="documented",
        note="Bridge must be running.",
    ),
    CUSTOM,
)

PROVIDERS_BY_ID: dict[str, Provider] = {provider.id: provider for provider in PROVIDERS}


def provider_by_id(provider_id: str) -> Provider:
    """Return a known provider, falling back to Custom for stale ids."""
    return PROVIDERS_BY_ID.get(provider_id, CUSTOM)


def _domain_of(email: str) -> str:
    """Lower-case domain part, or ``""`` when the address is not usable."""
    if not isinstance(email, str):
        return ""
    text = email.strip()
    local, separator, domain = text.rpartition("@")
    if not separator or not local.strip() or not domain.strip():
        return ""
    return domain.strip().rstrip(".").lower()


def _matches(patterns: tuple[str, ...], domain: str) -> bool:
    for pattern in patterns:
        if pattern.endswith(".*"):
            stem = pattern[:-2]
            if domain == stem or domain.startswith(f"{stem}."):
                return True
        elif domain == pattern:
            return True
    return False


def detect_provider(email: str) -> Provider:
    """Pick the provider card for ``email``; unknown domains get Custom.

    Matching is exact on the domain (no subdomain guessing), case-insensitive,
    and never raises: an empty or malformed address simply means Custom.
    """
    domain = _domain_of(email)
    if not domain:
        return CUSTOM
    for provider in PROVIDERS:
        if _matches(provider.domains, domain):
            return provider
    return CUSTOM
