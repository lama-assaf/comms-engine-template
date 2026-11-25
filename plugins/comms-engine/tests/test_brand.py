"""
The brand block: engine.json's `brand` is the one place the business is named,
and everything that used to spell a brand in code derives from it.

- config.brand() merges DEFAULT_BRAND, engine.json and engine.local.json, and
  normalises the prefixes (env_prefix ends with `_`, label_prefix has no dot)
- env_name derives <env_prefix><SECTION>_<KEY>; env_name_for the markers
- label and job_name are inverses; config.jobs() carries a derived label and
  resolves __ENV_PREFIX__ in a job's env; labels() lists them for the shell
- derive_brand fills a whole block from a slug and refuses a bad one
- engine.py init writes brand.json beside a temp engine.json (which it never
  edits), renders the root stream's streams.md cells from it, and is idempotent
- secrets.py takes the keychain service and the root stream from the brand
- the posting hook reads the marker from engine.json with json alone and falls
  back to the placeholder's marker when the file is unreadable
- memory.DEFAULT_STREAM is brand.slug; the shipped engine.json carries the
  placeholder and nothing of any real brand
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(ENGINE))
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, os.path.join(ENGINE, "schedule"))
sys.path.insert(0, os.path.join(ENGINE, "hooks"))

import config  # noqa: E402
import engine  # noqa: E402
import guard_posting  # noqa: E402
import memory  # noqa: E402
import render  # noqa: E402
import runjob  # noqa: E402

BASE = {
    "brand": {"slug": "zeta", "name": "Zeta Corp", "label_prefix": "org.zeta.", "env_prefix": "ZETA",
              "keychain_service": "zeta-keys"},
    "path": "/usr/bin",
    "jobs": [
        {"name": "social-engine", "program": ["/bin/zsh", "__REPO__/cycle.sh"]},
        {"name": "autopilot", "program": ["/usr/bin/env", "python3", "__REPO__/autopilot.py", "run"],
         "env": {"__ENV_PREFIX__JOB_FLAG": "1"}},
        {"name": "x-stream", "program": ["/bin/zsh", "-lc", "x"], "keep_alive": True, "optional": True},
    ],
    "params": {"cycle": {"job": "social-engine", "drafts": 3}, "secrets": {"required": [], "optional": []}},
    "streams": {"zeta": {"corpus_root": "__HOME__/corpus", "themes_file": "themes.json"}},
}

STREAMS_MD = """# streams

## registry

| slug | name | owner | autopilot | memory |
|---|---|---|---|---|
| zeta | Zeta Corp | confirmed | nothing | .atelier/memory |
| other | Other | unset | nothing | .atelier/memory/streams/other |

## pair rules

| from | to | rule |
|---|---|---|
| other | zeta | none recorded; Zeta Corp is named in prose here and stays |
"""

HANDLES_MD = """# handles

## own channels

| brand | platform | handle | status | themes | last_verified | note |
|---|---|---|---|---|---|---|
| Zeta Corp | X |  | collect | n/a: own channel | - | Zeta Corp is named in this prose cell and stays |
| Zeta Corp | LinkedIn |  | collect | n/a: own channel | - | - |
"""

CLAIMS_MD = """# claims

The example row is `C-zeta-0`; a real claim supersedes it.

| id | claim | grade |
|---|---|---|
| C-zeta-0 | Example row | asserted |
| C-zetamore-1 | Not this register's id shape; left alone | asserted |
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.base = os.path.join(self.dir, "engine.json")
        self.local = os.path.join(self.dir, "engine.local.json")
        self.streams = os.path.join(self.dir, "streams.md")
        with open(self.base, "w", encoding="utf-8") as f:
            json.dump(BASE, f)
        with open(self.streams, "w", encoding="utf-8") as f:
            f.write(STREAMS_MD)
        # init looks for handles.md and claims.md beside streams.md
        self.handles = os.path.join(self.dir, "handles.md")
        self.claims = os.path.join(self.dir, "claims.md")
        with open(self.handles, "w", encoding="utf-8") as f:
            f.write(HANDLES_MD)
        with open(self.claims, "w", encoding="utf-8") as f:
            f.write(CLAIMS_MD)

    def brand(self):
        return config.brand(self.base, self.local)


class Brand(Fixture):
    def test_merged_and_normalised(self):
        b = self.brand()
        self.assertEqual(b["slug"], "zeta")
        self.assertEqual(b["name"], "Zeta Corp")
        self.assertEqual(b["env_prefix"], "ZETA_", "a prefix without the underscore gets one")
        self.assertEqual(b["label_prefix"], "org.zeta", "a trailing dot is dropped")
        self.assertEqual(b["keychain_service"], "zeta-keys")

    def test_local_overrides_one_key_and_defaults_fill_the_rest(self):
        config.set_local("brand.keychain_service", "zeta-local", local=self.local)
        self.assertEqual(self.brand()["keychain_service"], "zeta-local")
        self.assertEqual(self.brand()["slug"], "zeta")
        with open(self.base, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in BASE.items() if k != "brand"}, f)
        b = config.brand(self.base, os.path.join(self.dir, "none.json"))
        self.assertEqual(b, config.DEFAULT_BRAND, "a file without the block is the placeholder brand")

    def test_an_empty_field_is_refused(self):
        with open(self.base, "w", encoding="utf-8") as f:
            json.dump({**BASE, "brand": {**BASE["brand"], "slug": ""}}, f)
        with self.assertRaises(config.ConfigError):
            self.brand()

    def test_brand_is_never_read_from_the_environment(self):
        env = {"ACME_BRAND_SLUG": "evil", config.ENV_PREFIX + "BRAND_SLUG": "evil"}
        self.assertEqual(config.cfg("brand.slug", env=env, base=self.base, local=self.local), "zeta")

    def test_env_and_label_prefixes_are_validated(self):
        # env_prefix: a shell identifier prefix, upper-cased for the caller
        self.assertEqual(config.derive_brand("my-brand")["env_prefix"], "MY_BRAND_")
        self.assertEqual(config.derive_brand("mb", env_prefix="mb")["env_prefix"], "MB_", "lower-case input is upper-cased")
        for bad in ("my-brand", "1ab", "a b", "a.b"):
            with self.assertRaises(config.ConfigError, msg=bad):
                config.derive_brand("north", env_prefix=bad)
        # label_prefix: reverse-DNS, lower-case
        self.assertEqual(config.derive_brand("north", label_prefix="org.example.north.")["label_prefix"], "org.example.north")
        for bad in ("Com Acme", "com..acme", "COM.ACME", "com.1acme", "com/acme"):
            with self.assertRaises(config.ConfigError, msg=bad):
                config.derive_brand("north", label_prefix=bad)
        # the same rules bind a block read from a file
        with open(self.base, "w", encoding="utf-8") as f:
            json.dump({**BASE, "brand": {"slug": "zeta", "name": "Zeta", "label_prefix": "Com Zeta",
                                          "env_prefix": "ZETA_", "keychain_service": "zeta-comms"}}, f)
        with self.assertRaises(config.ConfigError):
            self.brand()
        with open(self.base, "w", encoding="utf-8") as f:
            json.dump({**BASE, "brand": {"slug": "zeta", "name": "Zeta", "label_prefix": "com.zeta",
                                          "env_prefix": " zeta ", "keychain_service": "zeta-comms"}}, f)
        self.assertEqual(self.brand()["env_prefix"], "ZETA_", "stripped and upper-cased on read, as the hook does")

    def test_derive_brand_fills_from_the_slug_and_refuses_a_bad_one(self):
        b = config.derive_brand("my-co")
        self.assertEqual(b, {"slug": "my-co", "name": "My-co", "label_prefix": "com.my-co",
                             "env_prefix": "MY_CO_", "keychain_service": "my-co-comms"})
        b = config.derive_brand("myco", name="My Co", label_prefix="li.myco.", env_prefix="MC", keychain_service="k")
        self.assertEqual((b["name"], b["label_prefix"], b["env_prefix"], b["keychain_service"]), ("My Co", "li.myco", "MC_", "k"))
        for bad in ("", "A", "Acme", "1acme", "a", "with space", "x" * 25, "brand!", None):
            with self.assertRaises(config.ConfigError, msg=repr(bad)):
                config.derive_brand(bad)


class Derivations(Fixture):
    def test_env_names(self):
        self.assertTrue(config.ENV_PREFIX.endswith("_"))
        self.assertEqual(config.env_name("cycle.budget_usd"), config.ENV_PREFIX + "CYCLE_BUDGET_USD")
        self.assertEqual(config.env_name("params.corpus.root"), config.ENV_PREFIX + "CORPUS_ROOT")
        self.assertEqual(config.env_name("streams.acme.corpus_root"), config.ENV_PREFIX + "STREAMS_ACME_CORPUS_ROOT")
        self.assertEqual(config.env_name_for("REPO", self.base, self.local), "ZETA_REPO")
        self.assertEqual(config.env_name_for("job_flag", self.base, self.local), "ZETA_JOB_FLAG")

    def test_labels_and_names_are_inverses(self):
        self.assertEqual(config.label("social-engine", self.base, self.local), "org.zeta.social-engine")
        self.assertEqual(config.label("org.zeta.social-engine", self.base, self.local), "org.zeta.social-engine")
        self.assertEqual(config.job_name("org.zeta.score", self.base, self.local), "score")
        self.assertEqual(config.job_name("score", self.base, self.local), "score")
        self.assertEqual(config.labels(self.base, self.local), ["org.zeta.social-engine", "org.zeta.autopilot", "org.zeta.x-stream"])
        self.assertEqual(config.labels(self.base, self.local, optional=True), ["org.zeta.x-stream"])
        self.assertEqual(config.labels(self.base, self.local, optional=False), ["org.zeta.social-engine", "org.zeta.autopilot"])

    def test_jobs_carry_a_derived_label_and_the_resolved_env(self):
        jobs = config.jobs(self.base, self.local)
        self.assertEqual([j["label"] for j in jobs], config.labels(self.base, self.local))
        auto = config.job("autopilot", self.base, self.local)
        self.assertEqual(auto["env"], {"ZETA_JOB_FLAG": "1"})
        self.assertEqual(config.job("org.zeta.autopilot", self.base, self.local)["name"], "autopilot")
        with self.assertRaises(config.ConfigError):
            config.job("nowhere", self.base, self.local)
        with open(self.base, "w", encoding="utf-8") as f:
            json.dump({**BASE, "jobs": [{"label": "org.zeta.pinned", "program": ["x"]}]}, f)
        with self.assertRaises(config.ConfigError, msg="a job without a name has no label to derive"):
            config.jobs(self.base, self.local)

    def test_log_dir_follows_the_slug(self):
        self.assertEqual(config.log_dir("/home/someone", self.base, self.local), "/home/someone/Library/Logs/zeta-comms")

    def test_cli_prints_the_derivations(self):
        for argv, expect in ((["brand", "slug"], config.brand()["slug"]),
                             (["env-name", "cycle.budget_usd"], config.ENV_PREFIX + "CYCLE_BUDGET_USD"),
                             (["label", "social-engine"], config.label("social-engine")),
                             (["log-dir"], config.log_dir())):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = config.main(argv)
            self.assertEqual(rc, 0, argv)
            self.assertEqual(out.getvalue().strip(), expect, argv)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(config.main(["labels"]), 0)
        self.assertEqual(out.getvalue().split(), config.labels())
        self.assertEqual(config.main(["brand", "nothing"]), 1)

    def test_render_and_runjob_use_the_brand(self):
        out = os.path.join(self.dir, "plists")
        render.render_all(out, repo="/r", home="/home/someone", jobs_path=self.base)
        import plistlib
        with open(os.path.join(out, "org.zeta.autopilot.plist"), "rb") as f:
            plist = plistlib.load(f)
        env = plist["EnvironmentVariables"]
        self.assertEqual(env["COMMS_ENGINE_INSTANCE"], "/r", "a fixed name: the prefix lives inside the instance")
        self.assertEqual(env["ZETA_JOB_FLAG"], "1")
        self.assertEqual(plist["StandardOutPath"], "/home/someone/Library/Logs/zeta-comms/org.zeta.autopilot.log")
        self.assertEqual(plist["ProgramArguments"], ["/home/someone/.local/bin/comms-engine", "runjob", "org.zeta.autopilot"])
        spec = runjob.load_jobs(self.base)
        self.assertEqual([j["label"] for j in spec["jobs"]], config.labels(self.base, self.local))


class Init(Fixture):
    """`engine.py init` writes brand.json beside the fixture's engine.json and renders streams.md
    from it; engine.json itself is never edited."""

    def init(self, slug=None, **kw):
        return engine.init(slug, engine_json=self.base, streams_md=self.streams, local=self.local, **kw)

    def read(self):
        with open(os.path.join(self.dir, "brand.json"), encoding="utf-8") as f:
            doc = json.load(f)
        with open(self.streams, encoding="utf-8") as f:
            return doc, f.read()

    def engine_json(self):
        with open(self.base, encoding="utf-8") as f:
            return json.load(f)

    def test_writes_the_setup_file_and_renders_the_root_stream(self):
        result = self.init("north", name="North Ltd")
        doc, md = self.read()
        self.assertEqual(doc["brand"], {"slug": "north", "name": "North Ltd"})
        self.assertEqual(self.engine_json(), BASE, "engine.json stays as shipped: nobody edits it")
        self.assertEqual(config.brand(self.base, self.local),
                         {"slug": "north", "name": "North Ltd", "label_prefix": "com.north",
                          "env_prefix": "NORTH_", "keychain_service": "north-comms"})
        merged = config.load(self.base, self.local)
        self.assertEqual(list(merged["streams"]), ["north", "other"], "the root stream's key follows the slug")
        self.assertEqual(merged["streams"]["north"]["corpus_root"], "__HOME__/corpus", "its settings are kept")
        self.assertEqual(list(doc["streams"]), ["north", "other"], "the registry kept by hand was imported")
        self.assertEqual(doc["streams"]["north"]["owner"], "confirmed")
        self.assertIn("| north | North Ltd | confirmed |", md)
        self.assertIn("| other | north | none recorded; Zeta Corp is named in prose here and stays |", md,
                      "only cells equal to the old slug or name change; prose does not")
        self.assertNotRegex(md, r"\| zeta \|")
        self.assertEqual(sorted(os.path.basename(p) for p in result["changed"]),
                         ["brand.json", "claims.md", "handles.md", "streams.md"])
        self.assertEqual(result["previous"]["slug"], "zeta")
        with open(self.handles, encoding="utf-8") as f:
            handles = f.read()
        self.assertIn("| North Ltd | X |", handles, "the own-channel brand cells follow the name")
        self.assertIn("Zeta Corp is named in this prose cell and stays", handles)
        with open(self.claims, encoding="utf-8") as f:
            claims = f.read()
        self.assertIn("| C-north-0 |", claims)
        self.assertIn("The example row is `C-north-0`", claims, "the id is renamed in prose too: it is an identifier")
        self.assertIn("C-zetamore-1", claims, "only this slug's ids change")

    def test_an_import_alone_changes_no_row(self):
        with open(self.streams, encoding="utf-8") as f:
            before = f.read()
        result = self.init("zeta", name="Zeta Corp")
        self.assertEqual([os.path.basename(p) for p in result["changed"]], ["brand.json"])
        self.assertEqual(self.read()[1], before, "a registry kept by hand is carried over cell for cell")

    def test_idempotent_and_restampable(self):
        self.init("north", name="North Ltd")
        doc1, md1 = self.read()
        again = self.init("north", name="North Ltd")
        self.assertEqual(again["changed"], [])
        self.assertEqual(self.read(), (doc1, md1))
        self.init("south")
        doc, md = self.read()
        self.assertEqual(doc["brand"]["name"], "South")
        self.assertEqual(list(doc["streams"]), ["south", "other"])
        self.assertIn("| south | South | confirmed |", md)
        self.assertNotIn("North Ltd", md.split("## pair rules")[0])

    def test_refuses_a_bad_slug_and_writes_nothing(self):
        with open(self.streams, encoding="utf-8") as f:
            before = f.read()
        for bad in ("North", "n", "2north", "north co"):
            with self.assertRaises(config.ConfigError, msg=bad):
                self.init(bad)
        with open(self.streams, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "brand.json")))

    def test_the_flags_and_the_first_commands(self):
        flags = engine._init_flags(["--slug", "north", "--name", "North Ltd", "--env-prefix", "NO"])
        self.assertEqual(flags, {"slug": "north", "name": "North Ltd", "env_prefix": "NO"})
        with self.assertRaises(engine.Refused):
            engine._init_flags(["--name", "x"], interactive=False)
        with self.assertRaises(engine.Refused):
            engine._init_flags(["--slug", "north", "--colour", "blue"])
        with self.assertRaises(engine.Refused, msg="--from takes no other flag"):
            engine._init_flags(["--from", "x.json", "--slug", "north"])
        self.assertEqual(engine._init_flags(["--from", "x.json"]), {"from_file": "x.json"})
        result = self.init("north", name="North Ltd", env_prefix="NO")
        self.assertEqual(self.read()[0]["brand"], {"slug": "north", "name": "North Ltd", "env_prefix": "NO_"},
                         "a name the flags override is written; the rest derives from the slug")
        lines = engine.init_lines(result)
        self.assertIn("brand  north  (North Ltd); labels com.north.<job>, environment NO_*, keychain service north-comms", lines[0])
        text = "\n".join(lines)
        for cmd in ("engine doctor", "engine setup corpus", "engine setup cycle", "engine enable"):
            self.assertIn(cmd, text)

    def test_a_terminal_is_asked_the_few_questions(self):
        answers = {"slug": "north", "name": "North Ltd", "narrator": "a newsroom", "X handle": "northltd", "LinkedIn": ""}
        asked = []

        def ask(prompt, default):
            asked.append(prompt)
            return next(v for k, v in answers.items() if prompt.startswith(k))

        flags = engine._init_flags([], interactive=True, ask=ask)
        self.assertEqual(len(asked), 5, "slug, name, narrator, X, LinkedIn and nothing more")
        self.assertEqual(flags, {"slug": "north", "name": "North Ltd", "narrator": "a newsroom", "x": "northltd"})
        self.init(**flags)
        root = self.read()[0]["streams"]["north"]
        self.assertEqual((root["narrator"], root["channels"]), ("a newsroom", {"x": "@northltd"}))

    def test_from_a_setup_file_with_no_questions(self):
        src = os.path.join(self.dir, "given.json")
        with open(src, "w", encoding="utf-8") as f:
            json.dump({"brand": {"slug": "north", "name": "North Ltd"},
                       "streams": {"north": {"owner": "unset", "autopilot": "nothing"},
                                   "other": {"name": "Other", "pair_rules": [{"to": "north", "rule": "cite only"}]}}}, f)
        result = self.init(from_file=src)
        self.assertEqual(result["brand"]["slug"], "north")
        doc, md = self.read()
        self.assertEqual(doc["brand"]["slug"], "north")
        self.assertIn("| north | North Ltd | unset | nothing | .atelier/memory |", md)
        self.assertIn("| other | north | cite only |", md)
        with open(src, "w", encoding="utf-8") as f:
            json.dump({"brand": {"slug": "north"}, "streams": {"north": {"owner": "the founder"}}}, f)
        with self.assertRaises(engine.Refused) as ctx:
            self.init(from_file=src)
        self.assertIn("streams.north.owner", str(ctx.exception))
        self.assertEqual(self.read()[0]["streams"]["north"]["owner"], "unset", "a file with a problem writes nothing")

    def test_cli_init_writes_the_setup_file_and_never_engine_json(self):
        with mock.patch.object(config, "ENGINE_JSON", self.base), \
             mock.patch.object(engine, "STREAMS_MD", self.streams), \
             mock.patch.object(config, "LOCAL_JSON", self.local):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = engine.main(["init", "--slug", "north", "--name", "North Ltd"])
        self.assertEqual(rc, 0)
        self.assertIn("wrote  ", out.getvalue())
        self.assertEqual(self.read()[0]["brand"]["slug"], "north")
        self.assertEqual(self.engine_json(), BASE)
        self.assertEqual(engine.main(["init", "--slug", "Bad"]), 1)


class ConsumersOfTheBrand(unittest.TestCase):
    def test_secrets_service_and_root_stream(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("engine_secrets", os.path.join(ENGINE, "scripts", "secrets.py"))
        sec = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sec)
        b = config.brand()
        self.assertEqual(sec.KEYCHAIN_SERVICE, b["keychain_service"])
        self.assertEqual(sec.set_command("X")[sec.set_command("X").index("-s") + 1], b["keychain_service"])
        self.assertEqual(sec.scoped_name("APIFY_TOKEN", b["slug"]), "APIFY_TOKEN")
        self.assertEqual(sec.scoped_name("APIFY_TOKEN", "other"), "other/APIFY_TOKEN")

    def test_memory_root_stream_is_the_brand(self):
        self.assertEqual(memory.DEFAULT_STREAM, config.brand()["slug"])
        self.assertEqual(memory.DEFAULT_STREAM_NAME, config.brand()["name"])
        self.assertEqual(memory.streams()[0], memory.DEFAULT_STREAM, "the first registry row is the root stream")
        self.assertEqual(memory.slug_for(memory.DEFAULT_STREAM_NAME), memory.DEFAULT_STREAM)

    def test_engine_short_map_and_loaded_filter(self):
        b = config.brand()
        for alias, name in engine.JOB_NAMES.items():
            self.assertEqual(engine.SHORT[alias], f"{b['label_prefix']}.{name}")
            self.assertEqual(engine.label_for(name), engine.SHORT[alias])
        self.assertEqual(engine.short_for(engine.SHORT["cycle"]), "cycle")
        self.assertEqual(engine.LAUNCHD_LOGS, config.log_dir())
        self.assertIn(f"--stream {b['slug']} ", " ".join(engine.DOCTOR_CHECKS))

    def test_hook_has_no_job_marker(self):
        self.assertFalse(hasattr(guard_posting, "MARKER"))
        self.assertFalse(hasattr(guard_posting, "autopilot_marker"))
        send = "engine autopilot post"
        self.assertIsNone(guard_posting.verdict(send, {}), "the sender passes: its sends go through channels.send()")
        self.assertIsNotNone(guard_posting.verdict("npx xurl post hi", {}))

    def test_shipped_engine_json_is_the_placeholder_and_names_no_brand(self):
        with open(config.ENGINE_JSON, encoding="utf-8") as f:
            text = f.read()
        doc = json.loads(text)
        if doc.get("brand", {}).get("slug") != config.DEFAULT_BRAND["slug"]:
            # the one test about the committed template; once `engine.py init`
            # has stamped a brand this checkout is no longer the template
            self.skipTest(f"engine.py init has run (brand {doc['brand'].get('slug')!r}); the placeholder check is for the template")
        self.assertEqual(doc["brand"], config.DEFAULT_BRAND)
        self.assertEqual(list(doc["streams"]), [doc["brand"]["slug"]])
        self.assertTrue(all("name" in j and "label" not in j for j in doc["jobs"]), "labels are derived, never written")
        for sec, block in doc["params"].items():
            if "job" in block:
                self.assertIn(block["job"], [j["name"] for j in doc["jobs"]], sec)
        self.assertNotRegex(text, "(?i)" + "|".join(("lt" + "in", "zil" + "liqa", "r3" + "to", "/Us" + "ers/", "One" + "Drive")))


if __name__ == "__main__":
    unittest.main()


class BrandJson(unittest.TestCase):
    """brand.json at the root names the brand; engine.json keeps the placeholder and is not edited."""

    def test_the_shipped_setup_file_carries_the_same_brand_as_engine_json(self):
        with open(os.path.join(REPO, "brand.json"), encoding="utf-8") as f:
            bdoc = json.load(f)
        self.assertEqual(bdoc["brand"]["slug"], config.brand()["slug"])
        self.assertEqual(list(bdoc["streams"])[0], bdoc["brand"]["slug"], "the brand's own stream comes first")
        row = bdoc["streams"][bdoc["brand"]["slug"]]
        if bdoc["brand"]["slug"] == "acme":
            self.assertEqual((row["owner"], row["autopilot"]), ("unset", "nothing"), "a fresh clone ships shut")
            self.assertEqual(set(row["review"].values()), {"review"}, "and with every kind waiting for a person")

    def test_a_setup_file_of_two_keys_is_a_whole_brand(self):
        d = tempfile.mkdtemp()
        try:
            base = os.path.join(d, "engine.json")
            with open(base, "w") as f:
                json.dump({**BASE, "brand": dict(config.DEFAULT_BRAND), "streams": {"acme": {"themes_file": "t.json"}},
                           "params": {**BASE["params"], "channels": {"auth_config": {"acme": {"x": "ac_1"}}}}}, f)
            with open(os.path.join(d, "brand.json"), "w") as f:
                json.dump({"brand": {"slug": "nova", "name": "Nova"}, "streams": {"nova": {"owner": "unset"}}}, f)
            self.assertEqual(config.brand(base), {"slug": "nova", "name": "Nova", "label_prefix": "com.nova",
                                                  "env_prefix": "NOVA_", "keychain_service": "nova-comms"})
            self.assertEqual(config.label("autopilot", base), "com.nova.autopilot")
            self.assertEqual(config.env_name("cycle.drafts", base), "NOVA_CYCLE_DRAFTS")
            doc = config.load(base, os.path.join(d, "none.json"))
            self.assertEqual(doc["streams"], {"nova": {"themes_file": "t.json", "owner": "unset"}})
            self.assertEqual(doc["params"]["channels"]["auth_config"], {"nova": {"x": "ac_1"}})
        finally:
            shutil.rmtree(d, ignore_errors=True)


class EnginePin(unittest.TestCase):
    """brand.json pins the comms-engine version; doctor fails when the loaded plugin is another."""

    def test_the_line_fails_on_another_version_and_passes_on_the_pinned_one(self):
        self.assertFalse(engine.engine_version_result(pinned="1.0.0", loaded="1.1.0")["ok"])
        self.assertIn("pins 1.0.0, the loaded plugin is 1.1.0", engine.engine_version_result(pinned="1.0.0", loaded="1.1.0")["tail"])
        self.assertTrue(engine.engine_version_result(pinned="1.1.0", loaded="1.1.0")["ok"])
        self.assertFalse(engine.engine_version_result(pinned="1.0.0", loaded="")["ok"], "an unreadable plugin is not the pinned one")

    def test_no_pin_is_reported_not_failed(self):
        r = engine.engine_version_result(pinned="", loaded="1.0.0")
        self.assertTrue(r["ok"])
        self.assertIn("not pinned", r["tail"])

    def test_the_shipped_files_pin_the_engine_they_ship_with(self):
        loaded = engine.engine_version()
        self.assertRegex(loaded, config.VERSION_RE)
        for name in ("brand.json", "brand.example.json"):
            with open(os.path.join(os.path.dirname(os.path.dirname(ENGINE)), name), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["engine"], {"version": loaded}, name)
        self.assertEqual(engine.engine_version_result()["ok"], True)

    def test_the_pin_is_validated(self):
        doc = {"jobs": []}
        base = {"brand": {"slug": "acme"}, "streams": {"acme": {"owner": "unset", "autopilot": "nothing"}}}
        self.assertEqual([k for k, _, _ in config.brand_problems({**base, "engine": {"version": "1.0.0"}}, doc)], [])
        for bad, key in (({"version": "one"}, "engine.version"), ({"version": 1}, "engine.version"),
                         ({"version": "1.0.0", "channel": "beta"}, "engine.channel"), ("1.0.0", "engine")):
            self.assertIn(key, [k for k, _, _ in config.brand_problems({**base, "engine": bad}, doc)], bad)
        over = config.brand_overlay({**base, "engine": {"version": "2.3.4", "_note": "x"}}, {})
        self.assertEqual(over["params"]["engine"], {"version": "2.3.4"})
