# templates

The shapes the engine copies when it creates a memory file for a stream.
`voice.md` is the one in use: `scripts/onboard.py --write-voice` fills
`__NAME__`, `__SLUG__` and `__DATE__` and writes it as a stream's `voice.md`,
headings only. Add a template here only when a script will read it; the shape
of every other per-stream file is documented in `../streams/README.md`.
