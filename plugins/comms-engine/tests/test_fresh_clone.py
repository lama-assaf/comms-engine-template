#!/usr/bin/env python3
"""
A fresh clone of the template works, and carries nothing of the brand it came from.

The tree is copied the way a clone would arrive: every file `git ls-files`
would hand over (tracked and untracked, the ignored ones left behind, the
relative symlinks under `.claude/` kept as symlinks), into a temp directory
with no `.git`, no `handles.private.md`, no `engine.local.json` and no state
records. Against that copy, four things:

1. `config.py show` runs and prints the placeholder brand.
2. `engine.py status` runs; it may exit 1 (no job is loaded on a fresh
   machine), but it must not traceback.
3. `schedule/install.sh --dry-run` renders one plist per job, eight, every
   label `<brand.label_prefix>.<job name>`, and loads nothing.
4. A grep over the tree finds none of the previous brand's stealth terms, no
   machine home path, no per-machine profile name, and no file naming the
   brand the engine came from, or its earlier runtime: ALLOWED is empty.

The brand the clone carries is read from its own engine.json, so the checks
hold after `engine.py init` has stamped a real one as well as on the template. The brand's name
   is matched as a word (a letter on neither side), so `builtins` is not a
   hit. The stealth terms are not in this file: they are read from the
   maintainer's gitignored `.leak-terms`, and a failure names the line, never
   the term.

Then `engine new-instance`, run from the copy, writes a brand's instance in
another temp directory (NewInstance): the records and the memory as shapes, no
engine code, the plugin named, enabled and pinned, and the engine runs there.

Nothing here loads a launchd job, writes a keychain item or touches the
checkout: every command runs inside the copy, dry.

  python3 -m unittest discover plugins/comms-engine/tests
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(ENGINE))
PY = sys.executable

#: The previous brand's stealth terms are not written anywhere in this
#: repository. The maintainer keeps them in a gitignored local file, `.leak-terms`
#: at the root (or the file COMMS_LEAK_TERMS names): one term per line, `#` for a
#: comment, matched case-insensitively; a line starting with `=` is matched as
#: written, as a whole word. Without the file the term grep skips; a failure names
#: the line of the file, never the term, so a test log carries none of them.
LEAK_TERMS_FILE = os.environ.get("COMMS_LEAK_TERMS") or os.path.join(REPO, ".leak-terms")
MACHINE = ["/Us" + "ers/"]
#: The brand the engine came from, its sister brand and its earlier runtime, built from
#: pieces so this file spells none of them.
OTHERS = ("lt" + "in", "zil" + "liqa", "r3" + "to")
BRAND_RE = re.compile("|".join(rf"(?<![a-z]){t}|{t}(?![a-z])" for t in OTHERS), re.I)

#: Files that may name another brand, and why. None: the template is only the template.
ALLOWED = {}
#: Directories a clone does not carry and the grep does not read.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".next"}


def clone_tree(dst):
    """Copy what a clone would carry: `git ls-files -co --exclude-standard`
    when the tree is a git checkout, every non-ignored file otherwise."""
    try:
        out = subprocess.run(["git", "-C", REPO, "ls-files", "-co", "--exclude-standard", "-z"],
                             capture_output=True, check=True).stdout
        rels = [p for p in out.decode("utf-8").split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        rels = []
        for root, dirs, files in os.walk(REPO):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                rels.append(os.path.relpath(os.path.join(root, name), REPO))
    for rel in rels:
        if any(part in SKIP_DIRS for part in rel.split(os.sep)):
            continue
        src = os.path.join(REPO, rel)
        target = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.islink(src):
            os.symlink(os.readlink(src), target)
        elif os.path.isfile(src):
            shutil.copy2(src, target)
    return rels


def leak_patterns(path=None):
    """(label, pattern) for each term of the local leak-terms file, or None when
    there is no file. The label is the line number, never the term."""
    path = path or LEAK_TERMS_FILE
    if not os.path.isfile(path):
        return None
    out = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            term = line.strip()
            if not term or term.startswith("#"):
                continue
            if term.startswith("="):
                out.append((f"leak-terms line {n}", re.compile(r"\b" + re.escape(term[1:]) + r"\b")))
            else:
                out.append((f"leak-terms line {n}", re.compile(re.escape(term), re.I)))
    return out


def text_files(root):
    """Every regular text file under `root`, as (relative path, text)."""
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(base, d))]
        for name in sorted(files):
            path = os.path.join(base, name)
            if os.path.islink(path):
                continue
            with open(path, "rb") as f:
                raw = f.read()
            try:
                yield os.path.relpath(path, root), raw.decode("utf-8")
            except UnicodeDecodeError:
                continue


class FreshClone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="fresh-clone-")
        cls.root = os.path.join(cls.tmp, "template")
        os.makedirs(cls.root)
        cls.files = clone_tree(cls.root)
        with open(os.path.join(cls.root, "plugins", "comms-engine", "engine.json"), encoding="utf-8") as f:
            b = json.load(f).get("brand") or {}
        cls.slug = b.get("slug", "acme")
        cls.label_prefix = (b.get("label_prefix") or f"com.{cls.slug}").rstrip(".")
        cls.env_prefix = (b.get("env_prefix") or cls.slug.replace("-", "_")).strip().upper().rstrip("_") + "_"
        # the copy finds itself: no inherited instance may point it back at this checkout
        cls.env = {k: v for k, v in os.environ.items()
                   if not k.startswith(cls.env_prefix) and k not in ("COMMS_ENGINE_INSTANCE", "CLAUDE_PROJECT_DIR")}
        cls.env["HOME"] = os.path.join(cls.tmp, "home")
        os.makedirs(cls.env["HOME"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_in_clone(self, *argv):
        return subprocess.run(list(argv), cwd=self.root, env=self.env, capture_output=True, text=True, timeout=300)

    # ── what the clone carries ──────────────────────────────────────────

    def test_the_copy_is_a_clone_not_a_checkout(self):
        self.assertTrue(self.files, "nothing to copy")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".git")))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".atelier", "memory", "handles.private.md")),
                         "the private companion is gitignored and never reaches a clone")
        self.assertFalse(os.path.exists(os.path.join(self.root, "engine.local.json")))
        state = os.path.join(self.root, "state")
        records = [n for n in os.listdir(state) if n.endswith(".json")] if os.path.isdir(state) else []
        self.assertEqual(records, [], "a fresh clone ships no state records")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude", "commands")),
                         "the engine's commands come from the plugin, not from .claude/")

    def test_the_private_companion_is_gitignored(self):
        ignores = []
        for rel in (".gitignore", os.path.join(".atelier", "memory", ".gitignore")):
            path = os.path.join(self.root, rel)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    ignores.append(f.read())
        self.assertTrue(any(re.search(r"^\s*(\*\*/)?handles\.private\.md\s*$", t, re.M) for t in ignores),
                        "no .gitignore rule keeps handles.private.md out of the repository")

    # ── the engine runs ─────────────────────────────────────────────────

    def test_config_show_runs_and_names_the_brand(self):
        proc = self.run_in_clone(PY, "plugins/comms-engine/scripts/config.py", "show")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["brand"]["slug"], self.slug)
        self.assertEqual(doc["brand"]["label_prefix"], self.label_prefix)
        self.assertEqual(list(doc["streams"]), [self.slug], "the streams key is the brand's slug")
        self.assertEqual([j["name"] for j in doc["jobs"]][:1], ["corpus-cycle"])

    def test_engine_status_runs_without_a_traceback(self):
        proc = self.run_in_clone(PY, "plugins/comms-engine/scripts/engine.py", "status")
        self.assertIn(proc.returncode, (0, 1), proc.stderr)
        self.assertNotIn("Traceback", proc.stdout + proc.stderr)
        self.assertIn(self.label_prefix + ".", proc.stdout)

    def test_install_dry_run_renders_every_plist_and_loads_nothing(self):
        labels = self.run_in_clone(PY, "plugins/comms-engine/scripts/config.py", "labels")
        self.assertEqual(labels.returncode, 0, labels.stderr)
        expected = sorted(labels.stdout.split())
        self.assertEqual(len(expected), 12)
        self.assertTrue(all(l.startswith(self.label_prefix + ".") for l in expected), expected)

        # the script names its own interpreter; it is run the way a person runs it
        proc = self.run_in_clone("/bin/bash", "plugins/comms-engine/schedule/install.sh", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("nothing loaded", proc.stdout)
        rendered = sorted(re.findall(r"^\s+(" + re.escape(self.label_prefix) + r"\.[a-z-]+)\s", proc.stdout, re.M))
        self.assertEqual(rendered, expected)
        m = re.search(r"rendered to (\S+)", proc.stdout)
        self.assertIsNotNone(m, proc.stdout)
        out_dir = m.group(1).rstrip(":")
        if os.path.isdir(out_dir):
            plists = sorted(n[:-len(".plist")] for n in os.listdir(out_dir) if n.endswith(".plist"))
            self.assertEqual(plists, expected)
            shutil.rmtree(out_dir, ignore_errors=True)

    # ── the setup file ──────────────────────────────────────────────────

    def test_the_setup_file_is_clean_and_the_registry_matches_it(self):
        proc = self.run_in_clone(PY, "plugins/comms-engine/scripts/engine.py", "validate")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ok  brand.json", proc.stdout)
        proc = self.run_in_clone(PY, "plugins/comms-engine/scripts/engine.py", "apply", "--check")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("matches brand.json", proc.stdout)

    def test_init_stamps_a_brand_through_the_setup_file_alone(self):
        """In a second copy, so the clone the other tests read stays as it arrived."""
        root = os.path.join(self.tmp, "stamped")
        shutil.copytree(self.root, root, symlinks=True)
        engine_json = os.path.join(root, "plugins", "comms-engine", "engine.json")
        with open(engine_json, "rb") as f:
            before = f.read()

        def run(*argv):
            return subprocess.run([PY, *argv], cwd=root, env=self.env, capture_output=True, text=True, timeout=300)

        proc = run("plugins/comms-engine/scripts/engine.py", "init", "--slug", "nova", "--name", "Nova Works", "--x", "@novaworks")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        with open(engine_json, "rb") as f:
            self.assertEqual(f.read(), before, "init never edits engine.json")
        with open(os.path.join(root, "brand.json"), encoding="utf-8") as f:
            bdoc = json.load(f)
        self.assertEqual(bdoc["brand"], {"slug": "nova", "name": "Nova Works"})
        self.assertEqual(bdoc["streams"]["nova"]["channels"], {"x": "@novaworks"})
        self.assertNotIn(self.slug, bdoc["streams"]) if self.slug != "nova" else None
        self.assertEqual(run("plugins/comms-engine/scripts/config.py", "brand", "label_prefix").stdout.strip(), "com.nova")
        listed = run("plugins/comms-engine/scripts/memory.py", "--list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("nova", listed.stdout)
        doc = json.loads(run("plugins/comms-engine/scripts/config.py", "show").stdout)
        self.assertEqual(list(doc["streams"]), ["nova"])
        for cmd in ("validate", ("apply", "--check")):
            argv = [cmd] if isinstance(cmd, str) else list(cmd)
            proc = run("plugins/comms-engine/scripts/engine.py", *argv)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        again = run("plugins/comms-engine/scripts/engine.py", "init", "--from", "brand.json")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("nothing to write", again.stdout)

    # ── nothing of the previous brand ───────────────────────────────────

    def test_x_stream_rules_answers_without_a_key_or_handle(self):
        """A fresh clone has no own X handle and no key: one line, exit 1, no traceback."""
        env = {k: v for k, v in self.env.items() if k != "TWITTERAPI_IO_API_KEY"}
        proc = subprocess.run([PY, "plugins/comms-engine/scripts/x_stream.py", "rules"], cwd=self.root, env=env,
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertNotIn("Traceback", proc.stdout + proc.stderr)
        self.assertTrue(proc.stderr.startswith("x_stream: ") or "desired rules only" in proc.stdout, proc.stdout + proc.stderr)

    def test_gate_says_what_a_fresh_clone_lacks(self):
        gate = self.run_in_clone(PY, "plugins/comms-engine/scripts/gate_lint.py")
        self.assertEqual(gate.returncode, 0, gate.stderr)
        self.assertIn("no items", gate.stdout)
        self.assertIn("denylist: missing", gate.stdout)

    def test_no_machine_home_path(self):
        hits = []
        for rel, text in text_files(self.root):
            hits += [f"{rel}: {t}" for t in MACHINE if t in text]
        self.assertEqual(hits, [], "machine paths that may not be in the template:\n" + "\n".join(hits))

    def test_no_leak_term(self):
        patterns = leak_patterns()
        if patterns is None:
            self.skipTest("no leak-terms file (.leak-terms, or COMMS_LEAK_TERMS): the template ships "
                          "no terms; the maintainer keeps them locally")
        hits = [f"{rel}: {label}" for rel, text in text_files(self.root)
                for label, pat in patterns if pat.search(text)]
        self.assertEqual(hits, [], "terms that may not be in the template (see the lines named):\n" + "\n".join(hits))

    def test_the_leak_terms_file_is_gitignored(self):
        with open(os.path.join(REPO, ".gitignore"), encoding="utf-8") as f:
            self.assertRegex(f.read(), r"(?m)^/?\.leak-terms\s*$",
                             "the local leak-terms file must never be committed")

    def test_the_previous_brand_is_named_only_where_allowed(self):
        hits = []
        for rel, text in text_files(self.root):
            if rel in ALLOWED:
                continue
            if BRAND_RE.search(rel):
                hits.append(f"{rel}: in the file name")
            n = len(BRAND_RE.findall(text))
            if n:
                hits.append(f"{rel}: {n} mention(s)")
        self.assertEqual(hits, [], "files that still name the previous brand:\n" + "\n".join(hits))

    def test_the_allowed_files_each_have_a_reason(self):
        for rel, why in ALLOWED.items():
            self.assertTrue(why.strip(), rel)


class NewInstance(unittest.TestCase):
    """`engine new-instance`, run from a fresh clone of the template, writes a brand's instance
    repository: the records and the memory as shapes, no engine code, the plugin named and
    enabled, the engine pinned, `git init` done; and the engine runs against it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="new-instance-")
        cls.clone = os.path.join(cls.tmp, "template")
        os.makedirs(cls.clone)
        clone_tree(cls.clone)
        cls.env = {k: v for k, v in os.environ.items() if k not in ("COMMS_ENGINE_INSTANCE", "CLAUDE_PROJECT_DIR")}
        cls.env["HOME"] = os.path.join(cls.tmp, "home")
        os.makedirs(cls.env["HOME"])
        cls.engine = os.path.join(cls.clone, "plugins", "comms-engine", "bin", "engine")
        cls.root = os.path.join(cls.tmp, "acme-comms")
        cls.made = cls.run_engine(cls.clone, "new-instance", cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def run_engine(cls, cwd, *argv):
        return subprocess.run([PY, cls.engine, *argv], cwd=cwd, env=cls.env, capture_output=True, text=True, timeout=300)

    def test_it_is_written_and_says_what_comes_next(self):
        self.assertEqual(self.made.returncode, 0, self.made.stdout + self.made.stderr)
        self.assertIn("no engine code", self.made.stdout)
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".git")), "git init ran")

    def test_the_records_and_no_engine(self):
        for rel in ("brand.json", "themes.json", ".atelier/memory/streams.md", ".atelier/memory/claims.md",
                    "state/README.md", "streams/README.md", ".claude/settings.json", ".gitignore", "README.md"):
            self.assertTrue(os.path.isfile(os.path.join(self.root, rel)), rel)
        for rel in ("plugins", "Tooling", ".claude-plugin", "CLAUDE.md", ".atelier/memory/handles.private.md", "engine.local.json"):
            self.assertFalse(os.path.exists(os.path.join(self.root, rel)), rel)
        with open(os.path.join(self.clone, ".atelier", "memory", "claims.md"), encoding="utf-8") as a, \
                open(os.path.join(self.root, ".atelier", "memory", "claims.md"), encoding="utf-8") as b:
            self.assertEqual(a.read(), b.read(), "the memory arrives as the template's shapes")

    def test_the_plugin_is_named_enabled_and_pinned(self):
        with open(os.path.join(self.root, ".claude", "settings.json"), encoding="utf-8") as f:
            settings = json.load(f)
        self.assertEqual(settings["extraKnownMarketplaces"]["comms-engine"]["source"]["source"], "github")
        self.assertIs(settings["enabledPlugins"]["comms-engine@comms-engine"], True)
        self.assertIn("Skill(salon:claim-gate)", settings["permissions"]["deny"], "the deny list comes along")
        self.assertNotIn("hooks", settings)
        with open(os.path.join(self.clone, "plugins", "comms-engine", ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            version = json.load(f)["version"]
        with open(os.path.join(self.root, "brand.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["engine"], {"version": version})

    def test_the_engine_runs_against_it(self):
        for argv, said in ((("validate",), "ok  brand.json"), (("apply", "--check"), "matches brand.json"),
                           (("paths", "instance"), os.path.realpath(self.root))):
            proc = self.run_engine(self.root, *argv)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn(said, os.path.realpath(proc.stdout.strip()) if argv[0] == "paths" else proc.stdout)

    def test_nothing_of_a_machine_or_the_previous_brand(self):
        hits = []
        for rel, text in text_files(self.root):
            hits += [f"{rel}: {t}" for t in MACHINE if t in text]
            if BRAND_RE.search(text) or BRAND_RE.search(rel):
                hits.append(f"{rel}: the previous brand")
        self.assertEqual(hits, [])

    def test_from_a_setup_file_and_never_over_a_directory_in_use(self):
        setup = os.path.join(self.tmp, "nova.json")
        with open(setup, "w", encoding="utf-8") as f:
            json.dump({"brand": {"slug": "nova", "name": "Nova Works"},
                       "streams": {"nova": {"name": "Nova Works", "owner": "unset", "autopilot": "nothing"}}}, f)
        root = os.path.join(self.tmp, "nova-comms")
        proc = self.run_engine(self.clone, "new-instance", root, "--from", setup)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        with open(os.path.join(root, "brand.json"), encoding="utf-8") as f:
            bdoc = json.load(f)
        self.assertEqual(bdoc["brand"], {"slug": "nova", "name": "Nova Works"})
        self.assertIn("version", bdoc["engine"], "a setup file without a pin gets the engine that wrote the instance")
        proc = self.run_engine(root, "apply", "--check")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        again = self.run_engine(self.clone, "new-instance", root)
        self.assertEqual(again.returncode, 1)
        self.assertIn("not empty", again.stderr)


if __name__ == "__main__":
    unittest.main()
