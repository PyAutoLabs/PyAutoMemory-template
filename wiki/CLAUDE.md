# PyAutoMemory wikis — shared schema + usage rules

Every sub-wiki under `wiki/` gives an AI assistant broad scientific context
for one domain. They follow Karpathy's "LLM Wiki" pattern: concise,
cross-linked pages are read at query time, while canonical citation metadata
lives separately in [`../bibliography/`](../bibliography/README.md). This
file defines the schema once; each sub-wiki's own `CLAUDE.md` diverges only
on scope.

## Layout

```
PyAutoMemory/                  # repo root
├── wiki/                     # all sub-wikis (in git)
│   ├── CLAUDE.md             # this file — schema + usage rules
│   └── <domain>/             # one domain per sub-wiki, e.g. lensing/
│       ├── CLAUDE.md         # the sub-wiki's scope notes
│       ├── index.md          # the sub-wiki's own navigation
│       ├── log.md            # append-only compilation log
│       ├── concepts/         # one topic per page — the science
│       ├── entities/         # named things: surveys, instruments, software
│       └── sources/          # compact claim support (one paper = one section)
└── bibliography/             # canonical BibTeX, aliases, citation tooling
```

Papers are the ground truth; wiki pages are syntheses. If they disagree, update
the wiki and note the change in the sub-wiki's `log.md`.

## References and citation metadata

- `sources/*.md` records compact guidance about what claims a paper supports.
- `../bibliography/pyautomemory.bib` records canonical metadata and keys.
- `../bibliography/bibkey_aliases.yaml` maps known alternate keys to canonical keys.

Never record local PDF paths or fabricate metadata — source PDFs live
off-repo. A canonical key is local to PyAutoMemory: resolve it against a
target project's `.bib` before patching LaTeX. See
[`../bibliography/README.md`](../bibliography/README.md) for the workflow.

## Page types

| Type        | Folder       | Scope                                                 |
|-------------|--------------|-------------------------------------------------------|
| Concept     | `concepts/`  | One scientific concept (e.g. mass-sheet degeneracy)   |
| Entity      | `entities/`  | One named thing (survey, lens, code, collaboration)   |
| Sources     | `sources/`   | Claim support for one topic, one section per paper    |
| Index/log   | root         | Navigation and provenance                             |

## Naming

- File names are lowercase kebab-case: `mass-sheet-degeneracy.md`,
  `h0licow.md`, `time-delay-cosmography.md`.
- One concept per concept page. If a page tries to cover two ideas, split it.
- Source-collection pages are named by topic: `sources/dark-matter-substructure.md`.

## Cross-references

Use `[[page-slug]]` for wiki-internal links — for example
`[[mass-sheet-degeneracy]]` or `[[h0licow]]`. Slugs match the filename without
`.md`. A `[[link]]` that has no target file yet is fine — it marks a future
page to write.

External references use verified DOI, arXiv, journal, or author/year/title
metadata, never a local path.

## Frontmatter

Every wiki file starts with YAML frontmatter:

```yaml
---
title: Mass-sheet degeneracy
type: concept            # concept | entity | sources | meta
topics: [degeneracies, cosmography]
sources:                 # optional — papers most relevant to this page
  - Suyu et al. 2017 — H0LiCOW overview
  - Birrer et al. 2020 — TDCOSMO IV
status: stub             # stub | drafted | reviewed
---
```

Sources may be `[]` for pages that synthesize general field knowledge.

## Concept page structure

```
# Title

## TL;DR
One paragraph an assistant can quote back to a user.

## What it is
The physics / definition.

## Why it matters
How this concept shows up in the decisions the domain's software users make.

## Key results from the literature
Bullet list. Each bullet ends with `([[author-year-stub]])` so the LLM can
follow the link to the per-paper section.

## See also
- [[related-concept-1]]
- [[related-concept-2]]
```

## Entity page structure

Same idea but the headings are "What it is / Key facts / Papers / See also".
Use entity pages for: surveys (BELLS, H0liCOW), specific objects
(Abell 1201, the Cosmic Horseshoe), software (PyAutoLens, lenstronomy),
collaborations (TDCOSMO, Space Warps).

## Source-collection page structure

```
# Sources: <topic>

Papers covering this topic. Each paper has its own H2 section; cross-link with
`[[sources-<topic>#author-year-slug]]`.

## Author Year — short tag

**Canonical BibTeX key:** `KeyYYYY`
**Reference:** DOI/arXiv/journal reference if known
**Concepts:** [[concept-1]], [[concept-2]]

**Supports:**
- Claim this paper directly supports.
- Another claim this paper directly supports.

**Use when:**
- Situation where the citation is appropriate.

**Do not use for:**
- Similar but unsupported claim.
```

Keep entries short: normally 2–5 support bullets and no long prose. Do not copy
abstracts or infer claims from filenames. Add a TODO when support is unverified.

## How the assistant should use a wiki

1. On a user question, first open the sub-wiki's `index.md`.
2. Follow the relevant `concepts/` or `entities/` page.
3. Follow the source entry for claim scope and its canonical key for metadata.
4. Resolve that key against downstream `.bib` files before changing LaTeX.
5. If support or metadata is unclear, read the public paper and add a TODO
   rather than guessing. Log verified upgrades.

## Adding a sub-wiki

Create `wiki/<domain>/` with its own `CLAUDE.md` (scope notes only — this
schema is inherited, not copied), `index.md`, `log.md`, and the three page
folders. Give it a row in the repo-root `index.md` and `README.md` tables.
