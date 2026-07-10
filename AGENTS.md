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
   sub-wiki's own `index.md` (`lensing_wiki/`, `smbh_wiki/`, `cti_wiki/`,
   `methods_wiki/`, `galaxies_wiki/`).
2. **Then at most 2–3 pages.** Read only the concept/entity/source pages the
   index points you to. **Never bulk-load a sub-wiki.**
3. **Do not couple to the internal layout** — reach pages through the indexes,
   not hard-coded paths.

## What does NOT live here

- **Operational history** — what the organism *did* (prior tasks, decisions,
  failed approaches) lives in **PyAutoMind** (`complete.md`, GitHub issues),
  not here. Memory = what the science says; Mind = what the organism did.
- **Workflow state, health, execution** — Mind / Heart / Build respectively.

## This repo is personal

PyAutoMemory contains personal research material. **Never reference or copy
PyAutoMemory content into public or user-facing repos** (libraries,
workspaces, tutorials, assistants).
