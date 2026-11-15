"""Interactive Soorin QA login without stdout token capture or shell history secrets.

Run in a real terminal: python3 -m soorin.ops.qa_login
The token is saved to a mode-0600 local file, never echoed to stdout.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys
from urllib import error, request

DEFAULT_BASE = "http://127.0.0.1:2526"
DEFAULT_STATE = Path.home() / ".local/state/soorin-tkg-v1-qa/session.json"


def authenticate(base: str, email: str, password: str) -> tuple[str, dict]:
    if base != DEFAULT_BASE:
        raise ValueError("QA login is restricted to the loopback Soorin test API")
    payload = json.dumps({"email": email, "password": password}).encode()
    req = request.Request(base + "/api/v1/auth/login", data=payload,
                          method="POST", headers={"Content-Type": "application/json"})
    with request.build_opener(request.HTTPRedirectHandler()).open(req, timeout=20) as response:
        parsed = json.load(response)
    token = parsed.get("token")
    if not isinstance(token, str) or not token:
        raise ValueError("login response did not include a session token")
    return token, parsed.get("user") or {}


def save_token(path: Path, token: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    # Atomic replacement; token is never put on a command line or in stdout.
    import tempfile
    import contextlib
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=path.parent, prefix=".session-",
                                         delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            json.dump({"base_url": DEFAULT_BASE, "token": token}, handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()


def load_token(path: Path = DEFAULT_STATE) -> str:
    if path.is_symlink():
        raise ValueError("session file must not be a symlink")
    stat = path.stat()
    if stat.st_mode & 0o077:
        raise ValueError("session file must be readable only by its owner")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("base_url") != DEFAULT_BASE or not isinstance(data.get("token"), str):
        raise ValueError("invalid QA session file")
    return data["token"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--session-file", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args(argv)
    if args.base_url != DEFAULT_BASE:
        parser.error("only the local 127.0.0.1:2526 QA endpoint is supported")
    if not sys.stdin.isatty():
        parser.error("run directly from an interactive terminal (not inside $(), a pipe or heredoc)")
    try:
        email = input("Soorin account email: ").strip()
        if not email:
            parser.error("email cannot be empty")
        password = getpass.getpass("Soorin password: ")
        token, user = authenticate(args.base_url, email, password)
        save_token(args.session_file, token)
    except error.HTTPError as exc:
        print(f"Login rejected (HTTP {exc.code}). Check account credentials.", file=sys.stderr)
        return 1
    except (error.URLError, TimeoutError, ValueError, OSError) as exc:
        print(f"Login failed ({type(exc).__name__}); token not saved.", file=sys.stderr)
        return 1
    print(f"QA login successful; user={user.get('email', '<redacted>')}")
    print(f"Session saved securely to {args.session_file}; token not displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
