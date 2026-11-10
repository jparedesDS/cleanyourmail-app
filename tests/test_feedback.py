"""Feedback payload, checklist and the opt-in Worker client.

No test here opens a socket: every HTTP call patches ``urlopen``.
"""

from __future__ import annotations

import json
import urllib.error
from unittest import mock

import pytest

from cleanyourmail_app.domain.feedback import (
    FEEDBACK_ENDPOINT,
    FEEDBACK_KINDS,
    MAX_CHECKLIST,
    MAX_CONTACT,
    MAX_MESSAGE,
    FeedbackPayload,
    build_checklist,
    feedback_payload,
    validate_feedback,
)
from cleanyourmail_app.services.feedback import FeedbackError, send_feedback


def _checklist() -> str:
    return build_checklist(
        app_version="0.4.0",
        sidecar_version="1.2.2",
        provider="Gmail",
        mode="folders",
        categories=("newsletter", "promotion"),
        language="en",
        windows_version="10.0.19045",
    )


def _payload(**overrides) -> FeedbackPayload:
    fields = {
        "kind": "feedback",
        "message": "The review screen could explain what moves.",
        "checklist": "CleanYourMail app 0.4.0",
        "contact": "",
        "app_version": "CleanYourMail app 0.4.0",
    }
    fields.update(overrides)
    return FeedbackPayload(**fields)


def _response(body: bytes = b'{"ok":true}') -> mock.MagicMock:
    response = mock.MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = body
    return response


def _send(payload: FeedbackPayload, *, endpoint: str = "https://feedback.test") -> None:
    send_feedback(payload, endpoint=endpoint)


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://feedback.test",
        code,
        "error",
        hdrs=None,
        fp=None,
    )


def test_constants_match_the_worker_contract():
    assert FEEDBACK_ENDPOINT == "https://cleanyourmail-feedback.subtitleme.workers.dev"
    assert FEEDBACK_KINDS == ("feedback", "bug")
    assert MAX_MESSAGE == 4000
    assert MAX_CHECKLIST == 6000
    assert MAX_CONTACT == 200


def test_payload_as_dict_has_exact_fields_and_an_empty_honeypot():
    payload = _payload(contact="tester", app_version="CleanYourMail app 0.4.0")

    assert payload.as_dict() == {
        "kind": "feedback",
        "message": "The review screen could explain what moves.",
        "checklist": "CleanYourMail app 0.4.0",
        "contact": "tester",
        "app_version": "CleanYourMail app 0.4.0",
        "website": "",
    }


def test_payload_is_frozen():
    with pytest.raises(Exception):
        _payload().kind = "bug"  # type: ignore[misc]


def test_checklist_has_the_allowed_human_readable_lines():
    assert _checklist() == (
        "CleanYourMail app 0.4.0\n"
        "Sidecar: 1.2.2\n"
        "Windows: 10.0.19045\n"
        "Provider: Gmail\n"
        "Mode: folders\n"
        "Categories: newsletter, promotion\n"
        "Language: en"
    )


def test_checklist_deduplicates_categories_and_tolerates_missing_values():
    text = build_checklist(
        app_version="",
        sidecar_version="",
        provider="",
        mode="",
        categories=("newsletter", "newsletter", ""),
        language="",
        windows_version="",
    )

    assert text.splitlines() == [
        "CleanYourMail app (unknown)",
        "Sidecar: (unknown)",
        "Windows: (unknown)",
        "Provider: (unknown)",
        "Mode: (unknown)",
        "Categories: newsletter",
        "Language: (unknown)",
    ]


def test_checklist_never_leaks_account_paths_message_ids_or_tokens(monkeypatch):
    monkeypatch.setenv("CYM_TEST_EMAIL", "me@example.com")
    monkeypatch.setenv("CYM_TEST_PATH", r"C:\Users\xht\AppData\Roaming\cleanyourmail-app")
    monkeypatch.setenv("CYM_TEST_MESSAGE_ID", "<abc@example>")
    monkeypatch.setenv("CYM_TEST_TOKEN", "token-sentinel-9f3c")

    text = _checklist()
    lowered = text.lower()

    assert "me@example.com" not in lowered
    assert "c:" not in lowered
    assert "\\users" not in lowered
    assert "<abc@example>" not in lowered
    assert "token-sentinel-9f3c" not in lowered
    assert "token" not in lowered
    assert "password" not in lowered
    assert "cookie" not in lowered
    # An allowlist: every line is one of the seven reviewed facts.
    prefixes = (
        "CleanYourMail app ",
        "Sidecar: ",
        "Windows: ",
        "Provider: ",
        "Mode: ",
        "Categories: ",
        "Language: ",
    )
    assert len(text.splitlines()) == len(prefixes)
    assert all(line.startswith(prefixes) for line in text.splitlines())


def test_validation_accepts_a_normal_feedback():
    assert (
        validate_feedback(
            kind="feedback",
            message="Please improve the review copy",
            checklist=_checklist(),
            contact="tester#1234",
        )
        is None
    )


def test_validation_accepts_uppercase_kind_and_a_checklist_only():
    assert (
        validate_feedback(
            kind=" BUG ",
            message="",
            checklist="CleanYourMail app 0.4.0",
            contact="",
        )
        is None
    )


def test_validation_rejects_an_unknown_kind():
    assert (
        validate_feedback(kind="profile", message="hello", checklist="", contact="")
        == "feedback.invalid_kind"
    )


def test_validation_requires_a_message_or_a_checklist():
    assert (
        validate_feedback(kind="feedback", message="  ", checklist="\n", contact="")
        == "feedback.empty"
    )


def test_validation_rejects_long_fields():
    common = {"kind": "feedback", "message": "hello", "checklist": "", "contact": ""}

    assert (
        validate_feedback(**{**common, "message": "x" * (MAX_MESSAGE + 1)})
        == "feedback.message_too_long"
    )
    assert (
        validate_feedback(**{**common, "checklist": "x" * (MAX_CHECKLIST + 1)})
        == "feedback.checklist_too_long"
    )
    assert (
        validate_feedback(**{**common, "contact": "x" * (MAX_CONTACT + 1)})
        == "feedback.contact_too_long"
    )


def test_validation_accepts_the_exact_limits():
    assert (
        validate_feedback(
            kind="feedback",
            message="x" * MAX_MESSAGE,
            checklist="x" * MAX_CHECKLIST,
            contact="x" * MAX_CONTACT,
        )
        is None
    )


def test_feedback_payload_trims_every_field_and_lowercases_the_kind():
    payload = feedback_payload(
        kind="  BUG  ",
        message="  A real bug.  ",
        checklist="  CleanYourMail app 0.4.0\n  ",
        contact="  tester  ",
        app_version="  CleanYourMail app 0.4.0  ",
    )

    assert payload == FeedbackPayload(
        kind="bug",
        message="A real bug.",
        checklist="CleanYourMail app 0.4.0",
        contact="tester",
        app_version="CleanYourMail app 0.4.0",
    )


def test_send_posts_the_exact_json_body_and_headers():
    payload = _payload(contact="tester")
    expected = {
        "kind": "feedback",
        "message": "The review screen could explain what moves.",
        "checklist": "CleanYourMail app 0.4.0",
        "contact": "tester",
        "app_version": "CleanYourMail app 0.4.0",
        "website": "",
    }

    with mock.patch(
        "cleanyourmail_app.services.feedback.urllib.request.urlopen",
        return_value=_response(),
    ) as urlopen:
        _send(payload)

    request = urlopen.call_args.args[0]
    assert request.full_url == "https://feedback.test"
    assert request.get_method() == "POST"
    assert request.data == json.dumps(
        expected, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["accept"] == "application/json"
    assert headers["content-type"] == "application/json; charset=utf-8"
    assert headers["user-agent"] == "CleanYourMail-feedback/1"
    assert urlopen.call_args.kwargs["timeout"] == 20


def test_send_uses_a_custom_timeout_and_reads_at_most_4096_bytes():
    response = _response()
    with mock.patch(
        "cleanyourmail_app.services.feedback.urllib.request.urlopen",
        return_value=response,
    ):
        send_feedback(
            _payload(),
            endpoint="https://feedback.test",
            timeout=5,
        )

    response.read.assert_called_once_with(4096)


def test_send_never_prints_or_logs_the_payload(capsys):
    sentinel = "private-sentinel-a7f1"
    with mock.patch(
        "cleanyourmail_app.services.feedback.urllib.request.urlopen",
        return_value=_response(),
    ):
        _send(_payload(message=f"hello {sentinel}"))

    captured = capsys.readouterr()
    assert sentinel not in captured.out
    assert sentinel not in captured.err


def test_send_returns_none_on_ok_true():
    with mock.patch(
        "cleanyourmail_app.services.feedback.urllib.request.urlopen",
        return_value=_response(),
    ):
        assert _send(_payload()) is None


def test_empty_endpoint_is_not_configured():
    with pytest.raises(FeedbackError) as raised:
        _send(_payload(), endpoint="   ")

    assert raised.value.key == "feedback.not_configured"


def test_http_429_is_rate_limited():
    with mock.patch(
        "cleanyourmail_app.services.feedback.urllib.request.urlopen",
        side_effect=_http_error(429),
    ):
        with pytest.raises(FeedbackError) as raised:
            _send(_payload())

    assert raised.value.key == "feedback.rate_limited"


def test_http_503_is_not_configured():
    with mock.patch(
        "cleanyourmail_app.services.feedback.urllib.request.urlopen",
        side_effect=_http_error(503),
    ):
        with pytest.raises(FeedbackError) as raised:
            _send(_payload())

    assert raised.value.key == "feedback.not_configured"


@pytest.mark.parametrize("code", [400, 500])
def test_other_http_errors_fail(code):
    with mock.patch(
        "cleanyourmail_app.services.feedback.urllib.request.urlopen",
        side_effect=_http_error(code),
    ):
        with pytest.raises(FeedbackError) as raised:
            _send(_payload())

    assert raised.value.key == "feedback.failed"


@pytest.mark.parametrize(
    "side_effect",
    [
        urllib.error.URLError("no route"),
        TimeoutError("timed out"),
        OSError("socket closed"),
    ],
)
def test_transport_errors_fail(side_effect):
    with mock.patch(
        "cleanyourmail_app.services.feedback.urllib.request.urlopen",
        side_effect=side_effect,
    ):
        with pytest.raises(FeedbackError) as raised:
            _send(_payload())

    assert raised.value.key == "feedback.failed"


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[]",
        b'"ok"',
        b'{"ok":false}',
        b'{"ok":"true"}',
        b'{"ok":null}',
    ],
)
def test_malformed_or_not_ok_responses_fail(body):
    with mock.patch(
        "cleanyourmail_app.services.feedback.urllib.request.urlopen",
        return_value=_response(body),
    ):
        with pytest.raises(FeedbackError) as raised:
            _send(_payload())

    assert raised.value.key == "feedback.failed"


def test_serialized_body_has_no_secret_sentinel():
    token = "ghp_secret-sentinel-4d2c"
    payload = _payload(message="A normal report", checklist="CleanYourMail app 0.4.0")

    with mock.patch(
        "cleanyourmail_app.services.feedback.urllib.request.urlopen",
        return_value=_response(),
    ) as urlopen:
        _send(payload)

    body = urlopen.call_args.args[0].data.decode("utf-8").lower()
    assert token.lower() not in body
    assert "password" not in body
    assert "token" not in body
    assert "cookie" not in body
    assert "authorization" not in body
