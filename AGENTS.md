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
  [`wiki/AGENTS.md`](wiki/AGENTS.md). New sub-wikis are added beside the
  existing ones, never at the repo root.
- **`bibliography/`** — the *only* place BibTeX lives. One canonical file
  (`pyautomemory.bib`); never add loose `.bib` files anywhere else.

**Source PDFs live off-repo.** Never commit a paper (PDF/HTML, with or
without a file extension) — read it, stub it in the right
`wiki/<domain>/sources/*.md`, add its canonical entry to `bibliography/`,
and run `make validate`. Unrecognised top-level files/folders fail the lint;
the allowlist is in `scripts/validate_structure.py`.

## Skills

Organ-owned skills live in `skills/<name>/` (`SKILL.md` + the procedure),
like Mind's. [`skills/catch_up/`](skills/catch_up/catch_up.md) is the
after-time-away door: `scripts/catch_up.py` harvests what was missed since
the last ingest, the agent curates it into intake / cite / queue / skip, the
human confirms once, and the chosen papers are filed in one PR.

## What does NOT live here

- **Operational history** — what the organism *did* (prior tasks, decisions,
  failed approaches) lives in **PyAutoMind** (the `complete/<YYYY>/<MM>/`
  records, GitHub issues), not here. Memory = what the science says; Mind = what
  the organism did.
- **Workflow state, health, execution** — Mind / Heart / Build respectively.

## Scope: personal research material, out of scope for user-facing repos

PyAutoMemory holds personal research material. It is a public repo and its
wiki content is CC BY 4.0 (see LICENSE), but it is **out of scope for the
user-facing repos** (libraries, workspaces, tutorials, assistants): link to
it if you must, never inline or copy its content there — user-facing docs
must stand on their own without it.

<!-- repos_sync:history:begin -->
## Never rewrite history

Never rewrite pushed history on any repo with a remote — no `git init` over a
tracked repo, no force-push to `main`, no fresh-start "Initial commit", no
`filter-repo` / `filter-branch` / `rebase -i` on pushed branches. To get a
clean tree: `git fetch origin && git reset --hard origin/main && git clean -fd`.
<!-- repos_sync:history:end -->

<!-- repos_sync:deliverable:begin -->
## Sessions end at their deliverable

A session ends when it reports its deliverable — never arm anything that
outlives the turn to wait for CI, a review or a merge: no `send_later`, no
`subscribe_pr_activity`, no `CronCreate`, no `ScheduleWakeup`, no `/loop`, no
`RemoteTrigger` create/update/run. Judge once, report, stop; the human re-runs
`/prm` (or the batch review) when it is green. Measured: five batch members
armed hourly check-ins on 2026-08-31, and a mobile `/prm` re-armed a 60-minute
`send_later` hourly all night on 2026-09-03 with no task active, draining usage.
<!-- repos_sync:deliverable:end -->

<!-- repos_sync:filing:begin -->
## Where to file

Questions, help with code or an analysis, ideas, bug reports and results from a
user or collaborator — or an agent acting for one — go to
<https://github.com/orgs/PyAutoLabs/discussions> in the matching category
(Help & Questions, Ideas & Proposals, Bugs & Errors, Show and tell;
Announcements is maintainers-only), never to this repo's Issues. An agent never
runs `gh issue create` for such a report: it drafts the title, category and
body and hands them to the human (sessions cannot create Discussions). Only the
development flow — Mind prompt → `/start_dev` → `/create_issue` → one issue per
task → PR — opens issues here. Why: `PyAutoMind/policy/community_surface.md`.
<!-- repos_sync:filing:end -->

<!-- repos_sync:standards:begin -->
## Shared standards

Before changing a shared interface, consult the applicable
[organism standard](https://github.com/PyAutoLabs/PyAutoBrain/blob/main/docs/standards.md)
on demand, identify affected consumers, and validate their adoption. Change
generated guidance at its canonical source and regenerate.

For board changes, follow the applicable sizing, navigation and orchestration
standards and reuse Brain’s shared components. Keep domain data, prompt meaning
and approval boundaries with the board’s owner.
<!-- repos_sync:standards:end -->
