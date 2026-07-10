# example_wiki — schema + usage rules

This sub-wiki gives an AI assistant broad context for one domain. It follows
Karpathy's "LLM Wiki" pattern: concise, cross-linked pages read at query
time, while canonical citation metadata lives separately in
`../bibliography/`. Copy this folder to start a real sub-wiki; every sibling
wiki inherits this schema.

## Layout

```
PyAutoMemory/
├── example_wiki/             # one domain — the compiled wiki (in git)
│   ├── CLAUDE.md             # this file — schema + usage rules
│   ├── index.md              # the wiki's own navigation
│   ├── concepts/             # one topic per page — the science
│   ├── entities/             # named things: surveys, instruments, software
│   └── sources/              # compact claim support (one source = one section)
└── bibliography/             # canonical BibTeX, aliases, citation tooling
```

Sources are the ground truth; wiki pages are syntheses. If they disagree,
update the wiki and log the change.

## Page types

| Type    | Folder      | Scope                                            |
|---------|-------------|--------------------------------------------------|
| Concept | `concepts/` | One idea per page — split pages that cover two   |
| Entity  | `entities/` | One named thing (survey, instrument, code, team) |
| Sources | `sources/`  | Claim support for one topic, one section/source  |
| Index   | root        | Navigation and provenance                        |

## Conventions

- File names are lowercase kebab-case; one concept per concept page.
- Wiki-internal links use `[[page-slug]]`; a link with no target yet is
  fine — it marks a future page.
- External references use verified DOI/arXiv/journal metadata, never a
  local path; canonical keys live in `../bibliography/` and are validated
  by `make validate-literature-citations`.
- Every page starts with YAML frontmatter: `title`, `type`
  (concept | entity | sources | meta), `topics`, optional `sources`, and
  `status` (stub | drafted | reviewed).

## Concept page structure

`# Title` → `## TL;DR` (one quotable paragraph) → `## What it is` →
`## Why it matters for your project` → `## Key results from the
literature` (each bullet ends with a `([[source-slug]])` link) →
`## See also`.

## Source-collection page structure

One H2 section per source: the canonical BibTeX key, the reference, the
concepts it supports, a short **Supports:** bullet list, and **Use when /
Do not use for** guidance. Keep entries to 2–5 support bullets; never copy
abstracts or infer claims from filenames — add a TODO when support is
unverified.

## How an assistant should use this wiki

Open `index.md` first; follow the relevant concept/entity page; follow the
source entry for claim scope and its canonical key for metadata; if
support is unclear, read the public source and add a TODO rather than
guessing.
