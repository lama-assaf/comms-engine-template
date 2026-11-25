#!/bin/bash
# The engine's schedules on this Mac, from the `jobs` of engine.json (one
# directory up). No path in the repo names a machine: render.py writes the
# plists for this checkout, this script loads them into launchd for the
# logged-in user. Labels are <brand.label_prefix>.<job name>, derived by
# scripts/config.py and never typed here. engine.py enable/disable call this
# with --only; keep the command lines below as they are.
#
#   engine install --dry-run      render to a temp dir and print, load nothing
#   engine install                 render and (re)load every job except the optional ones
#   engine install --with-optional also the optional jobs (the X stream is billed per matched post)
#   engine install --only <label>  one job, optional or not: --only loads what it names
#   engine install --uninstall     boot out every job of this brand (plists kept)
#   engine install --status        what is loaded and when each job last ran
#
# CLAUDE_CONFIG_DIR: if the shell running this has it set, every job gets it, so
# the headless runs use that login. Unset means the default ~/.claude.
# The Mac must be awake: the nosleep job (caffeinate) is one of the jobs.
set -euo pipefail
# The engine is this file's own place; the instance (whose jobs these are) is
# scripts/paths.py's answer: COMMS_ENGINE_INSTANCE, CLAUDE_PROJECT_DIR, then the
# nearest parent of the working directory holding brand.json.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$(dirname "$HERE")"
REPO="$(python3 "$ENGINE/scripts/paths.py" instance)"
CONFIG="$ENGINE/scripts/config.py"
AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
MODE="${1:---install}"
ONLY=""
[ "${1:-}" = "--only" ] && { MODE="--install"; ONLY="${2:?label}"; }
WITH_OPTIONAL=0
[ "${1:-}" = "--with-optional" ] && { MODE="--install"; WITH_OPTIONAL=1; }

# Labels from engine.json through config.py, so the brand's prefix is read once, there.
optional_labels() { python3 "$CONFIG" labels --optional | tr '\n' ' '; }
all_labels() { python3 "$CONFIG" labels | tr '\n' ' '; }
required_secrets() { python3 -c "import json,sys;print(', '.join(json.load(open(sys.argv[1]))['params']['secrets']['required']))" "$ENGINE/engine.json"; }

case "$MODE" in
  --dry-run)
    OUT="$(mktemp -d)"
    python3 "$HERE/render.py" --out "$OUT" --repo "$REPO" ${CLAUDE_CONFIG_DIR:+--config-dir "$CLAUDE_CONFIG_DIR"} >/dev/null
    echo "rendered to $OUT (nothing loaded):"
    for p in "$OUT"/*.plist; do
      label="$(basename "$p" .plist)"
      loaded="$(launchctl list 2>/dev/null | awk -v l="$label" '$3==l{print "loaded"}')"
      printf '  %-26s %s\n' "$label" "${loaded:-not loaded}"
    done
    [ -x "$HOME/.local/bin/comms-engine" ] || echo "would also need: ~/.local/bin/comms-engine (engine shim --install)"
    echo "would also need: Mac awake ($(python3 "$CONFIG" label nosleep)), keychain items $(required_secrets) (and LINKEDIN_* for the autopilot to post)"
    ;;
  --install)
    # every plist runs the shim; without it launchd would start nothing
    [ -x "$HOME/.local/bin/comms-engine" ] || { echo "no ~/.local/bin/comms-engine: run \`engine shim --install\` first" >&2; exit 1; }
    mkdir -p "$AGENTS" "$(python3 "$CONFIG" log-dir)"
    skip="$(optional_labels)"
    [ "$WITH_OPTIONAL" = 1 ] && skip=""
    for label in $(all_labels); do
      [ -n "$ONLY" ] && [ "$label" != "$ONLY" ] && continue
      # the optional jobs are skipped only by the all-jobs install; --only names one on purpose
      if [ -z "$ONLY" ]; then
        case " $skip " in *" $label "*) echo "skipped   $label (optional; --with-optional)"; continue;; esac
      fi
      python3 "$HERE/render.py" --out "$AGENTS" --repo "$REPO" --only "$label" ${CLAUDE_CONFIG_DIR:+--config-dir "$CLAUDE_CONFIG_DIR"} >/dev/null
      launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
      launchctl bootstrap "$DOMAIN" "$AGENTS/$label.plist"
      echo "loaded    $label"
    done
    echo "check:    $0 --status"
    ;;
  --uninstall)
    for label in $(all_labels); do
      launchctl bootout "$DOMAIN/$label" 2>/dev/null && echo "booted out $label" || echo "not loaded $label"
    done
    ;;
  --status)
    python3 "$ENGINE/scripts/jobs_status.py"
    ;;
  *)
    sed -n '2,15p' "$0"; exit 2 ;;
esac
