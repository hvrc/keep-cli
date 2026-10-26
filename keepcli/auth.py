"""Signing in to Google Keep, and deciding where the token lives.

Google publishes no API for consumer Keep accounts. The only route is the one
Android devices use: hand Google a short-lived browser cookie, get back a
long-lived "master token".

That master token is **full access to the Google account** — not scoped to
Keep. There is no narrower credential on offer. Treat it like a password.

Where it gets stored is pluggable, because different environments want
different answers:

    env      KEEP_MASTER_TOKEN=...     nothing on disk at all.
                                       Best for agents, containers and CI.
    file     ~/.config/keep-cli/...    a 0600 file. Works on every OS,
                                       no platform services involved.
    keyring  OS credential store       macOS Keychain, Windows Credential
                                       Locker, Linux SecretService. Most
                                       secure on a personal machine.

Reads try env, then file, then keyring. Writes go wherever you ask, and
default to keyring when it is available, otherwise file.

The token is never written inside a git repository — see _refuse_in_repo.
"""
from __future__ import annotations

import getpass
import os
import pathlib
import subprocess
import sys
import uuid

from . import config

BACKENDS = ("env", "file", "keyring")

LOGIN_HELP = """\
Signing in to Google Keep as {email}
----------------------------------------------------------------------
1.  Open this page in Chrome:

        https://accounts.google.com/EmbeddedSetup

    Use an INCOGNITO window signed in only as this account. If several
    Google accounts share one Chrome profile this flow usually fails —
    that is the single most common cause of trouble.

2.  Sign in, then click "I agree".

    The page will then sit on a loading spinner forever. THAT IS NORMAL.
    It is waiting to talk to an Android device that does not exist.
    Ignore it and go to step 3; the cookie you need is already set.

3.  Find the cookie in DevTools:

        DevTools (Cmd+Option+I / F12)
          -> Application tab
          -> Storage -> Cookies -> https://accounts.google.com
          -> click the row named  oauth_token

    Copy the value from the "Cookie Value" pane at the BOTTOM of the
    panel, not from the table cell — the cell truncates long values
    without saying so. The value starts with  oauth2_4/

4.  Paste it at the prompt below. Input stays hidden.

What will trip you up:

  * The cookie is SINGLE USE. If this fails the value is spent: delete
    the oauth_token cookie, reload the page, copy a fresh one.
  * It expires within minutes, so paste it straight after copying.
  * A fresh cookie sometimes fails the first time with BadAuthentication
    for no visible reason. Try one more before assuming it is broken.
----------------------------------------------------------------------
"""


# --- helpers -------------------------------------------------------------

def _keyring():
    try:
        import keyring
        return keyring
    except ImportError:
        return None


def token_file(email: str) -> pathlib.Path:
    override = os.environ.get("KEEP_TOKEN_FILE")
    if override:
        return pathlib.Path(override).expanduser()
    safe = email.replace("/", "_").replace(os.sep, "_")
    return config.CONFIG_DIR / f"token-{safe}"


def _refuse_in_repo(path: pathlib.Path) -> None:
    """Never let a full-account credential land inside a git repo."""
    p = path.resolve()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            raise SystemExit(
                f"Refusing to write the master token to {p}\n"
                f"because {parent} is a git repository.\n\n"
                "This token is full access to the Google account. Committing or\n"
                "sharing it would hand over the whole account. Use the default\n"
                "location (outside the repo), or set KEEP_MASTER_TOKEN instead."
            )


def default_backend() -> str:
    return "keyring" if _keyring() is not None else "file"


# --- read / write / delete ----------------------------------------------

def get_token(email: str) -> str | None:
    env = os.environ.get("KEEP_MASTER_TOKEN")
    if env:
        return env.strip()

    path = token_file(email)
    if path.exists():
        got = path.read_text().strip()
        if got:
            return got

    kr = _keyring()
    if kr is not None:
        try:
            got = kr.get_password(config.SERVICE, email)
            if got:
                return got
        except Exception:
            pass

    if sys.platform == "darwin":  # direct Keychain fallback
        r = subprocess.run(["security", "find-generic-password",
                            "-s", config.SERVICE, "-a", email, "-w"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None


def token_source(email: str) -> str:
    """Where the token currently in use is coming from (for `keep status`)."""
    if os.environ.get("KEEP_MASTER_TOKEN"):
        return "environment (KEEP_MASTER_TOKEN)"
    if token_file(email).exists():
        return f"file ({token_file(email)})"
    kr = _keyring()
    if kr is not None:
        try:
            if kr.get_password(config.SERVICE, email):
                return f"OS keyring ({kr.get_keyring().__class__.__name__})"
        except Exception:
            pass
    if sys.platform == "darwin":
        r = subprocess.run(["security", "find-generic-password",
                            "-s", config.SERVICE, "-a", email, "-w"],
                           capture_output=True)
        if r.returncode == 0:
            return "macOS Keychain"
    return "nowhere - not signed in"


def set_token(email: str, token: str, backend: str | None = None) -> str:
    backend = backend or default_backend()
    if backend == "env":
        raise SystemExit(
            "Nothing to store: the 'env' backend means you supply the token\n"
            "yourself at run time. Export it like this:\n\n"
            f"    export KEEP_MASTER_TOKEN='...'\n\n"
            "Use 'keep login --store file' or '--store keyring' to save one."
        )
    if backend == "keyring":
        kr = _keyring()
        if kr is None:
            raise SystemExit("keyring is not installed - try: pip install keyring\n"
                             "or use:  keep login --store file")
        kr.set_password(config.SERVICE, email, token)
        return "OS keyring"
    if backend == "file":
        path = token_file(email)
        _refuse_in_repo(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token + "\n")
        path.chmod(0o600)
        return f"file {path}"
    raise SystemExit(f"unknown backend {backend!r} - choose from {', '.join(BACKENDS)}")


def delete_token(email: str) -> list[str]:
    removed = []
    path = token_file(email)
    if path.exists():
        path.unlink()
        removed.append(str(path))
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(config.SERVICE, email)
            removed.append("OS keyring")
        except Exception:
            pass
    if sys.platform == "darwin":
        r = subprocess.run(["security", "delete-generic-password",
                            "-s", config.SERVICE, "-a", email],
                           capture_output=True)
        if r.returncode == 0 and "OS keyring" not in removed:
            removed.append("macOS Keychain")
    return removed


# --- the login flow ------------------------------------------------------

def login(email: str, oauth_token: str | None = None,
          backend: str | None = None, show_token: bool = False) -> None:
    import gpsoauth

    if oauth_token is None:
        print(LOGIN_HELP.format(email=email))
        oauth_token = (getpass.getpass("paste oauth_token (hidden): ").strip()
                       if sys.stdin.isatty() else sys.stdin.readline().strip())

    if not oauth_token:
        raise SystemExit("nothing pasted - run 'keep login' again")
    if not oauth_token.startswith("oauth2_4/"):
        raise SystemExit(
            "That does not look like an oauth_token: it must start with 'oauth2_4/'.\n"
            "You may have copied the wrong cookie, or copied from the truncated\n"
            "table cell instead of the Cookie Value pane at the bottom."
        )

    dev = uuid.uuid4().hex[:16]
    res = gpsoauth.exchange_token(email, oauth_token, dev)
    token = res.get("Token")
    if not token:
        raise SystemExit(
            f"Google rejected the exchange: {res.get('Error', res)}\n\n"
            "Almost always a spent or expired cookie. Get a fresh one:\n"
            "  delete the oauth_token cookie in DevTools, reload EmbeddedSetup,\n"
            "  copy the new value, then run 'keep login' again straight away."
        )

    where = set_token(email, token, backend)
    config.set_account(email)
    config.set_device_id(email, dev)
    cache = config.cache_file(email)
    if cache.exists():
        cache.unlink()

    print(f"\nSigned in as {email}. Token stored in: {where}")
    if show_token:
        print("\n--- master token (treat as a password) ---")
        print(token)
        print("--- bind it to this device id ---")
        print(dev)
        print("\nOn another machine:")
        print("    export KEEP_MASTER_TOKEN='<the token above>'")
        print(f"    export KEEP_ACCOUNT='{email}'")
        print(f"    keep device-id {dev}")
    else:
        print("The token was not printed. Use --show-token if you need to copy it elsewhere.")
    print("\nCheck it works with:  keep status")
