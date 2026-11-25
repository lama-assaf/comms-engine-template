"""
The repository's own housekeeping, read from the tracked files: nothing runs.

2026-11-13: the first evaluation found no dependency manifest (a clone learned which
packages it needed from an ImportError), `^` ranges in the desk, the research store on
`latest`, no linter and no CI. These checks keep what was added from drifting:

- every third-party module a script or a test imports has an exact pin in
  requirements.txt (the research store's optional graph library is the one exception),
  and nothing is pinned that no file imports
- the two web apps name exact versions, so a lockfile refresh is a decision
- the research store's image is a version, not `latest`
- CI lints with the pinned ruff, runs this suite, typechecks the desk, and checks that
  the committed ui/dist is the build of ui/src
- the LICENSE is the Apache 2.0 text, unmodified, and the README names it
- no script, job, config or current doc names Notion (retired 2026-11-13); the dated
  plans and records that describe the build as it was are the exceptions
"""
import ast
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
REPO = os.path.abspath(os.path.join(ENGINE, "..", ".."))
#: where the Python lives: the engine, and the optional modules beside the instance
CODE_DIRS = (os.path.join(REPO, "plugins"), os.path.join(REPO, "Tooling"))

#: import name -> the distribution that provides it
DISTRIBUTIONS = {"yaml": "pyyaml", "requests": "requests", "pdfplumber": "pdfplumber", "pdfminer": "pdfminer.six",
                 "pptx": "python-pptx", "docx": "python-docx", "PIL": "pillow"}
#: imported inside a try and done without when absent: the research store's graph library, off
#: until someone installs it (research-store/README.md), and `rewrites`, a module of the engine
#: itself that the template does not ship (gate_lint.py judges the notes as they stand without it)
OPTIONAL = {"graphiti_core", "rewrites"}


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


def pins(name):
    """{distribution, lower case: version} of a requirements file; every line must be an exact pin."""
    out = {}
    for line in read(name).splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            m = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.!+-]+)", line)
            assert m, f"{name}: not an exact pin: {line!r}"
            out[m.group(1).lower()] = m.group(2)
    return out


def third_party_imports():
    files = [os.path.join(d, f) for top in CODE_DIRS for d, dirs, names in os.walk(top) for f in names if f.endswith(".py")
             if "node_modules" not in d and "__pycache__" not in d]
    local = {os.path.splitext(os.path.basename(f))[0] for f in files}
    found = {}
    for path in files:
        for node in ast.walk(ast.parse(read(path))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
            for name in names:
                top = name.split(".")[0]
                if top not in sys.stdlib_module_names and top not in local:
                    found.setdefault(top, os.path.relpath(path, REPO))
    return found


class PythonPackages(unittest.TestCase):
    def test_every_import_has_its_pin_and_every_pin_its_import(self):
        imports, pinned = third_party_imports(), pins("requirements.txt")
        for module, where in sorted(imports.items()):
            if module in OPTIONAL:
                continue
            self.assertIn(module, DISTRIBUTIONS, f"{where} imports {module}: name its distribution here and pin it in requirements.txt")
            self.assertIn(DISTRIBUTIONS[module], pinned, f"{where} imports {module}; requirements.txt has no pin for it")
        used = {DISTRIBUTIONS[m] for m in imports if m in DISTRIBUTIONS}
        self.assertEqual(set(pinned) - used, set(), "pinned, and imported by nothing")

    def test_the_linter_is_pinned_and_configured(self):
        self.assertEqual(list(pins("requirements-dev.txt")), ["ruff"])
        self.assertRegex(read("ruff.toml"), r'(?m)^select = \[.*"F".*\]$')


class WebPackages(unittest.TestCase):
    def test_both_apps_name_exact_versions(self):
        for app in (("Tooling", "desk"), ("plugins", "comms-engine", "ui")):
            pkg = json.loads(read(*app, "package.json"))
            lock = json.loads(read(*app, "package-lock.json"))["packages"]
            for name, version in {**pkg["dependencies"], **pkg["devDependencies"]}.items():
                with self.subTest(app=app, package=name):
                    self.assertRegex(version, r"^\d+\.\d+\.\d+$", "an exact version, no range")
                    self.assertEqual(lock["node_modules/" + name]["version"], version, "the lockfile agrees")

    def test_the_research_store_image_is_a_version(self):
        image = re.search(r"(?m)^\s*image:\s*(\S+)$", read("plugins", "comms-engine", "research-store", "docker-compose.yml")).group(1)
        self.assertRegex(image, r"^falkordb/falkordb:\d[\w.-]*$")


class Workflow(unittest.TestCase):
    def test_ci_runs_what_a_person_runs(self):
        ci = read(".github", "workflows", "ci.yml")
        for must in ("python -m pip install -r requirements.txt -r requirements-dev.txt", "ruff check plugins Tooling",
                     "python -m unittest discover plugins/comms-engine/tests", "npx tsc --noEmit", "npm run build", "npm test",
                     'git status --porcelain -- dist', "npm audit --audit-level=high", "contents: read"):
            self.assertIn(must, ci)
        self.assertNotRegex(ci, r"secrets\.", "the suite runs on fixtures: no job needs a secret")


class Licence(unittest.TestCase):
    def test_the_licence_is_the_unmodified_apache_2_text(self):
        import hashlib
        with open(os.path.join(REPO, "LICENSE"), "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        # the text as apache.org publishes it (LICENSE-2.0.txt); an edited licence is another licence
        self.assertEqual(digest, "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30")
        self.assertIn("Apache License 2.0: see `LICENSE`", read("README.md"))


#: dated history that names Notion as it was, and the desk's `notion_url` column, which only a
#: migration can drop (desk_sync.py no longer fills it)
NOTION_HISTORY = re.compile(r"(^|/)PLAN[^/]*\.md$|^TEMPLATE-CONTRACT\.md$|^\.atelier/memory/decisions/|^\.gg/"
                            r"|^Tooling/desk/(drizzle/|db/schema\.ts$)"
                            r"|^plugins/comms-engine/tests/test_repo_standards\.py$")


class NoNotion(unittest.TestCase):
    def test_no_current_file_names_notion(self):
        try:
            out = subprocess.run(["git", "-C", REPO, "ls-files", "-co", "--exclude-standard", "-z"],
                                 capture_output=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("not a git checkout")
        hits = []
        for rel in out.decode("utf-8").split("\0"):
            if (not rel or NOTION_HISTORY.search(rel) or "/dist/" in rel or "node_modules" in rel
                    or os.path.islink(os.path.join(REPO, rel))):  # .claude/ links: the canonical copy is read
                continue
            try:
                text = read(rel)
            except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
                continue
            hits += [f"{rel}:{n}" for n, line in enumerate(text.splitlines(), 1) if "notion" in line.lower()]
        self.assertEqual(hits, [], "Notion is retired; these still name it:\n" + "\n".join(hits))


class ThePluginStandsAlone(unittest.TestCase):
    """Since step 19 the engine is the comms-engine plugin, installed wherever Claude Code puts it:
    nothing in it may still name the old engine paths, which exist in no instance."""

    OLD = ("Tooling/" + "social-engine", "Tooling/" + "deck-reader")

    def test_no_old_engine_path_in_the_plugin(self):
        hits = []
        try:  # what a clone carries; a gitignored local build is not the plugin's
            out = subprocess.run(["git", "-C", ENGINE, "ls-files", "-co", "--exclude-standard", "-z", "--", "."],
                                 capture_output=True, check=True).stdout
            paths = [os.path.join(ENGINE, p) for p in out.decode("utf-8").split("\0") if p]
        except (OSError, subprocess.CalledProcessError):
            paths = [os.path.join(b, n) for b, d, fs in os.walk(ENGINE) for n in fs]
        for path in paths:
            if any(part in ("node_modules", "__pycache__", ".next") for part in path.split(os.sep)) or not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            hits += [f"{os.path.relpath(path, ENGINE)}: {old}" for old in self.OLD if old in text]
        self.assertEqual(hits, [])

    def test_the_manifest_and_the_marketplace_agree(self):
        manifest = json.loads(read("plugins", "comms-engine", ".claude-plugin", "plugin.json"))
        market = json.loads(read(".claude-plugin", "marketplace.json"))
        entry = next(p for p in market["plugins"] if p["name"] == manifest["name"])
        self.assertEqual(manifest["name"], "comms-engine")
        self.assertEqual(entry["source"], "./plugins/comms-engine")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertFalse(os.path.exists(os.path.join(ENGINE, "workflows")), "workflows/ is Claude Code's, for .js workflows")
        setup = json.loads(read("package.json"))
        self.assertEqual(setup["version"], manifest["version"], "the npx setup command ships with the engine it sets up")


if __name__ == "__main__":
    unittest.main()

