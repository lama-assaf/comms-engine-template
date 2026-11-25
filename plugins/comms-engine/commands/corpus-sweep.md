---
description: Sweep every folder of the strategy corpus (the root from engine.json) and report where each source stands - unread, stale, read, analysed or applied to memory. Step 1 of /corpus-cycle.
argument-hint: [--root <path>]
allowed-tools: Bash, Read, Glob, Grep
---

# /corpus-sweep

Inventory, nothing else. Walks every subfolder of the corpus root
(`params.corpus.root` in `engine.json`, overridden by
`--root`), whatever folders it holds now and whatever is added later,
fingerprints each file and reports its stage:

| stage | meaning | next command |
|---|---|---|
| `unread` | nothing in the repo reads it | `/corpus-read` |
| `stale` | the source changed after it was read | `/corpus-read` |
| `read` | narrative or extracted text exists, no brief yet | `/corpus-analyse` |
| `analysed` | a brief in `Docs/Research/` covers it, memory not yet updated | `/corpus-update` |
| `applied` | its brief's edits are in `.atelier/memory/` | nothing |

```bash
engine corpus_sweep --write $ARGUMENTS
```

Writes `Docs/Research/_corpus/manifest.json` and `sweep.md`. Both gitignored
on purpose: file names alone can name stealth partners.

Show the user the three to-do tables (needs reading, needs analysis, needs
memory update) and the one-line counts. Exit code 1 means something is pending;
exit code 2 means the root is not mounted or not yet set (`engine setup
corpus --root <path>`). Do not read, analyse or edit anything from here; say
which command comes next.
