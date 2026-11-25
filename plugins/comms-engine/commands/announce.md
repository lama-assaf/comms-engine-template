---
description: Take a partner announcement from its source folder to the calendar notes and through release - check the copy, clear the partner, write the announcement as one calendar item, render the banner, stage the release, record the posts, watch the first hours. Never publishes.
argument-hint: <folder> [--apply | --drafts | --release | --record x=URL linkedin=URL | --watch] [--date YYYY-MM-DD] [--time HH:MM] [--partner "Name"] [--handle @x] [--theme "#Theme"] [--slug slug] [--x-option A] [--post hand|engine] [--approved "note"] [--no-mail]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion, mcp__claude-in-chrome__tabs_context_mcp, mcp__claude-in-chrome__tabs_create_mcp, mcp__claude-in-chrome__tabs_close_mcp, mcp__claude-in-chrome__navigate, mcp__claude-in-chrome__computer, mcp__claude-in-chrome__read_page, mcp__claude-in-chrome__find, mcp__claude-in-chrome__file_upload, mcp__claude-in-chrome__get_page_text, mcp__claude-in-chrome__gif_creator, mcp__claude_ai_Gmail__search_threads, mcp__claude_ai_Gmail__get_thread
---

# /announce

The path a partner announcement takes: **folder, then the calendar notes, then
social posts**. The comms lead fills a folder (anywhere the user names; a shared drive
is the usual place) with:
- a blog-post `.docx`;
- a social-copy `.docx` with `## LinkedIn post` and `## X post` (`Option A`, `B`, ...);
- a banner.

This command takes that folder to a calendar note that the brand's site (through
the published-posts feed) and the sender read, then through the release. It
never publishes. Approving the item, marking its article live on the control
page and posting to X or LinkedIn by hand are a person's acts, by rule.

Announcements are the **facts** content kind: jointly authored with the
partner, approved by the people the stream's doctrine names, released by hand.
The theme pipeline (`/social-cycle`) never touches them; this command is the
assisted path for the checks, the note and the record.

## usage

Run the steps in order. Each one can be re-run safely: the item is found by its
slug and rewritten while nobody has decided it, never written twice.

| step | run | what it does | writes |
|---|---|---|---|
| check | `/announce <folder>` | Reads the copy and the banner. Runs the gate and the announcement checks. Lists what is missing, then stops. | nothing |
| apply | `/announce <folder> --apply` | Clears the partner, renders the banner, and writes the announcement as one calendar item at `Idea` (`announce_check.py write`): the article, and with `--post engine` the X post. | memory, the calendar note, attachments |
| drafts | `/announce <folder> --drafts` | In your own signed-in Chrome, through Claude in Chrome, fills the X composer as the brand's own X handle and the LinkedIn composer as the brand's page with the approved copy and the banner, and saves both as drafts. Never clicks Post or Schedule. | platform drafts |
| release | `/announce <folder> --release` | Run it once a person has approved the item and marked its article live on the control page. Checks the page is live and prints the paste kit. | nothing |
| record | `/announce <folder> --record x=URL linkedin=URL` | Run it after the posts are out. Adds them, with their links, to the engagement sheet. | engagement sheet |
| watch | `/announce <folder> --watch` | Reads replies, quotes and mentions since the release, drafts answers from published facts, and updates the engagement sheet. Run it at +1 h and +3 h, and the next morning. | engagement sheet |

## options

| option | default | used by | meaning |
|---|---|---|---|
| `--date YYYY-MM-DD` | today | check, apply | Release day. Sets the note's date and fills `[Date]`. |
| `--time HH:MM` | from the source mail, else asked | apply, release | Release time, in the stream's timezone (`autopilot.timezone` in `engine.json`). Goes into the report and the checklist. `--release` warns before this time. |
| `--partner "Name"` | the folder name | all | Display name, when the folder name is an abbreviation of it. |
| `--handle @x` | asked | apply | The partner's X handle. Checked to exist (twitterapi.io `user/info`) before it goes into `handles.md`. |
| `--theme "#Theme"` | suggested, then asked | check, apply | One of the themes in `.atelier/memory/themes.md`. Becomes the note's theme, not a hashtag in the copy. |
| `--slug slug` | from the title | all | The article address, `site.post_url` in `engine.json` with the slug filled. Checked to be unused. |
| `--x-option A` | `A` | check, apply | Which `Option` block of the X copy is the post. |
| `--post hand\|engine` | `hand` | apply, release | Who posts X. `hand` leaves X off the item, so no approval can schedule it; `engine` puts it on the item, and an approval schedules it for its day. LinkedIn is always by hand (banner image, @mentions). |
| `--approved "note"` | asked | apply | Your approval statement, recorded word for word. Without it, `--apply` stops and asks. |
| `--no-mail` | off | check, apply | Skip the mail search for the source instruction and release time. |

Examples:

```
/announce "<path to>/Announcements/<Partner>"
/announce "<path to>/Announcements/<Partner>" --partner "<Partner Name>" --handle @<partner> \
  --theme "#<Theme>" --slug <partner>-joins-<brand> --time 14:00 \
  --approved "copy approved, <who> <date>" --apply
/announce "<path to>/Announcements/<Partner>" --release
/announce "<path to>/Announcements/<Partner>" --record x=https://x.com/<own handle>/status/... linkedin=https://www.linkedin.com/feed/update/urn:li:share:...
/announce "<path to>/Announcements/<Partner>" --watch
```

Work in the session scratchpad: `<scratch>/announce/<partner>/`. Its
`plan.json` and the calendar note are the state between steps. The item's id is
`A-<date>-<slug>`; its note is in `Content/Calendar/` under the blog title.

## check

1. **Read the folder.**
   ```
   engine announce_check "<folder>" \
     --out <scratch>/announce/<partner> --partner ... --theme ... --slug ... \
     --x-option A --date YYYY-MM-DD
   ```
   It extracts both documents with `skills/deck-reader/scripts/extract_doc.py`
   and runs the claim gate. It adds the announcement checks:
   - placeholders;
   - names spelled two ways;
   - what the autopilot will refuse to post;
   - claims `status.md` does not carry;
   - another stream's vocabulary (the pair rules in `streams.md`);
   - partner clearance.

   It also measures the banner. It writes `plan.json` and `plan.md`, and exits
   1 while anything blocks or waits to be filled.

   The brand's own status rules (`STATUS_FLAGS`, `CLEARED_PHRASES`,
   `VOICE_FLAGS` in `announce_check.py`) ship empty in the template: until the
   brand writes them from its `status.md`, the checker catches placeholders,
   spelling and clearance and the claim gate catches the rest.

2. **Find the source and the approval.** Unless `--no-mail`, search the mail for
   the release instruction (the partner's name, `subject:announcement`) and
   quote its release time. The stream's doctrine says whose approval a
   partnership announcement needs; `status.md` names the sources.
   - Approval is the user's own statement: in `--approved`, or in their words in
     this session.
   - Never infer it from a folder, a draft, a mail asking for review, or a yes
     for another partner. An approval names one partner; a second partner in
     the same sentence is a second question.
   - Ask too whether the partner signed off its quote.

3. **Read the findings.** Approved copy goes out exactly as approved: a check
   that fails on approved copy is a question for the user, never an edit.
   - **block** stops the push: a status word or stealth term the gate binds, or
     an uncleared partner with no approval.
   - **fill**:
     - `[Date]` takes the release day, and `[website link]` the article URL.
     - A name memory already spells (`project.md`, `voice.md`) takes that
       spelling.

     Neither is an edit.
   - **learn** means approved copy says something our rules flag. The rules are
     behind. With `--apply`, record the wording as cleared:
     - a decision file;
     - a line in `status.md` (what can and cannot be said), and in `voice.md`
       for a template matter;
     - the pattern in the brand's `.atelier/memory/gate-rules.json`, under
       `announce` (`cleared_phrases`, or a narrower `status_flags` entry);
     - a test case in `tests/test_announce_check.py`.

     Operating claims stay flagged: "live", a go-live date, a latency figure,
     any present-tense capability `claims.md` does not evidence. Naming a
     service line is not claiming it runs.
   - **posting** says how a post must go out. `write` keeps it on the note's
     writer check (`gate_writer`), and it goes in the checklist.
   - **note** goes to the copy owner. A name spelled two ways that memory does
     not know is asked about, and corrected once the user confirms.

   The theme-post checks (no-claim panel, tag line, CTA, hook) do not apply to
   newsroom copy.

3b. **Stage it.** Once the plan has no block finding, spawn the
   `atelier:release-narrator` agent (the Agent tool, `subagent_type` its full
   name) for the staging only: in which order the article, the LinkedIn post
   and the X post go out, how far apart, and the one line that carries each.
   Its brief is `briefs/release-staging.md`: hand
   it over in full, with `plan.md`. It knows nothing else of this repository,
   it changes no word of the copy and it writes no file. Show its staging to
   the user beside the plan. If the agent type is not available the atelier
   plugin is not installed in this checkout: show the plan without a staging
   and say so.

   Without `--apply`, stop here. Show the plan, the staging, the fills, and
   the questions: approval, time, theme, handle.

## apply

4. **Clear the partner.** If `plan.json` says `cleared: false`, write
   `.atelier/memory/decisions/<date>-<partner>-cleared-for-announcement.md` in
   the shape `decisions/README.md` describes. Spell out:
   - what is cleared to name and tag;
   - the theme;
   - the tense the copy keeps;
   - what stays dark.

   Then:
   - Add a row to `handles.md` under cleared partners: the handle from
     `--handle`, `verified` once checked, LinkedIn at `collect`. Add a log line.
   - Take the party's row out of `handles.private.md`.
   - Record any **learn** wording as in step 3.
   - Run `engine gate_lint` and check that its `denylist:` line still reads the
     file.

5. **Render the banner.**
   - Blog cover: WebP 2400x1350 (16:9). The site bakes it as the article cover.
   - LinkedIn image: PNG. Keep a 1.91:1 source at its own ratio; otherwise use
     1600x900.
   - Render an SVG first (`qlmanage -t -s 2400`, or headless Chrome).
   - If the ratio is not 16:9:
     - Scale to fill and trim the sides when only background is trimmed.
     - Padding a gradient leaves visible bands.
     - Look at the result once.
   - Keep the rendered files in `Content/Calendar/attachments/<partner>-<date>/`.
     The cover goes to the site with the article and the PNG to LinkedIn by
     hand, both from there; name the path in the report.

6. **Write the item.** Make the confirmed corrections (a typo the user
   confirmed, a name memory spells) in the scratch `plan.json`, then:
   ```
   engine announce_check write <scratch>/announce/<partner> \
     --approved "<the user's approval, word for word>" --post hand|engine
   ```
   It fills `[Date]` and the link placeholders, and refuses (writing nothing) a
   plan with a block finding, a placeholder left, no release day or no
   approval. It writes one item through `repo.py`, at `Idea`:

   | field | value |
   |---|---|
   | stream | the brand's name (`config.py brand name`) |
   | type, pillar, format | Milestone, Partnerships, Announcement |
   | theme | `--theme` |
   | date, slug | `--date`, the slug |
   | excerpt | the lead sentence, in the copy's own words |
   | proof gate | the approval, word for word |
   | drafted by | `team` (a role, never a name) |
   | the article | the post without its H1, with the fills made |
   | the X post | with `--post engine` only, the chosen option as approved |

   LinkedIn is never on the item, and X only with `--post engine`: an approval
   schedules every post the item carries, and a post that is on the item and
   also posted by hand would go out twice. Re-running `write` rewrites the same
   item until it is decided; after that it refuses.

   Then the item goes the way every draft goes: the gatekeeper gates it with the
   next cycle; a person confirms its argument line and approves it on the
   control page, then marks the article live there at `--time`. Read the note
   back and check its fields and body.

## drafts

6a. **Save the posts as drafts on the platforms.** The APIs cannot do this: X has
    no draft endpoint, and our LinkedIn module only publishes live. So this step
    drives your own Chrome through Claude in Chrome.
    - **Before anything is typed:**
      - The extension must be connected (`tabs_context_mcp`). The headless
        DevTools Chrome is not signed in.
      - Never type a password, and never sign in for the user. If a login page
        appears, stop and ask.
      - Check the account: X must show the brand's own handle from
        `handles.md`, and the LinkedIn composer must say it posts as the
        brand's page. On anything else, stop.
    - **Never click** Post, Schedule, "Post now" or a send button. The only
      exits are **Save** (X: close the composer and choose Save) and **Save as
      draft** (LinkedIn: close the composer). Record a GIF of each run for review.
    - **X:** run the `x-post` skill on the X copy in `plan.json` (thread with
      the link as the second post when the body has none). **LinkedIn:** run the
      `linkedin-post` skill on the LinkedIn copy in `plan.json` with the banner
      and the cleared @mentions. Both skills hold the composer mechanics, the read-back
      and the save-as-draft steps, and both stop at Save.
    - Exporting the GIF is a browser download, so ask before exporting.
    - Say in the report when each draft was saved. Close the tabs you opened,
      except a composer left open for the person.

## release

7. **Check, then hand over the paste kit.** Run this step after a person has
   marked the article live on the control page at `--time`.
   - `engine export-published <scratch>/published.json`:
     if the item is not in it, say so and stop. If it is before `--time`, warn.
   - `curl` the article URL (`site.post_url` with the slug) until it answers
     200. The site revalidates within minutes.
   - If drafts were saved (step 6a), point to them: X under the composer's
     Drafts, LinkedIn under the page's drafts. The person opens each one and
     posts it. Otherwise print the paste kit:
     - **LinkedIn:** the text, the banner path in
       `Content/Calendar/attachments/`, and which @mentions to type in the
       editor.
     - **X:** the thread draft, with the post and then "Full announcement:
       <url>" as its second post. Both are published together: the link goes
       in the body or as the second post of the same thread, never as a reply
       added later.
   - With `--post engine`:
     - The approval scheduled the X post for its day; the sender posts it
       within the guardrails and adds the link as a separate reply
       (`autopilot.py links`), which is the placement the rule above retires,
       so prefer the hand-posted thread draft.
     - The sender holds an X post with a link in its body or over 280 raw
       characters. Choose `--post engine` at `write` only for a link-free post
       within that length, and say the link will come as a reply.
   - Remind the user to ask the partner (and the people quoted) to repost or
     quote from their own accounts. That is the reach a launch-day post does not
     have on its own.

## record

8. **Record the posts.** Run with the URLs of the hand posts
   (`x=...`, `linkedin=...`).
   - Nothing on the calendar changes: a hand post is not on the item, so the
     sender cannot post it again. Marking the article live stays a person's act
     on the control page.
   - Add the posts to the engagement sheet as "our post" items (the sheet
     lists decisions and acts only, no self-replies).
   - Add the expected questions, with answers from published facts:
     - Where the stream has a pair rule in `streams.md` (another business the
       brand is linked to), the question about that relationship comes every
       time the brand names a third party. The answer is the wording the pair
       rule allows, and nothing beyond it.
     - "Is it live?": say what the release says (planned, in development) and
       that we will say when it runs.
     - Price or token talk: stay out.
   - Before the release, ask the linked stream's comms whether its own handle
     will say anything.
   - Send roundup accounts the link before their weekly cut-off.

## watch

9. **The first hours.**
   - Read the replies, quotes and mentions on the recorded posts since the
     release:
     - X: twitterapi.io `tweet/replies`, `tweet/quotes`, `user/mentions`.
     - LinkedIn: `socialActions/{urn}/comments`.
   - Add each new one to the engagement sheet with a drafted answer: links to
     the article stated plainly, no apology, nothing that says the piece is new.
   - Nothing is posted.
   - Report how many came in, which need an answer today, and whether the
     partner reposted.

## report (every step)

Say:
- what was read or written, with the note's path;
- the decision file, if any;
- what waits on whom;
- the next step to run.

Append a line to `Docs/Research/` when a note goes to the copy owner.

## what this command will not do

- Approve the item, mark its article live, post to X or LinkedIn, or mark an
  engagement-queue entry `ready`. In the browser it saves drafts and stops.
- Sign in to anything, or type a password.
- Clear a partner without the user's own statement of approval.
- Change a word of approved copy. It fills placeholders, corrects confirmed
  typos, and updates the rules.
- Write a second item for a slug that already has one.
- Write a mail body or a contact's private details into the repository.
