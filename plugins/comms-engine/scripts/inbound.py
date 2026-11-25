#!/usr/bin/env python3
"""
inbound.py - the scheduled inbound poll: mentions, replies and comments on our own
accounts, as patterns only (PLAN-channels-hosting, the Reads decision).

  engine inbound poll [--dry-run] [--stream <slug>]
  engine inbound status [--stream <slug>]

`poll` runs `channels.inbound(stream, channel)` for each channel the stream has (X, LinkedIn),
keeps a cursor per stream and channel in `state/inbound.json`, and hands the patterns (channel,
tier, shape, theme, target post, count) to `engage.merge_inbound`, which folds them into
`state/engagement.json` `inbound`. No handle and no third party's text is stored (rule 6).

The X half reads X's own API, so it stays off until the owner's price sign-off for own-account
reads (`params.listen.x_own_price_signoff`) is recorded and the stream's own-reads driver
(`channels.x_own.<stream>`) is composio; listening's `x_read` driver and sign-off are separate. The
LinkedIn half reads comments on our recent posts through a `composio proxy` GET and runs only
when the stream's LinkedIn composio account is linked. `--dry-run` plans the queries and calls
nothing and writes nothing. Scheduled by the optional, not-loaded `inbound` job of engine.json.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import channels  # noqa: E402
import engage  # noqa: E402
import memory  # noqa: E402


def status_lines(stream):
    """One `(channel, state, reason)` per inbound channel the stream has."""
    out = []
    for key in channels.INBOUND_CHANNELS:
        state, reason = channels.inbound_status(stream, key)
        out.append((key, state, reason))
    return out


def poll(stream, dry_run=False):
    rc = 0
    for key in channels.INBOUND_CHANNELS:
        state, reason = channels.inbound_status(stream, key)
        if state == "off" or (state == "held" and not dry_run):
            print(f"inbound {stream}/{key}: {state} ({reason})")
            continue
        try:
            res = channels.inbound(stream, key, dry_run=dry_run)
        except channels.ChannelError as exc:
            print(f"inbound {stream}/{key}: failed: {exc}", file=sys.stderr)
            rc = 1
            continue
        plan = res["plan"]
        if dry_run:
            print(f"inbound {stream}/{key}: {state} ({reason}); would run {len(plan['queries'])} "
                  f"quer{'y' if len(plan['queries']) == 1 else 'ies'}, since_id {plan['since_id'] or '-'}, "
                  f"{plan['posts']} recent post(s)")
            for kind, q in plan["queries"]:
                print(f"  would run {kind:8} {q}")
            continue
        engage.merge_inbound(res["patterns"], stream=memory.stream(stream)["name"])
        print(f"inbound {stream}/{key}: {sum(p['count'] for p in res['patterns'])} new, {len(res['patterns'])} pattern(s)")
    if dry_run:
        print("\nnothing called, nothing written.")
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("poll", "status"):
        sp = sub.add_parser(name)
        sp.add_argument("--stream", default=memory.DEFAULT_STREAM)
        if name == "poll":
            sp.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "status":
            for key, state, reason in status_lines(args.stream):
                print(f"inbound {args.stream}/{key}: {state} ({reason})")
            return 0
        return poll(args.stream, args.dry_run)
    except (channels.ChannelError, memory.SharedMemoryError) as exc:
        print(f"inbound: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
