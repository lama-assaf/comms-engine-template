#!/usr/bin/env python3
"""
backup.py against a temp instance with a bare remote: the record alone is staged, a person's other
work is left as it was, the push is off unless asked, a conflict stops it with both sides kept, and
nothing is ever forced.

  python3 -m unittest discover plugins/comms-engine/tests
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import backup  # noqa: E402

ID = ["-c", "user.name=test", "-c", "user.email=test@example.invalid"]


def git(root, *args):
    return subprocess.run(["git", "-C", root, *ID, *args], capture_output=True, text=True, check=True).stdout.strip()


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class Backup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="backup-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.remote = os.path.join(self.tmp, "remote.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.remote], check=True)
        seed = os.path.join(self.tmp, "seed")
        subprocess.run(["git", "init", "-q", "-b", "main", seed], check=True)
        write(seed, ".gitignore", "state/*.log\n.atelier/memory/handles.private.md\n")
        write(seed, "brand.json", '{\n  "brand": {"slug": "acme"}\n}\n')
        write(seed, "themes.json", "{}\n")
        write(seed, ".atelier/memory/claims.md", "# claims\n")
        write(seed, "state/queue.json", "[]\n")
        write(seed, "docs/notes.md", "notes\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "seed")
        git(seed, "remote", "add", "origin", self.remote)
        git(seed, "push", "-q", "-u", "origin", "main")
        self.mac = os.path.join(self.tmp, "mac")
        self.other = os.path.join(self.tmp, "other")
        for d in (self.mac, self.other):
            subprocess.run(["git", "clone", "-q", self.remote, d], check=True, capture_output=True)
        self.lines = []

    def run_backup(self, **kw):
        self.lines = []
        return backup.run(self.mac, out=self.lines.append, **kw)

    def said(self):
        return "\n".join(self.lines)

    def remote_head(self):
        return subprocess.run(["git", "--git-dir", self.remote, "rev-parse", "main"], capture_output=True, text=True).stdout.strip()

    def change_the_record(self):
        write(self.mac, "Content/Calendar/Q-1.md", "a note\n")
        write(self.mac, ".atelier/memory/claims.md", "# claims\n| c-1 | evidenced |\n")
        write(self.mac, "state/queue.json", '[{"id": "Q-1"}]\n')
        write(self.mac, "state/new-record.json", "{}\n")                        # untracked state: not the record's
        write(self.mac, "state/schedule.log", "log\n")                          # ignored
        write(self.mac, ".atelier/memory/handles.private.md", "stealth\n")      # ignored, never committed

    def test_dry_says_what_and_changes_nothing(self):
        self.change_the_record()
        head = git(self.mac, "rev-parse", "HEAD")
        self.assertEqual(self.run_backup(dry=True, push=True), 0)
        self.assertIn("Content/Calendar/Q-1.md", self.said())
        self.assertIn("state/queue.json", self.said())
        self.assertNotIn("new-record", self.said())
        self.assertNotIn("handles.private", self.said())
        self.assertEqual(git(self.mac, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.mac, "diff", "--cached", "--name-only"), "", "nothing staged")

    def test_push_off_commits_the_record_alone_and_keeps_it_here(self):
        self.change_the_record()
        write(self.mac, "docs/notes.md", "a person's edit\n")
        write(self.mac, "docs/staged.md", "a person's staged work\n")
        git(self.mac, "add", "docs/staged.md")
        before = self.remote_head()
        self.assertEqual(self.run_backup(push=False), 0, self.said())
        files = git(self.mac, "show", "--name-only", "--format=", "HEAD").splitlines()
        self.assertEqual(sorted(files), [".atelier/memory/claims.md", "Content/Calendar/Q-1.md", "state/queue.json"])
        self.assertEqual(git(self.mac, "diff", "--cached", "--name-only"), "docs/staged.md", "a person's staged work stays staged")
        self.assertIn("docs/notes.md", git(self.mac, "diff", "--name-only"), "and their edit stays in the working tree")
        self.assertEqual(self.remote_head(), before, "nothing pushed")
        self.assertIn("push is off", self.said())

    def test_push_on_rebases_over_the_remote_and_pushes(self):
        write(self.other, "themes.json", '{"#t": {}}\n')
        git(self.other, "commit", "-q", "-am", "elsewhere")
        git(self.other, "push", "-q")
        self.change_the_record()
        self.assertEqual(self.run_backup(push=True), 0, self.said())
        self.assertEqual(self.remote_head(), git(self.mac, "rev-parse", "HEAD"))
        log = git(self.mac, "log", "--format=%s", "-3").splitlines()
        self.assertTrue(log[0].startswith("backup: the record"), log)
        self.assertEqual(log[1], "elsewhere", "rebased, not merged over")

    def test_a_conflict_stops_it_with_both_sides_kept(self):
        write(self.other, "brand.json", '{\n  "brand": {"slug": "nova"}\n}\n')
        git(self.other, "commit", "-q", "-am", "renamed elsewhere")
        git(self.other, "push", "-q")
        remote = self.remote_head()
        write(self.mac, "brand.json", '{\n  "brand": {"slug": "zeta"}\n}\n')
        self.assertEqual(self.run_backup(push=True), 1)
        self.assertIn("conflict", self.said())
        self.assertEqual(self.remote_head(), remote, "nothing pushed, nothing forced")
        self.assertIn('"zeta"', git(self.mac, "show", "HEAD:brand.json"), "this Mac's commit is kept")
        gitdir = os.path.join(self.mac, ".git")
        self.assertFalse(os.path.exists(os.path.join(gitdir, "rebase-merge")) or os.path.exists(os.path.join(gitdir, "rebase-apply")),
                         "no rebase left half done")
        self.assertEqual(self.run_backup(push=True), 1, "and it keeps stopping until a person settles it")

    def test_work_outside_the_record_holds_the_pull(self):
        self.change_the_record()
        write(self.mac, "docs/notes.md", "a person's edit\n")
        before = self.remote_head()
        self.assertEqual(self.run_backup(push=True), 1)
        self.assertIn("outside the record", self.said())
        self.assertIn("the commit is kept", self.said())
        self.assertEqual(self.remote_head(), before)

    def test_it_refuses_where_git_is_mid_operation_or_absent(self):
        git(self.mac, "checkout", "-q", "--detach")
        self.assertEqual(self.run_backup(push=True), 1)
        self.assertIn("detached", self.said())
        self.assertEqual(backup.run(os.path.join(self.tmp, "remote.git", "hooks"), push=False, out=self.lines.append), 1)
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        self.assertEqual(backup.run(plain, push=False, out=self.lines.append), 1, "a directory outside any repository")

    def test_nothing_changed_is_said_and_pending_commits_still_go(self):
        self.assertEqual(self.run_backup(push=False), 0)
        self.assertIn("nothing changed", self.said())
        write(self.mac, "themes.json", '{"#x": {}}\n')
        self.run_backup(push=False)
        self.assertEqual(self.run_backup(push=True), 0, self.said())
        self.assertEqual(self.remote_head(), git(self.mac, "rev-parse", "HEAD"), "an earlier commit kept here goes out")


if __name__ == "__main__":
    unittest.main()
