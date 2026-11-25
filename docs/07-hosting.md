# 7. Hosting: one brand's instance on an office Mac

One Mac on the office network runs one brand's whole instance: the instance
repository, the scheduled jobs, the control page and Claude Code (`claude -p`).
A person reaches the control page from a phone or a laptop over Tailscale,
signed in; nothing is on the public internet. This chapter is the runbook, and
`engine host-check` is its test: one ok/FAIL line for each thing below. The
decision behind it is `.atelier/memory/decisions/2026-11-14-package-and-host.md`.

Run every command as the Mac's dedicated user (7.1), from the instance root.

## 7.1 A user that stays logged in

LaunchAgents and the login keychain need a graphical session, so the jobs run
as a dedicated macOS user that logs in by itself after a restart.

1. **A user for the engine.** System Settings > Users & Groups > Add User, a
   standard account (for example `comms`). Nobody's own account: the keychain
   items and the jobs belong to this one.
2. **Automatic login.** System Settings > Users & Groups > Automatically log in
   as that user.

   **The trade-off: FileVault.** macOS turns automatic login off while FileVault
   is on. A Mac that restarts after a power cut then waits at the FileVault
   screen and runs no job until someone types the password. Choose one, and
   record the choice as a decision file:
   - FileVault off, automatic login on: the jobs survive a power cut; the disk
     is readable by whoever takes the Mac. Keep it in a locked room.
   - FileVault on: the disk is encrypted; after any restart a person must log
     in before anything runs. `host-check` reports this line as FAIL, on
     purpose, so the choice stays visible.
3. **Never sleep, restart after a power failure.**

   ```bash
   sudo pmset -a sleep 0 autorestart 1
   ```

   The instance's `nosleep` job (`caffeinate -is`) holds the Mac awake as well,
   once the jobs are installed (7.4).

## 7.2 The instance, outside the protected folders

launchd may not read `~/Desktop`, `~/Documents` or `~/Downloads`. Keep the
instance somewhere else:

```bash
mkdir -p ~/work && cd ~/work
git clone git@github.com:<owner>/<brand>-comms.git      # the brand's instance repository
cd <brand>-comms
```

A new brand starts its instance from the template checkout instead:
`engine new-instance ~/work/<brand>-comms --from <brand.json>`, then a first
commit and a push to the brand's own repository.

## 7.3 Claude Code and the engine

1. Install Claude Code for this user, then in the instance run `claude` once
   and trust the folder. It offers the `comms-engine` marketplace and the
   plugin `.claude/settings.json` enables; accept both. Install the plugins the
   roles call (atelier, salon, motion) as `engine plugins` lists them.
2. **The Claude token.** The jobs run `claude -p` with nobody at the keyboard,
   so they sign in with a subscription token, kept in the keychain:

   ```bash
   claude setup-token                                   # prints a token that lasts a year
   engine secrets --set CLAUDE_CODE_OAUTH_TOKEN         # paste it at the hidden prompt
   ```

   `engine secrets --set` records the date in `engine.local.json`
   (`host.claude_token_set`). `scripts/workflow.py` hands the token to each
   `claude -p` it starts and to nothing else; the corpus job does the same for
   its one call. `engine doctor` warns from day 330 and fails after a year:
   renew it the same way.
3. The other secrets, as `engine secrets` lists them.
4. `engine doctor`: every line ok, the version line included (the plugin is
   the one `brand.json` pins in `engine.version`).

## 7.4 The schedules

launchd needs a path that does not move, and the plugin's root moves on every
update. So every plist runs `~/.local/bin/comms-engine runjob <label>`, a small
shim that finds the installed engine for this instance at each start:

```bash
engine shim --install          # writes ~/.local/bin/comms-engine
comms-engine --where           # the engine it would run, and why
engine install --dry-run       # the plists, loads nothing
engine install                 # loads every job that brand.json turns on
```

Turn the hosted jobs on in `brand.json` (`jobs`: `control` and `backup`, off
in the template) and run `engine install` again, or `engine enable control`
and `engine enable backup`.

## 7.5 The door: Tailscale Serve

The control page binds 127.0.0.1 and stays there. Tailscale Serve puts it on
the tailnet over HTTPS, and tells it who is asking.

1. Install Tailscale, sign this Mac in to the office tailnet, and enable HTTPS
   certificates for the tailnet in its admin console.
2. Keep the page running (the `control` job, 7.4), then serve it:

   ```bash
   tailscale serve --bg 4320
   ```

3. Tell the engine this Mac's name and who may act, in the gitignored
   `engine.local.json` only:

   ```bash
   engine config set host.serve_name <machine>.<tailnet>.ts.net
   engine config set host.roles '{"<owner's login>": "alpha", "<editor's login>": "team"}'
   ```

   A login is the tailnet user Tailscale signs in (the `Tailscale-User-Login`
   header). Each maps to a role (`alpha`, `beta`, `team`), and that role, never
   the login, becomes the `by` of every act made over Tailscale. A login not in
   the map is refused, and so is a request without one. The map is read on each
   request: deleting a line closes the door for that login at once. The token
   check of the page still applies.

**What this trusts.** Any process on this Mac can call 127.0.0.1 with a
Tailscale header of its own choosing. That is the same trust the localhost page
has always had: whoever runs code on the Mac can act. Keep the Mac's user for
the engine alone.

## 7.6 The private denylist

`handles.private.md` (the stealth denylist) never goes through git. Copy it by
hand, over the tailnet, into `.atelier/memory/` (and each stream's own under
`.atelier/memory/streams/<slug>/`):

```bash
tailscale file cp handles.private.md <this-mac>:     # from the owner's machine
tailscale file get ~/work/<brand>-comms/.atelier/memory/   # on this Mac
```

Without it `channels.send()` blocks every send, and `host-check` fails.

## 7.7 History off the Mac

Git stays the history. The daily `backup` job (`scripts/backup.py`) commits the
record (`Content/`, `.atelier/memory/`, `brand.json`, `themes.json` and the
tracked `state/` files), pulls with rebase and pushes. It stops, and says why
in `state/backup.log`, on a conflict, on a tracked change outside the record,
or on a refused push; nothing is ever forced, and a conflict is settled by a
person.

1. **A deploy key, for this Mac alone.**

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/<brand>-comms-deploy -N "" -C "<brand>-comms office mac"
   ```

   Add the public half to the instance repository as a deploy key with write
   access, point `~/.ssh/config` at it for that host, and set the remote to its
   SSH URL. The key never goes into the repository.
2. `git push -u origin main` once, so the branch has an upstream.
3. `engine config set backup.push true`, then `engine backup --dry` to see what
   the next run would stage.

## 7.8 The check

```bash
engine host-check     # the path, pmset, automatic login, Tailscale Serve, the token, the denylist, the backup remote
engine doctor         # everything else, as on any machine
```

`host-check` reads only. Each FAIL line names the step above that fixes it.
