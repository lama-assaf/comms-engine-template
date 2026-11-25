# state — the engine's derived records

Everything here is written by the scripts under `../scripts/` and read back by
them, the desk and the dashboard page: the queue (`queue.json`), the run log
(`runs.json`), listening passes (`signals.json`), predictions, scores, the
calendar snapshot, the send ledger and the publish log. The vault note under
`Content/Calendar/` is the record; these files are indexes of it, and every
record names its stream (`scripts/state_check.py`).

The template ships this directory empty but for the two READMEs. The first
cycle creates what it needs; nothing here is edited by hand, and a few files
(`schedule.log`, `raw/`, `x-stream/`, the desk database) are gitignored because
they are audit trail, not source. `metrics-input/` is the one folder a person
writes into: see its README.
