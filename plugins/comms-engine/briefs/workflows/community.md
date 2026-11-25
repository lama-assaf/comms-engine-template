# community

Drafts for the Telegram or Discord of the stream {stream_name}. Your brief is
the file `briefs/community.md`: read it first and
follow it. You know nothing else of this repository.

Draft from what is already gated (`state/queue.json`,
gate verdict `pass`), write each draft as a proposal in
`state/engagement.json`, each proposal with `stream`
"{stream_name}" (`state_check.py` refuses any record without it), and send
nothing. Code checks the file still reads and logs the step.

Return: `proposals` (how many drafts you wrote).
