# claims — the fixture brand's register of what content may cite

One row per checkable claim. The shape is the one `scripts/memory.py` reads
from `.atelier/memory/claims.md`: a draft cites a row by `id`, the gate checks
that the id exists, is not superseded, and that a present-tense capability
sentence cites a row at grade `evidenced`. Written 2026-11-05 as a fixture;
the claims are invented.

**Columns.** `id` `C-acme-<n>`; `grade` evidenced · asserted · intended;
`tier` primary · institutional · trade · social; `themes` the hashtags the
claim bears on, or `—`; `corroboration` primary · two-independent · single ·
watching. The gate treats `watching` and `single` as uncitable.

## register

| id | claim | grade | source | date | tier | themes | supersedes | superseded_by | from | corroboration |
|---|---|---|---|---|---|---|---|---|---|---|
| C-acme-1 | Acme holds a qualification under the published issuer regime | evidenced | the register of qualified issuers, 2026-08-01 | 2026-08-01 | primary | #ThirdTheme | — | — | — | primary |
| C-acme-2 | The currency rail carries its own rules with each transfer | evidenced | the rail's published specification v2 | 2026-08-15 | primary | #FourthTheme | — | — | — | primary |
| C-acme-3 | Two trade outlets report a regulator reading the specification | asserted | trade press, two outlets, 2026-09-01 | 2026-09-01 | trade | #SixthTheme | — | — | — | two-independent |
| C-acme-4 | An identifier governed by a public standard is checkable by the relying party | evidenced | the standards body's governance framework | 2026-07-20 | primary | #ExampleTheme | — | — | — | primary |
| C-acme-5 | Acme operates a demonstrable issuance platform, shown to auditors | evidenced | the audit letter of 2026-09-03 | 2026-09-03 | primary | #SecondTheme | — | — | — | primary |
| C-acme-6 | The settlement set had four vetted members | evidenced | the membership list of 2026-06-01 | 2026-06-01 | primary | #SecondTheme | — | C-acme-7 | — | primary |
| C-acme-7 | The settlement set has five vetted members | evidenced | the membership list of 2026-09-10 | 2026-09-10 | primary | #SecondTheme | C-acme-6 | — | — | primary |
| C-acme-8 | A second jurisdiction is reading the identifier standard | asserted | one institutional report, not public | 2026-09-12 | institutional | #ExampleTheme | — | — | — | watching |
| C-acme-9 | Acme plans to provide the identity layer the wallet programme could anchor to | intended | Acme's own plan deck, 2026-09-15 | 2026-09-15 | primary | #ExampleTheme | — | — | — | two-independent |
| C-acme-10 | The compute region is accounted for by the hosting jurisdiction | asserted | one trade article | 2026-10-20 | trade | #FifthTheme | — | — | — | single |

## register log

- 2026-11-05: fixture written with ten rows.
