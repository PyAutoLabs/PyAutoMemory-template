"""Resolve every ``[[wikilink]]`` in the wiki against the pages that exist.

``[[slug]]`` is the wiki's cross-reference mechanism (``wiki/AGENTS.md``,
"Cross-references"): a slug is a page's filename without ``.md``, slugs are
unique across sub-wikis so a link needs no path (``wiki/smbh/AGENTS.md``), and
a link with no target yet is *legal* — it marks a page somebody meant to write.

That last rule is why this lint is a **ratchet, not a gate**. The wiki carries
hundreds of deliberate wanted-page links; failing on them would only teach
everyone to ignore the lint. So it fails on exactly one thing: an unresolved
*target* that is not in ``scripts/wikilink_baseline.txt``. Adding a link to a
target already known-dangling is fine (it is the same wanted page, referenced
once more); inventing a new dangling slug — the typo case, and the case where a
page was renamed out from under its references — is not.

Resolution, in full:

* A link is ``[[target]]``, ``[[target#anchor]]`` or ``[[target|label]]``
  (and the two combined). The anchor is **not** validated — it points inside a
  page, and the source pages' per-paper sections are not a structure this lint
  should freeze. The label is display text.
* ``target`` resolves if some ``wiki/<domain>/**/*.md`` has it as its stem —
  **any** sub-wiki, because slugs are unique across them and cross-wiki links
  are documented.
* A source page carries a second slug: ``wiki/<d>/sources/<topic>.md`` resolves
  both ``[[<topic>]]`` and ``[[sources-<topic>]]``, which is the form the
  schema's ``[[sources-<topic>#author-year-slug]]`` uses. Seed pages
  (``wiki/<d>/seed/<topic>.md``) resolve the same two ways.
* Fenced code blocks and inline code spans are skipped, so the schema pages can
  show the syntax (``[[page-slug]]``, ``[[related-concept-1]]``) without those
  examples counting as references.

Nothing resolves against the bibliography: a citation is a source *section*
reached through its page, and no unresolved target in the wiki today is a
canonical key (five collide with software keys — ``emcee``, ``dynesty`` — and
those are wanted entity pages, not citations).

Usage:
    python scripts/validate_wikilinks.py                 # summary, exit 1 on new
    python scripts/validate_wikilinks.py --list          # + the dangling targets
    python scripts/validate_wikilinks.py --write-baseline
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = Path(__file__).resolve().parent / "wikilink_baseline.txt"

#: ``[[target]]``, ``[[target#anchor]]``, ``[[target|label]]``. Non-greedy and
#: capped so an unclosed ``[[`` swallows a phrase, never half the page; DOTALL
#: because a link wrapped across two lines is still one link.
WIKILINK_RE = re.compile(r"\[\[([^\[\]]{1,200}?)\]\]", re.DOTALL)
FENCE_RE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")

#: Page folders whose stems also answer to a ``<folder>-<stem>`` slug.
PREFIXED_FOLDERS = ("sources", "seed")

#: The schema page itself is documentation *of* the syntax, not a page of
#: references: every example slug in it is illustrative.
SKIP_FILES = ("wiki/AGENTS.md", "wiki/CLAUDE.md")


def strip_code(text: str) -> str:
    """Blank out fenced blocks and inline code, keeping line count intact."""
    out: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        match = FENCE_RE.match(line)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token
            elif line.strip().startswith(fence):
                fence = None
            out.append("")
            continue
        out.append("" if fence else INLINE_CODE_RE.sub("", line))
    return "\n".join(out)


def wiki_files(root: Path) -> list[Path]:
    skip = {(root / rel).resolve() for rel in SKIP_FILES}
    return [p for p in sorted(root.glob("wiki/**/*.md"))
            if p.resolve() not in skip]


def page_slugs(root: Path) -> set[str]:
    """Every slug a link may resolve to, across all sub-wikis."""
    slugs: set[str] = set()
    for path in sorted(root.glob("wiki/**/*.md")):
        parts = path.relative_to(root).parts
        slugs.add(path.stem)
        if len(parts) >= 4 and parts[2] in PREFIXED_FOLDERS:
            slugs.add(f"{parts[2]}-{path.stem}")
    return slugs


def link_target(raw: str) -> str:
    """The page slug a raw link body names — anchor and label removed."""
    target = raw.split("#", 1)[0].split("|", 1)[0]
    return " ".join(target.split()).strip()


def collect_links(root: Path) -> list[tuple[Path, str]]:
    """``(file, target)`` for every wikilink in the wiki, in file order."""
    found: list[tuple[Path, str]] = []
    for path in wiki_files(root):
        body = strip_code(path.read_text(encoding="utf-8", errors="replace"))
        for match in WIKILINK_RE.finditer(body):
            target = link_target(match.group(1))
            if target:
                found.append((path, target))
    return found


def unresolved(root: Path) -> tuple[int, Counter]:
    """``(total_links, Counter(target -> occurrences))`` for dangling links."""
    slugs = page_slugs(root)
    links = collect_links(root)
    counts: Counter = Counter()
    for _, target in links:
        if target not in slugs:
            counts[target] += 1
    return len(links), counts


def read_baseline(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")}


def write_baseline(path: Path, targets: set[str]) -> None:
    path.write_text("\n".join(sorted(targets)) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--list", action="store_true", dest="show_list",
                        help="print the unresolved targets, most-referenced first")
    parser.add_argument("--write-baseline", action="store_true",
                        help="rewrite the baseline from the current state")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    total, counts = unresolved(root)
    targets = set(counts)
    print(f"{total} links, {sum(counts.values())} unresolved "
          f"across {len(targets)} targets")

    if args.show_list:
        for target, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {n:4d}  {target}")

    baseline = read_baseline(args.baseline)

    if args.write_baseline:
        dropped = baseline - targets
        added = targets - baseline
        write_baseline(args.baseline, targets)
        print(f"baseline rewritten: {len(targets)} targets "
              f"(+{len(added)} new, -{len(dropped)} resolved since)")
        return 0

    fresh = sorted(targets - baseline)
    if fresh:
        print(f"ERROR: {len(fresh)} unresolved target(s) not in "
              f"{args.baseline.name}:")
        for target in fresh:
            print(f"  - {target} ({counts[target]} reference(s))")
        print("A dangling link is legal — a NEW dangling target is not. Write "
              "the page, fix the slug, or accept it with "
              "`python scripts/validate_wikilinks.py --write-baseline`.")
        return 1

    gone = len(baseline - targets)
    tail = f" ({gone} baseline target(s) now resolve)" if gone else ""
    print(f"Wikilinks are valid — no new unresolved targets{tail}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
