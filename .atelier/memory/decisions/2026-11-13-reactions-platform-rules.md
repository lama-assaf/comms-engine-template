# decision: what the platforms allow an engine to do on its own, and what stays one click

date: 2026-11-13
status: proposed (the findings are recorded; the owner's sign-off below is not)

## context

`2026-11-13-autonomy-variety-engagement.md` lets likes and reposts run
automatically, within limits, behind a switch, and names the risk: X has
restricted automated likes, and the account is what is at stake. Step 12 of
`PLAN-autonomy.md` asks for the current rules to be read and recorded before
any reaction is built. This is that reading, done on 2026-11-13.

## what was read

**X, developer guidelines** (`docs.x.com/developer-guidelines`) and **X
Developer Policy** (`developer.x.com/en/developer-terms/policy`), both as
published on 2026-11-13. The help-centre page "Automation rules"
(`help.x.com/en/rules-and-policies/x-automation`) refused the fetch and was not
read; the two pages above link to it as the rule they summarise.

- **Likes.** "Likes must be directly initiated by the authenticated user.
  Automated, bulk, or indiscriminate liking, including auto-liking by keyword,
  hashtag, user, or schedule, is prohibited. Apps may not offer 'auto-like'
  features." The table of automated actions says the same: "Like posts: must be
  directly user-initiated." A like a person taps in a third-party app is given
  as an allowed case.
- **Reposts and quote posts.** Allowed "for informational/entertainment"
  purposes, "no bulk spam"; a quote post follows "the same rules as repost, no
  spam or manipulation".
- **Replies.** "Only if user engaged first. Max 1 reply per interaction." An
  automatic reply to someone who replied to our post or mentioned us is
  allowed; one to a person who did neither is "unsolicited interaction". The
  Developer Policy: "Always get explicit consent before sending people
  automated replies." And: "AI-powered app generates and posts replies:
  requires prior approval from X" before it is deployed.
- **Posts.** An automated account may post scheduled content with no
  unsolicited mentions and no identical content across accounts.
- **The account itself.** An automated account enables the "Automated" profile
  label, says in its bio that it is automated and who operates it, is linked to
  a human-managed account, and honours a request to stop at once.

**LinkedIn, API Terms of Use** (`linkedin.com/legal/l/api-terms-of-use`, last
revised 13 December 2022). Section 3.1, among what a developer must not do:
"Use the Content or the APIs to automate posting on the LinkedIn Services."
The terms say nothing separate about reactions.

**Composio's tool list** (`docs.composio.dev/toolkits/twitter`, toolkit version
20261101_00; `docs.composio.dev/toolkits/linkedin`, version 20261112_00). The
slugs below are copied from it, not guessed:

| act | X | LinkedIn |
|---|---|---|
| like | `TWITTER_USER_LIKE_POST` (`id`: our user id, `tweet_id`) | no tool creates a reaction; only `LINKEDIN_LIST_REACTIONS` reads them |
| undo a like | `TWITTER_UNLIKE_POST` (`id`, `tweet_id`) | none |
| repost | `TWITTER_RETWEET_POST` (`tweet_id`) | `LINKEDIN_CREATE_LINKED_IN_POST` with `reshareContext` |
| undo a repost | `TWITTER_UNRETWEET_POST` (`source_tweet_id`) | `LINKEDIN_DELETE_POST` on the reshare |
| quote | `TWITTER_CREATION_OF_A_POST` with `quote_tweet_id` | `LINKEDIN_CREATE_LINKED_IN_POST` with `reshareContext` and a commentary |
| take down | `TWITTER_POST_DELETE_BY_POST_ID` (`id`) | `LINKEDIN_DELETE_POST` (`post_urn`), `LINKEDIN_DELETE_COMMENT` (`comment_id`, `entity_urn`) |
| who am I | `TWITTER_USER_LOOKUP_ME` | `LINKEDIN_GET_MY_INFO` |

Composio's managed credentials for X were removed in February 2026: the brand
brings its own X developer app, so the limits and the policy standing are the
brand's own.

## decision (proposed)

What the engine does, given what was read. Items 1 and 5 tighten what the
earlier decision allowed; none loosens it.

1. **A like on X is never automatic.** It stays one click on the dashboard,
   which is the case X allows, whatever the `like` mode says. The key
   `channels.reactions_signoff.<stream>` exists because the plan asked for it,
   and it stays empty: X's rule is a prohibition, not a limit, so a sign-off
   would record that the owner accepts a breach of it, not that the breach is
   allowed. This decision recommends it is never filled.
2. **A repost or a quote post on X may run on `auto`**, inside small daily caps
   (`reactions_per_day`), one per target ever, on an eligible target only: an
   author on a verified, cleared row of `handles.md`, on the watchlist, or
   replying to our own post. A quote post carries text of ours and takes the
   whole gate.
3. **LinkedIn has no like from the engine.** No tool creates one. It is done
   by hand.
4. **A reshare on LinkedIn stays on `review`** by recommendation: it is a post,
   and the API terms forbid automating posting.
5. **Three things the owner should settle before any kind runs on `auto`:**
   - on X, the account carries the "Automated" label and says so in its bio;
   - on X, automatic replies go only to someone who replied to our post or
     mentioned us, one each, and replies written by a model need X's prior
     approval. The auto-reply switch that already exists does not check
     either: until X has approved, keep the reply and comment modes on
     `review` for X;
   - on LinkedIn, a post that goes out with no person in the loop is what
     section 3.1 names. Keep the `post` mode on `review` for LinkedIn unless
     the brand's own LinkedIn app carries terms that say otherwise.

## alternatives considered

- **Automatic likes on X behind a dated owner sign-off**, as the plan first
  had it. Not recommended: see item 1.
- **Likes through a browser session instead of the API.** Rejected outright:
  X answers automation outside the API with permanent suspension.
- **No reactions at all.** Rejected: reposts and quote posts are allowed, and
  one-click likes are.

## consequences

We keep the account inside the platforms' rules and lose automatic likes on X,
which the owner asked for. Likes on X cost one click each. Reposts and quote
posts on X can still run on their own.

We watch for: a change in X's developer guidelines on likes (re-read at each
monthly readout), a reply from X on approval for model-written replies, and
any platform notice on the brand's accounts.

## sign-off

Not recorded. The owner signs by adding a dated line here, a role and never a
name, saying which items are accepted:

    signed off: YYYY-MM-DD, by the owner, for: items 1 to 5 as written

Until that line exists this file is a proposal, the engine behaves as items 1
to 4 say (they are the stricter reading), and item 5 is a list of things the
owner has been told and has not yet answered.

## review

At the first monthly readout, and at once on any change to the pages read
above or any platform notice.
