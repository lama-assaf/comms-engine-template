# decisions

One file per significant project decision, in a lightweight ADR format. A
decision is the only thing that loosens shared memory: it confirms a stream's
owner, changes its `autopilot` cell, clears a partner to be named or tagged, or
removes a term from the denylist. The engine never writes one.

Filename: `YYYY-MM-DD-short-slug.md`. `scripts/session_brief.py` lists every
file matching that pattern on the first session after it appears, and takes
the title from the file's first `# ` heading (a leading `decision: ` is
dropped), so keep the date first and the title on line one. This README does
not match the pattern and is skipped.

Template:

```
# decision: [short title]

date: YYYY-MM-DD
status: [proposed | accepted | superseded by [other decision]]

## context

What is happening that requires a decision.

## decision

What we decided.

## alternatives considered

What else we looked at and why we did not pick it.

## consequences

What we expect to gain. What we explicitly give up. What we will watch for.

## review

When we will re-evaluate this. What would trigger a revisit.
```

Decisions are easier to remember than discussions. Write them down; revisit
them when context changes. Never name a person in a decision file: roles only.

## logged decisions

- `2026-11-13-autonomy-variety-engagement.md`: review becomes a switch per
  stream, channel and kind; the hold too; reactions within limits; one setup
  file. It rewords standing rules 1 and 4. It ships with the template because
  it changes the engine's rules, not one brand's memory.

- `2026-11-13-reactions-platform-rules.md` (proposed): what X, LinkedIn and
  Composio's tool list allow an engine to do on its own, read on that day. A
  like on X is never automatic; the owner's sign-off is not recorded yet.

- `2026-11-14-package-and-host.md`: the engine ships as the `comms-engine`
  plugin from this repository's own marketplace, each brand runs an instance
  repository, and the host is an office Mac behind Tailscale Serve.

Still expected per brand: the decision that confirms this stream's owner and
sets its `autopilot` setting.
