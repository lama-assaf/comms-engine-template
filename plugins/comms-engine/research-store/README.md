# research store

The working store of what is being watched (glossary: *research store*):
findings, candidate claims, sources and demand per theme, as Graphiti episodes
over FalkorDB. Nothing cites it: a claim becomes citable only as a row in
`.atelier/memory/claims.md`, promoted through `/corpus-analyse` and
`/corpus-update` (plan v2, A16; decision 6 as amended 2026-10-23).

## what runs where

| piece | where | state |
|---|---|---|
| FalkorDB | `docker compose -f research-store/docker-compose.yml up -d` | local container; a host is an owner decision |
| Graphiti | `python3 -m pip install graphiti-core[falkordb]` into the engine's Python | not installed yet on this machine (Python 3.14; check the package supports it before installing) |
| extraction model | the Anthropic model already in use, through Graphiti's Anthropic client | key through `scripts/secrets.py` as `ANTHROPIC_API_KEY` |
| embedder | **an owner decision**: Graphiti needs an embedding model and Anthropic does not serve one. Options, all open or self-hosted first: a local model through an OpenAI-compatible endpoint (Ollama), or a hosted embedder (Voyage, OpenAI) with its own key | unset; the store runs without embeddings only for exact-match queries |

`scripts/research_store.py` is the only writer. With the store unreachable or
the client not installed it falls back to the files: the daily watch still
writes `Docs/Research/watch/<date>.md`, the planning queries run over the
files and say `queries: files`, and no gate verdict changes.

## entity types

Claim (candidate: text, grade, tier, corroboration, themes, source, date),
Source (name, tier, url, date), Topic (hashtag; demand), Content (a note by
engine id with its cites and date). Episodes are the watch's findings, the
register's rows, the notes and the signals, ingested as text with their
`stream` on every node.
