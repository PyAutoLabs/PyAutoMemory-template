"""Validate links between PyAutoMemory source entries and canonical BibTeX metadata."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BIBLIOGRAPHY = ROOT / "bibliography" / "pyautomemory.bib"
DEFAULT_ALIASES = ROOT / "bibliography" / "bibkey_aliases.yaml"

BIBTEX_ENTRY = re.compile(
    r"^\s*@(?!comment\b|string\b|preamble\b)[A-Za-z]+\s*[({]\s*([^,\s]+)\s*,",
    re.MULTILINE | re.IGNORECASE,
)
CANONICAL_KEY = re.compile(
    r"^\*\*Canonical BibTeX key:\*\*\s*`([^`]+)`\s*$", re.MULTILINE
)
SOURCE_SECTION = re.compile(
    r"^## (?!See also\s*$)(.+?)\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL
)


@dataclass(frozen=True)
class BibtexInventory:
    keys: frozenset[str]
    duplicates: tuple[str, ...]


@dataclass(frozen=True)
class SourceCitation:
    path: Path
    line: int
    key: str


@dataclass(frozen=True)
class CitationValidation:
    bibliography: BibtexInventory
    citations: tuple[SourceCitation, ...]
    aliases: dict[str, str]
    missing_source_keys: tuple[SourceCitation, ...]
    claim_entries_without_keys: tuple[SourceCitation, ...]
    unreferenced_bibtex_keys: tuple[str, ...]
    missing_alias_targets: tuple[tuple[str, str], ...]

    @property
    def valid(self) -> bool:
        return not (
            self.bibliography.duplicates
            or self.missing_source_keys
            or self.claim_entries_without_keys
            or self.missing_alias_targets
        )


def parse_bibtex(text: str) -> BibtexInventory:
    """Parse entry keys without requiring a third-party BibTeX package."""

    seen: set[str] = set()
    duplicates: set[str] = set()
    for key in BIBTEX_ENTRY.findall(text):
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return BibtexInventory(frozenset(seen), tuple(sorted(duplicates)))


def extract_canonical_keys(
    markdown: str, path: Path = Path("<memory>")
) -> tuple[SourceCitation, ...]:
    return tuple(
        SourceCitation(
            path=path,
            line=markdown.count("\n", 0, match.start()) + 1,
            key=match.group(1),
        )
        for match in CANONICAL_KEY.finditer(markdown)
    )


def source_directories(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(path for path in root.glob("*_wiki/sources") if path.is_dir()))


def collect_source_citations(directories: tuple[Path, ...]) -> tuple[SourceCitation, ...]:
    citations: list[SourceCitation] = []
    for directory in directories:
        for path in sorted(directory.glob("*.md")):
            citations.extend(
                extract_canonical_keys(path.read_text(encoding="utf-8"), path=path)
            )
    return tuple(citations)


def collect_claim_entries_without_keys(
    directories: tuple[Path, ...],
) -> tuple[SourceCitation, ...]:
    missing: list[SourceCitation] = []
    for directory in directories:
        for path in sorted(directory.glob("*.md")):
            markdown = path.read_text(encoding="utf-8")
            for section in SOURCE_SECTION.finditer(markdown):
                body = section.group(2)
                if "**Supports:**" in body and not CANONICAL_KEY.search(body):
                    missing.append(
                        SourceCitation(
                            path=path,
                            line=markdown.count("\n", 0, section.start()) + 1,
                            key=section.group(1),
                        )
                    )
    return tuple(missing)


def parse_aliases(text: str) -> dict[str, str]:
    """Parse the intentionally flat alias-to-canonical YAML mapping."""

    aliases: dict[str, str] = {}
    content = text.strip()
    if not content or content == "{}":
        return aliases

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "{}":
            continue
        if ":" not in stripped:
            raise ValueError(f"invalid alias mapping on line {line_number}: {line!r}")
        alias, canonical = (
            part.strip().strip("'\"") for part in stripped.split(":", 1)
        )
        if not alias or not canonical:
            raise ValueError(f"invalid alias mapping on line {line_number}: {line!r}")
        aliases[alias] = canonical
    return aliases


def validate_citations(
    bibliography_path: Path = DEFAULT_BIBLIOGRAPHY,
    root: Path = ROOT,
    aliases_path: Path = DEFAULT_ALIASES,
) -> CitationValidation:
    bibliography = parse_bibtex(bibliography_path.read_text(encoding="utf-8"))
    directories = source_directories(root)
    citations = collect_source_citations(directories)
    claim_entries_without_keys = collect_claim_entries_without_keys(directories)
    aliases = parse_aliases(aliases_path.read_text(encoding="utf-8"))
    cited_keys = {citation.key for citation in citations}

    return CitationValidation(
        bibliography=bibliography,
        citations=citations,
        aliases=aliases,
        missing_source_keys=tuple(
            citation for citation in citations if citation.key not in bibliography.keys
        ),
        claim_entries_without_keys=claim_entries_without_keys,
        unreferenced_bibtex_keys=tuple(sorted(bibliography.keys - cited_keys)),
        missing_alias_targets=tuple(
            sorted(
                (alias, canonical)
                for alias, canonical in aliases.items()
                if canonical not in bibliography.keys
            )
        ),
    )


def _print_keys(label: str, keys: tuple[str, ...], show_all: bool) -> None:
    print(f"{label}: {len(keys)}")
    shown = keys if show_all else keys[:20]
    for key in shown:
        print(f"  - {key}")
    if len(shown) < len(keys):
        print(f"  ... {len(keys) - len(shown)} more (use --show-all)")


def run_validation(args: argparse.Namespace) -> int:
    try:
        result = validate_citations(args.bibliography, args.root, args.aliases)
    except (OSError, ValueError) as error:
        print(f"citation validation error: {error}")
        return 1

    print(f"Canonical BibTeX entries: {len(result.bibliography.keys)}")
    print(f"Wiki source entries with canonical keys: {len(result.citations)}")
    print(f"BibTeX key aliases: {len(result.aliases)}")
    _print_keys(
        "Duplicate canonical BibTeX keys", result.bibliography.duplicates, args.show_all
    )

    print(f"Source entries with missing canonical keys: {len(result.missing_source_keys)}")
    for citation in result.missing_source_keys:
        print(f"  - {citation.path}:{citation.line}: {citation.key}")

    print(
        "Claim entries without canonical key declarations: "
        f"{len(result.claim_entries_without_keys)}"
    )
    for citation in result.claim_entries_without_keys:
        print(f"  - {citation.path}:{citation.line}: {citation.key}")

    print(f"Aliases with missing canonical targets: {len(result.missing_alias_targets)}")
    for alias, canonical in result.missing_alias_targets:
        print(f"  - {alias} -> {canonical}")

    _print_keys(
        "BibTeX entries not referenced by a wiki source entry",
        result.unreferenced_bibtex_keys,
        args.show_all,
    )
    print("Citation metadata is valid." if result.valid else "Citation metadata is invalid.")
    return 0 if result.valid else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bibliography", type=Path, default=DEFAULT_BIBLIOGRAPHY)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES)
    parser.add_argument("--show-all", action="store_true")
    return parser


def main() -> int:
    return run_validation(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
