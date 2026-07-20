# PyAutoMemory — Agent Guidance

PyAutoMemory is the **Memory organ** of the PyAuto organism: long-term
knowledge — *what the science says*. Literature wikis, concepts, entities,
bibliographies. (The organs and boundaries are defined once in
`PyAutoBrain/ORGANISM.md`.)

## The read contract

Memory is **pull-only, on demand** — no agent queries it automatically. Consult
it when the work is scientific or a plan names a domain (lensing, SMBH,
CTI/Euclid, inference methods, galaxy evolution); skip it entirely for
packaging, tooling, and workflow tasks.

When you do read:

1. **Index first.** Start at [`index.md`](index.md), then the relevant
   sub-wiki's own `index.md` (`wiki/lensing/`, `wiki/smbh/`, `wiki/cti/`,
   `wiki/methods/`, `wiki/galaxies/`).
2. **Then at most 2–3 pages.** Read only the concept/entity/source pages the
   index points you to. **Never bulk-load a sub-wiki.**
3. **Do not couple to the internal layout** — reach pages through the indexes,
   not hard-coded paths.

## The write contract (layout rules)

The repo has exactly **two content homes**, enforced by
`make validate-structure` (CI runs it on every push/PR):

- **`wiki/<domain>/`** — every sub-wiki, following the shared schema in
  [`wiki/CLAUDE.md`](wiki/CLAUDE.md). New sub-wikis are added beside the
  existing ones, never at the repo root.
- **`bibliography/`** — the *only* place BibTeX lives. One canonical file
  (`pyautomemory.bib`) plus `bibkey_aliases.yaml`; never add loose `.bib`
  files anywhere else.

**Source PDFs live off-repo.** Never commit a paper (PDF/HTML, with or
without a file extension) — read it, stub it in the right
`wiki/<domain>/sources/*.md`, add its canonical entry to `bibliography/`,
and run `make validate`. Unrecognised top-level files/folders fail the lint;
the allowlist is in `scripts/validate_structure.py`.

## What does NOT live here

- **Operational history** — what the organism *did* (prior tasks, decisions,
  failed approaches) lives in **PyAutoMind** (the `complete/<YYYY>/<MM>/`
  records, GitHub issues), not here. Memory = what the science says; Mind = what
  the organism did.
- **Workflow state, health, execution** — Mind / Heart / Build respectively.

## This repo is personal

PyAutoMemory contains personal research material. **Never reference or copy
PyAutoMemory content into public or user-facing repos** (libraries,
workspaces, tutorials, assistants).

<!-- repos_sync:history:begin -->
## Never rewrite history

Never rewrite pushed history on any repo with a remote — no `git init` over a
tracked repo, no force-push to `main`, no fresh-start "Initial commit", no
`filter-repo` / `filter-branch` / `rebase -i` on pushed branches. To get a
clean tree: `git fetch origin && git reset --hard origin/main && git clean -fd`.
<!-- repos_sync:history:end -->
