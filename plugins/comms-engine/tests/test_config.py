"""
config.py: engine.json, engine.local.json and the environment, in that order.

- the three layers: local overrides a file default, the environment overrides both
- dotted paths: `cycle.drafts` and `params.cycle.drafts` are one key; a root
  (`streams`, `jobs`) is read as given; a missing key is the default (None), exit 1 on the CLI
- environment values are typed by what they override (int, bool, list)
- set_local writes engine.local.json and refuses `jobs`
- a params block's `job` (the job it belongs to, by name) is never overridden from
  the environment: the old autopilot launchd marker is gone and was never a job
- the brand block is config.brand(); labels and the environment prefix derive from
  it (tests/test_brand.py covers the derivations; here the fixture has no block, so
  it is the placeholder brand `acme`)
- show never prints a secret: engine.json holds the names only, and the merged
  document carries no value of a required secret even when one is exported
- the real engine.json has every section the contract names, with the eight jobs
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import config  # noqa: E402

BASE = {
    "path": "/usr/bin:__HOME__/.local/bin",
    "jobs": [{"name": "a", "program": ["/bin/zsh", "__REPO__/a.sh"]}],
    "params": {
        "cycle": {"job": "a", "drafts": 3, "budget_usd": 20, "listen": True, "weekday_flags": {"editor": True}},
        "corpus": {"root": "__HOME__/corpus", "include": [], "max": 8},
        "secrets": {"required": ["APIFY_TOKEN"]},
    },
    "streams": {"acme": {"corpus_root": "__HOME__/corpus", "themes_file": "themes.json"}},
}


class Layers(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.base = os.path.join(self.dir, "engine.json")
        self.local = os.path.join(self.dir, "engine.local.json")
        with open(self.base, "w") as f:
            json.dump(BASE, f)

    def get(self, path, env=None, **kw):
        return config.cfg(path, env=env or {}, base=self.base, local=self.local, home="/home/someone", **kw)

    def test_file_default_then_local_then_env(self):
        self.assertEqual(self.get("cycle.drafts"), 3)
        config.set_local("cycle.drafts", 5, local=self.local)
        self.assertEqual(self.get("cycle.drafts"), 5)
        self.assertEqual(self.get("cycle.drafts", env={"ACME_CYCLE_DRAFTS": "7"}), 7)
        # the other keys of the section survive a local override of one
        self.assertEqual(self.get("cycle.budget_usd"), 20)

    def test_dotted_paths_and_roots(self):
        self.assertEqual(self.get("params.cycle.drafts"), self.get("cycle.drafts"))
        self.assertEqual(config.keys_for("cycle.drafts"), ["params", "cycle", "drafts"])
        self.assertEqual(config.keys_for("streams.acme.corpus_root"), ["streams", "acme", "corpus_root"])
        # the prefix is the brand's in the files named; the fixture has no block, so the placeholder's
        self.assertEqual(config.env_name("cycle.budget_usd", self.base, self.local), "ACME_CYCLE_BUDGET_USD")
        self.assertEqual(config.env_name("params.corpus.root", self.base, self.local), "ACME_CORPUS_ROOT")
        self.assertEqual(config.env_name("streams.acme.corpus_root", self.base, self.local), "ACME_STREAMS_ACME_CORPUS_ROOT")
        self.assertEqual(self.get("cycle.weekday_flags.editor"), True)
        self.assertIsNone(self.get("cycle.nothing"))
        self.assertEqual(self.get("cycle.nothing", default=9), 9)

    def test_env_is_typed_and_expanded(self):
        self.assertIs(self.get("cycle.listen", env={"ACME_CYCLE_LISTEN": "off"}), False)
        self.assertIs(self.get("cycle.listen", env={"ACME_CYCLE_LISTEN": "1"}), True)
        self.assertEqual(self.get("corpus.include", env={"ACME_CORPUS_INCLUDE": "a, b"}), ["a", "b"])
        self.assertEqual(self.get("corpus.max", env={"ACME_CORPUS_MAX": "2"}), 2)
        self.assertEqual(self.get("corpus.root"), "/home/someone/corpus")
        self.assertEqual(self.get("corpus.root", env={"ACME_CORPUS_ROOT": "/Volumes/x"}), "/Volumes/x")
        # a whole section comes back with the environment applied to its leaves
        sec = self.get("cycle", env={"ACME_CYCLE_WEEKDAY_FLAGS_EDITOR": "false", "ACME_CYCLE_DRAFTS": "1"})
        self.assertEqual(sec["drafts"], 1)
        self.assertIs(sec["weekday_flags"]["editor"], False)
        self.assertEqual(sec["budget_usd"], 20)
        # a default is typed too when the file has no key
        self.assertEqual(self.get("cycle.extra", env={"ACME_CYCLE_EXTRA": "4"}, default=0), 4)

    def test_job_key_is_metadata_not_a_parameter(self):
        env = {"ACME_CYCLE_JOB": "1", "ACME_CYCLE_DRAFTS": "4"}
        self.assertEqual(self.get("cycle.job", env=env), "a")
        block = config.params("cycle", env=env, base=self.base, local=self.local, home="/home/someone")
        self.assertEqual(block["job"], "a")
        self.assertEqual(block["drafts"], 4)  # the other leaves still take the environment
        self.assertEqual(config.show(env=env, base=self.base, local=self.local, home="/home/someone")["params"]["cycle"]["job"], "a")

    def test_jobs_streams_and_set_local(self):
        self.assertEqual(config.jobs(base=self.base)[0]["program"][1], "__REPO__/a.sh")
        self.assertEqual(config.job("a", base=self.base)["label"], "com.acme.a")
        self.assertEqual(config.job("com.acme.a", base=self.base)["name"], "a")
        with self.assertRaises(config.ConfigError):
            config.job("none", base=self.base)
        st = config.streams(env={}, base=self.base, local=self.local, home="/home/someone")
        self.assertEqual(st["acme"]["corpus_root"], "/home/someone/corpus")
        config.set_local("streams.beta.corpus_root", "/z", local=self.local)
        st = config.streams(env={}, base=self.base, local=self.local, home="/home/someone")
        self.assertEqual(st["beta"]["corpus_root"], "/z")
        self.assertEqual(st["acme"]["themes_file"], "themes.json")
        with open(self.local) as f:
            self.assertEqual(json.load(f), {"streams": {"beta": {"corpus_root": "/z"}}})
        with self.assertRaises(config.ConfigError):
            config.set_local("jobs", [], local=self.local)
        # a local file that names jobs anyway is ignored, not merged
        with open(self.local, "w") as f:
            json.dump({"jobs": [], "params": {"cycle": {"drafts": 2}}}, f)
        self.assertEqual(len(config.load(self.base, self.local)["jobs"]), 1)
        self.assertEqual(self.get("cycle.drafts"), 2)

    def test_show_holds_no_secret(self):
        out = config.show(env={"APIFY_TOKEN": "sekrit-value-123", "ACME_CYCLE_DRAFTS": "4"},
                          base=self.base, local=self.local, home="/home/someone")
        blob = json.dumps(out)
        self.assertNotIn("sekrit-value-123", blob)
        self.assertEqual(out["params"]["cycle"]["drafts"], 4)
        self.assertEqual(out["params"]["secrets"]["required"], ["APIFY_TOKEN"])
        self.assertEqual(out["path"], "/usr/bin:/home/someone/.local/bin")


class RealFile(unittest.TestCase):
    def test_engine_json_shape(self):
        with open(config.ENGINE_JSON) as f:
            doc = json.load(f)
        self.assertEqual(len(doc["jobs"]), 12)
        for sec in ("corpus", "cycle", "autopilot", "engagement", "score", "claims_check", "x_stream", "store", "secrets", "plugins"):
            self.assertIn(sec, doc["params"], sec)
        self.assertEqual(set(doc["streams"]), {doc["brand"]["slug"]}, "the streams key is the brand's slug")
        labels = {j["name"] for j in doc["jobs"]}
        for sec, block in doc["params"].items():
            if "job" in block:
                self.assertIn(block["job"], labels, sec)
        blob = json.dumps(doc)
        self.assertNotIn("/" + "Users/", blob)
        for name in doc["params"]["secrets"]["required"] + doc["params"]["secrets"]["optional"]:
            self.assertRegex(name, r"^[A-Z][A-Z0-9_]+$")

    def test_cli_get_with_env_winning(self):
        script = os.path.join(ENGINE, "scripts", "config.py")
        prefix = config.brand()["env_prefix"]  # the checkout's own, whatever init stamped
        env = {k: v for k, v in os.environ.items() if not k.startswith(prefix)}
        out = subprocess.run([sys.executable, script, "get", "cycle.budget_usd"], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        # The CLI agrees with the API on this checkout: the tracked 20 unless an
        # engine.local.json (engine.py setup cycle) says otherwise on this machine.
        expected = config.cfg("cycle.budget_usd", env={})
        self.assertEqual(out.stdout.strip(), str(expected))
        if not os.path.exists(config.LOCAL_JSON):
            self.assertEqual(expected, 20)
        out = subprocess.run([sys.executable, script, "get", "cycle.budget_usd"], capture_output=True, text=True,
                             env={**env, prefix + "CYCLE_BUDGET_USD": "5"})
        self.assertEqual(out.stdout.strip(), "5")
        out = subprocess.run([sys.executable, script, "get", "cycle.listen"], capture_output=True, text=True, env=env)
        self.assertEqual(out.stdout.strip(), "true" if config.cfg("cycle.listen", env={}) else "false")
        out = subprocess.run([sys.executable, script, "get", "nowhere.at_all"], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 1)
        out = subprocess.run([sys.executable, script, "show"], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0)
        self.assertIn("params", json.loads(out.stdout))

    def test_shell_scripts_read_config(self):
        for rel in ("plugins/comms-engine/scripts/cycle.sh", "plugins/comms-engine/skills/deck-reader/scripts/corpus_cycle_daily.sh"):
            with open(os.path.join(os.path.dirname(os.path.dirname(ENGINE)), rel), encoding="utf-8") as f:
                text = f.read()
            self.assertRegex(text, r'config\.py"? get', rel)
        with open(os.path.join(ENGINE, "scripts", "cycle.sh"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("CYCLE_BUDGET_USD", text)
        self.assertIn("brand env_prefix", text, "the shell asks config.py for the prefix once")
        with open(os.path.join(os.path.dirname(os.path.dirname(ENGINE)), "plugins/comms-engine/skills/deck-reader/scripts/corpus_cycle_daily.sh"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("CORPUS_ROOT", text)
        self.assertIn("CORPUS_BUDGET_USD", text)
        self.assertIn("brand env_prefix", text)


if __name__ == "__main__":
    unittest.main()


BRAND_FILE = {
    "_about": "a note",
    "brand": {"slug": "zeta", "name": "Zeta"},
    "streams": {"zeta": {"name": "Zeta", "owner": "unset", "autopilot": "nothing",
                         "review": {"post": "review", "like": "auto"}, "drivers": {"x_read": "composio"}}},
    "drivers": {"write": "composio", "x_read": "twitterapi"},
    "jobs": {"a": False},
    "plugins": {"roles": {}},
}


class BrandFile(unittest.TestCase):
    """brand.json: merged between engine.json and engine.local.json, checked on load by validate.

    - a fixture without a brand.json reads as before; the file beside engine.json is merged when there
    - the slug it names re-keys engine.json's placeholder defaults, and the rest of the brand derives from it
    - `drivers` and `jobs` land where the scripts already read them; engine.local.json and the environment still win
    - validate names the key and the fix for an unknown key, a wrong type and a missing stream
    - the shipped brand.json and brand.example.json are clean
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.base = os.path.join(self.dir, "engine.json")
        self.local = os.path.join(self.dir, "engine.local.json")
        self.brand = os.path.join(self.dir, "brand.json")
        with open(self.base, "w") as f:
            json.dump(BASE, f)

    def write(self, doc):
        with open(self.brand, "w") as f:
            json.dump(doc, f)

    def get(self, path, env=None, **kw):
        return config.cfg(path, env=env or {}, base=self.base, local=self.local, home="/home/someone", **kw)

    def test_the_file_is_found_beside_a_fixture_and_in_the_instance(self):
        self.assertEqual(config.brand_path(self.base), self.brand)
        self.assertEqual(config.brand_path(config.SHIPPED_ENGINE_JSON),
                         os.path.join(config.paths.instance(), "brand.json"),
                         "the engine's own engine.json reads the instance's brand.json")
        self.assertEqual(config.brand_path(), os.path.join(config.REPO, "brand.json"))

    def test_no_file_changes_nothing(self):
        self.assertEqual(config.load(self.base, self.local), BASE)
        self.assertEqual(config.validate(self.base, self.local), [])

    def test_merge_order_and_the_rekeyed_defaults(self):
        self.write(BRAND_FILE)
        b = config.brand(self.base, self.local)
        self.assertEqual((b["slug"], b["name"], b["label_prefix"], b["env_prefix"], b["keychain_service"]),
                         ("zeta", "Zeta", "com.zeta", "ZETA_", "zeta-comms"))
        st = config.streams(env={}, base=self.base, local=self.local, home="/home/someone")
        self.assertEqual(list(st), ["zeta"], "engine.json's placeholder key follows the brand's slug")
        self.assertEqual(st["zeta"]["corpus_root"], "/home/someone/corpus")
        self.assertEqual(st["zeta"]["owner"], "unset")
        self.assertEqual(st["zeta"]["review"]["like"], "auto")
        self.assertNotIn("drivers", st["zeta"])
        self.assertEqual(self.get("channels.write_driver.zeta"), "composio")
        self.assertEqual(self.get("channels.x_read.zeta"), "composio", "a stream's own driver outranks the file's")
        # the file outranks engine.json, engine.local.json outranks the file, the environment outranks both
        config.set_local("streams.zeta.autopilot", "by switch", local=self.local)
        self.assertEqual(self.get("streams.zeta.autopilot"), "by switch")
        self.assertEqual(self.get("streams.zeta.autopilot", env={"ZETA_STREAMS_ZETA_AUTOPILOT": "nothing"}), "nothing")
        self.assertEqual(self.get("cycle.drafts"), 3, "what the file does not name keeps engine.json's default")

    def test_jobs_on_and_off(self):
        self.write(BRAND_FILE)
        j = config.jobs(self.base)[0]
        self.assertTrue(j["optional"] and j["off"])
        self.assertEqual(j["label"], "com.zeta.a")
        self.assertEqual(config.labels(self.base, optional=True), ["com.zeta.a"])
        self.write({**BRAND_FILE, "jobs": {"a": True}})
        self.assertNotIn("optional", config.jobs(self.base)[0])

    def test_the_same_slug_keeps_the_names_engine_json_carries(self):
        with open(self.base, "w") as f:
            json.dump({**BASE, "brand": {"slug": "zeta", "name": "Old", "label_prefix": "org.zeta", "env_prefix": "ZT_",
                                         "keychain_service": "zeta-keys"}}, f)
        self.write(BRAND_FILE)
        b = config.brand(self.base, self.local)
        self.assertEqual((b["name"], b["label_prefix"], b["env_prefix"]), ("Zeta", "org.zeta", "ZT_"))

    def test_validate_names_the_key_and_the_fix(self):
        bad = json.loads(json.dumps(BRAND_FILE))
        bad["colour"] = "red"
        bad["streams"]["zeta"]["owner"] = "the founder"
        bad["streams"]["zeta"]["review"]["like"] = True
        bad["streams"]["zeta"]["posts_per_day"] = {"x": "two"}
        bad["streams"]["zeta"]["reactions_per_day"] = {"x": {"like": -1}}
        bad["jobs"] = {"a": "off", "nope": True}
        bad["drivers"]["write"] = "carrier-pigeon"
        self.write(bad)
        lines = config.validate(self.base, self.local)
        text = "\n".join(lines)
        for key in ("brand.json: colour: unknown key", "streams.zeta.owner:", "streams.zeta.review.like: True is not a mode",
                    "streams.zeta.posts_per_day.x:", "streams.zeta.reactions_per_day.x.like:", "jobs.a: must be true or false",
                    "jobs.nope: no such job", "drivers.write: 'carrier-pigeon' is not a driver"):
            self.assertIn(key, text)
        self.assertTrue(all(". Fix: " in ln for ln in lines), lines)

    def test_a_missing_stream_and_a_bad_slug_and_a_file_that_does_not_parse(self):
        self.write({"brand": {"slug": "zeta"}, "streams": {"other": {"pair_rules": [{"to": "nobody", "rule": "x"}]}}})
        text = "\n".join(config.validate(self.base, self.local))
        self.assertIn("streams.zeta: missing stream", text)
        self.assertIn("pair_rules[0].to: 'nobody' is not a stream", text)
        self.write({"brand": {"slug": "Not A Slug"}, "streams": {}})
        self.assertIn("brand: slug 'Not A Slug'", "\n".join(config.validate(self.base, self.local)))
        with open(self.brand, "w") as f:
            f.write("{ not json")
        lines = config.validate(self.base, self.local)
        self.assertEqual(len(lines), 1)
        self.assertIn("does not parse as JSON", lines[0])
        with open(self.brand, "w") as f:
            json.dump(BRAND_FILE, f)
        with open(self.local, "w") as f:
            json.dump({"jobs": []}, f)
        self.assertIn("engine.local.json: jobs: ignored", "\n".join(config.validate(self.base, self.local)))

    def test_the_shipped_files_are_clean(self):
        self.assertEqual(config.validate(), [])
        root = os.path.dirname(os.path.dirname(ENGINE))
        with open(config.ENGINE_JSON) as f:
            doc = json.load(f)
        for name in ("brand.json", "brand.example.json"):
            with open(os.path.join(root, name)) as f:
                bdoc = json.load(f)
            self.assertEqual(config.brand_problems(bdoc, doc), [], name)
            self.assertIn("_about", bdoc, name)
            self.assertEqual(set(bdoc["jobs"]), {j["name"] for j in doc["jobs"]}, name)
        with open(os.path.join(root, "brand.json")) as f:
            self.assertLessEqual(len(f.read().splitlines()), 45, "the setup file stays small")

    def test_the_cli_validates(self):
        script = os.path.join(ENGINE, "scripts", "engine.py")
        out = subprocess.run([sys.executable, script, "validate"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("ok  brand.json", out.stdout)
