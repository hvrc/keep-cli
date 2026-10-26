"""Connecting to Keep, plus the handful of Keep behaviours worth knowing about."""
from __future__ import annotations

import json
import sys

import gkeepapi
from gkeepapi.node import ColorValue

from . import auth, config

# Keep's colour picker, left to right, skipping the default white swatch.
PALETTE = {
    1: ColorValue.Red,      2: ColorValue.Orange, 3: ColorValue.Yellow,
    4: ColorValue.Green,    5: ColorValue.Teal,   6: ColorValue.Blue,
    7: ColorValue.DarkBlue, 8: ColorValue.Purple, 9: ColorValue.Pink,
    10: ColorValue.Brown,   11: ColorValue.Gray,
}
COLOR_NAMES = {n: c.name for n, c in PALETTE.items()}

NOT_LOGGED_IN = """\
Not signed in to Google Keep.

    keep login

walks you through it (it takes a couple of minutes and needs Chrome).
"""


def resolve_account(explicit: str | None = None) -> str:
    email = explicit or config.account()
    if not email:
        raise SystemExit(
            "No account configured.\n\n"
            "    keep login --account you@gmail.com\n\n"
            "or set KEEP_ACCOUNT in your environment."
        )
    return email


def connect(account: str | None = None, fresh: bool = False) -> gkeepapi.Keep:
    """Authenticate and return a synced Keep client.

    Uses a local cache of Keep's state so repeat commands are fast; pass
    fresh=True to ignore it and re-read everything from the server.
    """
    email = resolve_account(account)
    token = auth.get_token(email)
    if not token:
        raise SystemExit(NOT_LOGGED_IN)

    state = None
    cache = config.cache_file(email)
    if cache.exists() and not fresh:
        try:
            state = json.loads(cache.read_text())
        except json.JSONDecodeError:
            state = None

    keep = gkeepapi.Keep()
    try:
        keep.authenticate(email, token, state=state,
                          device_id=config.device_id(email))
    except Exception as exc:
        raise SystemExit(
            f"Could not sign in to Keep ({type(exc).__name__}: {exc}).\n\n"
            "The stored token has probably been revoked — that happens if you\n"
            "changed your Google password or signed the device out. Run:\n\n"
            "    keep login\n"
        )
    return keep


def save_cache(keep: gkeepapi.Keep, account: str | None = None) -> None:
    email = resolve_account(account)
    try:
        config.cache_file(email).write_text(json.dumps(keep.dump()))
    except Exception:
        pass  # a broken cache is never worth failing a command over


def live_notes(keep: gkeepapi.Keep):
    return [n for n in keep.all() if not n.trashed]


def label_names(note) -> list[str]:
    return [l.name for l in note.labels.all()]


def by_label(keep: gkeepapi.Keep, name: str):
    lbl = keep.findLabel(name)
    if lbl is None:
        raise SystemExit(f"No label called {name!r}. Try:  keep labels")
    return [n for n in live_notes(keep) if lbl in n.labels.all()]


def get_or_make_label(keep: gkeepapi.Keep, name: str):
    return keep.findLabel(name) or keep.createLabel(name)


def display_order(notes):
    """Keep shows notes by its `sort` field, highest first.

    Not by date. Keep gives every new note a RANDOM sort value, which is why
    notes created in a deliberate order still appear shuffled. `keep reorder`
    rewrites these into a sequence.
    """
    return sorted(notes, key=lambda n: int(n.sort), reverse=True)


def next_sort(keep: gkeepapi.Keep, step: int = 1000) -> int:
    vals = [int(n.sort) for n in keep.all() if not n.trashed]
    return (max(vals) + step) if vals else 1_000_000
