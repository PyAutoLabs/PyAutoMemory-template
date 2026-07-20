"""Tests for the canonical PyAutoMemory citation layer."""

from pathlib import Path

from scripts.validate_literature_citations import (
    extract_canonical_keys,
    parse_aliases,
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


def _fixture_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    bibliography = tmp_path / "literature.bib"
    bibliography.write_text("@article{Alpha2024,\n}\n", encoding="utf-8")
    sources = tmp_path / "wiki" / "example" / "sources"
    sources.mkdir(parents=True)
    aliases = tmp_path / "aliases.yaml"
    aliases.write_text("", encoding="utf-8")
    return bibliography, sources, aliases


def test_detect_missing_canonical_key(tmp_path):
    bibliography, sources, aliases = _fixture_paths(tmp_path)
    (sources / "topic.md").write_text(
        "**Canonical BibTeX key:** `Missing2025`\n", encoding="utf-8"
    )

    result = validate_citations(bibliography, tmp_path, aliases)

    assert [citation.key for citation in result.missing_source_keys] == [
        "Missing2025"
    ]
    assert not result.valid


def test_validate_alias_targets(tmp_path):
    bibliography, _, aliases = _fixture_paths(tmp_path)
    aliases.write_text(
        "LocalKey: Alpha2024\nBrokenKey: Missing2025\n", encoding="utf-8"
    )

    result = validate_citations(bibliography, tmp_path, aliases)

    assert parse_aliases(aliases.read_text(encoding="utf-8")) == {
        "LocalKey": "Alpha2024",
        "BrokenKey": "Missing2025",
    }
    assert result.missing_alias_targets == (("BrokenKey", "Missing2025"),)
    assert not result.valid


def test_detect_claim_entry_without_key(tmp_path):
    bibliography, sources, aliases = _fixture_paths(tmp_path)
    (sources / "topic.md").write_text(
        "## Alpha 2024 — result\n\n**Supports:**\n- A claim.\n",
        encoding="utf-8",
    )

    result = validate_citations(bibliography, tmp_path, aliases)

    assert [(entry.key, entry.line) for entry in result.claim_entries_without_keys] == [
        ("Alpha 2024 — result", 1)
    ]
    assert not result.valid
