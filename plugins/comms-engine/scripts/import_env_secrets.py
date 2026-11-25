#!/usr/bin/env python3
"""
import_env_secrets.py - move KEY=VALUE secrets from a file into the keychain.

A one-time step when an earlier setup kept its credentials in a `.env` file.
This reads that file (any KEY=VALUE file), and stores the named keys as
generic passwords under the brand's keychain service (engine.json
brand.keychain_service, read through scripts/secrets.py), with the
`-T /usr/bin/security` ACL that unattended reads need. Values are never
printed. Nothing is deleted from the source file; do that by hand afterwards.

  engine import_env_secrets ~/old-setup/.env --dry-run
  engine import_env_secrets ~/old-setup/.env \
      TWITTERAPI_IO_API_KEY APIFY_TOKEN \
      LINKEDIN_CLIENT_ID LINKEDIN_CLIENT_SECRET LINKEDIN_ORG_ID LINKEDIN_ACCESS_TOKEN \
      LINKEDIN_REFRESH_TOKEN LINKEDIN_TOKEN_EXPIRES_AT LINKEDIN_MEMBER_ID X_CLIENT_ID X_CLIENT_SECRET

With no names, every key in the file is offered. `--stream <slug>` stores
under the stream-scoped account (`<slug>/NAME`), as secrets.py resolves it.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import secrets as sec  # noqa: E402


def read_env(path):
    values = {}
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value:
                values[key.strip()] = value
    return values


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in argv
    stream = None
    if "--stream" in argv:
        stream = argv[argv.index("--stream") + 1]
        args = [a for a in args if a != stream]
    if not args:
        print(__doc__)
        return 2
    values = read_env(args[0])
    names = args[1:] or sorted(values)
    rc = 0
    for name in names:
        if name not in values:
            print(f"{name}: not in {args[0]}, skipped")
            continue
        account = sec.scoped_name(name, stream)
        if dry:
            print(f"{name}: would store as keychain account '{account}' ({len(values[name])} chars)")
            continue
        cmd = ["/usr/bin/security", "add-generic-password", "-s", sec.KEYCHAIN_SERVICE, "-a", account,
               "-T", "/usr/bin/security", "-U", "-w", values[name]]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            print(f"{name}: stored as '{account}'")
        else:
            print(f"{name}: FAILED ({proc.stderr.strip()[:120]})")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
