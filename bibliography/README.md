# Canonical PyAutoMemory bibliography

`pyautomemory.bib` is the canonical metadata layer shared by every sub-wiki under `../wiki/` in this
repository. Wiki source entries explain which claims papers support; the BibTeX file records
citation metadata and canonical keys. Keep PDFs, local paths, abstracts, and long paper
summaries out of both layers.

All canonical metadata lives in this folder; loose `.bib` files must not be
added elsewhere in the repo. (The file was consolidated from a legacy
personal library in 2026-07 — the merge audit is in git history.)

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

## Downstream projects

Before patching another project's LaTeX, inspect that project's `.bib`. Match papers by DOI,
then arXiv ID, then title/authors, and use the project's existing key when present. Do not
assume a PyAutoMemory canonical key exists downstream. (A key-alias subsystem existed but was
never used and was retired in #34; renaming a canonical key is a sed across the wiki, which
validation guards.)

## Validation

```bash
make validate-literature-citations
# or: python scripts/validate_literature_citations.py
```

Duplicate canonical keys, missing source keys, and new claim entries without canonical keys
fail validation. Canonical entries not yet referenced by a wiki source entry are reported but
do not fail; use `--show-all` for the complete list.
