"""Tests for the read-only canonical-key candidates report."""

from pathlib import Path

from scripts.canonical_key_candidates import (
    build_report,
    fold,
    parse_entries,
    render_markdown,
    surname,
)

BIB = """
@article{Smith2019,
author = {Smith, Jane and Doe, John},
doi = {10.1000/abc.1},
eprint = {1901.00001},
title = {{Supermassive black holes in the early universe}},
year = {2019}
}

@article{Gomez2016,
author = {G{\\'{o}}mez, L. G. and Arg{\\"{u}}elles, C. R.},
title = {{Strong lensing by fermionic dark matter in galaxies}},
year = {2016}
}

@article{Hall2014,
author = {Hall, D. J.},
title = {{Single-trap pumping technique}},
year = {2014}
}

@article{Hall2014a,
author = {Hall, D. J.},
title = {{In situ trap parameter studies}},
year = {2014}
}
"""

TODO = """**Canonical BibTeX key:** TODO — no unique match found in `bibliography/pyautomemory.bib`.
**Reference:** TODO — identify the public paper record.
"""


def _write(tmp_path: Path, page: str) -> Path:
    bib = tmp_path / "bibliography" / "pyautomemory.bib"
    bib.parent.mkdir(parents=True)
    bib.write_text(BIB, encoding="utf-8")
    sources = tmp_path / "wiki" / "demo" / "sources"
    sources.mkdir(parents=True)
    (sources / "page.md").write_text(page, encoding="utf-8")
    return bib


def test_fold_and_surname_strip_latex_accents():
    assert fold("G{\\'{o}}mez") == "gomez"
    assert surname("G{\\'{o}}mez, L. G. and Other, A.") == "gomez"
    assert surname("Jane Smith and John Doe") == "smith"


def test_parse_entries_reads_identifiers():
    entries = {entry.key: entry for entry in parse_entries(BIB)}
    assert entries["Smith2019"].doi == "10.1000/abc.1"
    assert entries["Smith2019"].arxiv == "1901.00001"
    assert entries["Gomez2016"].first_author == "gomez"


def test_unique_author_year_with_tag_overlap_is_high(tmp_path):
    bib = _write(tmp_path, "# P\n\n## Gómez 2016 — fermionic DM\n\n" + TODO)
    (section,) = build_report(tmp_path, bib)
    assert section.candidates[0]["key"] == "Gomez2016"
    assert section.candidates[0]["confidence"] == "high"


def test_doi_in_body_is_exact_and_ranked_first(tmp_path):
    page = "# P\n\n## Hall 2014 — anything\n\n" + TODO + "See doi:10.1000/abc.1\n"
    bib = _write(tmp_path, page)
    (section,) = build_report(tmp_path, bib)
    assert section.candidates[0] == {
        "key": "Smith2019", "by": "doi", "confidence": "exact", "score": 1.0,
        "title": "Supermassive black holes in the early universe",
    }


def test_ambiguous_author_year_ranks_by_tag_and_never_high(tmp_path):
    bib = _write(tmp_path, "# P\n\n## Hall 2014 — traps in situ\n\n" + TODO)
    (section,) = build_report(tmp_path, bib)
    assert [c["key"] for c in section.candidates] == ["Hall2014a", "Hall2014"]
    assert section.candidates[0]["confidence"] == "medium"
    assert section.candidates[1]["confidence"] == "low"


def test_filled_sections_are_ignored_and_report_never_writes(tmp_path):
    page = "# P\n\n## Smith 2019 — SMBHs\n\n**Canonical BibTeX key:** `Smith2019`\n"
    bib = _write(tmp_path, page)
    before = (tmp_path / "wiki/demo/sources/page.md").read_text()
    assert build_report(tmp_path, bib) == []
    assert "TODO sections: 0" in render_markdown([])
    assert (tmp_path / "wiki/demo/sources/page.md").read_text() == before


def test_normalize_arxiv_strips_prefix_and_version():
    from scripts.canonical_key_candidates import normalize_arxiv

    assert normalize_arxiv("arxiv:1302.1873v1") == "1302.1873"
    assert normalize_arxiv("astro-ph/0101213") == "astro-ph/0101213"


def test_title_only_heading_matches_by_normalized_title(tmp_path):
    page = "# P\n\n## Strong lensing fermionic dark matter galaxies\n\n" + TODO
    bib = _write(tmp_path, page)
    (section,) = build_report(tmp_path, bib)
    assert section.candidates[0]["key"] == "Gomez2016"
    assert section.candidates[0]["by"] == "title"


def test_prefixed_heading_parses_inner_author_year(tmp_path):
    bib = _write(tmp_path, "# P\n\n## UnRead — Smith 2019 black holes early universe\n\n" + TODO)
    (section,) = build_report(tmp_path, bib)
    assert section.author == "smith" and section.year == "2019"
    assert section.candidates[0]["key"] == "Smith2019"
