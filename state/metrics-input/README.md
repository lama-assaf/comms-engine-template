# metrics-input — numbers a person read off the platform

Until the LinkedIn and X logins exist (plan v2, Block C), this folder is the
only full source of engagement numbers. `scripts/score.py` reads it nightly;
everything else it knows comes from listening and is marked partial.

One file per published item, named by its id (`Q-…`, the engine's queue id;
an item published before the engine kept its own id): `state/metrics-input/<id>.json`.
Add a read each time you look; the scorer uses the latest read before each
window closes (72 hours, 7 days).

```json
{"reads": [
  {"at": "2026-10-30T08:00:00+01:00", "platform": "X",
   "impressions": 1200, "likes": 14, "reposts": 3, "quotes": 2,
   "replies": 5, "substantive_replies": 2, "saves": 1,
   "link_clicks": 9, "profile_clicks": 4,
   "negatives": {"unfollows": 0, "hides": 0, "corrections": 1}}
]}
```

- Counts only. Never write a handle, a name or a comment's text here.
- `substantive_replies`: replies that ask, object or add, not a bare emoji
  or "great post". `corrections`: replies that say the post is wrong.
- One object per platform per read; LinkedIn and X for the same piece go
  in the same file as separate reads.
