#!/usr/bin/env python3
"""scripts/backfill_arxiv_refs.py — give every queue line its arXiv ref.

The Dashboard can only offer a paper's abstract page and its 📄 PDF button when
the queue line carries a ref (``… — 2608.23534``). The nightly digest has
written refs since it existed, but the bulk of ``reading-queue.md`` predates it:
those lines are bare titles, and a bare title can only be rendered as an arXiv
*title search* — a results page, a squint and a tap, per paper, on a phone.

This script retires that fallback. For every ref-less line it asks the arXiv API
for the title, and appends ``— <id>`` **only** when exactly one arXiv paper's
title matches after normalisation (``arxiv_refs.match_entries``). Anything
looser is left alone: a wrong id is worse than a search box, because it sends
the reader confidently to somebody else's paper.

It is idempotent and resumable — a line that already has a ref is skipped, so
successive runs only ever work on what is left. Lines arXiv genuinely does not
have (a journal-only paper, a thesis, a talk) are simply never matched and are
re-attempted each run; that is the cost of holding no per-line failure state,
and it is bounded by ``--limit``.

A *transport* failure is a different thing from a non-match and is reported as
one. ``arxiv_refs`` retries 429/406/5xx and network errors along a back-off
ladder honouring ``Retry-After``; a lookup that still gets no answer raises
``ArxivAPIError``, which this script counts as ``api_failed`` (never as
``unmatched``), stops the run on, never NOTE-marks, and turns into a non-zero
exit — so an arXiv outage goes red instead of logging "N ref-less, 0 resolved"
(2026-09-14..18, when this job ran green every night through 429s and 406s).

Run by ``.github/workflows/arxiv_refs.yml`` (a checkout has no arXiv access
inside a sandboxed session; CI does). Locally:

    python scripts/backfill_arxiv_refs.py                 # report, change nothing
    python scripts/backfill_arxiv_refs.py --write         # apply
    python scripts/backfill_arxiv_refs.py --write --limit 60
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import arxiv_refs  # noqa: E402
import board  # noqa: E402
import inbox_actions  # noqa: E402

MEMORY_HOME = Path(__file__).resolve().parents[1]

#: The files whose paper lines carry refs. Both use the same title/ref grammar,
#: so both are backfilled by the same pass.
TARGETS = (inbox_actions.QUEUE_FILE, inbox_actions.INBOX_FILE)


def candidates(text: str, source: str) -> list[tuple[int, str]]:
    """``[(line_index, title), …]`` for the lines this pass could fill in.

    Which lines *are* papers is not re-decided here: the queue's section gating
    and the inbox's date-stamped line grammar are read straight off the two
    parsers that render the board, so a line the board does not show as a paper
    is never touched. Of those, a line qualifies when it is not already DONE
    (reading history needs no new links) and carries no ref.
    """
    out = []
    in_section = False
    for i, raw in enumerate(text.splitlines()):
        if source == inbox_actions.INBOX_FILE:
            stamped = inbox_actions.parse_line(raw)
            if not stamped:
                continue
            body = stamped[1]
        else:
            m = board.QUEUE_SECTION_RE.match(raw)
            if m and not m.group(1).startswith("#"):
                in_section = True
                continue
            if not in_section or not raw.strip():
                continue
            body = raw.strip()
        paper = board._parse_paper(body)
        # `kind != "paper"` is the whole point of the marker: a `__Heading__`
        # and a `NOTE ` line are not papers, so they are never looked up — not
        # this run and not any future one. Without that, every night spends an
        # arXiv call on a line that can never resolve.
        if paper["kind"] != "paper":
            continue
        if paper["done"] or paper["ref"] or not paper["title"]:
            continue
        out.append((i, paper["title"]))
    return out


def mark_unresolved_line(raw_line: str) -> str:
    """`raw_line` prefixed `NOTE `, the "stop asking about this one" marker.

    Written only under ``--mark-unresolved``, never by the nightly run. The
    distinction matters: a title arXiv cannot identify is usually not a
    non-paper but a real paper whose line lost something on the way in (a
    LaTeX redshift, a wrapped subtitle), and those are worth re-trying after a
    human fixes the line. So the nightly keeps asking, and a human who has
    looked at the misses runs this once to retire the ones that are genuinely
    prose, links or headings. The text is untouched and the line stays in
    place — the never-delete rule covers annotations too.
    """
    stripped = raw_line.lstrip()
    indent = raw_line[:len(raw_line) - len(stripped)]
    return f"{indent}NOTE {stripped.rstrip()}"


def apply_ref(raw_line: str, ref: str) -> str:
    """`raw_line` with ``— <ref>`` appended, preserving its exact prefix.

    Appending rather than rewriting keeps the inbox's date stamp, any stray
    indentation and the title's own punctuation byte-for-byte intact — the queue
    is a human-edited file and this script is a guest in it.
    """
    return f"{raw_line.rstrip()} — {ref}"


def backfill(root: Path, *, write: bool, limit: int, mark_unresolved: bool = False,
             resolve=arxiv_refs.resolve_title,
             delay: float = arxiv_refs.API_DELAY_SECONDS,
             sleep=time.sleep, log=print) -> dict:
    """Resolve up to `limit` ref-less titles across the queue and the inbox.

    With `mark_unresolved`, a line that arXiv answered for but could not
    uniquely identify is also `NOTE `-marked so no later run asks about it
    again — a human-driven cleanup, never the nightly's own decision (see
    :func:`mark_unresolved_line`). A line whose lookup failed on *transport*
    is never marked: a NOTE-mark is permanent and must only ever follow an
    actual answer from arXiv.

    Stats: ``matched``/``unmatched`` count answers; ``api_failed`` counts
    lookups that got no answer after the retry ladder. The first such failure
    stops the run (every later lookup would hit the same dead endpoint), so
    ``api_failed`` is 0 or 1 and ``unattempted`` counts the titles left behind
    in that file within `limit` (later files are not opened).
    """
    stats = {"scanned": 0, "matched": 0, "unmatched": 0, "api_failed": 0,
             "unattempted": 0, "marked": 0, "files": []}
    budget = limit
    api_down = False
    for name in TARGETS:
        path = root / name
        if not path.exists():
            continue
        lines = path.read_text(errors="replace").splitlines()
        todo = candidates("\n".join(lines), name)
        stats["scanned"] += len(todo)
        changed = file_marked = 0
        for n, (idx, title) in enumerate(todo):
            if budget <= 0:
                break
            budget -= 1
            try:
                ref = resolve(title)
            except arxiv_refs.ArxivAPIError as e:
                # A transport failure is not a negative identification. Stop
                # here: another title would hit the same dead endpoint, and
                # --mark-unresolved must never turn an outage into permanent
                # NOTE markers.
                stats["api_failed"] += 1
                stats["unattempted"] += min(len(todo) - n - 1, budget)
                api_down = True
                log(f"  ! arXiv API failure  {title[:90]} ({e})")
                break
            if ref:
                lines[idx] = apply_ref(lines[idx], ref)
                changed += 1
                stats["matched"] += 1
                log(f"  ✔ {ref}  {title[:90]}")
            else:
                stats["unmatched"] += 1
                if mark_unresolved:
                    lines[idx] = mark_unresolved_line(lines[idx])
                    changed += 1
                    file_marked += 1
                    stats["marked"] += 1
                    log(f"  ✖ NOTE-marked     {title[:90]}")
                else:
                    log(f"  · no unique match  {title[:90]}")
            # Politeness, not throughput: arXiv asks for a few seconds between
            # calls, and this job has all night.
            if budget > 0:
                sleep(delay)
        if changed:
            stats["files"].append(name)
            if write:
                path.write_text("\n".join(lines) + "\n")
        marked = f", {file_marked} NOTE-marked" if file_marked else ""
        failed = (f", {stats['api_failed']} API failure — run stopped"
                  if api_down else "")
        log(f"{name}: {len(todo)} ref-less, {changed - file_marked} resolved"
            f"{marked}{failed}{'' if write else ' (dry run — nothing written)'}")
        if api_down:
            break
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                    help="apply the refs (default: report only)")
    ap.add_argument("--limit", type=int, default=60,
                    help="most arXiv lookups to make in one run (default 60)")
    ap.add_argument("--mark-unresolved", action="store_true",
                    help="also NOTE-mark every line that fails to resolve, so "
                         "later runs skip it. A human-reviewed cleanup for "
                         "lines that are prose, links or headings rather than "
                         "papers — never used by the nightly run, which keeps "
                         "re-trying in case a line gets fixed.")
    ap.add_argument("--root", type=Path, default=MEMORY_HOME)
    args = ap.parse_args(argv)

    stats = backfill(args.root, write=args.write, limit=args.limit,
                     mark_unresolved=args.mark_unresolved)
    marked = f", {stats['marked']} NOTE-marked" if stats["marked"] else ""
    failed = (f", {stats['api_failed']} arXiv API failure "
              f"({stats.get('unattempted', 0)} more not attempted)"
              if stats["api_failed"] else "")
    print(f"\n{stats['matched']} resolved, {stats['unmatched']} unresolved"
          f"{marked}{failed}, {stats['scanned']} ref-less lines in total.")
    if stats["api_failed"]:
        print("ARXIV API FAILURE: a lookup got no answer after the retry ladder; "
              "the run stopped there. Unresolved counts above are answers only "
              "— nothing was NOTE-marked on a failed lookup.")
    # A genuine no-match is normal and stays exit 0. A transport failure is a
    # broken run: by the time it surfaces, _api_query has spent its whole retry
    # ladder and the run has stopped, so transport failure is the outcome for
    # every lookup after it — the dominant one. Exit non-zero so the job goes
    # red; the workflow still commits whatever resolved before the failure.
    return 1 if stats["api_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
