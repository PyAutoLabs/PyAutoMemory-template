# Canonical PyAutoMemory bibliography

`pyautomemory.bib` is the canonical metadata layer shared by every sub-wiki under `../wiki/` in this
repository. Wiki source entries explain which claims papers support; the BibTeX file records
citation metadata and canonical keys. Keep PDFs, local paths, abstracts, and long paper
summaries out of both layers.

> Renamed from `pyautopaper.bib` (when this repo was PyAutoPaper); the back-compat
> `pyautopaper.bib` symlink was retired in 2026-07 once nothing referenced it.

The initial canonical file prioritised `library.bib`. Entries with new keys from the other
tracked legacy `.bib` files were added, but conflicting records never replaced the
`library.bib` entry. The legacy root-level `.bib` files were deleted in 2026-07 after a
key-level audit confirmed every unique key already existed here (they remain in git
history). All canonical metadata lives in this folder; loose `.bib` files must not be
added elsewhere in the repo.

## Adding a paper

1. Verify the paper from an authoritative public record or the paper itself.
2. Search `pyautomemory.bib` by DOI, arXiv ID, and title. Reuse the existing canonical key;
   otherwise add verified metadata under a unique, stable author-year key.
3. Add a compact section to the relevant `../wiki/<domain>/sources/*.md` using the inherited
   schema in [`../wiki/CLAUDE.md`](../wiki/CLAUDE.md).
4. Add concept/entity links only where the paper materially supports existing text.
5. Run `make validate-literature-citations`.

Never record a local PDF path or infer claims from a filename. If metadata or support is
uncertain, add a TODO rather than guessing.

## Aliases and downstream projects

`bibkey_aliases.yaml` is a flat YAML mapping from a known alternate key to its canonical key:

```yaml
Suyu16H0: Suyu2016Holicow
```

Before patching another project's LaTeX, inspect that project's `.bib`. Match papers by DOI,
then arXiv ID, then title/authors, and use the project's existing key when present. Do not
assume a PyAutoMemory canonical key exists downstream. Add an alias only for an alternate key
that is actually in use.

## Validation

```bash
make validate-literature-citations
# or: python scripts/validate_literature_citations.py
```

Duplicate canonical keys, missing source keys, new claim entries without canonical keys, and
aliases with missing targets fail validation. Canonical entries not yet referenced by a wiki
source entry are reported but do not fail; use `--show-all` for the complete list.
