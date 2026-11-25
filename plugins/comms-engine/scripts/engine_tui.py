#!/usr/bin/env python3
"""
engine_tui.py - the engine console as one terminal screen, over engine.py.

Why: engine.py has the subcommands, but an operator still has to remember
them. This screen lists the eight launchd jobs with their state, the streams,
the secrets and the plugins on the left, shows the selected item on the right
(what it is, when it runs, whether it is loaded, its parameters, its last log
lines), and runs engine.py's actions on a key. Every action leaves the exact
command it ran on the bottom line, so the screen teaches the CLI.

curses from the standard library, no dependency. Nothing here calls launchctl
or spawns a process of its own: every act is an engine.py function, and an act
that prints or asks (run, enable, disable, setup, onboarding) suspends the
screen and runs on the plain terminal, then comes back.

  engine engine_tui

Keys: j/k or arrows move · tab next section · r run (dry) · R run (live, asks
y; refused for autopilot, x-stream, nosleep) · e enable (asks y) · d disable
(asks y) · s setup · l logs · o onboard a stream · g refresh · ? help · q quit.
Needs 80x24.
Headless (no terminal) it says so and exits 2: use `engine.py status`.
"""
import datetime as dt
import os
import shlex
import sys

try:
    import curses
except ImportError:  # the model still imports; only the screen needs curses
    curses = None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config  # noqa: E402
import engine  # noqa: E402
import memory  # noqa: E402

ENGINE_PY = "engine"
MIN_W, MIN_H = 80, 24
LEFT_W = 34
LOG_LINES = 15

#: Key name -> action. getch() codes become names through key_name(); the
#: table is a plain dict so the test reads it without a screen.
KEYS = {
    "j": "down", "KEY_DOWN": "down",
    "k": "up", "KEY_UP": "up",
    "TAB": "section",
    "r": "run_dry",
    "R": "run_live",
    "e": "enable",
    "d": "disable",
    "s": "setup",
    "l": "logs",
    "o": "onboard",
    "g": "refresh",
    "?": "help",
    "q": "quit",
}

HELP = [
    "keys",
    "  j / k, arrows   move          tab   next section",
    "  r   run now, dry (the job's --dry-run form; engine.py run <job>)",
    "  R   run now, live through runjob.py; asks y; refused for autopilot,",
    "      x-stream and nosleep (launchd starts those, never a hand)",
    "  e   enable   schedule/install.sh --only <label>  (renders and loads; asks y)",
    "  d   disable  launchctl bootout gui/<uid>/<label>  (plist stays; asks y)",
    "  s   setup    the job's questionnaire on the terminal; secrets and",
    "               plugins rows show their tables; a stream row onboards",
    "  l   logs     the job's last lines in this pane (l again: detail)",
    "  o   onboard  a stream: asks the slug, runs engine.py onboard-stream",
    "  g   refresh  re-read status   ?  this help   q  quit",
    "",
    "the bottom line is the exact command the last action ran, and its exit.",
    "nothing here posts or publishes; a setup never loads a job (e does).",
]


def visible_lines(lines, view, n):
    """What fits in n rows: a log view keeps its tail, every other view its head."""
    if n <= 0:
        return []
    return lines[-n:] if view == "logs" else lines[:n]


def too_small_message(h, w):
    return f"engine_tui: terminal is {w}x{h}; needs at least {MIN_W}x{MIN_H} (q quits)"


def key_name(ch):
    """A getch() code as the name KEYS uses; None for a code the table cannot hold."""
    if ch is None or ch < 0:
        return None
    if ch == 9:
        return "TAB"
    if curses is not None:
        if ch == curses.KEY_UP:
            return "KEY_UP"
        if ch == curses.KEY_DOWN:
            return "KEY_DOWN"
    if 32 <= ch < 127:
        return chr(ch)
    return None


def shell(argv):
    return shlex.join(list(argv))


# --- the model: rows, detail, actions (no screen) ----------------------------------

class Row:
    """One line of the left pane. kind: section, job, stream, secrets, plugins."""

    def __init__(self, kind, key, text, data=None):
        self.kind, self.key, self.text, self.data = kind, key, text, data or {}

    @property
    def selectable(self):
        return self.kind != "section"


def job_state(status_row):
    """jobs_status's state text as the one word the left pane shows."""
    if status_row is None:
        return "?"
    s = status_row.get("state", "")
    if s.startswith("stale"):
        return "stale"
    if s == "not loaded":
        return "off"
    if s == "loaded, never ran":
        return "never"
    return "ok"


def when_text(last_run, today):
    """hh:mm when the last run was today, else MM-DD; '-' when it never ran."""
    if not last_run:
        return "-"
    day, _, clock = str(last_run).partition("T")
    if day == today:
        return clock[:5] or "-"
    return day[5:10] or "-"


def calendar_text(job):
    """`Mon-Fri 07:15` from a job's StartCalendarInterval list."""
    cal = job.get("calendar") or []
    if not cal:
        return "always on (keep_alive)" if job.get("keep_alive") else "no schedule"
    names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    times = sorted({f"{c.get('Hour', 0):02d}:{c.get('Minute', 0):02d}" for c in cal})
    days = sorted({c["Weekday"] for c in cal if "Weekday" in c})
    if not days:
        when = "daily"
    elif days == [1, 2, 3, 4, 5]:
        when = "Mon-Fri"
    else:
        when = ",".join(names[d % 7] for d in days)
    return f"{when} {', '.join(times)}"


def build_rows(st, jobs, streams, today):
    """The left pane: jobs with state and last run, then streams, secrets, plugins."""
    by_label = {r["job"]: r for r in st.get("jobs", [])}
    rows = [Row("section", None, "jobs")]
    for j in jobs:
        label = j["label"]
        short = engine.short_for(label)
        sr = by_label.get(label)
        text = f"  {short:<13}{job_state(sr):<7}{when_text(sr and sr.get('last_run'), today)}"
        rows.append(Row("job", short, text, {"label": label, "job": j, "status": sr}))
    rows.append(Row("section", None, "streams"))
    for slug, row in streams.items():
        owner = str(row.get("owner", "?"))
        rows.append(Row("stream", slug, f"  {slug:<13}{owner}", {"stream": row}))
    rows.append(Row("section", None, "secrets"))
    req = [s for s in st.get("secrets", []) if s.get("required")]
    present = [s for s in req if s.get("present")]
    rows.append(Row("secrets", "secrets", f"  secrets      {len(present)}/{len(req)} present"))
    rows.append(Row("section", None, "plugins"))
    pl = st.get("plugins", [])
    if pl and all(p.get("installed") is None for p in pl):
        text = "  plugins      unknown"
    else:
        text = f"  plugins      {sum(1 for p in pl if p.get('installed'))}/{len(pl)} installed"
    rows.append(Row("plugins", "plugins", text))
    return rows


def _fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return ", ".join(map(str, v)) if v else "[]"
    return str(v)


def _param_lines(params, indent="  "):
    out = []
    for k, v in params.items():
        if k == "job":
            continue
        if isinstance(v, dict):
            for k2, v2 in v.items():
                out.append(f"{indent}{k}.{k2} = {_fmt(v2)}")
        else:
            out.append(f"{indent}{k} = {_fmt(v)}")
    return out


class Outcome:
    """What one key did: a message, a command to run on the terminal, or quit."""

    def __init__(self, message=None, command=None, on_terminal=None, quit=False):
        self.message, self.command, self.on_terminal, self.quit = message, command, on_terminal, quit


def _setup_rc(job):
    """engine.setup on the terminal; a refusal is one printed line and exit 1."""
    try:
        out = engine.setup(job, {}, interactive=True)
    except (engine.Refused, engine.UnknownJob, config.ConfigError, ValueError) as e:
        print(f"engine: {e.args[0] if e.args else e}")
        return 1
    return int(out.get("_exit", 0)) if isinstance(out, dict) else 0


class Model:
    """Everything the screen shows and does, without the screen.

    `refresh()` re-reads engine.status() and the registries; `rows` is the
    left pane, `detail_lines()` the right one, `perform(action)` the key's
    effect. Tests patch engine.status, config.jobs and memory.load_streams.
    """

    def __init__(self, today=None):
        self.today = today or dt.date.today().isoformat()
        self.status = {"jobs": [], "secrets": [], "plugins": [], "last_cycle": {}}
        self.rows = []
        self.cursor = 0
        self.view = "detail"  # detail | logs | help
        self.last = f"{ENGINE_PY} status"
        self.error = None

    # -- data --------------------------------------------------------------------
    def refresh(self):
        self.error = None
        try:
            self.status = engine.status()
        except Exception as e:  # a screen with a reason beats a traceback
            self.error = f"status: {e}"
        try:
            jobs = config.jobs()
        except Exception as e:
            jobs, self.error = [], f"engine.json: {e}"
        try:
            streams = memory.load_streams()
        except Exception as e:
            streams, self.error = {}, f"streams.md: {e}"
        self.rows = build_rows(self.status, jobs, streams, self.today)
        self.cursor = min(self.cursor, len(self.rows) - 1)
        if self.rows and not self.rows[self.cursor].selectable:
            self.move(1)
        return self

    def selected(self):
        return self.rows[self.cursor] if self.rows else None

    def summary(self):
        """The three status lines (secrets, plugins, last cycle) for the title bar."""
        try:
            return engine.status_lines(self.status)[-3:]
        except Exception:
            return []

    # -- movement --------------------------------------------------------------------
    def move(self, delta):
        n = len(self.rows)
        if not n:
            return
        i = self.cursor
        for _ in range(n):
            i = (i + delta) % n
            if self.rows[i].selectable:
                self.cursor = i
                return

    def jump_section(self):
        n = len(self.rows)
        for step in range(1, n + 1):
            i = (self.cursor + step) % n
            if self.rows[i].kind == "section":
                self.cursor = i
                self.move(1)
                return

    # -- the right pane -------------------------------------------------------------
    def detail_lines(self):
        if self.view == "help":
            return list(HELP)
        row = self.selected()
        if row is None:
            return [self.error or "nothing to show"]
        if self.view == "logs" and row.kind == "job":
            return self._log_lines(row, n=200) or [f"no log yet for {row.data['label']}"]
        if row.kind == "job":
            return self._job_lines(row)
        if row.kind == "stream":
            return self._stream_lines(row)
        if row.kind == "secrets":
            return self._secret_lines()
        if row.kind == "plugins":
            return self._plugin_lines()
        return []

    def _log_lines(self, row, n):
        try:
            return engine.logs(row.data["label"], n)
        except Exception as e:
            return [f"logs: {e}"]

    def _job_lines(self, row):
        j, sr, label, short = row.data["job"], row.data["status"], row.data["label"], row.key
        lines = [f"{label}  ({short})",
                 f"what:      {j.get('what', '')}",
                 f"when:      {calendar_text(j)}",
                 f"loaded:    {'yes' if sr and sr.get('loaded') else 'no'}    state: {sr['state'] if sr else '?'}",
                 f"last run:  {(sr or {}).get('last_run') or 'never'}"]
        if j.get("optional"):
            lines.append("optional:  the all-jobs install skips it; e (enable) loads it by name")
        section = engine.PARAMS_SECTION.get(short)
        if section:
            try:
                params = config.params(section)
            except Exception as e:
                params = {"error": str(e)}
            lines.append(f"params ({section}):")
            lines.extend(_param_lines(params) or ["  (none)"])
        lines.append(f"log (last {LOG_LINES}):")
        logs = self._log_lines(row, LOG_LINES)
        if not logs:
            lines.append("  (no log yet)")
        for ln in logs:
            lines.append(ln if ln.startswith("==") else "  " + ln)
        return lines

    def _stream_lines(self, row):
        s = row.data["stream"]
        lines = [f"stream {row.key}  ({s.get('name', row.key)})",
                 f"owner:     {s.get('owner', '?')}   (a state, never a name)",
                 f"autopilot: {s.get('autopilot', '?')}",
                 f"memory:    {s.get('memory', '?')}"]
        try:
            cfg = config.streams().get(row.key, {})
        except Exception as e:
            cfg = {"error": str(e)}
        lines.append("engine.json streams block:")
        lines.extend(_param_lines(cfg) or ["  (none; o onboards the stream)"])
        if s.get("guardrails"):
            lines.append("guardrails:")
            lines.extend(f"  {k} = {v}" for k, v in s["guardrails"].items())
        return lines

    def _secret_lines(self):
        lines = ["secrets  (names only; values resolve through secrets.py)"]
        for s in sorted(self.status.get("secrets", []), key=lambda s: not s.get("required")):
            tag = "required" if s.get("required") else "optional"
            if s.get("present"):
                lines.append(f"  {s['name']}: present ({s.get('backend')}; {tag})")
            else:
                lines.append(f"  {s['name']}: MISSING  -> engine.py secrets --set {s['name']}  ({tag})")
        return lines

    def _plugin_lines(self):
        lines = [f"plugins  marketplace {config.cfg('plugins.marketplace', '')}"]
        for p in self.status.get("plugins", []):
            if p.get("installed") is None:
                lines.append(f"  {p['name']}: unknown (claude not on PATH)")
            elif p.get("installed"):
                lines.append(f"  {p['name']}: installed")
            else:
                lines.append(f"  {p['name']}: not installed  -> claude plugin install {p['name']}")
        return lines

    # -- actions ------------------------------------------------------------------------
    def perform(self, action, confirm=None, prompt=None):
        """One key's effect. `confirm(question) -> bool` and `prompt(question, default) -> str`
        are the screen's; tests pass lambdas. Returns an Outcome."""
        confirm = confirm or (lambda q: False)
        prompt = prompt or (lambda q, default: default)
        row = self.selected()
        if action == "quit":
            return Outcome(quit=True)
        if action in ("down", "up"):
            self.move(1 if action == "down" else -1)
            self.view = "detail"
            return Outcome()
        if action == "section":
            self.jump_section()
            self.view = "detail"
            return Outcome()
        if action == "refresh":
            self.refresh()
            return Outcome(message="status re-read", command=f"{ENGINE_PY} status")
        if action == "help":
            self.view = "detail" if self.view == "help" else "help"
            return Outcome()
        if action == "logs":
            if row is None or row.kind != "job":
                return Outcome(message="logs: select a job")
            self.view = "detail" if self.view == "logs" else "logs"
            return Outcome(command=f"{ENGINE_PY} logs {row.key}")
        if action == "onboard":
            return self._onboard(row.key if row is not None and row.kind == "stream" else "", prompt)
        if action == "setup":
            return self._setup(row, prompt)
        if action in ("run_dry", "run_live", "enable", "disable"):
            if row is None or row.kind != "job":
                return Outcome(message=f"{action.replace('_', ' ')}: select a job")
            return self._job_action(action, row, confirm)
        return Outcome(message=f"unknown action {action!r}")

    def _job_action(self, action, row, confirm):
        short, label = row.key, row.data["label"]
        if action == "run_live":
            if short in engine.LIVE_REFUSED:
                return Outcome(message=f"run --live {short}: refused; {label} is started by launchd only "
                                       f"(e enables it), and the PreToolUse hook would refuse a hand-run anyway")
            cmd = shell(engine.live_command(short))
            if not confirm(f"run {short} LIVE through runjob.py ({cmd})? y/N"):
                return Outcome(message=f"run --live {short}: not confirmed; nothing ran")
            return Outcome(command=cmd, on_terminal=lambda: engine.run(short, live=True))
        if action == "run_dry":
            cmds = engine.dry_commands(short)
            cmd = " && ".join(shell(c) for c in cmds) if cmds else f"{ENGINE_PY} run {short}  (nothing to dry-run)"
            return Outcome(command=cmd, on_terminal=lambda: engine.run(short, live=False))
        # loading or unloading a job changes what runs unattended: asked once, with the command
        if action == "enable":
            cmd = f"engine install --only {label}"
            if not confirm(f"enable {label} through install.sh ({cmd})? y/N"):
                return Outcome(message=f"enable {short}: not confirmed; nothing ran")
            return Outcome(command=cmd, on_terminal=lambda: engine.enable(short))
        cmd = f"launchctl bootout gui/{os.getuid()}/{label}"
        if not confirm(f"boot out {label} ({cmd})? y/N"):
            return Outcome(message=f"disable {short}: not confirmed; nothing ran")
        return Outcome(command=cmd, on_terminal=lambda: engine.disable(short))

    def _setup(self, row, prompt):
        if row is None:
            return Outcome(message="setup: select a job, a stream, secrets or plugins")
        if row.kind == "stream":
            return self._onboard(row.key, prompt)
        if row.kind in ("secrets", "plugins"):
            job = row.kind
        else:
            job = row.key
        return Outcome(command=f"{ENGINE_PY} setup {job}", on_terminal=lambda: _setup_rc(job))

    def _onboard(self, default, prompt):
        slug = (prompt("stream slug to onboard", default) or "").strip().lower()
        if not slug:
            return Outcome(message="onboard-stream: no slug; nothing ran")
        return Outcome(command=f"{ENGINE_PY} onboard-stream {slug}",
                       on_terminal=lambda: engine.main(["onboard-stream", slug]))


# --- the screen ----------------------------------------------------------------------------

def _put(scr, y, x, text, attr=0, width=None):
    """addnstr that never raises at the screen's edge."""
    h, w = scr.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    n = (w - x - 1) if width is None else min(width, w - x - 1)
    if n <= 0:
        return
    try:
        scr.addnstr(y, x, text, n, attr)
    except curses.error:
        pass


def _draw(scr, model):
    scr.erase()
    h, w = scr.getmaxyx()
    if h < MIN_H or w < MIN_W:
        _put(scr, 0, 0, too_small_message(h, w))
        scr.refresh()
        return
    bold, dim, rev = curses.A_BOLD, curses.A_DIM, curses.A_REVERSE
    _put(scr, 0, 0, "engine console", bold)
    summary = "  ".join(model.summary())
    _put(scr, 0, 16, summary, dim)
    if model.error:
        _put(scr, 1, 0, model.error, bold)
    top, bottom = 2, h - 3  # rows top..bottom-1 hold the panes
    for y in range(top, bottom):
        _put(scr, y, LEFT_W, "|", dim)
    visible = bottom - top
    first = max(0, min(model.cursor - visible + 1, len(model.rows) - visible)) if len(model.rows) > visible else 0
    for i, row in enumerate(model.rows[first:first + visible]):
        y = top + i
        idx = first + i
        if row.kind == "section":
            _put(scr, y, 0, row.text, bold, LEFT_W - 1)
        else:
            _put(scr, y, 0, row.text.ljust(LEFT_W - 1), rev if idx == model.cursor else 0, LEFT_W - 1)
    x = LEFT_W + 2
    for i, line in enumerate(visible_lines(model.detail_lines(), model.view, visible)):
        _put(scr, top + i, x, line, bold if i == 0 and model.view != "logs" else 0)
    hint = "j/k move  tab section  r dry  R live  e enable  d disable  s setup  l logs  o onboard  ? help  q quit"
    _put(scr, h - 2, 0, hint, dim)
    _put(scr, h - 1, 0, model.last, rev)
    scr.refresh()


def _ask_key(scr, question):
    h, w = scr.getmaxyx()
    _put(scr, h - 1, 0, question.ljust(w - 1), curses.A_BOLD)
    scr.refresh()
    return scr.getch()


def _ask_text(scr, question, default):
    h, w = scr.getmaxyx()
    label = f"{question} [{default}]: "
    _put(scr, h - 1, 0, label.ljust(w - 1), curses.A_BOLD)
    scr.refresh()
    curses.echo()
    curses.curs_set(1)
    try:
        raw = scr.getstr(h - 1, min(len(label), w - 2)).decode("utf-8", "replace").strip()
    except (curses.error, KeyboardInterrupt):
        raw = ""
    finally:
        curses.noecho()
        curses.curs_set(0)
    return raw or default


def _on_terminal(scr, outcome):
    """Suspend curses, run the act on the plain terminal, wait for Enter, resume."""
    curses.endwin()
    print(f"$ {outcome.command}", flush=True)
    try:
        rc = outcome.on_terminal()
    except KeyboardInterrupt:
        rc = 130
        print("\ninterrupted", flush=True)
    print(f"\n-- exit {rc}; press Enter to return to the console --", flush=True)
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    scr.clear()
    scr.refresh()
    return rc


def _screen(scr, model, result):
    curses.curs_set(0)
    scr.keypad(True)
    model.refresh()
    while True:
        _draw(scr, model)
        name = key_name(scr.getch())
        action = KEYS.get(name)
        if action is None:
            continue
        h, w = scr.getmaxyx()
        if (h < MIN_H or w < MIN_W) and action != "quit":
            continue
        outcome = model.perform(
            action,
            confirm=lambda q: _ask_key(scr, q) in (ord("y"), ord("Y")),
            prompt=lambda q, default: _ask_text(scr, q, default))
        if outcome.quit:
            result["exit"] = 0
            return
        if outcome.on_terminal is not None:
            rc = _on_terminal(scr, outcome)
            model.last = f"$ {outcome.command}  -> exit {rc}"
            model.refresh()
        elif outcome.command:
            model.last = f"$ {outcome.command}" + (f"  ({outcome.message})" if outcome.message else "")
        elif outcome.message:
            model.last = outcome.message


def _flush_stdin():
    try:
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("engine_tui: needs a terminal; use engine.py status")
        return 2
    if curses is None:
        print("engine_tui: curses is not available here; use engine.py status")
        return 2
    result = {"exit": 0}
    model = Model()
    try:
        curses.wrapper(_screen, model, result)
    except KeyboardInterrupt:
        result["exit"] = 0
    _flush_stdin()
    return result["exit"]


if __name__ == "__main__":
    sys.exit(main())
