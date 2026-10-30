"""Small, local settings store. It never stores secrets."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "cleanyourmail-app"


def app_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / APP_NAME


def default_config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        return base / "cleanyourmail" / "cleanyourmail.toml"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "cleanyourmail" / "cleanyourmail.toml"
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "cleanyourmail" / "cleanyourmail.toml"


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


@dataclass
class Settings:
    cli_path: str = ""
    config_path: str = ""

    def resolved_config_path(self) -> Path:
        if self.config_path.strip():
            return Path(self.config_path).expanduser()
        return default_config_path()


def load_settings() -> Settings:
    path = settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    return Settings(
        cli_path=str(raw.get("cli_path") or ""),
        config_path=str(raw.get("config_path") or ""),
    )


def save_settings(settings: Settings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cli_path": settings.cli_path,
        "config_path": settings.config_path,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
