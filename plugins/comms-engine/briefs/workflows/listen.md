# listen

Run the listening pass for the stream {stream_name}, as your definition
describes: `scripts/listen.py`, the primary-source sweep, then write
`state/signals.json` and log `assess` through `scripts/runlog.py`.

Return: `findings` (how many findings you wrote), `content` (how many are
content-shaped, for the writer), `conversation` (how many are conversation-shaped,
for the engagement pass).
