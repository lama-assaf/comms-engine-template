#!/usr/bin/env python3
"""
backup.py - the instance's record into git, and git off the Mac: the daily `backup` job.

Why: on a hosted Mac (docs/07-hosting.md) the record is written by the jobs and
the control page, and git stays its history. This commits what the engine and a
person changed in the record, and, where the owner turned it on, takes it off
the machine: pull with rebase, then push. A disk that dies then loses at most a
day.

What it stages, and nothing else (a person's other work is never swept in):

  Content/  .atelier/memory/  brand.json  themes.json   new and changed files, .gitignore honoured
                                                        (handles.private.md never: it is ignored)
  state/                                                the files git already tracks, changed

It commits those paths alone (`git commit -- <paths>`), so anything else a
person staged stays staged and uncommitted. Then, only when params.backup.push
is true: `git pull --rebase` and `git push`, never forced. It stops, and says
why, rather than clobber anything:

  - a rebase or merge already in progress, or a detached HEAD: nothing is done;
  - tracked changes outside the record (they would block the rebase): the
    commit is kept, nothing is pulled or pushed;
  - a rebase conflict: the rebase is aborted, so the local commit and the
    remote's are both kept as they were, and nothing is pushed;
  - a push the remote refuses: logged, nothing forced.

The push key is the Mac's deploy key, set up outside this repository; no key is
ever a file here.

  engine backup --dry      what would be staged, and where it would go; changes nothing
  engine backup            commit the record; pull and push when params.backup.push is true
"""
import datetime as dt
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
sys.path.insert(0, HERE)
import config  # noqa: E402

REPO = paths.instance()
#: The record: new and changed files under these, .gitignore honoured.
RECORD = ("Content", ".atelier/memory", "brand.json", "themes.json")
#: Only the files git already tracks under these.
TRACKED_ONLY = ("state",)
GIT_TIMEOUT = 300


class Stopped(Exception):
    """The backup stopped short on purpose; the message is the log line."""


def git(root, *args, check=True):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_EDITOR="true")
    proc = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=GIT_TIMEOUT, env=env)
    if check and proc.returncode != 0:
        raise Stopped(f"git {args[0]} failed: {(proc.stderr or proc.stdout).strip().splitlines()[-1:] or ['']}")
    return proc


def _existing(root, rels):
    return [r for r in rels if os.path.exists(os.path.join(root, r))]


def pending(root):
    """[(status, path)] of what a backup would stage: the record's changes and the tracked state files' changes."""
    out = []
    record = _existing(root, RECORD)
    if record:
        lines = git(root, "status", "--porcelain", "--untracked-files=all", "--", *record).stdout.splitlines()
        out += [(ln[:2].strip() or "?", ln[3:]) for ln in lines if ln.strip()]
    tracked = _existing(root, TRACKED_ONLY)
    if tracked:
        names = git(root, "diff", "--name-only", "HEAD", "--", *tracked).stdout.splitlines()
        out += [("M", n) for n in names if n.strip()]
    return out


def _state_problem(root):
    gitdir = git(root, "rev-parse", "--git-dir").stdout.strip()
    gitdir = gitdir if os.path.isabs(gitdir) else os.path.join(root, gitdir)
    for marker, what in (("rebase-merge", "a rebase"), ("rebase-apply", "a rebase"), ("MERGE_HEAD", "a merge")):
        if os.path.exists(os.path.join(gitdir, marker)):
            return f"{what} is already in progress here; finish or abort it by hand, nothing backed up"
    if git(root, "symbolic-ref", "-q", "HEAD", check=False).returncode != 0:
        return "HEAD is detached; check out the instance's branch, nothing backed up"
    return None


def _identity(root):
    """`-c` flags for the commit when this repository and machine name no committer; config is never written."""
    if git(root, "config", "user.email", check=False).stdout.strip():
        return []
    slug = config.brand()["slug"]
    return ["-c", f"user.name={slug} comms backup", "-c", f"user.email=backup@{slug}.invalid"]


def run(root=None, push=None, dry=False, now=None, out=print):
    """Back the record up; returns 0 when it did all it was asked, 1 when it stopped short (and said why)."""
    root = root or REPO
    push = bool(config.cfg("backup.push", False)) if push is None else push
    now = now or dt.datetime.now(dt.timezone.utc)
    if git(root, "rev-parse", "--is-inside-work-tree", check=False).stdout.strip() != "true":
        out(f"backup: {root} is not a git repository; nothing backed up")
        return 1
    try:
        why = _state_problem(root)
        if why:
            raise Stopped(why)
        todo = pending(root)
        upstream = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False).stdout.strip()
        if dry:
            for st, path in todo:
                out(f"  {st:<2} {path}")
            out(f"backup --dry: {len(todo)} change(s) in the record; push {'on, to ' + (upstream or 'no upstream') if push else 'off (params.backup.push)'}; nothing changed")
            return 0
        committed = False
        if todo:
            record, tracked = _existing(root, RECORD), _existing(root, TRACKED_ONLY)
            if record:
                git(root, "add", "--", *record)
            if tracked:
                git(root, "add", "-u", "--", *tracked)
            message = f"backup: the record, {now.strftime('%Y-%m-%d %H:%M')} UTC ({len(todo)} change(s))"
            git(root, *_identity(root), "commit", "-q", "-m", message, "--", *(record + tracked))
            committed = True
            out(f"backup: committed {len(todo)} change(s) in the record")
        else:
            out("backup: nothing changed in the record")
        if not push:
            out("backup: push is off (params.backup.push); the commit stays on this Mac")
            return 0
        if not upstream:
            raise Stopped("the branch has no upstream to pull from and push to; set one once (git push -u <remote> <branch>)")
        if git(root, "status", "--porcelain", "--untracked-files=no").stdout.strip():
            raise Stopped("tracked changes outside the record would block the rebase; "
                          + ("the commit is kept, " if committed else "") + "nothing pulled or pushed")
        pull = git(root, "pull", "--rebase", "--no-autostash", "-q", check=False)
        if pull.returncode != 0:
            if _state_problem(root):
                git(root, "rebase", "--abort", check=False)
            raise Stopped("the pull did not rebase cleanly (a conflict with the remote); the rebase is aborted, "
                          "this Mac's commit and the remote's are both kept, nothing pushed: settle it by hand")
        pushed = git(root, "push", "-q", check=False)
        if pushed.returncode != 0:
            raise Stopped("the remote refused the push (nothing forced): "
                          + ((pushed.stderr or "").strip().splitlines() or [""])[-1][:160])
        out(f"backup: pushed to {upstream}")
        return 0
    except Stopped as e:
        out(f"backup: stopped: {e}")
        return 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    unknown = [a for a in argv if a not in ("--dry",)]
    if unknown:
        print("usage: engine backup [--dry]", file=sys.stderr)
        return 2
    return run(dry="--dry" in argv)


if __name__ == "__main__":
    sys.exit(main())
