# /catch_up — "…so… I've been lost for a while"

After time away the suggestion tiers have lapsed (seven days), the reading
queue has grown, and the nightly digest may not even have run. This door
collects everything missed **since memory last took a paper in**, for one
scope, lets the human triage it once, and files what they choose. A
**PyAutoMemory primitive**: the harvest is `scripts/catch_up.py` (read its
docstring for how the cutoff and the three sources work); this skill curates
and files.

## Usage

```
/catch_up                      # strong lensing (the default)
/catch_up lensing
/catch_up interests            # SMBHs, Galaxy Formation / Evolution, Dark Matter, Stats, Interests
/catch_up interests SMBHs      # one interests topic (a reading-queue section, verbatim)
/catch_up all
/catch_up lensing --since 2026-09-01   # override the cutoff
```

## Steps

1. **Resolve the Memory checkout.** The canonical one, never a guessed sibling:
   `python3 <Brain>/agents/_repo_paths.py path PyAutoMemory --required --root <workspace>`.
   Report its repo root and branch. Filing needs a clean worktree off
   `origin/main` on a `feature/catch-up-<scope>-<date>` branch
   (`git worktree add -b … <path> origin/main`); the harvest itself is
   read-only and may run from the canonical checkout.
2. **Harvest.** `python scripts/catch_up.py --scope <scope> [--topic <T>] [--since D] --json`
   (network: the arXiv gap-fill imports the Mind digest's query; set
   `PYAUTO_MIND` if Mind is not found). Report one line:
   **"N days lost, M candidates since <cutoff>"** — plus the per-source counts
   (`counts`: queue / history / arxiv), `dropped_in_memory`, and every entry of
   `warnings` verbatim (a skipped arXiv source or a `truncated` interests
   window is a real gap, never hide it).
3. **Curate.** Read each candidate's abstract (fetch it from arXiv for the few
   with none) and rank against the human's interests — take the concepts from
   the scope's `wiki/<domain>/index.md` (for lensing: PyAutoLens-style
   modelling methods, dark-matter substructure, interferometry, Euclid and
   survey lens searches, time-delay cosmography, lensed sources/quasars, JAX /
   differentiable inference). Propose four tiers, each paper with a one-line
   **why**:
   - **intake** — full filing: bib entry + a proper section in `sources/`.
   - **cite** — bib entry + a one-line stub, worth citing, not pivotal.
   - **queue** — not now; add (or keep) a `reading-queue.md` line.
   - **skip** — off-topic or superseded; nothing is written.
   More than ~20 candidates → a ranked table (tier · id · title · first
   author · why), intake and cite first. Queue lines already in the queue that
   land in **queue** or **skip** stay as they are — never delete a queue line.
4. **Stop for the human.** Present the table and wait. They move papers
   between tiers; the confirmed table is the only input to step 5. This is the
   one human gate — do not file anything before it.
5. **File.** In the filing worktree, delegate to **Opus subagents** in batches
   (≈5–8 papers each, disjoint `sources/` pages where possible, each given a
   progress file). Each paper follows the board's filing recipe
   (`_read_prompt` in `scripts/board.py`):
   verify it against an authoritative record (arXiv / ADS), add its canonical
   entry to `bibliography/pyautomemory.bib` per `bibliography/README.md`
   ("Adding a paper" — search for an existing key first), stub it in the
   matching `wiki/<domain>/sources/*.md` page per `wiki/AGENTS.md` (intake: a
   full section; cite: a one-line stub), and mark any queue line
   `DONE <YYYY-MM-DD> — <title>` in place. **queue** tier papers not already
   queued get a line appended to the right `## <Section>` (title ` — <arXiv id>`).
6. **Validate and record.** `make validate` (and `make test` if a script was
   touched) must be green. Append one entry to each touched
   `wiki/<domain>/log.md`: `## <date> — Catch-up since <cutoff>` listing the
   papers filed per tier.
7. **Ship.** One commit, one PR against `main` summarising the tier counts and
   the cutoff; report its URL and stop. The human merges — a paper is not in
   memory until the PR lands (the dashboard banner resets from the merge).

## Notes

- The cutoff is the newest DONE line in the scope's queue sections or the
  newest commit that adds a bib entry **and** touches the scope's
  `wiki/<domain>/sources/` (a restructure or a bib tidy-up does not count). A
  scope never ingested (the interests sub-wikis were imported, not filed) cuts
  off at its oldest suggestion instead, and says so in `warnings`.
- The interests arXiv query is whole categories; it is capped (most recent
  first) and reported `truncated`. Lean on the interests-file history there,
  and narrow with a topic.
- Never arm a wait for CI or the merge; end at the PR.
