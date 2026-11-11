"""Read the public GitHub release feed and download a verified installer.

This module is network-only: it never starts an installer, writes outside the
chosen target directory or sends account data. The only requests are the public
release metadata and the release's two public assets.

SHA-256 is read from the same release as the installer, so it detects a corrupt
or partial download, not a compromised maintainer account. Code signing is the
next security step; until then the person's confirmation is the human check.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import posixpath
import re
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

RELEASES_API = "https://api.github.com/repos/jparedesDS/cleanyourmail-app/releases/latest"
RELEASES_PAGE = "https://github.com/jparedesDS/cleanyourmail-app/releases/latest"

INSTALLER_PREFIX = "CleanYourMail-Setup-"
ALLOWED_HOSTS: frozenset[str] = frozenset({
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
})
MAX_INSTALLER_BYTES = 200 * 1024 * 1024

_TIMEOUT_SECONDS = 10.0
_MAX_FEED_BYTES = 1024 * 1024
_MAX_CHECKSUM_BYTES = 4096
_CHUNK_BYTES = 64 * 1024
_VERSION_RE = re.compile(r"[0-9]+(?:\.[0-9]+)*")
_CHECKSUM_RE = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{64}(?![0-9A-Fa-f])")

Opener = Callable[..., Any]


class UpdateError(RuntimeError):
    """A release check or installer download failed."""


@dataclass
class UpdateInfo:
    """One newer release and, when available, its verified-asset URLs."""

    version: str
    tag: str
    installer_url: str = ""
    checksum_url: str = ""
    notes: str = ""
    published_at: str = ""


def parse_version(value: Any) -> tuple[int, ...]:
    """Turn ``v1.2.3`` or ``1.2.3`` into ``(1, 2, 3)``.

    Malformed values return an empty tuple so they can never compare as newer.
    """

    if not isinstance(value, str):
        return ()
    text = value.strip()
    if text[:1] in {"v", "V"}:
        text = text[1:]
    if not text:
        return ()
    parts = text.split(".")
    if any(not part.isascii() or not part.isdigit() for part in parts):
        return ()
    return tuple(int(part) for part in parts)


def is_newer(latest: Any, current: Any) -> bool:
    """True only when both versions are valid and ``latest`` is higher.

    Trailing zero components are ignored, so ``0.6`` equals ``0.6.0``.
    """

    new_version = parse_version(latest)
    old_version = parse_version(current)
    if not new_version or not old_version:
        return False
    width = max(len(new_version), len(old_version))
    padded_new = new_version + (0,) * (width - len(new_version))
    padded_old = old_version + (0,) * (width - len(old_version))
    return padded_new > padded_old


def check_for_update(
    current_version: str,
    *,
    opener: Opener | None = None,
) -> UpdateInfo | None:
    """Return the newest release when it is newer than ``current_version``.

    A malformed tag or an older/equal release returns ``None``. A release whose
    installer or checksum asset is missing, misnamed or hosted elsewhere still
    returns an ``UpdateInfo`` but with empty URLs: the caller falls back to the
    public release page instead of installing anything.
    """

    request = urllib.request.Request(
        RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"CleanYourMail/{_safe_user_agent_token(current_version)}",
        },
    )
    open_url = opener if opener is not None else urllib.request.urlopen

    try:
        with open_url(request, timeout=_TIMEOUT_SECONDS) as response:
            raw = response.read(_MAX_FEED_BYTES + 1)
    except urllib.error.HTTPError as error:
        error.close()
        raise UpdateError("GitHub returned an error for the release feed.") from error
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
        http.client.HTTPException,
    ) as error:
        raise UpdateError("Could not reach the GitHub release feed.") from error

    if not isinstance(raw, (bytes, bytearray)):
        raise UpdateError("GitHub returned an unreadable release feed.")
    if len(raw) > _MAX_FEED_BYTES:
        raise UpdateError("GitHub returned an oversized release feed.")

    try:
        payload = json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UpdateError("GitHub returned an unreadable release feed.") from error
    if not isinstance(payload, dict):
        raise UpdateError("GitHub returned an invalid release feed.")

    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise UpdateError("The release feed has no tag name.")
    version = _version_from_tag(tag)
    if not version or not is_newer(version, current_version):
        return None

    installer_name = f"{INSTALLER_PREFIX}{version}.exe"
    checksum_name = f"{installer_name}.sha256"
    installer_url, checksum_url = _release_asset_urls(
        payload.get("assets"), installer_name, checksum_name
    )
    notes = payload.get("body")
    published_at = payload.get("published_at")
    return UpdateInfo(
        version=version,
        tag=tag.strip(),
        installer_url=installer_url,
        checksum_url=checksum_url,
        notes=notes if isinstance(notes, str) else "",
        published_at=published_at if isinstance(published_at, str) else "",
    )


def download_update(
    info: UpdateInfo,
    *,
    opener: Opener | None = None,
    target_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Download and verify the installer named by ``info``.

    The checksum is fetched first, the installer is streamed to a ``.part``
    file, and only a matching SHA-256 is promoted with ``os.replace`` to the
    final ``.exe`` path. Any failure removes the partial file and raises
    ``UpdateError``; nothing is ever executed here.
    """

    if not isinstance(info, UpdateInfo):
        raise TypeError("download_update() needs an UpdateInfo value")
    version = info.version if isinstance(info.version, str) else ""
    if not _VERSION_RE.fullmatch(version):
        raise UpdateError("The release version cannot name an installer.")

    installer_name = f"{INSTALLER_PREFIX}{version}.exe"
    checksum_name = f"{installer_name}.sha256"
    _require_allowed_url(info.installer_url, "installer")
    _require_allowed_url(info.checksum_url, "checksum")
    if _url_filename(info.installer_url) != installer_name:
        raise UpdateError("The installer asset has an unexpected file name.")
    if _url_filename(info.checksum_url) != checksum_name:
        raise UpdateError("The checksum asset has an unexpected file name.")

    directory = (
        Path(target_dir) if target_dir is not None else Path(tempfile.gettempdir())
    )
    final_path = directory / installer_name
    part_path = directory / f"{installer_name}.part"
    open_url = opener if opener is not None else urllib.request.urlopen
    completed = False

    try:
        directory.mkdir(parents=True, exist_ok=True)
        expected_digest = _fetch_checksum(
            open_url,
            info.checksum_url,
            version,
            installer_name,
        )
        actual_digest = _fetch_installer(
            open_url,
            info.installer_url,
            version,
            part_path,
        )
        if not hmac.compare_digest(actual_digest, expected_digest):
            raise UpdateError("The downloaded installer did not match its SHA-256.")
        os.replace(part_path, final_path)
        completed = True
        return final_path
    except UpdateError:
        raise
    except Exception as error:
        raise UpdateError("Could not download the update.") from error
    finally:
        if not completed:
            _remove_file(part_path)


def _version_from_tag(tag: str) -> str:
    text = tag.strip()
    if text[:1] in {"v", "V"}:
        text = text[1:]
    return text if _VERSION_RE.fullmatch(text) else ""


def _release_asset_urls(
    assets: Any,
    installer_name: str,
    checksum_name: str,
) -> tuple[str, str]:
    by_name: dict[str, str] = {}
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = asset.get("name")
            url = asset.get("browser_download_url")
            if isinstance(name, str) and isinstance(url, str):
                by_name.setdefault(name, url)

    installer_url = by_name.get(installer_name, "")
    checksum_url = by_name.get(checksum_name, "")
    if not (
        _is_allowed_url(installer_url)
        and _is_allowed_url(checksum_url)
        and _url_filename(installer_url) == installer_name
        and _url_filename(checksum_url) == checksum_name
    ):
        return "", ""
    return installer_url, checksum_url


def _safe_user_agent_token(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    text = re.sub(r"[^0-9A-Za-z._-]", "-", text)
    return text or "unknown"


def _is_allowed_url(url: Any) -> bool:
    """True only for HTTPS URLs on the two recognised GitHub hosts."""

    if not isinstance(url, str) or not url:
        return False
    if any(ord(character) < 0x21 or ord(character) > 0x7E for character in url):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme.lower() != "https":
        return False
    if parts.username is not None or parts.password is not None:
        return False
    if parts.hostname is None or parts.hostname.lower() not in ALLOWED_HOSTS:
        return False
    return port in (None, 443)


def _require_allowed_url(url: Any, role: str) -> None:
    if not _is_allowed_url(url):
        raise UpdateError(f"The update {role} URL is not an allowed GitHub HTTPS URL.")


def _url_filename(url: str) -> str:
    try:
        return posixpath.basename(urlsplit(url).path)
    except ValueError:
        return ""


def _asset_request(url: str, version: str, accept: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": f"CleanYourMail/{version}",
        },
    )


def _ensure_allowed_final_url(response: Any) -> None:
    """Reject a redirect whose final URL is not an allowed GitHub host."""

    geturl = getattr(response, "geturl", None)
    if not callable(geturl):
        raise UpdateError("The update download did not report a final URL.")
    try:
        final_url = geturl()
    except Exception as error:
        raise UpdateError("The update download did not report a final URL.") from error
    if not isinstance(final_url, str) or not final_url:
        raise UpdateError("The update download did not report a final URL.")
    if not _is_allowed_url(final_url):
        raise UpdateError("The update download was redirected to an untrusted host.")


def _fetch_checksum(
    open_url: Opener,
    url: str,
    version: str,
    installer_name: str,
) -> str:
    request = _asset_request(url, version, "text/plain")
    try:
        with open_url(request, timeout=_TIMEOUT_SECONDS) as response:
            _ensure_allowed_final_url(response)
            raw = response.read(_MAX_CHECKSUM_BYTES + 1)
    except UpdateError:
        raise
    except urllib.error.HTTPError as error:
        error.close()
        raise UpdateError("Could not download the update checksum.") from error
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
        http.client.HTTPException,
    ) as error:
        raise UpdateError("Could not download the update checksum.") from error

    if not isinstance(raw, (bytes, bytearray)):
        raise UpdateError("The update checksum file is unreadable.")
    if len(raw) > _MAX_CHECKSUM_BYTES:
        raise UpdateError("The update checksum file is too large.")
    match = _CHECKSUM_RE.search(bytes(raw).decode("utf-8", "replace"))
    if match is None:
        raise UpdateError("The update checksum file is malformed.")
    text = bytes(raw).decode("utf-8", "replace")
    for line in text.splitlines():
        parsed = re.fullmatch(
            r"([0-9A-Fa-f]{64})[ \t]+\*?(.+?)[ \t]*",
            line.strip(),
        )
        if parsed and Path(parsed.group(2)).name == installer_name:
            return parsed.group(1).lower()
    raise UpdateError("The update checksum does not name the expected installer.")


def _fetch_installer(
    open_url: Opener,
    url: str,
    version: str,
    part_path: Path,
) -> str:
    request = _asset_request(url, version, "application/octet-stream")
    digest = hashlib.sha256()
    total = 0
    try:
        with open_url(request, timeout=_TIMEOUT_SECONDS) as response:
            _ensure_allowed_final_url(response)
            with part_path.open("wb") as handle:
                while True:
                    chunk = response.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray)):
                        raise UpdateError("The update installer response is unreadable.")
                    total += len(chunk)
                    if total > MAX_INSTALLER_BYTES:
                        raise UpdateError("The update installer is larger than 200 MB.")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
    except UpdateError:
        raise
    except urllib.error.HTTPError as error:
        error.close()
        raise UpdateError("Could not download the update installer.") from error
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
        http.client.HTTPException,
    ) as error:
        raise UpdateError("Could not download the update installer.") from error
    return digest.hexdigest()


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


__all__ = [
    "ALLOWED_HOSTS",
    "MAX_INSTALLER_BYTES",
    "RELEASES_API",
    "RELEASES_PAGE",
    "UpdateError",
    "UpdateInfo",
    "check_for_update",
    "download_update",
    "is_newer",
    "parse_version",
]
