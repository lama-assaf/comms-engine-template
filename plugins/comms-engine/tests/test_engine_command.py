"""
/engine: the command file's tables match engine.py, and the console is linked in.

claude/commands/engine.md carries the setup questions by hand (a job, a key,
a default, a path, a prompt per row) so the chat face can ask them without
reading Python; this guards that copy against engine.QUESTIONS drifting:

- the (job, key) set of the setup table is QUESTIONS plus EXTRA_FLAGS, and each
  row's path is the one engine.py writes
- the onboarding table carries every flag onboard.py takes, write-voice included
- the frontmatter has description, argument-hint and allowed-tools
- when .claude/ is present, the command and the skill symlinks resolve
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(ENGINE))
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import engine  # noqa: E402

COMMAND = os.path.join(ENGINE, "commands", "engine.md")
SKILL = os.path.join(ENGINE, "skills", "engine-console", "SKILL.md")


def table_rows(text, header_start):
    """The cells of every body row of the markdown table whose header starts with `header_start`."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(header_start):
            rows = []
            for body in lines[i + 2:]:
                if not body.startswith("|"):
                    break
                rows.append([c.strip() for c in body.strip().strip("|").split("|")])
            return rows
    raise AssertionError(f"no table starting {header_start!r}")


class CommandFile(unittest.TestCase):
    def setUp(self):
        with open(COMMAND, encoding="utf-8") as f:
            self.text = f.read()

    def test_frontmatter(self):
        head = self.text.split("---")[1]
        for key in ("description:", "argument-hint:", "allowed-tools:"):
            self.assertIn(key, head)
        self.assertIn("AskUserQuestion", head)

    def test_setup_table_matches_engine_questions(self):
        rows = table_rows(self.text, "| job | key | default | path | prompt |")
        documented = {}
        for job, key, _default, path, _prompt in rows:
            documented[(job, key.strip("`").replace("-", "_"))] = path.strip("`")
        expected = {}
        for short, qs in engine.QUESTIONS.items():
            for key, path, _ in qs:
                expected[(short, key)] = path
            for key in engine.EXTRA_FLAGS.get(short, ()):
                expected[(short, key)] = "(not written)"
        self.assertEqual(set(documented), set(expected))
        for k, path in expected.items():
            self.assertEqual(documented[k], path, k)
        # the keys no script reads yet are marked in the table too
        for (job, key), path in documented.items():
            row = next(r for r in rows if r[0] == job and r[1].strip("`").replace("-", "_") == key)
            if path in engine.INERT:
                self.assertIn("not read by any script yet", row[4], (job, key))

    def test_onboarding_table_carries_every_flag(self):
        rows = table_rows(self.text, "| key | default | prompt |")
        keys = {r[0].strip("`") for r in rows}
        self.assertEqual(keys, {"owner-confirmed", "corpus-root", "channels", "write-voice", "voice-from", "themes-file"})
        line = next(l for l in self.text.splitlines() if "engine onboard-stream <slug>" in l and "--owner-confirmed" in l)
        self.assertIn("[--write-voice]", line)
        self.assertRegex(self.text, r"exit 2 .*unknown slug")

    def test_skill_and_command_ship_with_the_plugin(self):
        self.assertTrue(os.path.exists(SKILL))
        self.assertTrue(os.path.exists(COMMAND))
        settings = os.path.join(REPO, ".claude", "settings.json")
        if not os.path.isfile(settings):
            self.skipTest(".claude/ is not in this checkout")
        with open(settings, encoding="utf-8") as f:
            self.assertIs(json.load(f)["enabledPlugins"].get("comms-engine@comms-engine"), True)


if __name__ == "__main__":
    unittest.main()
