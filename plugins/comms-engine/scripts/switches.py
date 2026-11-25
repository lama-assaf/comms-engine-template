#!/usr/bin/env python3
"""
switches.py - the review switch: a mode per stream, channel and kind of send, and a pause per stream.

One question, one place: may this go out without a person? The answer is a
mode, `review` (the default: a person decides) or `auto` (what passes the
automatic checks goes out, what fails stays in the queue), for each stream,
channel and kind:

  post, reply, comment, like, repost, quote   the kinds of send
  hold                                        the statistics, partner and certification
                                              class of standing rule 4: on `auto` the
                                              hold check passes without a release act

`mode(stream, channel, kind)` is what `channels.send()`, the engine's own
approval (`autopilot.py approve`) and the reactions sender read, at every
call, so a change takes effect on the next send. It can only TIGHTEN what the
stream's setup allows (`streams_allow`): a stream whose owner is `unset` or
whose autopilot is `nothing` is `review` whatever was stored, and so is a
channel that is drafts-only or inside `all hours` quiet hours. A kind other
than a reply or a comment may be `auto` only where the stream's autopilot is
`by switch`, set once by a person at onboarding.

A person changes a mode on the dashboard (`/api/switch`). The change is a
`switch` act in `state/acts.jsonl` (role and time on it), and `apply_act()`
below - the act applier, the only code that writes `state/switches.json` -
turns the act into the live value. Turning a mode to `auto` takes one
confirmation; a written reason is optional, as it is for an approval. Turning
it back to `review` needs neither.

  state/switches.json
    {"switches": {"<stream>/<channel>": {...}},          the auto-reply switch as first recorded
     "modes":    {"<stream>/<channel>/<kind>": {stream, channel, kind, mode, by, at, reason, act}},
     "pauses":   {"<stream>": {stream, paused, by, at, reason, act}}}

Where no mode was ever stored, the default is the stream's `review` setting
in brand.json (`streams.<slug>.review.<kind>`, a mode or `{channel: mode}`);
for a reply or a comment the auto-reply switch stored before modes existed,
then `channels.auto_reply.<stream>.<channel>`, still count.

The pause stops every send of a stream at once: `channels.send()` reads
`paused(stream)` first, before any other check. Pausing is one click and
needs no confirmation; resuming does. Both are `pause` acts.

  engine switches            # every mode and pause, read-only
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = paths.state()
sys.path.insert(0, HERE)

import config  # noqa: E402
import memory  # noqa: E402

FILE = "switches.json"
KINDS = config.REVIEW_KINDS
MODES = config.REVIEW_MODES
#: The kinds the auto-reply switch covered before modes existed.
REPLY_KINDS = ("reply", "comment")
BY_SWITCH = "by switch"
CONFIRM = "Turning the auto-reply on needs your confirmation: it lets the engine send replies without your approval."
CONFIRM_AUTO = ("Switching this to automatic needs your confirmation: what passes the automatic checks "
                "will go out without anyone reading it first.")
CONFIRM_RESUME = "Resuming needs your confirmation: every send that was stopped may go out again."
RESTRICTED = re.compile(r"\b(?:replies|comments|engagement)\s*:\s*(?:manual|nothing|none)\b", re.I)
#: The three presets of the Autonomy page: the mode of every kind.
PRESETS = {
    "review-everything": {k: "review" for k in KINDS},
    "review-posts-only": {"post": "review", "quote": "review", "hold": "review",
                          "reply": "auto", "comment": "auto", "like": "auto", "repost": "auto"},
    "fully-automatic": {k: "auto" for k in KINDS},
}


class SwitchError(ValueError):
    """A switch change that cannot be made, said in one line."""


def _path(state=None):
    return os.path.join(state or STATE, FILE)


def _key(stream, channel):
    import channels
    return f"{memory.stream(stream)['slug']}/{channels.channel_key(channel)}"


def load(state=None):
    try:
        with open(_path(state), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    for section in ("switches", "modes", "pauses"):
        if not isinstance(data.get(section), dict):
            data[section] = {}
    return data


def _save(data, state=None):
    p = _path(state)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in data.items() if v or k == "switches"}, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def get(stream, channel, state=None):
    """The stored auto-reply record for this stream and channel, or None when it was never changed."""
    return load(state)["switches"].get(_key(stream, channel))


def stored(stream, channel, kind, state=None):
    """The stored mode record for this stream, channel and kind, or None."""
    return load(state)["modes"].get(f"{_key(stream, channel)}/{kind}")


# --- what the stream's setup allows -----------------------------------------------------------

def by_switch(row):
    """Whether the stream's autopilot setting is `by switch`."""
    return str(row.get("autopilot", "")).strip().lower().startswith(BY_SWITCH)


def streams_allow(stream, channel, kind="reply"):
    """`(ok, why)`: does the stream's setup (brand.json, rendered into `streams.md`) leave room
    for this kind to go out on this channel without a person."""
    import channels
    import guardrails
    row = memory.stream(stream)
    key = channels.channel_key(channel)
    g = guardrails.parse_guardrails(row)
    name = row["name"]
    if g["autopilot"].lower().startswith("nothing") or not memory.may_draft(stream):
        return False, f"{name}: autopilot is '{g['autopilot'] or 'nothing'}' and owner is '{row['owner']}' (streams.md): nothing leaves without a person."
    disp = channels.DISPLAY.get(key)
    if disp is None:
        return False, f"{key} is not a channel that takes replies or comments."
    if key not in [k for k, _ in channels.stream_channels(stream)]:
        return False, f"{key} is not one of {name}'s own channels in streams.md."
    if disp in g["drafts_only"]:
        return False, f"{name}: {disp} is drafts-only (streams.md guardrails)."
    if g["quiet"]["all"]:
        return False, f"{name}: quiet hours are 'all hours' until onboarded (streams.md)."
    if kind in REPLY_KINDS:
        if RESTRICTED.search(g["autopilot"]):
            return False, f"{name}: the autopilot cell keeps replies manual (streams.md)."
    elif not by_switch(row):
        return False, (f"{name}: autopilot is not `by switch`, so a {kind} always waits for a person. "
                       "A person sets it once, at onboarding, on a decision.")
    return True, ""


def default_mode(stream, channel, kind):
    """The mode where none was stored: the stream's `review` setting, `review` when it names none."""
    import channels
    slug = memory.stream(stream)["slug"]
    key = channels.channel_key(channel)
    setting = (config.cfg(f"streams.{slug}.review", {}) or {}).get(kind)
    if isinstance(setting, dict):
        setting = setting.get(key)
    if setting in MODES:
        return setting
    if kind in REPLY_KINDS and config.cfg(f"channels.auto_reply.{slug}.{key}", False) is True:
        return "auto"
    return "review"


def wanted(stream, channel, kind, state=None):
    """`(mode, record or None)`: the mode asked for, before the stream's setup has its say."""
    if kind not in KINDS:
        raise SwitchError(f"unknown kind {kind!r}; one of {', '.join(KINDS)}")
    rec = stored(stream, channel, kind, state)
    if rec is not None:
        return ("auto" if rec.get("mode") == "auto" else "review"), rec
    if kind in REPLY_KINDS:
        legacy = get(stream, channel, state)
        if legacy is not None:
            return ("auto" if legacy.get("value") is True else "review"), legacy
    return default_mode(stream, channel, kind), None


def mode(stream, channel, kind, state=None):
    """The mode in force now, `review` or `auto`: what was asked for, and the setup still allowing it."""
    want, _rec = wanted(stream, channel, kind, state)
    if want == "auto" and streams_allow(stream, channel, kind)[0]:
        return "auto"
    return "review"


def effective(stream, channel, state=None):
    """Whether an unapproved reply may go out now (the auto-reply switch): `mode(.., "reply")` is `auto`."""
    return mode(stream, channel, "reply", state) == "auto"


# --- the pause --------------------------------------------------------------------------------

def pause_record(stream, state=None):
    return load(state)["pauses"].get(memory.stream(stream)["slug"])


def paused(stream, state=None):
    """Whether every send of the stream is stopped now. Read by `channels.send()` at every send."""
    rec = pause_record(stream, state)
    return bool(rec and rec.get("paused") is True)


# --- the applier ------------------------------------------------------------------------------

def apply_act(act, state=None, apath=None):
    """The act applier: turn one pending `switch` or `pause` act into the live value, or refuse it.
    Returns the outcome, `applied` or `refused: <reason>`, and ends the act with it. The only
    writer of switches.json."""
    import acts
    stream, payload = act["stream"], act.get("payload") or {}
    outcome = "applied"
    try:
        slug = memory.stream(stream)["slug"]
        reason = str(payload.get("reason") or "").strip()
        if act.get("kind") == "pause":
            if not isinstance(payload.get("paused"), bool):
                outcome = "refused: not a pause act with a true or false value"
            else:
                data = load(state)
                data["pauses"][slug] = {"stream": slug, "paused": payload["paused"], "by": act["by"], "at": act["at"],
                                        "reason": reason, "act": act["id"]}
                _save(data, state)
        elif act.get("kind") != "switch":
            outcome = "refused: not a switch act"
        elif "mode" in payload:
            key = _key(stream, payload.get("channel"))
            kind, new = payload.get("kind"), payload.get("mode")
            if kind not in KINDS or new not in MODES:
                outcome = "refused: not a switch act with a known kind and a mode of review or auto"
            else:
                if new == "auto":
                    ok, why = streams_allow(stream, payload["channel"], kind)
                    if not ok:
                        outcome = f"refused: {why}"
                if outcome == "applied":
                    data = load(state)
                    data["modes"][f"{key}/{kind}"] = {"stream": slug, "channel": key.split("/", 1)[1], "kind": kind,
                                                     "mode": new, "by": act["by"], "at": act["at"], "reason": reason,
                                                     "act": act["id"]}
                    _save(data, state)
        else:
            key = _key(stream, payload.get("channel"))
            value = payload.get("value")
            if not isinstance(value, bool):
                outcome = "refused: not a switch act with a true or false value"
            elif value:
                ok, why = streams_allow(stream, payload["channel"])
                if not ok:
                    outcome = f"refused: {why}"
            if outcome == "applied":
                data = load(state)
                channel = key.split("/", 1)[1]
                data["switches"][key] = {"stream": slug, "channel": channel, "value": value, "by": act["by"],
                                         "at": act["at"], "reason": reason, "act": act["id"]}
                # the auto-reply switch is the reply and comment modes: one act sets both
                for kind in REPLY_KINDS:
                    data["modes"][f"{key}/{kind}"] = {"stream": slug, "channel": channel, "kind": kind,
                                                     "mode": "auto" if value else "review", "by": act["by"],
                                                     "at": act["at"], "reason": reason, "act": act["id"]}
                _save(data, state)
    except Exception as exc:  # the act must still end with an outcome
        outcome = f"refused: {exc}"
    if outcome == "applied":
        acts.applied(act["id"], path=apath)
    else:
        acts.refused(act["id"], outcome[len("refused: "):], path=apath)
    return outcome


def _resolve(stream, channel):
    import channels
    try:
        return memory.stream(stream)["slug"], channels.channel_key(channel)
    except (memory.SharedMemoryError, channels.ChannelError) as exc:
        raise SwitchError(str(exc))


def change(stream, channel, value, by="alpha", reason=None, confirm=False, state=None):
    """The auto-reply switch: record a `switch` act that sets the reply and comment modes together,
    and apply it. Returns `{id?, stream, channel, value, outcome, by, at, reason}`.

    A refusal is an answer, not an error: turning it on without a confirmation records no
    act; one the stream's setup does not allow records an act that ends `refused`."""
    import acts
    import channels
    import desk_acts
    if not isinstance(value, bool):
        raise SwitchError("the switch is true (on) or false (off)")
    slug, key = _resolve(stream, channel)
    out = {"stream": slug, "channel": key, "value": value, "by": desk_acts.role_of(by)}
    if value and confirm is not True:
        return dict(out, outcome=f"refused: {CONFIRM}")
    apath = os.path.join(state or STATE, channels.ACTS_FILE)
    act = acts.record("switch", slug, f"{slug}/{key}", {"channel": key, "value": value, "reason": str(reason or "").strip()},
                      base=None, by=out["by"], path=apath)
    outcome = apply_act(act, state, apath)
    return dict(out, id=act["id"], at=act["at"], outcome=outcome, reason=str(reason or "").strip())


def set_mode(stream, channel, kind, new, by="alpha", reason=None, confirm=False, state=None):
    """Record a `switch` act for one stream, channel and kind, and apply it.
    Returns `{id?, stream, channel, kind, mode, outcome, by, at, reason}`.

    `auto` takes one confirmation and no written reason; `review` takes neither. An `auto`
    the stream's setup does not allow records an act that ends `refused`."""
    import acts
    import channels
    import desk_acts
    if kind not in KINDS:
        raise SwitchError(f"unknown kind {kind!r}; one of {', '.join(KINDS)}")
    if new not in MODES:
        raise SwitchError(f"the mode is review or auto, got {new!r}")
    slug, key = _resolve(stream, channel)
    out = {"stream": slug, "channel": key, "kind": kind, "mode": new, "by": desk_acts.role_of(by)}
    if new == "auto" and confirm is not True:
        return dict(out, outcome=f"refused: {CONFIRM_AUTO}")
    apath = os.path.join(state or STATE, channels.ACTS_FILE)
    act = acts.record("switch", slug, f"{slug}/{key}/{kind}",
                      {"channel": key, "kind": kind, "mode": new, "reason": str(reason or "").strip()},
                      base=None, by=out["by"], path=apath)
    outcome = apply_act(act, state, apath)
    return dict(out, id=act["id"], at=act["at"], outcome=outcome, reason=str(reason or "").strip())


def preset(stream, name, by="alpha", confirm=False, state=None):
    """Apply one of PRESETS to every channel of a stream: one `switch` act per channel and kind
    whose mode changes. Returns the list of `set_mode` results (a refusal among them is an answer)."""
    import channels
    if name not in PRESETS:
        raise SwitchError(f"unknown preset {name!r}; one of {', '.join(PRESETS)}")
    slug, _ = _resolve(stream, "x")
    if any(m == "auto" for m in PRESETS[name].values()) and confirm is not True:
        return [{"stream": slug, "outcome": f"refused: {CONFIRM_AUTO}"}]
    out = []
    for key in [k for k, _ in channels.stream_channels(slug) if k in channels.DISPLAY]:
        for kind, new in PRESETS[name].items():
            if wanted(slug, key, kind, state)[0] != new:
                out.append(set_mode(slug, key, kind, new, by=by, reason=f"preset: {name}", confirm=True, state=state))
    return out


def set_pause(stream, value, by="alpha", reason=None, confirm=False, state=None):
    """Pause or resume every send of a stream: a `pause` act, applied at once.
    Pausing needs nothing; resuming needs a confirmation."""
    import acts
    import channels
    import desk_acts
    if not isinstance(value, bool):
        raise SwitchError("the pause is true (stop every send) or false (resume)")
    slug, _ = _resolve(stream, "x")
    out = {"stream": slug, "paused": value, "by": desk_acts.role_of(by)}
    if not value and confirm is not True:
        return dict(out, outcome=f"refused: {CONFIRM_RESUME}")
    apath = os.path.join(state or STATE, channels.ACTS_FILE)
    act = acts.record("pause", slug, slug, {"paused": value, "reason": str(reason or "").strip()},
                      base=None, by=out["by"], path=apath)
    outcome = apply_act(act, state, apath)
    return dict(out, id=act["id"], at=act["at"], outcome=outcome, reason=str(reason or "").strip())


# --- what the dashboard shows -----------------------------------------------------------------

def rows(state=None):
    """The auto-reply rows: one per stream and reply-taking channel, with the live value,
    whether the stream's setup allows it on, and who last changed it, when and why."""
    import channels
    out = []
    try:
        slugs = memory.streams()
    except memory.SharedMemoryError:
        return out
    for slug in slugs:
        try:
            chans = [k for k, _ in channels.stream_channels(slug) if k in channels.DISPLAY]
        except memory.SharedMemoryError:
            continue
        for key in chans:
            want, rec = wanted(slug, key, "reply", state)
            rec = rec or {}
            ok, why = streams_allow(slug, key)
            value = want == "auto"
            out.append({"stream": slug, "name": memory.stream(slug)["name"], "channel": key, "label": channels.DISPLAY[key],
                        "value": value, "on": value and ok, "allowed": ok, "why": why, "stored": bool(rec),
                        "by": rec.get("by"), "at": rec.get("at"), "reason": rec.get("reason") or ""})
    return out


def policy(state=None):
    """Every stream's review policy: its autopilot setting, its pause, and per channel and kind the
    mode asked for, the mode in force, whether the setup allows `auto` and who last changed it."""
    import channels
    out = []
    try:
        slugs = memory.streams()
    except memory.SharedMemoryError:
        return out
    for slug in slugs:
        try:
            row = memory.stream(slug)
            chans = [k for k, _ in channels.stream_channels(slug) if k in channels.DISPLAY]
        except memory.SharedMemoryError:
            continue
        pause = pause_record(slug, state) or {}
        entry = {"stream": slug, "name": row["name"], "autopilot": row.get("autopilot", "").strip(),
                 "by_switch": by_switch(row), "owner": row.get("owner", "").strip(),
                 "paused": pause.get("paused") is True,
                 "pause": {"by": pause.get("by"), "at": pause.get("at"), "reason": pause.get("reason") or ""},
                 "channels": []}
        for key in chans:
            kinds = []
            for kind in KINDS:
                want, rec = wanted(slug, key, kind, state)
                rec = rec or {}
                ok, why = streams_allow(slug, key, kind)
                kinds.append({"kind": kind, "wanted": want, "mode": "auto" if want == "auto" and ok else "review",
                              "allowed": ok, "why": why, "stored": bool(rec), "default": default_mode(slug, key, kind),
                              "by": rec.get("by"), "at": rec.get("at"), "reason": rec.get("reason") or ""})
            entry["channels"].append({"channel": key, "label": channels.DISPLAY[key], "kinds": kinds})
        modes = {k["kind"]: {c["kinds"][i]["wanted"] for c in entry["channels"]} for i, k in enumerate(
            entry["channels"][0]["kinds"])} if entry["channels"] else {}
        entry["preset"] = next((name for name, want in PRESETS.items()
                                if modes and all(modes[k] == {m} for k, m in want.items())), None)
        out.append(entry)
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="the review modes and pauses (read-only; change them on the dashboard)")
    ap.add_argument("--state", default=STATE)
    a = ap.parse_args(argv)
    for entry in policy(a.state):
        print(f"{entry['stream']}  autopilot: {entry['autopilot'] or 'nothing'}  {'PAUSED' if entry['paused'] else 'running'}")
        for ch in entry["channels"]:
            print(f"  {ch['channel']:<9} " + "  ".join(f"{k['kind']}={k['mode']}" for k in ch["kinds"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
