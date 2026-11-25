#!/usr/bin/env python3
"""
secrets.py - the one place a token is resolved.

Nothing in the engine reads a token from a file or from the keychain directly.
Every caller asks `get_secret(name)` and takes what comes back, so a later
sovereign store (PLAN.md Phase 6) is a new branch inside `_backends()` rather
than a second pass over listen.py, sync.py and cycle.sh.

Resolution chain, in order, first hit wins:

  1. the process environment            os.environ[name]
  2. the macOS login keychain           generic password, service
                                        engine.json brand.keychain_service
                                        (`acme-comms` for the shipped brand),
                                        account = the secret's name

The environment comes first so a shell that already exported a value (cycle.sh
does exactly that, and so does a developer testing against a scratch token)
wins over the stored one without touching the keychain.

Seeding an item, once per machine:

    engine secrets --set APIFY_TOKEN

which asks for the value at macOS's own hidden prompt, so it never lands in an
argument list, a shell history or a file. It runs the same thing as

    security add-generic-password -s "$(engine config brand keychain_service)" \\
        -a APIFY_TOKEN -w '<token>' -T /usr/bin/security

`-T /usr/bin/security` is load-bearing. It puts the `security` binary on the
item's ACL, which is what lets the unattended launchd run (the social-engine
job's plist) read the item without macOS raising the
"allow access?" GUI prompt that would otherwise stall the cycle until someone
clicked it. `-U` updates a value but NOT an ACL, so an item that was created
without `-T` has to be deleted and re-added, not updated.

The login keychain must be unlocked for the read to succeed, which it is
whenever the user is logged in - the schedule is a user LaunchAgent, not a
system daemon, so it only ever runs in that state.

Usage as a library:

    import secrets as engine_secrets           # from scripts/
    token = engine_secrets.get_secret("APIFY_TOKEN")

Usage as a command, for shells that need the values exported (cycle.sh, and an
interactive session's shell profile):

    eval "$(engine secrets --export APIFY_TOKEN TWITTERAPI_IO_API_KEY)"

Note on the name: this module shadows the Python standard library's `secrets`
module for any process whose sys.path[0] is this scripts/ directory. Nothing in
the engine or its dependencies imports stdlib `secrets`, and this module
deliberately does not either.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as _config  # noqa: E402

# One keychain service for the whole repository, named by engine.json's brand
# block; the account is the secret's name, so `security find-generic-password
# -s <service> -a APIFY_TOKEN` is readable by a person looking for it in
# Keychain Access. The root stream keeps bare account names; another stream's
# secret is stored as `<slug>/<NAME>` (scoped_name).
KEYCHAIN_SERVICE = _config.brand()["keychain_service"]
ROOT_STREAM = _config.brand()["slug"]

# How long a keychain read may take before we give up. A locked keychain or a
# missing ACL entry surfaces as a GUI prompt, which from a headless launchd run
# never gets answered; the timeout turns that hang into a loud failure instead
# of a cycle that silently sits there until the next one is due.
KEYCHAIN_TIMEOUT = 15


class SecretNotFound(RuntimeError):
    """No backend in the chain could produce the named secret."""


def _from_env(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value else None


def _from_keychain(name: str) -> str | None:
    """Read a generic password from the macOS login keychain.

    Returns None when the item is absent (or when we are not on macOS at all),
    so resolution can fall through to the caller's error; anything else - a
    locked keychain, a denied ACL - is raised, because silently reporting
    "not found" for a permission problem sends whoever is debugging it to the
    wrong place.
    """
    if sys.platform != "darwin":
        return None
    try:
        proc = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s", KEYCHAIN_SERVICE,
                "-a", name,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=KEYCHAIN_TIMEOUT,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        raise SecretNotFound(
            f"{name}: the keychain read timed out after {KEYCHAIN_TIMEOUT}s. "
            "That usually means macOS is waiting on an 'allow access?' prompt "
            "nobody can answer. Re-seed the item with -T /usr/bin/security."
        ) from None

    if proc.returncode == 0:
        # -w prints the password and a trailing newline, nothing else.
        return proc.stdout.rstrip("\n") or None

    err = (proc.stderr or "").strip()
    # errSecItemNotFound - the item simply is not there. Fall through.
    if "could not be found" in err or "SecKeychainSearchCopyNext" in err:
        return None
    raise SecretNotFound(f"{name}: keychain read failed ({proc.returncode}): {err}")


# The chain, in resolution order. A future sovereign store is appended here.
_BACKENDS = (
    ("environment", _from_env),
    ("macOS keychain", _from_keychain),
)


def scoped_name(name: str, stream: str | None) -> str:
    """The name a stream's secret is stored under (plan v2, A13).

    One stream's token can never act for another: a secret asked for with
    `stream="beta"` resolves only `BETA_<NAME>` (environment) or the
    keychain account `beta/<NAME>`, never the bare `<NAME>`. The root stream
    (brand.slug) keeps the bare names, so the brand's own secrets need no scope.
    """
    if not stream or stream.strip().lower() == ROOT_STREAM:
        return name
    return f"{stream.strip().lower()}/{name}"


def get_secret(name: str, required: bool = True, stream: str | None = None) -> str | None:
    """Resolve one secret through the chain: environment, then keychain.

    With `stream`, the stream-scoped name is resolved (`scoped_name`): the
    environment variable is the slug upper-cased and joined with an underscore
    (`BETA_APIFY_TOKEN`), the keychain account is `beta/APIFY_TOKEN`.
    Raises SecretNotFound when nothing in the chain has it and `required` is
    true (the default); returns None when `required` is false.
    """
    scoped = scoped_name(name, stream)
    env_name = scoped.replace("/", "_").upper()
    for label, backend in _BACKENDS:
        value = backend(env_name if label == "environment" else scoped)
        if value:
            return value
    if not required:
        return None
    raise SecretNotFound(
        f"{scoped} not found. Looked in: "
        + ", ".join(label for label, _ in _BACKENDS)
        + f". Seed it with:  security add-generic-password -s {KEYCHAIN_SERVICE} "
        f"-a {scoped} -w '<value>' -T /usr/bin/security"
    )


def set_command(name: str) -> list[str]:
    """The `security` call that stores one secret, prompting for its value.

    `-w` comes last with no argument, which makes `security` ask for the value
    itself (twice, hidden) rather than take it from the command line. `-U`
    replaces the value of an item that already exists, so a bad paste is fixed
    by running it again; it does not touch an existing item's ACL (see above).
    """
    return [
        "/usr/bin/security",
        "add-generic-password",
        "-s", KEYCHAIN_SERVICE,
        "-a", name,
        "-T", "/usr/bin/security",
        "-U",
        "-w",
    ]


def export_lines(names: list[str]) -> str:
    """`export NAME='value'` lines for the named secrets, safe to eval."""
    return "\n".join(
        f"export {n}={shlex.quote(get_secret(n))}" for n in names
    )


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--export":
        names = argv[2:]
        if not names:
            print("usage: secrets.py --export NAME [NAME ...]", file=sys.stderr)
            return 2
        try:
            print(export_lines(names))
        except SecretNotFound as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        return 0

    if len(argv) >= 2 and argv[1] == "--set":
        if len(argv) != 3:
            print("usage: secrets.py --set NAME", file=sys.stderr)
            return 2
        if sys.platform != "darwin":
            print("--set writes the macOS keychain; export NAME in the environment instead.", file=sys.stderr)
            return 2
        name = argv[2]
        print(f"Paste the value for {name} at the prompt (it stays hidden), then press Return.")
        rc = subprocess.run(set_command(name)).returncode
        if rc == 0:
            print(f"{name}: stored in the keychain under service {KEYCHAIN_SERVICE}.")
            return main([argv[0], "--check", name])
        print(f"{name}: not stored (security exited {rc}).", file=sys.stderr)
        return rc

    if len(argv) >= 2 and argv[1] == "--check":
        names = argv[2:] or ["APIFY_TOKEN", "TWITTERAPI_IO_API_KEY"]
        rc = 0
        for n in names:
            # Report which backend answered, and never the value itself: this
            # is run to confirm a seeding, often with someone looking over the
            # shoulder, so it prints a length and nothing more.
            try:
                for label, backend in _BACKENDS:
                    value = backend(n)
                    if value:
                        print(f"{n}: resolved from {label} ({len(value)} chars)")
                        break
                else:
                    print(f"{n}: NOT FOUND", file=sys.stderr)
                    rc = 1
            except SecretNotFound as e:
                print(f"{n}: ERROR {e}", file=sys.stderr)
                rc = 1
        return rc

    print(__doc__.strip().splitlines()[0], file=sys.stderr)
    print("usage: secrets.py --export NAME [NAME ...] | --check [NAME ...] | --set NAME", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
