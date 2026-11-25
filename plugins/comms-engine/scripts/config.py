#!/usr/bin/env python3
"""
config.py - the one read path into engine.json.

Why: the engine's parameters used to live in four places (jobs.json, the
environment block of cycle.sh, corpus_cycle_daily.sh, the plists). engine.json
holds them all; this module layers the per-machine file and the environment
over it so a script asks `cfg("cycle.budget_usd", 20)` and gets the same answer
whether a person set it in the console, in engine.local.json, or exported
<ENV_PREFIX>CYCLE_BUDGET_USD in a shell. The environment wins, so nothing that
works today changes.

The brand block is the other thing this module owns. engine.json's `brand`
(slug, name, label_prefix, env_prefix, keychain_service) is the one place the
business this checkout serves is named; everything that used to spell a brand
in code derives it from here:

  job label               <label_prefix>.<job name>        label("social-engine")
  environment override    <env_prefix><SECTION>_<KEY>      env_name("cycle.budget_usd")
  the repo marker         <env_prefix>REPO                 env_name_for("REPO")
  keychain service        brand.keychain_service           brand()["keychain_service"]
  root stream             brand.slug                       memory.DEFAULT_STREAM
  launchd log directory   ~/Library/Logs/<slug>-comms      log_dir()

`engine.py init` is the one command that writes the block; a fresh clone
carries the placeholder `acme` / `Acme` until it runs.

Layers, lowest first:

  1. engine.json          tracked: the shipped defaults nobody edits, no machine
                          named
  2. brand.json           tracked, at the repository root: the one setup file of
                          a project (the brand, each stream, the drivers, which
                          jobs are on, the plugin roles), written by `engine.py
                          init` or the dashboard's Setup page. Its shape is its
                          own (see brand.example.json); `brand_overlay` turns it
                          into engine.json's shape before the merge, and
                          `validate` names the key and the fix for an unknown
                          key, a wrong type or a missing stream.
  3. engine.local.json    gitignored, beside engine.json: this machine's
                          overrides of `brand`, `params` and `streams` (never
                          `jobs`: a schedule is a tracked change)
  4. <ENV_PREFIX><SECTION>_<KEY>
                          the environment: the dotted path upper-cased with `_`
                          between segments, a leading `params.` dropped, so with
                          the shipped brand `cycle.budget_usd` reads
                          ACME_CYCLE_BUDGET_USD and `streams.acme.corpus_root`
                          ACME_STREAMS_ACME_CORPUS_ROOT. Typed by the value it
                          overrides (bool, int, float, comma-separated list,
                          JSON for a dict). The prefix itself is never read from
                          the environment: it comes from the file.

A path whose first segment is not a top-level section (`brand`, `jobs`,
`params`, `streams`, `path`) is read under `params`, so `cycle.drafts` and
`params.cycle.drafts` are the same key. A block's `job` key names the job it
belongs to (by job name) and is never overridden from the environment (it
names a job, not an environment variable). `__HOME__`, `__REPO__` (the instance) and
`__ENGINE__` (the engine's root) in a string are expanded on
read; `__ENV_PREFIX__` in a job's `env` keys becomes the brand's prefix. jobs()
returns the entries with their label derived and placeholders otherwise kept,
because render.py substitutes __REPO__, __ENGINE__ and __HOME__ itself. engine.json never
holds a secret, only the names of secrets (`params.secrets`): the values come
from scripts/secrets.py.

  engine config get cycle.budget_usd     # one value; bools print true/false
  engine config set corpus.root "/path"  # writes engine.local.json
  engine config show                     # the merged document as JSON
  engine config validate                 # brand.json checked: the key and the fix per problem
  engine config brand [slug|name|...]    # the brand block, or one field
  engine config env-name cycle.budget_usd   # ACME_CYCLE_BUDGET_USD
  engine config label social-engine      # com.acme.social-engine
  engine config labels [--optional|--required]   # every job's label, one per line
  engine config log-dir                  # ~/Library/Logs/<slug>-comms
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
REPO = paths.instance()
ENGINE_JSON = os.path.join(ENGINE, "engine.json")
#: The engine.json this module ships beside, whatever ENGINE_JSON is later pointed at.
SHIPPED_ENGINE_JSON = os.path.abspath(ENGINE_JSON)
LOCAL_JSON = paths.local_json()
#: brand.json, the project's setup file. None derives its place from the
#: engine.json being read (`brand_path`), so a fixture that points ENGINE_JSON
#: elsewhere never picks up this checkout's file; a test may name one outright.
BRAND_JSON = None
#: What brand.json may hold at its top level (keys starting with `_` are notes).
BRAND_FILE_KEYS = ("brand", "engine", "streams", "drivers", "jobs", "plugins")
#: The engine version a brand.json may pin: major.minor.patch, an optional pre-release or build after it.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
#: The kinds of send a review mode is set for, and the two modes. `hold` is the
#: statistics, partner and certification class of standing rule 4.
REVIEW_KINDS = ("post", "reply", "comment", "like", "repost", "quote", "hold")
REVIEW_MODES = ("review", "auto")
#: The channels a stream may list in brand.json, by key.
CHANNEL_KEYS = ("x", "linkedin", "telegram", "discord", "website")
REACTION_KINDS = ("like", "repost", "quote")
#: brand.json `drivers` key -> (the params.channels map it sets, the values it may take).
DRIVER_KEYS = {
    "write": ("write_driver", ("native", "composio")),
    "x_read": ("x_read", ("twitterapi", "composio")),
    "x_own": ("x_own", ("twitterapi", "composio")),
}
#: The placeholder brand a fresh clone carries; also what a file without a
#: `brand` block (a test fixture) resolves to, so every derivation has an answer.
DEFAULT_BRAND = {
    "slug": "acme",
    "name": "Acme",
    "label_prefix": "com.acme",
    "env_prefix": "ACME_",
    "keychain_service": "acme-comms",
}
BRAND_KEYS = tuple(DEFAULT_BRAND)
#: What `engine.py init` accepts as a slug: lower-case, starts with a letter,
#: 2 to 24 characters of [a-z0-9-]. A slug is a launchd label segment, a
#: directory name under streams/ and a registry key, so it stays this plain.
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,23}$")
#: An env_prefix is a shell identifier prefix: upper-case, a letter first, ends
#: with `_`, so `<prefix>REPO` can be exported by a shell and read by zsh's
#: `${(P)v}`. Lower-case input is upper-cased before the check.
ENV_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9_]*_$")
#: A label_prefix is reverse-DNS: lower-case dot-separated segments, each a
#: letter first, so the derived launchd label stays a plain identifier.
LABEL_PREFIX_RE = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)*$")
#: Top-level sections; any other first segment is read under `params`.
ROOTS = ("brand", "jobs", "params", "streams", "path")
#: Sections engine.local.json may not override.
LOCAL_FROZEN = ("jobs", "path")

_MISSING = object()


def _paths(base, local):
    """The files a read uses: the module's current ENGINE_JSON / LOCAL_JSON unless given.

    Resolved at call time, not in the signature, so a caller that points
    `config.ENGINE_JSON` elsewhere (the test fixture, a second checkout) is
    honoured by every function here.
    """
    return (ENGINE_JSON if base is None else base, LOCAL_JSON if local is None else local)


class ConfigError(KeyError):
    """An unknown job, a bad brand value, or a per-machine write into a tracked section."""


# --- files -------------------------------------------------------------------

def _read_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _deep_merge(base, over):
    """Dicts merge key by key; anything else in `over` replaces."""
    if not isinstance(base, dict) or not isinstance(over, dict):
        return over
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(base.get(k), v) if k in base else v
    return out


def brand_path(base=None):
    """Where brand.json is for the engine.json being read.

    The instance's brand.json (paths.instance()) for the engine's own
    engine.json, the file beside engine.json otherwise (a fixture directory). BRAND_JSON,
    when a caller set it, names the file for the module's own ENGINE_JSON.
    """
    base = ENGINE_JSON if base is None else base
    if BRAND_JSON is not None and os.path.abspath(base) == os.path.abspath(ENGINE_JSON):
        return BRAND_JSON
    if os.path.abspath(base) == SHIPPED_ENGINE_JSON:
        return os.path.join(paths.instance(), "brand.json")
    return os.path.join(os.path.dirname(os.path.abspath(base)), "brand.json")


def read_brand_file(base=None):
    """brand.json as written, `{}` when there is none."""
    doc = _read_json(brand_path(base))
    return doc if isinstance(doc, dict) else {}


def _brand_block(bdoc, doc):
    """The whole brand block brand.json asks for, or None when it names no slug.

    The same slug as engine.json keeps engine.json's derived names and takes
    brand.json's keys over them; a new slug derives every name from itself, so
    a setup file of two keys (slug, name) is a complete brand.
    """
    b = bdoc.get("brand")
    if not isinstance(b, dict) or not isinstance(b.get("slug"), str) or not b["slug"].strip():
        return None
    given = {k: v for k, v in b.items() if k in BRAND_KEYS and isinstance(v, str) and v.strip()}
    shipped = dict(DEFAULT_BRAND)
    shipped.update({k: v for k, v in (doc.get("brand") or {}).items() if k in BRAND_KEYS})
    if given["slug"].strip() == str(shipped.get("slug", "")).strip():
        return _normalise({**shipped, **given})
    return derive_brand(given["slug"].strip(), given.get("name"), given.get("label_prefix"),
                        given.get("env_prefix"), given.get("keychain_service"))


def _rekey(doc, old, new):
    """engine.json's defaults keyed by the placeholder slug, carried under the brand's slug.

    `streams.<old>` and every map of `params.channels` keyed by `<old>` follow
    the rename, so engine.json itself is never edited to name a brand.
    """
    if old == new:
        return doc
    out = dict(doc)
    streams = doc.get("streams")
    if isinstance(streams, dict) and old in streams and new not in streams:
        out["streams"] = {(new if k == old else k): v for k, v in streams.items()}
    chan = (doc.get("params") or {}).get("channels")
    if isinstance(chan, dict):
        moved = {}
        for k, v in chan.items():
            if isinstance(v, dict) and old in v and new not in v:
                v = {(new if kk == old else kk): vv for kk, vv in v.items()}
            moved[k] = v
        out["params"] = {**doc["params"], "channels": moved}
    return out


def brand_overlay(bdoc, doc):
    """brand.json in engine.json's shape: what `load` merges over the defaults.

    `brand` becomes the whole derived block; `streams.<slug>` keeps its keys
    (narrator, owner, autopilot, review, the caps) beside the engine-local ones;
    `drivers` (the file's, then a stream's own) become
    `params.channels.{write_driver,x_read,x_own}.<slug>`; `jobs` (name: on or
    off) becomes `params.schedule.on`; `plugins` lands under `params.plugins`.
    Keys starting with `_` are notes and are dropped. A value of the wrong type
    is left out here and named by `validate`.
    """
    out = {}
    block = _brand_block(bdoc, doc)
    if block:
        out["brand"] = block
    params = {}
    streams = bdoc.get("streams")
    if isinstance(streams, dict):
        out["streams"] = {slug: {k: v for k, v in row.items() if not k.startswith("_") and k != "drivers"}
                          for slug, row in streams.items() if isinstance(row, dict) and not slug.startswith("_")}
        shared = bdoc.get("drivers") if isinstance(bdoc.get("drivers"), dict) else {}
        chan = {}
        for slug, row in streams.items():
            if not isinstance(row, dict) or slug.startswith("_"):
                continue
            own = row.get("drivers") if isinstance(row.get("drivers"), dict) else {}
            for key, (section, _allowed) in DRIVER_KEYS.items():
                value = own.get(key, shared.get(key))
                if isinstance(value, str) and value.strip():
                    chan.setdefault(section, {})[slug] = value.strip().lower()
        if chan:
            params["channels"] = chan
    on = bdoc.get("jobs")
    if isinstance(on, dict):
        params["schedule"] = {"on": {k: v for k, v in on.items() if isinstance(v, bool)}}
    plugins = bdoc.get("plugins")
    if isinstance(plugins, dict):
        params["plugins"] = {k: v for k, v in plugins.items() if not k.startswith("_")}
    pin = bdoc.get("engine")
    if isinstance(pin, dict):
        params["engine"] = {k: v for k, v in pin.items() if not k.startswith("_")}
    if params:
        out["params"] = params
    return out


def load(base=None, local=None):
    """engine.json, then brand.json, then engine.local.json; no environment yet."""
    base, local = _paths(base, local)
    doc = _read_json(base)
    bdoc = read_brand_file(base)
    if bdoc:
        over = brand_overlay(bdoc, doc)
        old = str((doc.get("brand") or {}).get("slug") or DEFAULT_BRAND["slug"])
        doc = _deep_merge(_rekey(doc, old, (over.get("brand") or {}).get("slug", old)), over)
    over = {k: v for k, v in _read_json(local).items() if k not in LOCAL_FROZEN}
    return _deep_merge(doc, over)


# --- the brand -----------------------------------------------------------------

def brand(base=None, local=None):
    """The brand block: DEFAULT_BRAND under engine.json's `brand`, brand.json's, then engine.local.json's.

    Every key is a non-empty string; env_prefix ends with `_` and label_prefix
    has no trailing dot, so the derivations below can concatenate blindly.
    """
    base, local = _paths(base, local)
    doc = load(base, local)
    b = dict(DEFAULT_BRAND)
    b.update({k: v for k, v in (doc.get("brand") or {}).items() if k in BRAND_KEYS})
    return _normalise(b)


def _normalise(b):
    """Strip, normalise and validate a brand block; ConfigError names the field at fault.

    The same rules hold for a block read from a file and one derive_brand
    builds, so a prefix the file carries is never looser than one `init` writes.
    """
    out = {}
    for k in BRAND_KEYS:
        v = b.get(k)
        if not isinstance(v, str) or not v.strip():
            raise ConfigError(f"brand.{k}: must be a non-empty string")
        out[k] = v.strip()
    out["env_prefix"] = out["env_prefix"].upper().rstrip("_") + "_"
    if not ENV_PREFIX_RE.match(out["env_prefix"]):
        raise ConfigError(f"brand.env_prefix {out['env_prefix']!r}: must match {ENV_PREFIX_RE.pattern} "
                          "(a shell identifier: letters, digits and underscores, a letter first)")
    out["label_prefix"] = out["label_prefix"].rstrip(".")
    if not LABEL_PREFIX_RE.match(out["label_prefix"]):
        raise ConfigError(f"brand.label_prefix {out['label_prefix']!r}: must match {LABEL_PREFIX_RE.pattern} "
                          "(reverse-DNS, lower-case, such as com.acme)")
    if not SLUG_RE.match(out["slug"]):
        raise ConfigError(f"brand.slug {out['slug']!r}: must match {SLUG_RE.pattern} (lower-case, a letter first, 2-24 chars)")
    return out


def derive_brand(slug, name=None, label_prefix=None, env_prefix=None, keychain_service=None):
    """A whole brand block from a slug and what was given; the rest follows the slug.

    Refuses a slug SLUG_RE does not accept: the slug becomes a label segment,
    a directory name and a registry key, so it stays plain.
    """
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise ConfigError(f"slug {slug!r}: must match {SLUG_RE.pattern} (lower-case, a letter first, 2-24 chars)")
    return _normalise({
        "slug": slug,
        "name": (name or "").strip() or slug.capitalize(),
        "label_prefix": (label_prefix or "").strip().rstrip(".") or f"com.{slug}",
        "env_prefix": ((env_prefix or "").strip().rstrip("_") or slug.replace("-", "_").upper()) + "_",
        "keychain_service": (keychain_service or "").strip() or f"{slug}-comms",
    })


#: The environment prefix of this checkout, read once at import for the module
#: constants other scripts build on (secrets.py, the hook's marker, the shells).
ENV_PREFIX = brand()["env_prefix"]


def env_name_for(suffix, base=None, local=None):
    """`<env_prefix><SUFFIX>` for a marker that is not a config path (REPO, WEBHOOK_SECRET)."""
    base, local = _paths(base, local)
    return brand(base, local)["env_prefix"] + str(suffix).upper()


def label(name, base=None, local=None):
    """A job's launchd label: `<label_prefix>.<name>`; a label passed in is returned as is."""
    base, local = _paths(base, local)
    prefix = brand(base, local)["label_prefix"] + "."
    return name if str(name).startswith(prefix) else prefix + str(name)


def job_name(label_or_name, base=None, local=None):
    """The job name of a label (`com.acme.score` -> `score`); a bare name is returned as is."""
    base, local = _paths(base, local)
    prefix = brand(base, local)["label_prefix"] + "."
    s = str(label_or_name)
    return s[len(prefix):] if s.startswith(prefix) else s


def log_dir(home=None, base=None, local=None):
    """Where launchd writes each job's own stdout: `~/Library/Logs/<slug>-comms`.

    Outside the repository because a path under ~/Desktop or ~/Documents is
    refused by macOS folder protection when launchd opens it.
    """
    base, local = _paths(base, local)
    home = home or os.path.expanduser("~")
    return os.path.join(home, "Library", "Logs", f"{brand(base, local)['slug']}-comms")


# --- paths and the environment -----------------------------------------------

def keys_for(path):
    """`cycle.drafts` -> ["params", "cycle", "drafts"]; a root stays as given."""
    parts = [p for p in str(path).split(".") if p]
    if not parts:
        raise ConfigError("empty path")
    if parts[0] not in ROOTS:
        parts = ["params", *parts]
    return parts


def env_name(path, base=None, local=None):
    """The environment variable that overrides a path (leading `params` dropped).

    The prefix is the brand's in the files given, so a read against another
    engine.json (a test fixture, a second checkout) names that file's variables.
    """
    base, local = _paths(base, local)
    parts = keys_for(path)
    if parts[0] == "params":
        parts = parts[1:]
    return brand(base, local)["env_prefix"] + "_".join(p.upper() for p in parts)


def _coerce(raw, like):
    """Type an environment string by the value it overrides (or the default)."""
    if isinstance(like, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(like, int):
        return int(raw)
    if isinstance(like, float):
        return float(raw)
    if isinstance(like, list):
        return [s.strip() for s in raw.split(",") if s.strip()]
    if isinstance(like, dict):
        return json.loads(raw)
    return raw


def _expand(value, home=None, repo=REPO):
    home = home or os.path.expanduser("~")
    if isinstance(value, str):
        return value.replace("__HOME__", home).replace("__REPO__", repo).replace("__ENGINE__", ENGINE)
    if isinstance(value, list):
        return [_expand(v, home, repo) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v, home, repo) for k, v in value.items()}
    return value


def _env_applies(parts):
    """`jobs` and `brand` are never overridden; a params block's `job` is metadata (the job name), not a parameter."""
    if parts[0] in ("jobs", "brand"):
        return False
    return not (parts[0] == "params" and len(parts) == 3 and parts[2] == "job")


def _apply_env(value, parts, env, prefix=None):
    """Overlay the environment on a value and, when it is a dict, on its leaves."""
    if not _env_applies(parts):
        return value
    prefix = ENV_PREFIX if prefix is None else prefix
    name = _env_name_with(prefix, parts)
    if name in env:
        return _coerce(env[name], value)
    if isinstance(value, dict):
        return {k: _apply_env(v, [*parts, k], env, prefix) for k, v in value.items()}
    return value


def _env_name_with(prefix, parts):
    parts = list(parts)
    if parts and parts[0] == "params":
        parts = parts[1:]
    return prefix + "_".join(p.upper() for p in parts)


def _walk(doc, parts):
    cur = doc
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return _MISSING
    return cur


# --- the API -----------------------------------------------------------------

def cfg(path, default=None, env=None, base=None, local=None, home=None):
    """One value by dotted path: the environment first, then the files, then `default`.

    A key nothing has returns `default` (None unless given); the CLI turns that
    into exit 1. An environment value is typed by the file's value, or by the
    default when the file has no key.
    """
    base, local = _paths(base, local)
    env = os.environ if env is None else env
    parts = keys_for(path)
    value = _walk(load(base, local), parts)
    prefix = brand(base, local)["env_prefix"]
    name = _env_name_with(prefix, parts) if _env_applies(parts) else None
    if name and name in env:
        like = value if value is not _MISSING else default
        return _expand(_coerce(env[name], like), home)
    if value is _MISSING:
        return default
    return _expand(_apply_env(value, parts, env, prefix), home)


def _with_label(j, b):
    """A job entry with `label` derived from its `name` and `__ENV_PREFIX__` in its env resolved."""
    if "name" not in j:
        raise ConfigError(f"a job without a `name` in engine.json: {j}")
    out = dict(j)
    out["label"] = b["label_prefix"] + "." + j["name"]
    if j.get("env"):
        out["env"] = {k.replace("__ENV_PREFIX__", b["env_prefix"]): v for k, v in j["env"].items()}
    return out


def jobs(base=None, local=None):
    """The `jobs` list with each label derived, the placeholders kept as render.py and runjob.py need them.

    brand.json's `jobs` (name: true or false) says which are on: a job set off
    is `optional` (the all-jobs install skips it) and carries `off: true`; a
    job set on is installed with the rest whatever engine.json's default says.
    """
    base, local = _paths(base, local)
    b = brand(base, local)
    on = read_brand_file(base).get("jobs")
    on = on if isinstance(on, dict) else {}
    out = []
    for j in _read_json(base).get("jobs", []):
        j = _with_label(j, b)
        want = on.get(j["name"])
        if want is False:
            j["optional"] = True
            j["off"] = True
        elif want is True:
            j.pop("optional", None)
        out.append(j)
    return out


def job(name_or_label, base=None, local=None):
    """One job by name or label; an unknown one raises, never defaults."""
    base, local = _paths(base, local)
    for j in jobs(base, local):
        if name_or_label in (j["name"], j["label"]):
            return j
    raise ConfigError(f"no job {name_or_label!r} in engine.json; jobs: {[j['name'] for j in jobs(base, local)]}")


def labels(base=None, local=None, optional=None):
    """Every job's label in file order; optional=True only the optional ones, False only the rest."""
    base, local = _paths(base, local)
    return [j["label"] for j in jobs(base, local)
            if optional is None or bool(j.get("optional")) is optional]


def streams(env=None, base=None, local=None, home=None):
    """`{slug: {corpus_root, themes_file, ...}}`, every override applied."""
    base, local = _paths(base, local)
    return cfg("streams", {}, env=env, base=base, local=local, home=home)


def params(section, env=None, base=None, local=None, home=None):
    """One job's whole `params` block, every override applied."""
    base, local = _paths(base, local)
    return cfg(f"params.{section}", {}, env=env, base=base, local=local, home=home)


def set_local(path, value, local=None):
    """Write one override into engine.local.json (created if absent) and return the file's content.

    `jobs` and `path` are refused: a schedule changes in engine.json, tracked.
    """
    local = _paths(None, local)[1]
    parts = keys_for(path)
    if parts[0] in LOCAL_FROZEN:
        raise ConfigError(f"{path}: `{parts[0]}` is tracked in engine.json, not overridden per machine")
    doc = _read_json(local)
    cur = doc
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value
    with open(local, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return doc


def show(env=None, base=None, local=None, home=None):
    """The merged document with every override applied: what the scripts will read."""
    base, local = _paths(base, local)
    env = os.environ if env is None else env
    doc = load(base, local)
    prefix = brand(base, local)["env_prefix"]
    out = {}
    for k, v in doc.items():
        if k.startswith("_"):
            continue
        if k == "jobs":
            out[k] = jobs(base, local)
        elif k == "brand":
            out[k] = brand(base, local)
        else:
            out[k] = _expand(_apply_env(v, [k], env, prefix), home)
    return out


# --- validation ----------------------------------------------------------------

def _is_count(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _stream_problems(slug, row, slugs):
    """What is wrong with one stream of brand.json: `(key, problem, fix)` rows."""
    out = []
    at = f"streams.{slug}"
    text_keys = ("name", "narrator", "objectives", "autopilot", "quiet_hours", "blocked_topics",
                 "hold_for_review", "memory", "corpus_root", "themes_file")
    known = text_keys + ("owner", "channels", "review", "drafts_only", "posts_per_day", "reactions_per_day",
                         "pair_rules", "drivers", "corpus_status")
    for k, v in row.items():
        if k.startswith("_"):
            continue
        if k not in known:
            out.append((f"{at}.{k}", "unknown key", f"remove it, or use one of: {', '.join(sorted(known))}"))
        elif k in text_keys and not isinstance(v, str):
            out.append((f"{at}.{k}", f"must be text, got {type(v).__name__}", 'write it in quotes, such as "nothing"'))
        elif isinstance(v, str) and ("|" in v or "\n" in v):
            out.append((f"{at}.{k}", "holds `|` or a line break, which a table cell of streams.md cannot", "reword it on one line without `|`"))
    if "owner" in row and row["owner"] not in ("confirmed", "unset"):
        out.append((f"{at}.owner", f"{row['owner']!r} is not one of confirmed, unset",
                    'write "confirmed" once a decision file confirms the owner, else "unset"; never a name'))
    if "corpus_status" in row and row["corpus_status"] not in ("candidate", "confirmed"):
        out.append((f"{at}.corpus_status", f"{row['corpus_status']!r} is not one of candidate, confirmed",
                    'write "candidate" until the corpus has been swept once'))
    if isinstance(row.get("autopilot"), str) and not row["autopilot"].strip():
        out.append((f"{at}.autopilot", "is empty", 'write "nothing" (drafts only), "by switch", or the rule a decision file set'))
    ch = row.get("channels")
    if ch is not None and not isinstance(ch, str):
        if not isinstance(ch, dict):
            out.append((f"{at}.channels", f"must be an object of channel: handle, got {type(ch).__name__}",
                        'write {"x": "@handle", "linkedin": "linkedin.com/company/slug"}, or {} until collected'))
        else:
            for k, v in ch.items():
                if k not in CHANNEL_KEYS:
                    out.append((f"{at}.channels.{k}", "unknown channel", f"use one of: {', '.join(CHANNEL_KEYS)}"))
                elif not isinstance(v, str):
                    out.append((f"{at}.channels.{k}", "the handle must be text", 'write it in quotes, "" until collected'))
    review = row.get("review")
    if review is not None:
        if not isinstance(review, dict):
            out.append((f"{at}.review", f"must be an object of kind: mode, got {type(review).__name__}",
                        'write {"post": "review", "like": "auto"}; a kind left out is "review"'))
        else:
            for k, v in review.items():
                if k not in REVIEW_KINDS:
                    out.append((f"{at}.review.{k}", "unknown kind", f"use one of: {', '.join(REVIEW_KINDS)}"))
                    continue
                modes = v if isinstance(v, dict) else {"": v}
                for chan, mode in modes.items():
                    key = f"{at}.review.{k}" + (f".{chan}" if chan else "")
                    if chan and chan not in CHANNEL_KEYS:
                        out.append((key, "unknown channel", f"use one of: {', '.join(CHANNEL_KEYS)}"))
                    elif mode not in REVIEW_MODES:
                        out.append((key, f"{mode!r} is not a mode",
                                    'write "review" (a person decides) or "auto" (what passes the checks goes out), in quotes'))
    d = row.get("drafts_only")
    if d is not None and not (isinstance(d, str) or (isinstance(d, list) and all(isinstance(x, str) for x in d))):
        out.append((f"{at}.drafts_only", "must be text or a list of channel names", 'write "all", "none", or ["Blog", "X"]'))
    posts = row.get("posts_per_day")
    if posts is not None and not isinstance(posts, str):
        if not isinstance(posts, dict):
            out.append((f"{at}.posts_per_day", f"must be an object, got {type(posts).__name__}",
                        'write {"x": 2, "linkedin": 1, "blog_per_week": 2, "blog_days_apart": 3}'))
        else:
            for k, v in posts.items():
                if k not in ("x", "linkedin", "blog_per_week", "blog_days_apart"):
                    out.append((f"{at}.posts_per_day.{k}", "unknown key", "use x, linkedin, blog_per_week or blog_days_apart"))
                elif not _is_count(v):
                    out.append((f"{at}.posts_per_day.{k}", f"must be a whole number of 0 or more, got {v!r}", "write a number without quotes"))
    reactions = row.get("reactions_per_day")
    if reactions is not None:
        if not isinstance(reactions, dict):
            out.append((f"{at}.reactions_per_day", f"must be an object, got {type(reactions).__name__}",
                        'write {"x": {"like": 20, "repost": 3}}'))
        else:
            for chan, caps in reactions.items():
                if chan not in CHANNEL_KEYS:
                    out.append((f"{at}.reactions_per_day.{chan}", "unknown channel", f"use one of: {', '.join(CHANNEL_KEYS)}"))
                elif not isinstance(caps, dict):
                    out.append((f"{at}.reactions_per_day.{chan}", "must be an object of kind: number", 'write {"like": 20, "repost": 3}'))
                else:
                    for k, v in caps.items():
                        if k not in REACTION_KINDS:
                            out.append((f"{at}.reactions_per_day.{chan}.{k}", "unknown kind", f"use one of: {', '.join(REACTION_KINDS)}"))
                        elif not _is_count(v):
                            out.append((f"{at}.reactions_per_day.{chan}.{k}", f"must be a whole number of 0 or more, got {v!r}",
                                        "write a number without quotes"))
    pairs = row.get("pair_rules")
    if pairs is not None:
        if not isinstance(pairs, list):
            out.append((f"{at}.pair_rules", f"must be a list, got {type(pairs).__name__}",
                        'write [] or [{"to": "<stream>", "rule": "...", "basis": "..."}]'))
        else:
            for i, p in enumerate(pairs):
                if not isinstance(p, dict) or not all(isinstance(p.get(k), str) and p.get(k).strip() for k in ("to", "rule")):
                    out.append((f"{at}.pair_rules[{i}]", "needs `to` and `rule` as text", 'write {"to": "<stream>", "rule": "...", "basis": "..."}'))
                elif p["to"] not in slugs:
                    out.append((f"{at}.pair_rules[{i}].to", f"{p['to']!r} is not a stream of this file", f"use one of: {', '.join(sorted(slugs))}"))
    out += _driver_problems(f"{at}.drivers", row.get("drivers"))
    return out


def _driver_problems(at, drivers):
    if drivers is None:
        return []
    if not isinstance(drivers, dict):
        return [(at, f"must be an object, got {type(drivers).__name__}", 'write {"write": "composio", "x_read": "twitterapi", "x_own": "twitterapi"}')]
    out = []
    for k, v in drivers.items():
        if k.startswith("_"):
            continue
        if k not in DRIVER_KEYS:
            out.append((f"{at}.{k}", "unknown key", f"use one of: {', '.join(DRIVER_KEYS)}"))
        elif v not in DRIVER_KEYS[k][1]:
            out.append((f"{at}.{k}", f"{v!r} is not a driver", f"use one of: {', '.join(DRIVER_KEYS[k][1])}"))
    return out


def brand_problems(bdoc, doc):
    """What is wrong with a brand.json document, as `(key, problem, fix)` rows; `doc` is engine.json."""
    out = []
    if not isinstance(bdoc, dict):
        return [("(file)", "must be a JSON object", "start from brand.example.json")]
    for k in bdoc:
        if not k.startswith("_") and k not in BRAND_FILE_KEYS:
            out.append((k, "unknown key", f"remove it, or use one of: {', '.join(BRAND_FILE_KEYS)} (a job's parameters go in engine.local.json)"))
    b = bdoc.get("brand")
    slug = None
    if not isinstance(b, dict):
        out.append(("brand", "missing", 'write {"slug": "<slug>", "name": "<Name>"}, or run engine.py init'))
    else:
        for k, v in b.items():
            if k.startswith("_"):
                continue
            if k not in BRAND_KEYS:
                out.append((f"brand.{k}", "unknown key", f"use one of: {', '.join(BRAND_KEYS)}"))
            elif not isinstance(v, str) or not v.strip():
                out.append((f"brand.{k}", "must be non-empty text", "write it in quotes, or leave the key out to derive it from the slug"))
        if isinstance(b.get("slug"), str) and b["slug"].strip():
            try:
                slug = _brand_block(bdoc, doc)["slug"]
            except ConfigError as e:
                out.append(("brand", str(e.args[0]), "lower-case letters, digits and dashes, a letter first, 2 to 24 characters"))
        elif "slug" not in b:
            out.append(("brand.slug", "missing", 'write the brand\'s slug, such as "acme"'))
    streams = bdoc.get("streams")
    if not isinstance(streams, dict):
        out.append(("streams", "missing" if streams is None else f"must be an object, got {type(streams).__name__}",
                    "write one entry per stream, keyed by slug; the brand's own stream first"))
        streams = {}
    slugs = {s for s in streams if not s.startswith("_")}
    if slug and slug not in slugs:
        out.append((f"streams.{slug}", "missing stream: the brand's own stream has no entry",
                    f'add "{slug}": {{"name": ..., "owner": "unset", "autopilot": "nothing"}} under streams'))
    for s in sorted(slugs):
        row = streams[s]
        if not SLUG_RE.match(s):
            out.append((f"streams.{s}", "not a slug", "lower-case letters, digits and dashes, a letter first, 2 to 24 characters"))
        if not isinstance(row, dict):
            out.append((f"streams.{s}", f"must be an object, got {type(row).__name__}", "see brand.example.json"))
            continue
        out += _stream_problems(s, row, slugs)
    out += _driver_problems("drivers", bdoc.get("drivers"))
    on = bdoc.get("jobs")
    if on is not None:
        names = [j.get("name") for j in doc.get("jobs", []) if isinstance(j, dict)]
        if not isinstance(on, dict):
            out.append(("jobs", f"must be an object of job name: true or false, got {type(on).__name__}",
                        'write {"autopilot": true, "x-stream": false}'))
        else:
            for k, v in on.items():
                if k.startswith("_"):
                    continue
                if k not in names:
                    out.append((f"jobs.{k}", "no such job", f"use one of: {', '.join(names)}"))
                elif not isinstance(v, bool):
                    out.append((f"jobs.{k}", f"must be true or false without quotes, got {v!r}", "true runs the job with the rest, false leaves it out"))
    pin = bdoc.get("engine")
    if pin is not None:
        if not isinstance(pin, dict):
            out.append(("engine", f"must be an object, got {type(pin).__name__}", 'write {"version": "1.0.0"}'))
        else:
            for k, v in pin.items():
                if k.startswith("_"):
                    continue
                if k != "version":
                    out.append((f"engine.{k}", "unknown key", "only `version` is set here"))
                elif not isinstance(v, str) or not VERSION_RE.match(v.strip()):
                    out.append(("engine.version", f"must be a version such as \"1.0.0\", got {v!r}",
                                "write the comms-engine plugin version this brand runs, in quotes"))
    plugins = bdoc.get("plugins")
    if plugins is not None:
        if not isinstance(plugins, dict):
            out.append(("plugins", f"must be an object, got {type(plugins).__name__}", 'write {"roles": {}}'))
        else:
            for k, v in plugins.items():
                if k.startswith("_"):
                    continue
                if k != "roles":
                    out.append((f"plugins.{k}", "unknown key", "only `roles` is set here; the marketplace is a per-machine setting"))
                elif not isinstance(v, dict):
                    out.append(("plugins.roles", f"must be an object of role: entry, got {type(v).__name__}", "see brand.example.json"))
                else:
                    for role, entry in v.items():
                        if role.startswith("_"):
                            continue
                        if not isinstance(entry, dict):
                            out.append((f"plugins.roles.{role}", "must be an object", 'write {"use": "<plugin>:<name>", "version": "1.2.3", "brief": "<file>"}'))
                            continue
                        for kk, vv in entry.items():
                            if kk not in ("use", "kind", "version", "brief", "fallback", "when") and not kk.startswith("_"):
                                out.append((f"plugins.roles.{role}.{kk}", "unknown key", "use one of: use, kind, version, brief, fallback, when"))
                            elif not kk.startswith("_") and not isinstance(vv, str):
                                out.append((f"plugins.roles.{role}.{kk}", "must be text", "write it in quotes"))
    return out


def validate(base=None, local=None):
    """Every problem with the setup of this checkout, one line each: the file, the key, what is wrong and the fix.

    brand.json is checked key by key; a file that does not parse is one line
    naming the place. An empty list is a clean setup. A checkout without a
    brand.json has nothing to check: engine.json's defaults apply.
    """
    base, local = _paths(base, local)
    path = brand_path(base)
    name = os.path.basename(path)
    lines = []
    try:
        doc = _read_json(base)
    except ValueError as e:
        return [f"{os.path.basename(base)}: does not parse as JSON ({e}). Fix: restore the shipped file; nobody edits it"]
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                bdoc = json.load(f)
        except ValueError as e:
            return [f"{name}: does not parse as JSON ({e}). Fix: check the commas and quotes near that line, or start from brand.example.json"]
        lines += [f"{name}: {key}: {problem}. Fix: {fix}" for key, problem, fix in brand_problems(bdoc, doc)]
    try:
        over = _read_json(local)
    except ValueError as e:
        return lines + [f"{os.path.basename(local)}: does not parse as JSON ({e}). Fix: check the commas and quotes near that line"]
    for k in over if isinstance(over, dict) else []:
        if k in LOCAL_FROZEN:
            lines.append(f"{os.path.basename(local)}: {k}: ignored, a schedule is not set per machine. "
                         f"Fix: remove it; turn a job on or off under `jobs` in {name}")
    return lines


# --- CLI ---------------------------------------------------------------------

def _print_value(v):
    if isinstance(v, bool):
        print("true" if v else "false")
    elif isinstance(v, (dict, list)):
        print(json.dumps(v, indent=2, ensure_ascii=False))
    else:
        print(v)


def _parse_value(raw):
    # A JSON literal when it is one (3, true, [..]), the plain string otherwise,
    # so `set corpus.root "/a path"` needs no quoting dance.
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def validate_cli():
    """Print each problem, or one ok line; exit 1 when there is a problem."""
    rel = os.path.relpath(brand_path(), REPO)
    problems = validate()
    for line in problems:
        print(line)
    if problems:
        print(f"validate: {len(problems)} problem(s)")
        return 1
    if not os.path.exists(brand_path()):
        print(f"ok  no {rel}: engine.json's defaults apply (engine.py init writes one)")
    else:
        print(f"ok  {rel}: brand {brand()['slug']}, {len(read_brand_file().get('streams') or {})} stream(s)")
    return 0


USAGE = ("usage: config.py get <path> | set <path> <value> | show | validate | brand [<key>] | "
         "env-name <path> | label <job> | labels [--optional|--required] | log-dir")
COMMANDS = ("get", "set", "show", "validate", "brand", "env-name", "label", "labels", "log-dir")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in COMMANDS:
        print(__doc__.strip().splitlines()[0])
        print(USAGE, file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "show":
            print(json.dumps(show(), indent=2, ensure_ascii=False))
            return 0
        if cmd == "validate":
            return validate_cli()
        if cmd == "brand":
            b = brand()
            if not rest:
                _print_value(b)
                return 0
            if rest[0] not in b:
                print(f"config: brand has no {rest[0]!r}; keys: {', '.join(BRAND_KEYS)}", file=sys.stderr)
                return 1
            print(b[rest[0]])
            return 0
        if cmd == "env-name":
            if len(rest) != 1:
                print("usage: config.py env-name <path>", file=sys.stderr)
                return 2
            print(env_name(rest[0]))
            return 0
        if cmd == "label":
            if len(rest) != 1:
                print("usage: config.py label <job>", file=sys.stderr)
                return 2
            print(job(rest[0])["label"])
            return 0
        if cmd == "labels":
            optional = True if "--optional" in rest else False if "--required" in rest else None
            print("\n".join(labels(optional=optional)))
            return 0
        if cmd == "log-dir":
            print(log_dir())
            return 0
        if cmd == "get":
            if len(rest) != 1:
                print("usage: config.py get <path>", file=sys.stderr)
                return 2
            value = cfg(rest[0], _MISSING)
            if value is _MISSING:
                print(f"config: {rest[0]}: not in engine.json (and no override)", file=sys.stderr)
                return 1
            _print_value(value)
            return 0
        if len(rest) != 2:
            print("usage: config.py set <path> <value>", file=sys.stderr)
            return 2
        set_local(rest[0], _parse_value(rest[1]))
    except ConfigError as e:
        print(f"config: {e.args[0]}", file=sys.stderr)
        return 1
    print(f"{'.'.join(keys_for(rest[0]))} = {rest[1]}  ({os.path.relpath(LOCAL_JSON, REPO)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
