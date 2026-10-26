"""Where keep-cli keeps its settings.

Nothing secret lives here — the master token goes in the OS keyring. This file
only remembers which Google account you're using and the device id that token
is bound to.
"""
from __future__ import annotations

import json
import os
import pathlib

APP = "keep-cli"
SERVICE = "keep-master-token"

CONFIG_DIR = pathlib.Path(os.environ.get("KEEP_CLI_CONFIG_DIR") or
                          pathlib.Path.home() / ".config" / APP)
CACHE_DIR = pathlib.Path(os.environ.get("KEEP_CLI_CACHE_DIR") or
                         pathlib.Path.home() / ".cache" / APP)
CONFIG_FILE = CONFIG_DIR / "config.json"


def load() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=1) + "\n")
    CONFIG_FILE.chmod(0o600)


def account() -> str | None:
    """The Google account in use. KEEP_ACCOUNT overrides the config file."""
    return os.environ.get("KEEP_ACCOUNT") or load().get("account")


def set_account(email: str) -> None:
    data = load()
    data["account"] = email
    save(data)


def device_id(email: str) -> str | None:
    return load().get("devices", {}).get(email)


def set_device_id(email: str, dev: str) -> None:
    data = load()
    data.setdefault("devices", {})[email] = dev
    save(data)


def cache_file(email: str) -> pathlib.Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = email.replace("/", "_").replace(os.sep, "_")
    return CACHE_DIR / f"{safe}.json"
