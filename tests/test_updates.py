"""The GitHub release feed and the verified installer download.

Every test injects a fake opener: the suite never touches the network, never
downloads a real installer and never executes anything.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error

import pytest

from cleanyourmail_app.services import updates
from cleanyourmail_app.services.updates import (
    RELEASES_API,
    UpdateError,
    UpdateInfo,
    check_for_update,
    download_update,
    is_newer,
    parse_version,
)

VERSION = "0.6.0"
CURRENT = "0.5.0"
BASE = "https://github.com/jparedesDS/cleanyourmail-app/releases/download/v0.6.0"
INSTALLER_NAME = f"CleanYourMail-Setup-{VERSION}.exe"
CHECKSUM_NAME = f"{INSTALLER_NAME}.sha256"
INSTALLER_URL = f"{BASE}/{INSTALLER_NAME}"
CHECKSUM_URL = f"{BASE}/{CHECKSUM_NAME}"


class FakeResponse:
    """A context manager that looks enough like ``urlopen()`` for the tests."""

    def __init__(self, payload: bytes | list[object], *, url: str | None = None) -> None:
        self._chunks = list(payload) if isinstance(payload, list) else [payload]
        self._url = url
        self.closed = False
        self.read_sizes: list[int] = []

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self.closed = True
        return False

    def geturl(self) -> str | None:
        return self._url

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if not self._chunks:
            return b""
        item = self._chunks[0]
        if isinstance(item, BaseException):
            self._chunks.pop(0)
            raise item
        if not isinstance(item, bytes):
            raise AssertionError(f"unexpected fake chunk: {item!r}")
        if size is None or size < 0 or len(item) <= size:
            self._chunks.pop(0)
            return item
        self._chunks[0] = item[size:]
        return item[:size]


class FakeOpener:
    """Records every request and returns, or raises, the queued responses."""

    def __init__(self, *responses: object) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[object, float]] = []

    @property
    def request_urls(self) -> list[str]:
        return [request.full_url for request, _timeout in self.calls]

    def __call__(self, request: object, *, timeout: float) -> FakeResponse:
        self.calls.append((request, timeout))
        if not self._responses:
            raise AssertionError("unexpected extra request")
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        assert isinstance(response, FakeResponse)
        return response


def _release(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "tag_name": f"v{VERSION}",
        "body": "Release notes",
        "published_at": "2026-11-11T10:00:00Z",
        "assets": [
            {"name": INSTALLER_NAME, "browser_download_url": INSTALLER_URL},
            {"name": CHECKSUM_NAME, "browser_download_url": CHECKSUM_URL},
        ],
    }
    payload.update(overrides)
    return payload


def _feed(payload: dict[str, object]) -> FakeResponse:
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def _sha_file(payload: bytes, digest: str | None = None) -> FakeResponse:
    value = digest if digest is not None else hashlib.sha256(payload).hexdigest()
    return FakeResponse(f"{value}  {INSTALLER_NAME}\n".encode("ascii"))


def _info(*, installer: str = INSTALLER_URL, checksum: str = CHECKSUM_URL) -> UpdateInfo:
    return UpdateInfo(VERSION, f"v{VERSION}", installer, checksum)


# --- version parsing -------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.6.0", (0, 6, 0)),
        ("v0.6.0", (0, 6, 0)),
        ("V1.2", (1, 2)),
        ("  v2.10.3.1  ", (2, 10, 3, 1)),
    ],
)
def test_parse_version_accepts_tags_and_plain_versions(value, expected):
    assert parse_version(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "v", "  ", "0..1", "0.6.0-beta", "release-0.6.0", "0.6.", ".6", None, 6, ("0", "6")],
)
def test_parse_version_returns_empty_for_malformed_values(value):
    assert parse_version(value) == ()


@pytest.mark.parametrize(
    ("latest", "current"),
    [
        ("0.6.0", "0.5.0"),
        ("v0.6.0", "v0.5.9"),
        ("1.0", "0.99.99"),
        ("0.6.0.1", "0.6.0"),
    ],
)
def test_is_newer_accepts_a_higher_version(latest, current):
    assert is_newer(latest, current) is True


@pytest.mark.parametrize(
    ("latest", "current"),
    [
        ("0.6.0", "0.6.0"),
        ("v0.6", "0.6.0"),
        ("0.6.0", "0.6"),
        ("0.5.9", "0.6.0"),
        ("nightly", "0.5.0"),
        ("0.6.0", "nightly"),
        ("", ""),
    ],
)
def test_is_newer_rejects_equal_older_or_malformed_values(latest, current):
    assert is_newer(latest, current) is False


# --- release feed ----------------------------------------------------------


def test_check_reads_the_release_and_returns_the_asset_urls():
    opener = FakeOpener(_feed(_release()))

    info = check_for_update(CURRENT, opener=opener)

    assert info == UpdateInfo(
        version=VERSION,
        tag=f"v{VERSION}",
        installer_url=INSTALLER_URL,
        checksum_url=CHECKSUM_URL,
        notes="Release notes",
        published_at="2026-11-11T10:00:00Z",
    )
    request, timeout = opener.calls[0]
    assert request.full_url == RELEASES_API
    assert request.get_header("Accept") == "application/vnd.github+json"
    assert request.get_header("User-agent") == f"CleanYourMail/{CURRENT}"
    assert timeout == 10


@pytest.mark.parametrize("tag", ["v0.5.0", "v0.4.9", "v0.5", "V0.5.0.0"])
def test_check_returns_none_when_the_release_is_not_newer(tag):
    opener = FakeOpener(_feed(_release(tag_name=tag)))
    assert check_for_update(CURRENT, opener=opener) is None


@pytest.mark.parametrize("tag", ["nightly", "release-latest", "v"])
def test_check_returns_none_for_a_malformed_tag(tag):
    opener = FakeOpener(_feed(_release(tag_name=tag)))
    assert check_for_update(CURRENT, opener=opener) is None


def test_check_without_the_checksum_asset_falls_back_to_the_release_page():
    payload = _release(
        assets=[{"name": INSTALLER_NAME, "browser_download_url": INSTALLER_URL}]
    )
    info = check_for_update(CURRENT, opener=FakeOpener(_feed(payload)))

    assert info is not None
    assert info.version == VERSION
    assert info.installer_url == ""
    assert info.checksum_url == ""


def test_check_with_a_wrong_installer_name_falls_back_to_the_release_page():
    payload = _release(
        assets=[
            {
                "name": f"CleanYourMail-Setup-{VERSION}-unsigned.exe",
                "browser_download_url": INSTALLER_URL,
            },
            {"name": CHECKSUM_NAME, "browser_download_url": CHECKSUM_URL},
        ]
    )
    info = check_for_update(CURRENT, opener=FakeOpener(_feed(payload)))

    assert info is not None
    assert info.installer_url == ""
    assert info.checksum_url == ""


def test_check_refuses_an_asset_url_from_an_unrecognised_host():
    payload = _release(
        assets=[
            {
                "name": INSTALLER_NAME,
                "browser_download_url": f"https://evil.example/{INSTALLER_NAME}",
            },
            {"name": CHECKSUM_NAME, "browser_download_url": CHECKSUM_URL},
        ]
    )
    info = check_for_update(CURRENT, opener=FakeOpener(_feed(payload)))

    assert info is not None
    assert info.installer_url == ""
    assert info.checksum_url == ""


def test_check_refuses_a_non_https_asset_url():
    payload = _release(
        assets=[
            {"name": INSTALLER_NAME, "browser_download_url": f"http://github.com/{INSTALLER_NAME}"},
            {"name": CHECKSUM_NAME, "browser_download_url": CHECKSUM_URL},
        ]
    )
    info = check_for_update(CURRENT, opener=FakeOpener(_feed(payload)))

    assert info is not None
    assert info.installer_url == ""
    assert info.checksum_url == ""


def test_check_maps_an_http_error_to_update_error():
    error = urllib.error.HTTPError(RELEASES_API, 403, "rate limited", {}, None)
    with pytest.raises(UpdateError):
        check_for_update(CURRENT, opener=FakeOpener(error))


def test_check_maps_a_network_error_to_update_error():
    with pytest.raises(UpdateError):
        check_for_update(CURRENT, opener=FakeOpener(OSError("offline")))


@pytest.mark.parametrize(
    "body",
    [
        b"{not json",
        b"[]",
        b"null",
        b"{}",
        b'{"tag_name": 6}',
        b'{"tag_name": ""}',
    ],
)
def test_check_maps_a_malformed_feed_to_update_error(body):
    with pytest.raises(UpdateError):
        check_for_update(CURRENT, opener=FakeOpener(FakeResponse(body)))


# --- installer download ----------------------------------------------------


def test_download_verifies_the_sha256_and_moves_the_file_into_place(tmp_path):
    payload = b"fake installer bytes"
    opener = FakeOpener(_sha_file(payload), FakeResponse(payload))

    path = download_update(_info(), opener=opener, target_dir=tmp_path)

    assert path == tmp_path / INSTALLER_NAME
    assert path.read_bytes() == payload
    assert not (tmp_path / f"{INSTALLER_NAME}.part").exists()
    assert opener.request_urls == [CHECKSUM_URL, INSTALLER_URL]
    assert [timeout for _request, timeout in opener.calls] == [10, 10]
    installer_request = opener.calls[1][0]
    assert installer_request.get_header("User-agent") == f"CleanYourMail/{VERSION}"


def test_download_uses_the_temp_directory_by_default(tmp_path, monkeypatch):
    payload = b"payload"
    monkeypatch.setattr(updates.tempfile, "gettempdir", lambda: str(tmp_path))

    path = download_update(
        _info(), opener=FakeOpener(_sha_file(payload), FakeResponse(payload))
    )

    assert path == tmp_path / INSTALLER_NAME
    assert path.read_bytes() == payload


def test_download_rejects_a_wrong_hash_and_leaves_no_exe(tmp_path):
    payload = b"tampered bytes"
    opener = FakeOpener(_sha_file(payload, "0" * 64), FakeResponse(payload))

    with pytest.raises(UpdateError):
        download_update(_info(), opener=opener, target_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_download_rejects_a_malformed_checksum_file(tmp_path):
    opener = FakeOpener(FakeResponse(b"not-a-sha256\n"), FakeResponse(b"payload"))

    with pytest.raises(UpdateError):
        download_update(_info(), opener=opener, target_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_download_maps_a_checksum_http_error_to_update_error(tmp_path):
    error = urllib.error.HTTPError(CHECKSUM_URL, 404, "not found", {}, None)
    with pytest.raises(UpdateError):
        download_update(_info(), opener=FakeOpener(error), target_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("installer", "checksum"),
    [
        (f"https://evil.example/{INSTALLER_NAME}", CHECKSUM_URL),
        (f"http://github.com/{INSTALLER_NAME}", CHECKSUM_URL),
        (f"https://github.com.evil.example/{INSTALLER_NAME}", CHECKSUM_URL),
        (f"https://github.com@evil.example/{INSTALLER_NAME}", CHECKSUM_URL),
        (INSTALLER_URL, f"https://evil.example/{CHECKSUM_NAME}"),
        (INSTALLER_URL, f"http://objects.githubusercontent.com/{CHECKSUM_NAME}"),
        (f"{BASE}/Another-Setup-{VERSION}.exe", CHECKSUM_URL),
        (INSTALLER_URL, f"{BASE}/Another-Setup-{VERSION}.exe.sha256"),
    ],
)
def test_download_refuses_an_untrusted_url_or_filename(tmp_path, installer, checksum):
    opener = FakeOpener()

    with pytest.raises(UpdateError):
        download_update(
            _info(installer=installer, checksum=checksum),
            opener=opener,
            target_dir=tmp_path,
        )

    assert opener.calls == []
    assert list(tmp_path.iterdir()) == []


def test_download_refuses_a_release_without_both_assets(tmp_path):
    opener = FakeOpener()

    with pytest.raises(UpdateError):
        download_update(_info(checksum=""), opener=opener, target_dir=tmp_path)

    assert opener.calls == []
    assert list(tmp_path.iterdir()) == []


def test_download_refuses_a_redirect_to_an_untrusted_host(tmp_path):
    payload = b"payload"
    redirect = FakeResponse(payload, url="https://evil.example/installer.exe")
    opener = FakeOpener(_sha_file(payload), redirect)

    with pytest.raises(UpdateError):
        download_update(_info(), opener=opener, target_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_download_cap_is_200_mb():
    assert updates.MAX_INSTALLER_BYTES == 200 * 1024 * 1024


def test_download_refuses_an_oversized_installer(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "MAX_INSTALLER_BYTES", 8)
    payload = b"123456789"
    opener = FakeOpener(_sha_file(payload), FakeResponse(payload))

    with pytest.raises(UpdateError):
        download_update(_info(), opener=opener, target_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_download_cleans_up_after_a_partial_download(tmp_path):
    payload = b"expected"
    partial = FakeResponse([b"half", OSError("connection reset")])
    opener = FakeOpener(_sha_file(payload), partial)

    with pytest.raises(UpdateError):
        download_update(_info(), opener=opener, target_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_download_replaces_an_existing_installer_only_after_verification(tmp_path):
    target = tmp_path / INSTALLER_NAME
    target.write_bytes(b"old installer")
    payload = b"new installer"
    opener = FakeOpener(_sha_file(payload), FakeResponse(payload))

    path = download_update(_info(), opener=opener, target_dir=tmp_path)

    assert path == target
    assert path.read_bytes() == payload
    assert sorted(entry.name for entry in tmp_path.iterdir()) == [INSTALLER_NAME]


def test_download_rejects_a_non_update_info_value(tmp_path):
    with pytest.raises(TypeError):
        download_update("nope", opener=FakeOpener(), target_dir=tmp_path)


def test_download_rejects_an_unsafe_version_token(tmp_path):
    info = UpdateInfo("../0.6.0", "v0.6.0", INSTALLER_URL, CHECKSUM_URL)

    with pytest.raises(UpdateError):
        download_update(info, opener=FakeOpener(), target_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []
