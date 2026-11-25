#!/bin/zsh
# One scheduled turn of the loop. Called by launchd (schedule/*.plist) or by hand.
#
#   engine cycle                  # the weekday chain
#   engine cycle --no-listen
#   engine cycle --only engage    # the engagement chain
#
# Code runs the cycle: scripts/workflow.py runs the chain named in engine.json
# (params.chains.weekday), one workflow after another, each model step its own
# headless Claude Code call with its own budget and tool list, each run leaving a
# record under state/runs/<workflow>/. A failure reads "gate failed", not an exit
# code. Plain `claude` from PATH: no wrapper, no CLAUDE_CONFIG_DIR unless the
# plist sets one. Nothing is published to the site or a handle from here: a send
# is channels.send()'s alone, and the PreToolUse hook refuses a raw one.
set -euo pipefail
# The engine and the instance. By hand, this file's own location says where the
# engine is; under the launchd launcher (schedule/runjob.py) the text arrives
# through `zsh -c`, so $0 is not a file and the launcher names the engine in
# COMMS_ENGINE_HOME. The instance (brand.json, memory, Content/, state/) is
# scripts/paths.py's answer: COMMS_ENGINE_INSTANCE, then CLAUDE_PROJECT_DIR, then
# the nearest parent of the working directory holding brand.json.
ENGINE="${COMMS_ENGINE_HOME:-}"
[ -n "$ENGINE" ] && [ -f "$ENGINE/scripts/paths.py" ] || ENGINE="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)" || ENGINE=""
[ -f "$ENGINE/scripts/paths.py" ] || { echo "cycle.sh: the engine is not found; set COMMS_ENGINE_HOME" >&2; exit 2; }
REPO="$(python3 "$ENGINE/scripts/paths.py" instance)"
STATE="$(python3 "$ENGINE/scripts/paths.py" state)"
export COMMS_ENGINE_INSTANCE="$REPO" COMMS_ENGINE_HOME="$ENGINE"
# The prefix: config.py when it runs; otherwise engine.json read with json alone,
# so a <PREFIX>CYCLE_BUDGET_USD set by launchd or a shell is still honoured when
# the module cannot import. The placeholder's prefix is the last resort, when
# engine.json itself is unreadable.
PREFIX="$(python3 "$ENGINE/scripts/config.py" brand env_prefix 2>/dev/null \
  || python3 -c 'import json,sys;p=(json.load(open(sys.argv[1])).get("brand") or {}).get("env_prefix","");print((p.strip().upper().rstrip("_")+"_") if p.strip() else "ACME_")' "$ENGINE/engine.json" 2>/dev/null \
  || echo ACME_)"
cd "$REPO"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
# A headless `claude -p` stops background subagents that are still running ten
# minutes after the orchestrator's last turn, and the listener (paid X queries,
# then scoring) takes longer than that. The first launchd cycle of 2026-11-05
# ended there: "stopping them", no signals, no drafts, exit 0. Zero waits.
export CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0

# Tokens. No plaintext env block lives anywhere: scripts/secrets.py resolves
# each one (environment first, then the macOS keychain) and prints export lines
# we evaluate here. Assign first, then eval, so `set -e` stops the cycle on a
# failed resolve instead of running on with an unset token.
secret_exports="$(python3 "$ENGINE/scripts/secrets.py" --export TWITTERAPI_IO_API_KEY)"
eval "$secret_exports"
unset secret_exports

# Parameters from engine.json through config.py (brand.json, engine.local.json,
# then the environment, win there too); the brand-prefixed variables keep winning
# here, with the prefix resolved above even when config.py cannot run. The
# runner reads cycle.budget_usd and cycle.drafts through the same path, so the
# budget is exported under the name config.py reads.
cfg() { python3 "$ENGINE/scripts/config.py" get "$1" 2>/dev/null || echo "$2"; }
v="${PREFIX}CYCLE_BUDGET_USD"; budget="${(P)v:-$(cfg cycle.budget_usd 20)}"
v="${PREFIX}CYCLE_DRAFTS";     drafts="${(P)v:-$(cfg cycle.drafts 3)}"
export "${PREFIX}CYCLE_BUDGET_USD=$budget"

# Which workflows are due (the weekly editor on Monday, the blog slots on Friday,
# the readout on the first weekday of the month; listening, the voice pass and
# motion by their switches in engine.json) is the runner's to decide, from each
# workflow's `when`. `--only engage` is the engagement job's chain.
chain=weekday
extra=""
case " $* " in *" --drafts "*) ;; *) extra="--drafts $drafts" ;; esac
args=("$@")
case " $* " in *" --only engage "*) chain=engagement; extra=""; args=() ;; esac

LOG="$STATE/schedule.log"
mkdir -p "$STATE"
echo "=== social-cycle $(date -u +%FT%TZ) $* $extra (chain $chain, claude $(claude --version 2>/dev/null | head -1)) ===" | tee -a "$LOG"

# The headless flags of every model call (the allowlist per workflow, the deny
# list, no prompt left waiting, the budget per call, the plugins a schedule has no
# use for switched off, never a bare run) are scripts/workflow.py's, in one place.
# -e is off around the run so the block can close with the exit code engine.py
# status reads (`=== social-cycle exit N ===`); the script still exits with it.
set +e
python3 -u "$ENGINE/scripts/workflow.py" chain "$chain" "${args[@]}" ${=extra} 2>&1 | tee -a "$LOG"
rc=${pipestatus[1]}
set -e
echo "=== social-cycle exit $rc ===" | tee -a "$LOG"
exit "$rc"
