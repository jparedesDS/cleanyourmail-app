from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from cleanyourmail_app.server import AppState, create_server
from cleanyourmail_app.settings import Settings

FAKE = """\
import json, sys
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "plan":
    print(json.dumps({"path": "plan.json", "args": sys.argv[2:], "plan": {"stats": {"messages": 2, "actionable": 1}, "actions": [{"type": "move", "category": "newsletter", "mailbox": "INBOX", "uids": [1], "dest": "CleanYourMail/Newsletters"}]}}))
else:
    print(json.dumps({"ok": True, "command": cmd, "args": sys.argv[2:]}))
"""


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.script = root / "mail.py"
        self.script.write_text(FAKE, encoding="utf-8")
        self.config = root / "cleanyourmail.toml"
        self.config.write_text("# test\n", encoding="utf-8")
        settings = Settings(cli_path=str(self.script), config_path=str(self.config))
        self.state = AppState(settings=settings, startup_token="test-token")
        self.state.cli_path = self.script
        self.server = create_server(port=0, state=self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = int(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        request_headers = {"Accept": "application/json"}
        if headers:
            request_headers.update(headers)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=request_headers)
        response = conn.getresponse()
        raw = response.read()
        response_headers = dict(response.getheaders())
        conn.close()
        payload = None
        if raw and "application/json" in response_headers.get("Content-Type", ""):
            payload = json.loads(raw.decode("utf-8"))
        return response.status, response_headers, payload

    def open_session(self):
        status, headers, _ = self.request("GET", "/?token=test-token")
        self.assertEqual(status, 303)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        status, _, payload = self.request("GET", "/api/state", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        return cookie, payload["csrf"]

    def test_one_time_token_and_state(self):
        status, _, _ = self.request("GET", "/")
        self.assertEqual(status, 403)
        cookie, csrf = self.open_session()
        self.assertTrue(cookie.startswith("cym_session="))
        self.assertTrue(csrf)
        # The startup token is consumed.
        status, _, _ = self.request("GET", "/?token=test-token")
        self.assertEqual(status, 403)

    def test_security_headers_and_static_files(self):
        cookie, _ = self.open_session()
        status, headers, _ = self.request("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Cache-Control"], "no-store")
        status, headers, _ = self.request(
            "GET", "/static/styles.css", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers["Content-Type"])
        status, _, _ = self.request(
            "GET", "/static/../server.py", headers={"Cookie": cookie})
        self.assertEqual(status, 404)

    def test_csrf_origin_and_json_validation(self):
        cookie, csrf = self.open_session()
        origin = f"http://127.0.0.1:{self.port}"
        status, _, _ = self.request(
            "POST", "/api/validate", body={}, headers={"Cookie": cookie})
        self.assertEqual(status, 403)
        status, _, _ = self.request(
            "POST", "/api/validate", body={},
            headers={"Cookie": cookie, "X-CSRF-Token": csrf,
                     "Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        status, _, payload = self.request(
            "POST", "/api/validate", body={},
            headers={"Cookie": cookie, "X-CSRF-Token": csrf, "Origin": origin})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["command"], "validate")
        status, _, _ = self.request(
            "POST", "/api/validate", body="not-json",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf, "Origin": origin,
                     "Content-Type": "application/json"})
        self.assertEqual(status, 400)

    def test_plan_apply_and_no_double_apply(self):
        cookie, csrf = self.open_session()
        origin = f"http://127.0.0.1:{self.port}"
        headers = {"Cookie": cookie, "X-CSRF-Token": csrf, "Origin": origin}
        status, _, payload = self.request("POST", "/api/plan", body={"mode": "folders", "categories": ["newsletter", "spam"]}, headers=headers)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("--category", payload["data"]["args"])
        self.assertIn("newsletter", payload["data"]["args"])
        self.assertIn("spam", payload["data"]["args"])
        self.assertEqual(self.state.plan_path, "plan.json")
        status, _, payload = self.request("POST", "/api/plan/review", body={"reviewed": True}, headers=headers)
        self.assertEqual(status, 200)
        self.assertTrue(payload["reviewed"])
        status, _, payload = self.request("POST", "/api/apply", body={"confirm": "APPLY", "limit": 5}, headers=headers)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("--limit", payload["data"]["args"])
        self.assertIn("5", payload["data"]["args"])
        self.assertTrue(self.state.plan_applied)
        status, _, payload = self.request("POST", "/api/apply", body={"confirm": "APPLY"}, headers=headers)
        self.assertEqual(status, 409)
        self.assertIn("already", payload["error"])

    def test_host_header_is_checked(self):
        cookie, _ = self.open_session()
        status, _, _ = self.request(
            "GET", "/api/state", headers={"Cookie": cookie, "Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_lock_invalidates_the_session(self):
        cookie, csrf = self.open_session()
        origin = f"http://127.0.0.1:{self.port}"
        status, _, payload = self.request(
            "POST", "/api/lock", body={},
            headers={"Cookie": cookie, "X-CSRF-Token": csrf, "Origin": origin})
        self.assertEqual(status, 200)
        self.assertTrue(payload["locked"])
        status, _, _ = self.request("GET", "/api/state", headers={"Cookie": cookie})
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
