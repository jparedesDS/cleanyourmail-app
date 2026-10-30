"""Local-only HTTP server for the CleanYourMail desktop UI."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import traceback
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import __version__
from . import cli
from .security import SESSION_COOKIE, Session, SessionStore, new_token
from .settings import Settings, load_settings, save_settings

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = APP_ROOT / "static"
MAX_BODY = 64 * 1024

CSP = (
    "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
    "img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
    "form-action 'none'"
)


@dataclass
class AppState:
    settings: Settings
    sessions: SessionStore = field(default_factory=SessionStore)
    startup_token: str = ""
    startup_token_used: bool = False
    cli_path: Path | None = None
    plan_path: str | None = None
    plan_data: dict[str, Any] | None = None
    plan_reviewed: bool = False
    plan_applied: bool = False


def _state_payload(state: AppState, session: Session) -> dict[str, Any]:
    config_path = state.settings.resolved_config_path()
    return {
        "ok": True,
        "csrf": session.csrf,
        "cli_path": str(state.cli_path) if state.cli_path else "",
        "config_path": str(config_path),
        "config_exists": config_path.is_file(),
        "password_env_set": bool(os.environ.get("CYM_PASSWORD")),
        "plan_ready": bool(state.plan_path),
        "plan_reviewed": state.plan_reviewed,
        "plan_applied": state.plan_applied,
        "app_version": __version__,
    }


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "CleanYourMailApp/" + __version__
    sys_version = ""

    @property
    def state(self) -> AppState:
        return self.server.app_state  # type: ignore[attr-defined]

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def log_message(self, fmt: str, *args: Any) -> None:
        # Never log query strings, cookies or request bodies.
        return

    # -- responses ---------------------------------------------------------

    def _headers(self, content_type: str) -> dict[str, str]:
        return {
            "Content-Type": content_type,
            "Content-Security-Policy": CSP,
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            "Cross-Origin-Opener-Policy": "same-origin",
        }

    def _send(self, status: int, body: bytes, content_type: str,
              extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        headers = self._headers(content_type)
        if extra:
            headers.update(extra)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any],
              extra: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"ok": False, "error": message})

    def _text(self, status: int, message: str) -> None:
        self._send(status, message.encode("utf-8"), "text/plain; charset=utf-8")

    def _redirect(self, location: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(303)
        headers = self._headers("text/plain; charset=utf-8")
        headers["Location"] = location
        if extra:
            headers.update(extra)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -- session -----------------------------------------------------------

    def _cookie_session_id(self) -> str:
        raw = self.headers.get("Cookie", "")
        if not raw:
            return ""
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:
            return ""
        morsel = jar.get(SESSION_COOKIE)
        return morsel.value if morsel else ""

    def _session(self) -> Session | None:
        return self.state.sessions.get(self._cookie_session_id())

    def _set_session_cookie(self, session: Session) -> dict[str, str]:
        return {
            "Set-Cookie": (
                f"{SESSION_COOKIE}={session.session_id}; Path=/; HttpOnly; "
                "SameSite=Strict; Max-Age=28800"
            )
        }

    def _clear_session_cookie(self) -> dict[str, str]:
        return {
            "Set-Cookie": (
                f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
            )
        }

    def _require_session(self) -> Session | None:
        session = self._session()
        if session is None:
            self._error(401, "Session expired. Restart the app.")
        return session

    def _origins(self) -> set[str]:
        return {
            f"http://127.0.0.1:{self.port}",
            f"http://localhost:{self.port}",
        }

    def _require_csrf(self, session: Session) -> bool:
        origin = self.headers.get("Origin", "")
        if origin not in self._origins():
            self._error(403, "Origin not allowed.")
            return False
        token = self.headers.get("X-CSRF-Token", "")
        if not token or not self.state.sessions.token_matches(session.csrf, token):
            self._error(403, "Invalid CSRF token.")
            return False
        return True

    def _require_host(self) -> bool:
        host = self.headers.get("Host", "").lower()
        allowed = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        if host not in allowed:
            self._error(403, "Host not allowed.")
            return False
        return True

    # -- static ------------------------------------------------------------

    def _serve_index(self) -> None:
        path = STATIC_DIR / "index.html"
        if not path.is_file():
            self._error(500, "UI files are missing.")
            return
        self._send(200, path.read_bytes(), "text/html; charset=utf-8")

    def _serve_static(self, raw_path: str) -> None:
        relative = urllib.parse.unquote(raw_path[len("/static/"):])
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            self._error(404, "Not found.")
            return
        target = (STATIC_DIR / relative).resolve()
        try:
            target.relative_to(STATIC_DIR)
        except ValueError:
            self._error(404, "Not found.")
            return
        if not target.is_file():
            self._error(404, "Not found.")
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), content_type)

    # -- request body ------------------------------------------------------

    def _read_json(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            raise ValueError("Expected application/json.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid Content-Length.") from error
        if length <= 0 or length > MAX_BODY:
            raise ValueError("Invalid request size.")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("Invalid JSON.") from error
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object.")
        return payload

    # -- CLI ---------------------------------------------------------------

    def _run(self, command: list[str], body: dict[str, Any], timeout: int = 120,
             require_config: bool = True) -> dict[str, Any]:
        if self.state.cli_path is None:
            raise cli.CliError(
                "CleanYourMail CLI not found. Set the path to cleanyourmail/tools/mail.py."
            )
        password = body.get("password")
        if password is not None and not isinstance(password, str):
            raise ValueError("password must be a string.")
        return cli.run(
            command,
            cli_path=self.state.cli_path,
            config_path=self.state.settings.resolved_config_path(),
            password=password or None,
            timeout=timeout,
            require_config=require_config,
        )

    def _result_payload(self, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": result["ok"],
            "exit_code": result["exit_code"],
            "data": result["data"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
        }

    # -- GET ---------------------------------------------------------------

    def do_GET(self) -> None:
        if not self._require_host():
            return
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path == "/":
            session = self._session()
            if session is not None:
                self._serve_index()
                return
            token = urllib.parse.parse_qs(parsed.query).get("token", [""])[0]
            if (not self.state.startup_token_used
                    and token
                    and self.state.sessions.token_matches(self.state.startup_token, token)):
                self.state.startup_token_used = True
                session = self.state.sessions.create()
                self._redirect("/", self._set_session_cookie(session))
                return
            self._text(403, "Open the URL printed by the app (it contains a one-time token).")
            return
        if path.startswith("/static/"):
            if self._require_session() is None:
                return
            self._serve_static(path)
            return
        if path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return
        if path == "/api/state":
            session = self._require_session()
            if session is None:
                return
            self._json(200, _state_payload(self.state, session))
            return
        self._error(404, "Not found.")

    # -- POST --------------------------------------------------------------

    def do_POST(self) -> None:
        if not self._require_host():
            return
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        session = self._require_session()
        if session is None:
            return
        if not self._require_csrf(session):
            return
        try:
            body = self._read_json()
        except ValueError as error:
            self._error(400, str(error))
            return
        try:
            self._route_post(path, body, session)
        except cli.CliError as error:
            self._error(400, str(error))
        except ValueError as error:
            self._error(400, str(error))
        except Exception:
            traceback.print_exc(file=sys.stderr)
            self._error(500, "The app could not complete that action.")

    def _route_post(self, path: str, body: dict[str, Any], session: Session) -> None:
        if path == "/api/settings":
            self._save_settings(body, session)
        elif path == "/api/init":
            self._init_config(body)
        elif path == "/api/validate":
            self._json(200, self._result_payload(self._run(["validate"], body, 60)))
        elif path == "/api/doctor":
            self._json(200, self._result_payload(self._run(["doctor"], body, 90)))
        elif path == "/api/scan":
            days = self._int(body, "days", 1, 3650, 365)
            self._json(200, self._result_payload(
                self._run(["scan", "--days", str(days)], body, 900)
            ))
        elif path == "/api/report":
            top = self._int(body, "top", 1, 200, 30)
            self._json(200, self._result_payload(
                self._run(["report", "--top", str(top)], body, 120)
            ))
        elif path == "/api/plan":
            mode = body.get("mode", "folders")
            if mode not in {"folders", "archive"}:
                raise ValueError("mode must be folders or archive.")
            categories = body.get("categories", [])
            if not isinstance(categories, list):
                raise ValueError("categories must be a list.")
            allowed = {"newsletter", "promotion", "social", "notification", "cold", "spam"}
            unknown = set(categories) - allowed
            if unknown:
                raise ValueError(f"Unknown categories: {', '.join(sorted(unknown))}.")
            command = ["plan", "--mode", mode]
            for category in categories:
                command.extend(["--category", str(category)])
            result = self._run(command, body, 120)
            payload = self._result_payload(result)
            data = result.get("data") or {}
            if result["ok"] and isinstance(data, dict) and data.get("path"):
                self.state.plan_path = str(data["path"])
                self.state.plan_data = data.get("plan") if isinstance(data.get("plan"), dict) else None
                self.state.plan_reviewed = False
                self.state.plan_applied = False
            self._json(200, payload)
        elif path == "/api/plan/review":
            if not self.state.plan_path:
                raise ValueError("Build a plan first.")
            if self.state.plan_applied:
                self._error(409, "This plan has already been applied. Build a new plan.")
                return
            reviewed = body.get("reviewed")
            if not isinstance(reviewed, bool):
                raise ValueError("reviewed must be true or false.")
            self.state.plan_reviewed = reviewed
            self._json(200, {"ok": True, "reviewed": reviewed})
        elif path == "/api/apply":
            self._apply(body)
        elif path == "/api/unsubscribe":
            self._unsubscribe(body)
        elif path == "/api/journal":
            self._json(200, self._result_payload(self._run(["journal"], body, 60)))
        elif path == "/api/undo":
            self._undo(body)
        elif path == "/api/lock":
            self.state.sessions.destroy(session.session_id)
            self._json(200, {"ok": True, "locked": True}, self._clear_session_cookie())
        else:
            self._error(404, "Not found.")

    # -- route helpers -----------------------------------------------------

    def _int(self, body: dict[str, Any], name: str, low: int, high: int, default: int) -> int:
        raw = body.get(name, default)
        try:
            value = int(raw)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} must be a number.") from error
        if value < low or value > high:
            raise ValueError(f"{name} must be between {low} and {high}.")
        return value

    def _save_settings(self, body: dict[str, Any], session: Session) -> None:
        cli_path = body.get("cli_path", "")
        config_path = body.get("config_path", "")
        if not isinstance(cli_path, str) or not isinstance(config_path, str):
            raise ValueError("Paths must be strings.")
        if cli_path.strip():
            found = cli.find_cli(cli_path.strip(), APP_ROOT)
            if found is None:
                raise ValueError("tools/mail.py was not found at that path.")
        else:
            found = cli.find_cli(None, APP_ROOT)
        settings = Settings(cli_path=cli_path.strip(), config_path=config_path.strip())
        save_settings(settings)
        self.state.settings = settings
        self.state.cli_path = found
        self._json(200, _state_payload(self.state, session))

    def _init_config(self, body: dict[str, Any]) -> None:
        email = body.get("email", "")
        if not isinstance(email, str) or "@" not in email or len(email) > 320:
            raise ValueError("Enter a valid email address.")
        config_path = self.state.settings.resolved_config_path()
        if config_path.exists() and not body.get("force"):
            self._error(409, f"{config_path} already exists. Use force to overwrite.")
            return
        config_path.parent.mkdir(parents=True, exist_ok=True)
        result = self._run(
            ["init", "--email", email, "--path", str(config_path)],
            body,
            60,
            require_config=False,
        )
        if result["ok"]:
            settings = Settings(cli_path=self.state.settings.cli_path,
                                config_path=str(config_path))
            save_settings(settings)
            self.state.settings = settings
        self._json(200, self._result_payload(result))

    def _apply(self, body: dict[str, Any]) -> None:
        if not self.state.plan_path:
            raise ValueError("Build a plan first.")
        if self.state.plan_applied:
            self._error(409, "This plan has already been applied. Build a new plan.")
            return
        if not self.state.plan_reviewed:
            self._error(409, "Review the plan before applying it.")
            return
        if body.get("confirm") != "APPLY":
            raise ValueError('confirm must be "APPLY".')
        limit = self._int(body, "limit", 1, 10000, 50)
        result = self._run(
            ["apply", self.state.plan_path, "--yes", "--action", "move",
             "--limit", str(limit)],
            body,
            900,
        )
        if result["ok"]:
            self.state.plan_reviewed = False
            self.state.plan_applied = True
        self._json(200, self._result_payload(result))

    def _unsubscribe(self, body: dict[str, Any]) -> None:
        if not self.state.plan_path:
            raise ValueError("Build a plan first.")
        if body.get("confirm") != "UNSUBSCRIBE":
            raise ValueError('confirm must be "UNSUBSCRIBE".')
        limit = self._int(body, "limit", 1, 50, 10)
        result = self._run(
            ["unsubscribe", self.state.plan_path, "--yes", "--limit", str(limit)],
            body,
            900,
        )
        self._json(200, self._result_payload(result))

    def _undo(self, body: dict[str, Any]) -> None:
        if body.get("confirm") != "UNDO":
            raise ValueError('confirm must be "UNDO".')
        run = body.get("run", "last")
        if not isinstance(run, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run):
            raise ValueError("Invalid run id.")
        result = self._run(["undo", "--run", run, "--yes"], body, 900)
        self._json(200, self._result_payload(result))


def create_server(host: str = "127.0.0.1", port: int = 0,
                  state: AppState | None = None) -> AppServer:
    state = state or AppState(settings=load_settings())
    server = AppServer((host, port), Handler)
    server.app_state = state  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local CleanYourMail app")
    parser.add_argument("--port", type=int, default=0,
                        help="Local port (default: random)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Do not open the browser")
    parser.add_argument("--cli", default=None,
                        help="Path to cleanyourmail/tools/mail.py")
    parser.add_argument("--config", default=None,
                        help="Path to cleanyourmail.toml")
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.cli:
        settings.cli_path = args.cli
    if args.config:
        settings.config_path = args.config
    if args.cli or args.config:
        save_settings(settings)

    state = AppState(settings=settings)
    state.cli_path = cli.find_cli(settings.cli_path or None, APP_ROOT)
    state.startup_token = new_token()
    server = create_server(port=args.port, state=state)
    port = int(server.server_address[1])
    url = f"http://127.0.0.1:{port}/?token={state.startup_token}"

    print(f"CleanYourMail app {__version__}", flush=True)
    print(f"Local URL: {url}", flush=True)
    if state.cli_path:
        print(f"CLI: {state.cli_path}", flush=True)
    else:
        print("CLI not found yet; set the path in the app.", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
