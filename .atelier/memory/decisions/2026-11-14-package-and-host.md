# decision: the engine ships as the comms-engine plugin and runs on an office Mac

date: 2026-11-14
status: accepted

## context

Step 19 of `PLAN-autonomy.md` packages the engine as a plugin with one
instance repository per brand (`PLAN-workflows.md` step 6) and hosts it
(H1 to H6 of `PLAN-channels-hosting.md`). Both waited on the owner: where the
plugin lives, what this repository becomes, which machine runs the jobs, what
door the dashboard sits behind and how Claude Code signs in on that machine.

## decision

The owner, 2026-11-14:

1. **Plugin home.** This repository is the plugin's source and its own
   marketplace (`.claude-plugin/marketplace.json` lists `comms-engine` from
   `./plugins/comms-engine`). There is no separate engine repository.
2. **This repository** becomes the instance template. The engine code leaves
   `Tooling/social-engine/` for `plugins/comms-engine/`; the root keeps only
   what a brand owns (`brand.json`, memory, content, state, streams).
3. **Host.** A Mac on the office network. launchd and the keychain stay;
   systemd timers and a Linux secrets backend are not built. A small installed
   command, `~/.local/bin/comms-engine`, is the fixed path launchd runs.
4. **Door.** Tailscale Serve in front of the control page, which still binds
   127.0.0.1. The `Tailscale-User-Login` header maps to a role through the
   gitignored `engine.local.json host.roles`; an unmapped login is refused.
5. **Claude on the host.** A subscription token from `claude setup-token`,
   kept in the keychain as `CLAUDE_CODE_OAUTH_TOKEN` and given only to
   `claude -p` through `secrets.py`.

## alternatives considered

- A separate engine repository: two places to change for one fix, and
  hand-porting between copies is what step 6 set out to stop.
- A VPS with systemd: a second scheduler and a second secrets backend to keep
  in step with launchd and the keychain, for no gain on one brand.
- Cloudflare Access: a second account and a public hostname; Tailscale keeps
  the page off the internet.
- An API key for Claude: billed per call; the subscription token is already paid.

## consequences

- Each brand gets its own instance repository from `engine new-instance`,
  pinning `engine.version` in its `brand.json`; `doctor` fails on a mismatch.
- The office Mac needs a dedicated user with automatic login (LaunchAgents and
  the login keychain need a GUI session), which macOS refuses while FileVault
  is on. The owner chooses; `docs/07-hosting.md` names the trade-off.
- Any process on the Mac can set Tailscale headers on 127.0.0.1: the same
  trust as today's localhost page.
- The token lasts a year; `doctor` warns 35 days before.

## review

When a second host or a non-macOS host is needed, or when Tailscale identity
headers stop being enough to tell people apart.
