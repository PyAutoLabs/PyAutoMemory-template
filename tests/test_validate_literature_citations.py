"""Tests for the canonical PyAutoMemory citation layer."""

from pathlib import Path

from scripts.validate_literature_citations import (
    extract_canonical_keys,
    parse_bibtex,
    validate_citations,
)


def test_parse_small_bibtex_file():
    inventory = parse_bibtex(
        """
@article{Alpha2024,
  title = {Alpha},
}
@misc{Beta2025,
  title = {Beta},
}
"""
    )

    assert inventory.keys == {"Alpha2024", "Beta2025"}
    assert inventory.duplicates == ()


def test_extract_canonical_keys_from_source_markdown():
    citations = extract_canonical_keys(
        """
## Alpha 2024 — result

**Canonical BibTeX key:** `Alpha2024`
**Reference:** doi:example
"""
    )

    assert [(citation.key, citation.line) for citation in citations] == [
        ("Alpha2024", 4)
    ]


def _fixture_paths(tmp_path: Path) -> tuple[Path, Path]:
    bibliography = tmp_path / "literature.bib"
    bibliography.write_text("@article{Alpha2024,\n}\n", encoding="utf-8")
    sources = tmp_path / "wiki" / "example" / "sources"
    sources.mkdir(parents=True)
    return bibliography, sources


def test_detect_missing_canonical_key(tmp_path):
    bibliography, sources = _fixture_paths(tmp_path)
    (sources / "topic.md").write_text(
        "**Canonical BibTeX key:** `Missing2025`\n", encoding="utf-8"
    )

    result = validate_citations(bibliography, tmp_path)

    assert [citation.key for citation in result.missing_source_keys] == [
        "Missing2025"
    ]
    assert not result.valid


def test_detect_claim_entry_without_key(tmp_path):
    bibliography, sources = _fixture_paths(tmp_path)
    (sources / "topic.md").write_text(
        "## Alpha 2024 — result\n\n**Supports:**\n- A claim.\n",
        encoding="utf-8",
    )

    result = validate_citations(bibliography, tmp_path)

    assert [(entry.key, entry.line) for entry in result.claim_entries_without_keys] == [
        ("Alpha 2024 — result", 1)
    ]
    assert not result.valid


def test_seed_pages_are_validated_like_sources(tmp_path):
    # `seed/` holds the 2026-05 import's unverified source pages. It is where a
    # broken canonical key is most likely to sit, so the validator must walk it
    # rather than go quiet on the half of the wiki that needs it most.
    bibliography, _ = _fixture_paths(tmp_path)
    seed = tmp_path / "wiki" / "example" / "seed"
    seed.mkdir(parents=True)
    (seed / "topic.md").write_text(
        "**Canonical BibTeX key:** `Missing2025`\n", encoding="utf-8"
    )

    result = validate_citations(bibliography, tmp_path)

    assert [citation.key for citation in result.missing_source_keys] == [
        "Missing2025"
    ]
    assert not result.valid
