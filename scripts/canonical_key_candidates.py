"""Rank canonical BibTeX candidates for wiki sections whose key is still TODO.

Read-only: emits a candidates report (section -> ranked candidate keys with a
confidence label) and never writes a key into the wiki. Every proposed match
must be verified against the public paper record by a human (or an agent
acting for one) before the section is filled — see ``bibliography/README.md``:
never fabricate, uncertain stays TODO.

Matching order, strongest first: DOI and arXiv id quoted in the section body,
then first-author surname + year (the heading's ``Author Year — tag`` stem),
ranked by overlap between the heading tag and the entry title.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from scripts.validate_literature_citations import (
    DEFAULT_BIBLIOGRAPHY,
    ROOT,
    SOURCE_SECTION,
    source_directories,
)

TODO_KEY = re.compile(r"^\*\*Canonical BibTeX key:\*\*\s*TODO\b", re.MULTILINE)
HEADING = re.compile(r"^(?P<author>.+?)\s+(?P<year>(?:18|19|20)\d\d)[a-z]?\b\s*(?:[—–-]+\s*(?P<tag>.*))?$")
INNER_AUTHOR_YEAR = re.compile(r"(?:^|[—–-]\s*)(?P<author>[A-Z][A-Za-zÀ-ÿ'\-]+)(?:\s+(?:&|and)\s+[A-Z][A-Za-zÀ-ÿ'\-]+|\s+et\s+al\.?)?\s+(?P<year>(?:18|19|20)\d\d)[a-z]?\b")
#: Minimum share of a heading's content words that must appear in an entry
#: title before a title-only match is proposed.
TITLE_OVERLAP = 0.6
DOI = re.compile(r"10\.\d{4,9}/[^\s;,)`]+", re.IGNORECASE)
ARXIV = re.compile(r"\b(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?\b")
ENTRY_START = re.compile(r"^\s*@(?!comment\b|string\b|preamble\b)[A-Za-z]+\s*[({]\s*([^,\s]+)\s*,", re.MULTILINE | re.IGNORECASE)
FIELD = re.compile(r"^\s*([A-Za-z]+)\s*=\s*(.*?),?\s*$", re.MULTILINE)

STOPWORDS = frozenset(
    "a an and as at by for from in into of on or the to with via using new "
    "its their is are be we our paper study".split()
)


@dataclass(frozen=True)
class BibEntry:
    key: str
    first_author: str
    year: str
    title: str
    doi: str = ""
    arxiv: str = ""


@dataclass
class TodoSection:
    path: Path
    line: int
    heading: str
    author: str = ""
    year: str = ""
    tag: str = ""
    body: str = ""
    candidates: list[dict] = field(default_factory=list)


def fold(text: str) -> str:
    """Lower-case ASCII fold, stripping LaTeX accents and braces."""

    text = re.sub(r"\\[`'^\"~=.uvHcdbtr]\s*\{?([A-Za-z])\}?", r"\1", text)
    text = re.sub(r"\\([oOlL])\b", r"\1", text)
    text = text.replace("{", "").replace("}", "")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def surname(author_field: str) -> str:
    first = re.split(r"\s+and\s+", author_field.strip(), maxsplit=1)[0]
    first = fold(first).strip()
    name = first.split(",", 1)[0] if "," in first else (first.split() or [""])[-1]
    return re.sub(r"[^a-z]", "", name)


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", fold(text)) if w not in STOPWORDS and len(w) > 1}


def normalize_arxiv(identifier: str) -> str:
    """``arXiv:1302.1873v1`` -> ``1302.1873``; old-style ids keep their archive."""

    identifier = re.sub(r"^arxiv:", "", identifier.strip(), flags=re.IGNORECASE)
    return re.sub(r"v\d+$", "", identifier).lower()


def parse_entries(text: str) -> list[BibEntry]:
    starts = list(ENTRY_START.finditer(text))
    entries = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        fields = {
            name.lower(): value.strip().strip("{}\"").strip()
            for name, value in FIELD.findall(text[match.end():end])
        }
        arxiv = normalize_arxiv(fields.get("arxivid") or fields.get("eprint") or "")
        entries.append(
            BibEntry(
                key=match.group(1),
                first_author=surname(fields.get("author", "")),
                year=re.sub(r"\D", "", fields.get("year", ""))[:4],
                title=fields.get("title", ""),
                doi=fields.get("doi", "").lower(),
                arxiv=arxiv.lower(),
            )
        )
    return entries


def collect_todo_sections(root: Path) -> list[TodoSection]:
    sections = []
    for directory in source_directories(root):
        for path in sorted(directory.glob("*.md")):
            markdown = path.read_text(encoding="utf-8")
            for match in SOURCE_SECTION.finditer(markdown):
                body = match.group(2)
                if not TODO_KEY.search(body):
                    continue
                heading = match.group(1).strip()
                section = TodoSection(
                    path=path.relative_to(root),
                    line=markdown.count("\n", 0, match.start()) + 1,
                    heading=heading,
                    body=body,
                )
                parsed = HEADING.match(heading)
                if parsed:
                    section.author = re.sub(r"[^a-z]", "", fold(parsed.group("author").split()[0]))
                    section.year = parsed.group("year")
                    section.tag = parsed.group("tag") or ""
                else:
                    # "Prefix — Author Year tag" (e.g. "UnRead — Belfiore 2017 MaNGA ...")
                    inner = INNER_AUTHOR_YEAR.search(heading)
                    if inner:
                        section.author = re.sub(r"[^a-z]", "", fold(inner.group("author")))
                        section.year = inner.group("year")
                        section.tag = heading[inner.end():].strip(" —–-")
                    else:
                        section.tag = heading
                sections.append(section)
    return sections


def rank(section: TodoSection, entries: list[BibEntry]) -> list[dict]:
    found: dict[str, dict] = {}
    body = section.body
    for doi in {d.lower().rstrip(".") for d in DOI.findall(body)}:
        for entry in entries:
            if entry.doi and entry.doi == doi:
                found[entry.key] = {"key": entry.key, "by": "doi", "confidence": "exact", "score": 1.0, "title": entry.title}
    for arxiv in {a.lower() for a in ARXIV.findall(body)}:
        for entry in entries:
            if entry.arxiv and entry.arxiv == arxiv and entry.key not in found:
                found[entry.key] = {"key": entry.key, "by": "arxiv", "confidence": "exact", "score": 1.0, "title": entry.title}
    if section.author and section.year:
        tag_words = words(section.tag)
        same = [e for e in entries if e.first_author == section.author and e.year == section.year]
        for entry in same:
            if entry.key in found:
                continue
            overlap = len(tag_words & words(entry.title))
            score = overlap / len(tag_words) if tag_words else 0.0
            if len(same) == 1:
                confidence = "high" if overlap else "medium"
            else:
                confidence = "medium" if overlap else "low"
            found[entry.key] = {
                "key": entry.key, "by": "author+year", "confidence": confidence,
                "score": round(score, 2), "title": entry.title,
            }
    if not found and not (section.author and section.year):
        tag_words = words(section.tag)
        if len(tag_words) >= 3:
            for entry in entries:
                overlap = len(tag_words & words(entry.title))
                score = overlap / len(tag_words)
                if score >= TITLE_OVERLAP:
                    found[entry.key] = {
                        "key": entry.key, "by": "title",
                        "confidence": "medium" if score >= 0.8 else "low",
                        "score": round(score, 2), "title": entry.title,
                    }
    order = {"exact": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(found.values(), key=lambda c: (order[c["confidence"]], -c["score"], c["key"]))


def build_report(root: Path, bibliography: Path) -> list[TodoSection]:
    entries = parse_entries(bibliography.read_text(encoding="utf-8"))
    sections = collect_todo_sections(root)
    for section in sections:
        section.candidates = rank(section, entries)
    return sections


def render_markdown(sections: list[TodoSection]) -> str:
    matched = [s for s in sections if s.candidates]
    lines = [
        "# Canonical-key TODO candidates",
        "",
        f"TODO sections: {len(sections)}; with at least one candidate: {len(matched)}.",
        "Candidates are proposals only — verify each against the public paper record before filling.",
        "",
    ]
    for section in sections:
        lines.append(f"## {section.path}:{section.line} — {section.heading}")
        if not section.candidates:
            lines.append("- no candidate")
        for candidate in section.candidates:
            lines.append(
                f"- `{candidate['key']}` [{candidate['confidence']}, {candidate['by']}, "
                f"tag overlap {candidate['score']}] {candidate['title']}"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--bibliography", type=Path, default=DEFAULT_BIBLIOGRAPHY)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    args = parser.parse_args(argv)
    sections = build_report(args.root, args.bibliography)
    if args.json:
        print(json.dumps([
            {"path": str(s.path), "line": s.line, "heading": s.heading, "candidates": s.candidates}
            for s in sections
        ], indent=2))
    else:
        print(render_markdown(sections))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
