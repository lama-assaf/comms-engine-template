#!/bin/bash
# Optional: reports what this machine still lacks to run the engine. Nothing is
# linked or copied: the engine's agents, skills, commands and hooks load from the
# comms-engine plugin, which the instance's .claude/settings.json enables.
#
#   install.sh --check   (the default) the plugins, secrets, tools and schedules
set -euo pipefail
ENGINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(python3 "$ENGINE/scripts/paths.py" instance)"
MODE="${1:---check}"

check() {
  echo "== plugins (enabled in .claude/settings.json; installed per machine)"
  if command -v claude >/dev/null 2>&1; then
    # engine.py plugins asks `claude plugin list --json` whether each name in engine.json
    # plugins.names loads in this checkout; a name in the plain listing can be a plugin that
    # failed to load, or one installed for another checkout. The marketplace it prints is
    # engine.json plugins.marketplace (`claude plugin marketplace add <that url>` comes first).
    python3 "$ENGINE/scripts/engine.py" plugins 2>&1 | sed 's/^/  /' || true
  else
    echo "  MISSING  claude (install Claude Code first)"
  fi
  echo "== secrets (keychain service $(python3 "$ENGINE/scripts/config.py" brand keychain_service))"
  python3 "$ENGINE/scripts/secrets.py" --check TWITTERAPI_IO_API_KEY APIFY_TOKEN 2>&1 | sed 's/^/  /' || true
  echo "== tools"
  for bin in python3 node npx pdftoppm; do
    command -v "$bin" >/dev/null 2>&1 && echo "  ok       $bin" || echo "  MISSING  $bin"
  done
  python3 - <<'PY'
import importlib.util as u
for mod in ("requests", "yaml", "pdfplumber", "pptx"):
    print(f"  {'ok      ' if u.find_spec(mod) else 'MISSING '} python: {mod}")
PY
  echo "== schedules"
  launchctl list 2>/dev/null | grep -F "$(python3 "$ENGINE/scripts/config.py" brand label_prefix)." | awk '{print "  loaded   " $3}' || true
  echo "  (install with: engine install)"
}

case "$MODE" in
  --check) check ;;
  *) echo "usage: $0 [--check]"; exit 2 ;;
esac
