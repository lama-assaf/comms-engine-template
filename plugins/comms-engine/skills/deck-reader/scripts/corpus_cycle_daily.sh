#!/bin/zsh
# Daily corpus cycle, run by launchd (the corpus-cycle job, 06:30 weekdays),
# before the 07:15 social cycle, so memory is current when the engine drafts.
#
# Cheap first: the sweep fingerprints every file in the corpus root and exits 0 when
# nothing is new, changed or stale and nothing sits at read/analysed. Only then
# does it spend a Claude run on /corpus-cycle, which reads what changed, briefs
# it, and applies the tighten-only memory edits. Nothing is committed; the diff
# waits in the working tree for review.
#
# The Claude run is scoped, not unrestricted: it may read and edit files, run
# the corpus scripts and the verification commands CLAUDE.md names, and nothing
# else. A tool call outside the allowlist is denied in -p mode rather than
# prompted, which is the intended failure. Plain `claude` from PATH; the plist
# may set CLAUDE_CONFIG_DIR when a separate login is wanted. zsh, not bash:
# launchd on this Mac may run /bin/zsh and python3 against files under
# ~/Desktop, and /bin/bash is refused (Operation not permitted).
set -uo pipefail
# The engine and the instance. By hand, this file's own location says where the
# engine is; under the launchd launcher (schedule/runjob.py) the text arrives
# through `zsh -c` and the launcher names the engine in COMMS_ENGINE_HOME. The
# instance and its state/ are scripts/paths.py's answer (COMMS_ENGINE_INSTANCE,
# CLAUDE_PROJECT_DIR, then the nearest parent of the working directory holding
# brand.json).
HERE="$(cd "$(dirname "${(%):-%x}")" 2>/dev/null && pwd)" || HERE="$PWD"
ENGINE="${COMMS_ENGINE_HOME:-}"
for c in "$ENGINE" "$HERE/../../.."; do
  [ -n "$c" ] && [ -f "$c/scripts/paths.py" ] && { ENGINE="$(cd "$c" && pwd)"; break; }
done
[ -f "$ENGINE/scripts/paths.py" ] || { echo "corpus_cycle_daily.sh: the engine is not found; set COMMS_ENGINE_HOME" >&2; exit 2; }
DECK="$ENGINE/skills/deck-reader/scripts"
REPO="$(python3 "$ENGINE/scripts/paths.py" instance)"
LOG_DIR="$(python3 "$ENGINE/scripts/paths.py" state)"
export COMMS_ENGINE_INSTANCE="$REPO" COMMS_ENGINE_HOME="$ENGINE"
# The prefix: config.py when it runs; otherwise engine.json read with json alone,
# so a <PREFIX>CORPUS_ROOT set by launchd or a shell is still honoured when the
# module cannot import. The placeholder's prefix is the last resort.
PREFIX="$(python3 "$ENGINE/scripts/config.py" brand env_prefix 2>/dev/null \
  || python3 -c 'import json,sys;p=(json.load(open(sys.argv[1])).get("brand") or {}).get("env_prefix","");print((p.strip().upper().rstrip("_")+"_") if p.strip() else "ACME_")' "$ENGINE/engine.json" 2>/dev/null \
  || echo ACME_)"
LOG="$LOG_DIR/corpus-cycle.log"
STAMP="$(date +%Y-%m-%dT%H:%M)"
# the engine's bin/ first: the run's allowlist names `engine <script>`
export PATH="$ENGINE/bin:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin"
# Headless claude stops background subagents still running 10 min after the
# orchestrator's last turn; the deck reader's passes can run longer. Zero waits.
export CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0
unset ANTHROPIC_API_KEY GITHUB_TOKEN GH_TOKEN
cd "$REPO" || exit 2
mkdir -p "$LOG_DIR"

# Parameters from engine.json through config.py (engine.local.json and the
# environment win there too); the brand-prefixed variables keep winning here,
# with the prefix resolved above even when config.py cannot run, and a missing
# config.py falls back to the values this script shipped with.
# The corpus root has no useful fallback: `engine.py setup corpus --root` sets it.
cfg() { python3 "$ENGINE/scripts/config.py" get "$1" 2>/dev/null || echo "$2"; }
v="${PREFIX}CORPUS_ROOT";       CORPUS="${(P)v:-$(cfg corpus.root "$HOME/Documents/Strategy")}"
v="${PREFIX}CORPUS_BUDGET_USD"; BUDGET="${(P)v:-$(cfg corpus.budget_usd 10)}"
v="${PREFIX}CORPUS_MAX";        MAX="${(P)v:-$(cfg corpus.max 8)}"
v="${PREFIX}CORPUS_APPLY";      APPLY=""
[ "${(P)v:-$(cfg corpus.apply true)}" = true ] && APPLY="--apply"
if [ ! -d "$CORPUS" ]; then
  echo "$STAMP corpus root not mounted; skipping" | tee -a "$LOG"
  exit 0
fi

if python3 "$DECK/corpus_sweep.py" --root "$CORPUS" --only-todo > "$LOG_DIR/corpus-todo.md" 2>&1; then
  echo "$STAMP nothing pending in the corpus; no Claude run" | tee -a "$LOG"
  exit 0
fi

echo "$STAMP pending work found, running /corpus-cycle" | tee -a "$LOG"
cat "$LOG_DIR/corpus-todo.md" | tee -a "$LOG"

# The plugins a schedule has no use for (engine.json plugins.interactive_only: the Motion
# plugin, whose session hook may install npm packages) are switched off for this run alone.
PLUGIN_SETTINGS="$(python3 "$ENGINE/scripts/engine.py" plugins --headless-settings 2>/dev/null || echo '{}')"
ALLOWED="Read,Glob,Grep,Write,Edit,Agent"
ALLOWED="$ALLOWED,Bash(engine corpus_sweep *),Bash(engine extract_deck *),Bash(engine extract_doc *)"
ALLOWED="$ALLOWED,Bash(python3 -m unittest discover $ENGINE/tests)"
ALLOWED="$ALLOWED,Bash(engine listen --dry-run)"
ALLOWED="$ALLOWED,Bash(unzip -p *),Bash(pdftoppm *),Bash(soffice *),Bash(ls *),Bash(find *),Bash(wc *),Bash(head *),Bash(sed -n *)"
ALLOWED="$ALLOWED,Bash(git diff *),Bash(git status *),Bash(git checkout -- .atelier/memory/*)"
# What an unattended run must never do, whatever a document it read asks of it: write a
# script (the allowlist would then run it), rewrite an agent, a command, a hook or
# CLAUDE.md (the next run would obey it), or run secrets.py. A deny outranks the allowlist.
DENIED="Edit(**/*.py),Edit(**/*.sh),Edit(.claude/**),Edit(plugins/**),Edit(~/.claude/**),Edit(CLAUDE.md),Bash(python3 *secrets.py*),Bash(engine secrets*)"

# The host's Claude token (claude setup-token, kept by secrets.py), for this call alone: set just
# before it and unset after it, so no script of this job sees it. A machine without one keeps
# claude's own login.
token_export="$(python3 "$ENGINE/scripts/secrets.py" --export CLAUDE_CODE_OAUTH_TOKEN 2>/dev/null || true)"
[ -n "$token_export" ] && eval "$token_export"
unset token_export
claude -p "/corpus-cycle $APPLY --max $MAX" \
  --permission-mode acceptEdits \
  --permission-prompts none \
  --max-budget-usd "$BUDGET" \
  --settings "$PLUGIN_SETTINGS" \
  --disallowedTools "$DENIED" \
  --allowedTools "$ALLOWED" \
  --output-format text \
  2>&1 | tee "$LOG_DIR/corpus-cycle.last.md" | tee -a "$LOG"
RC=${pipestatus[1]}
unset CLAUDE_CODE_OAUTH_TOKEN
echo "$STAMP /corpus-cycle exit $RC" | tee -a "$LOG"
python3 "$DECK/corpus_sweep.py" --root "$CORPUS" --write >/dev/null 2>&1 || true
git -C "$REPO" diff --stat .atelier/memory/ | tail -3 | tee -a "$LOG"
exit "$RC"
