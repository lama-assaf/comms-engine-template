---
name: publish
description: The website-first publish path for an Alpha-approved queue item. Writes the Obsidian calendar note, which the brand's site reads through the published-posts feed once a person marks the article live, and prepares the teaser handoff. Never runs on an unapproved item.
---

# publish

*Facts first, website first. Everything publishes on the brand's own site
before anywhere else. Traffic there is the ignition.*

This is Beta pipeline 1, *content repository as the single source*, using the
repository that already exists: `Content/Calendar/` in this vault. The website
reads the published-posts feed built from those notes (`GET /api/published` on
the control page, or `engine export-published <file>`): the brand's Blog
posts a person has marked live. The site itself is the website named in
`streams.md`; its article URL shape is `site.post_url` in `engine.json`.

## the chain

```
scripts/apply_edits.py  (Alpha's desk edits, from /social-cycle step 6)
   └─ Content/Calendar/<title>.md            title, post and both teasers, but
                                             only while the note still hashes to
                                             the base_hash the desk recorded;
                                             a conflict is skipped and flagged,
                                             never merged and never overwritten
scripts/repo.py --all  (at draft, from /social-cycle step 6, after the gate)
   └─ Content/Calendar/<title>.md            frontmatter + full post   (status: Idea)
   └─ Content/Calendar/<title> - teasers.md  LinkedIn + X teasers      (status: Idea)
   └─ state/queue.json                       the derived index, rebuilt from the notes
Content/Calendar/<title>.md (alpha_status: approved)
   └─ scripts/publish.py <id>                reads the item from its note
        ├─ repo.write_item(item, "Ready")    the same two notes, rewritten in place
        │    Content/Calendar/<title>.md        full post              (status: Ready)
        │    Content/Calendar/<title> - teasers.md  teasers            (status: Drafting)
Alpha on the control page: "Mark the article live" (the blog-live act)
   └─ POST site.webhook_url  (<ENV_PREFIX>WEBHOOK_SECRET)  → revalidate + rebuild
   └─ the post appears at site.post_url with the slug filled
Teasers: scheduled for their day by the approval; the sender adds the article link in a first reply once it is live
```

The manual blog-live act is deliberate. The doctrine says
*"released manually through a dedicated approval flow"*; the engine stops one
step short of the site on purpose.

## workflow

1. Read the decision. Accept only `alpha_status == "approved"`. Anything else:
   report and stop.
2. Run `claim-gate` once more on the final text (an edit on the desk is a
   new draft). `publish.py` enforces this rather than trusting it: an item whose
   note carries a `desk_edit` resolution newer than its `gate.reviewed_at` is
   refused, and so is one whose desk edit is still in conflict with the note.
   Both are cleared by a person (the gatekeeper re-reading, or
   `scripts/apply_edits.py <id> --prefer desk|vault`), never by `--force`
   outside a dry run.
3. `engine publish <id>`: it calls
   `repo.write_item(item, "Ready")`, which finds the item's existing notes by
   `engine_id` and rewrites them in place, carrying the publish record
   forward. Add
   `--webhook` only when `site.webhook_url` is set in `engine.json`, the user
   has set `<ENV_PREFIX>WEBHOOK_SECRET` (`config.py env-name` prints the exact
   name for this brand) and asked for the rebuild.
4. Log the step in `state/runs.json` and mark the item `published_to:
   ["vault"]`: `publish.py` writes that, with `published_at` and
   `vault_note`, onto the item's **note**, where the item lives, and rebuilds
   `state/queue.json` from the notes. The index is a derivation: a value
   written there instead is lost at the next rebuild.
5. The teasers go out on their day through `channels.send()` once approved
   (the approval schedules `<id>:x` and `<id>:linkedin`); the article link
   follows as a first reply once a person has marked the article live. Sending
   needs a person's approval of that specific text (salon hard rule).

## rules

- Facts (press releases) never go through this path. They are jointly authored,
  partner-synchronised and released by hand (`/announce` is the assisted path
  for their checks and rows). This path is for themes.
- Frontmatter values must match the calendar vocabulary: status
  Idea/Drafting/Ready/Scheduled/Published, stream the brand's name, type
  Evergreen/Reactive/Milestone, platform Blog. `repo.py` is the only writer of
  an engine note; never hand-edit one to move it along.
- The note also carries seven engine keys: `engine_id`, `theme`, `finding_id`,
  `logic`, `gate_verdict`, `alpha_status`, `hooks_considered`. They are local to
  the vault and never reach the site feed.
- Never set `status: Published` from the engine.
- The note also carries `desk_edit`, the record of how Alpha's last desk edit
  was resolved (`applied`, `desk` or `vault`, with the timestamp). It is local
  to the vault like the seven engine keys, and it is what makes a dropped edit
  durable: nothing in this engine can delete the record the desk holds.
