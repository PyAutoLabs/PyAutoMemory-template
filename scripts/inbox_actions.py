"""scripts/inbox_actions.py — the arXiv inbox: append, sweep, add, dismiss.

The inbox (``arxiv-inbox.md``) is the tier in front of the reading queue.
PyAutoMind's nightly ``arxiv_papers.yml`` appends the digest's surviving papers
here; the Dashboard renders each with four one-tap actions; ``queue_actions.yml``
processes the ➕ ``queue-add`` and ✖️ ``queue-dismiss`` taps, and the nightly job
sweeps whatever nobody acted on within :data:`INBOX_WINDOW_DAYS`.

This module is the single owner of the inbox line format and of the window, so
neither is re-expressed in a workflow's shell. ``board.py`` imports the parsing
helpers rather than re-deriving them, and PyAutoMind's workflow runs this script
inside a PyAutoMemory checkout rather than writing the format itself.

A swept line is not lost — git history holds it. That is deliberate: the
never-delete rule in ``reading-queue.md`` protects *reading history*, and an
un-acted suggestion is not history.

Stdlib-only and idempotent, like ``queue_mark_done.py`` beside it: appending a
paper already in the inbox (or already in the reading queue) is a no-op, and
acting on a line that is already gone is a success, not an error.

The module also owns the inbox's **freshness stamp** — one ``last digest:
<date>`` line the nightly digest rewrites on every run, papers or none. An empty
inbox is ambiguous without it (arXiv was quiet, or the filing broke and the
papers were lost); with it, a stamp dated today makes the quiet day *positive
evidence*, exactly as the ``#papers`` empty-day heartbeat does on the Slack side.
It is replaced rather than accumulated, so the sweep never has to age it out.

Each subcommand prints exactly one status token on stdout.

Usage:
    python scripts/inbox_actions.py append --papers-file survivors.json
    python scripts/inbox_actions.py stamp
    python scripts/inbox_actions.py sweep
    python scripts/inbox_actions.py add     --body-file /tmp/issue_body.txt
    python scripts/inbox_actions.py dismiss --body-file /tmp/issue_body.txt
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

#: How long an un-acted suggestion survives in the inbox. Defined once here;
#: board.py imports it for the days-left column and the nightly sweep passes
#: nothing, so there is no second literal to drift.
INBOX_WINDOW_DAYS = 7

#: How long the board waits before calling a silent digest broken, in weekdays
#: (the digest runs Mon-Fri). Two, not one: the nominal fire is 02:00 UTC and
#: GitHub cron only ever jitters *later* (0-3 h under load), so a board rendered
#: early can legitimately see yesterday's stamp with nothing wrong. Two weekdays
#: of silence is a pattern rather than a slip.
INBOX_STALE_WEEKDAYS = 2

#: Where ➕ sends a paper. The digest is strong-lensing-only, so every inbox
#: paper routes to one reading-queue section; a multi-section inbox is a later
#: problem, and this constant is where it starts.
INBOX_TARGET_SECTION = "Strong Lensing"

INBOX_FILE = "arxiv-inbox.md"
QUEUE_FILE = "reading-queue.md"

#: ``<YYYY-MM-DD> — <rest>``. The rest is a queue-shaped paper (title, then an
#: optional ` — <ref>`), so board.py can hand it to its own ``_parse_paper``.
INBOX_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+—\s+(\S.*)$")
#: Same ref grammar as board.py's QUEUE_REF_RE — kept in step deliberately.
REF_RE = re.compile(
    r"^(.*\S)\s+—\s+((?:arXiv:)?\d{4}\.\d{4,5}(?:v\d+)?|https?://\S+)$")
#: The freshness stamp. Deliberately NOT date-first, so it can never collide
#: with INBOX_LINE_RE and be read back as a paper.
STAMP_RE = re.compile(r"^last digest:\s*(\d{4}-\d{2}-\d{2})\s*$")
#: The prose header ends here; the stamp and the papers live below it.
SEPARATOR = "---"
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
BODY_LINE_RE = re.compile(r"^line:\s*(.+?)\s*$", re.MULTILINE)
BODY_FILE_RE = re.compile(r"^file:\s*(.+?)\s*$", re.MULTILINE)
BODY_SECTION_RE = re.compile(r"^section:\s*(.+?)\s*$", re.MULTILINE)


# --- parsing ------------------------------------------------------------------
def parse_line(raw: str) -> tuple[str, str] | None:
    """``(added_date, paper_text)`` for an inbox paper line, else None."""
    m = INBOX_LINE_RE.match(raw.strip())
    return (m.group(1), m.group(2)) if m else None


def split_ref(text: str) -> tuple[str, str | None]:
    """``(title, ref)`` — the trailing ` — <arXiv id or URL>` if there is one."""
    m = REF_RE.match(text)
    return (m.group(1), m.group(2)) if m else (text, None)


def identity(text: str) -> str:
    """What makes two inbox/queue entries the same paper.

    The bare arXiv number when there is one (so ``2608.21253``, ``arXiv:2608.21253``
    and ``…v1`` all collide), else the case-folded title. Titles are a weak key,
    but a paper with no ref is exactly the case where nothing better exists.
    """
    title, ref = split_ref(text)
    if ref and not ref.startswith("http"):
        return re.sub(r"v\d+$", "", ref.removeprefix("arXiv:"))
    if ref:
        return ref
    return " ".join(title.lower().split())


def papers(text: str) -> list[dict]:
    """Every paper line in the inbox, in file order."""
    out = []
    for raw in text.splitlines():
        parsed = parse_line(raw)
        if parsed:
            added, rest = parsed
            title, ref = split_ref(rest)
            out.append({"added": added, "title": title, "ref": ref,
                        "text": rest, "line": raw.strip()})
    return out


def days_left(added: str, today: datetime.date) -> int:
    """Days this paper has left before it lapses (never below zero)."""
    try:
        stamp = datetime.date.fromisoformat(added)
    except ValueError:
        return 0
    return max(0, INBOX_WINDOW_DAYS - (today - stamp).days)


def last_digest(text: str) -> str | None:
    """The date of the last recorded digest run, or None if never stamped."""
    for raw in text.splitlines():
        m = STAMP_RE.match(raw.strip())
        if m:
            return m.group(1)
    return None


def weekdays_since(stamp: str, today: datetime.date) -> int:
    """Weekdays elapsed since ``stamp``, counting neither endpoint's weekend.

    The digest only runs Mon-Fri, so calendar days overstate its silence: a
    Monday board reading Friday's stamp is three days but zero *missed runs*.
    Counts the days strictly after ``stamp`` up to and including ``today``.
    """
    try:
        start = datetime.date.fromisoformat(stamp)
    except ValueError:
        return 0
    n, day = 0, start
    while day < today:
        day += datetime.timedelta(days=1)
        if day.weekday() < 5:
            n += 1
    return n


def is_stale(stamp: str | None, today: datetime.date) -> bool:
    """Whether a digest has been silent long enough to suspect it is broken.

    A missing stamp is NOT stale: ``spawn.py`` empties ``arxiv-inbox.md`` for
    the template repos, so a freshly spawned Memory has never run a digest and
    has nothing to be late for. Absence of evidence, not evidence of breakage.
    """
    if stamp is None:
        return False
    return weekdays_since(stamp, today) >= INBOX_STALE_WEEKDAYS


# --- transitions --------------------------------------------------------------
def set_last_digest(inbox_text: str, date: str) -> str:
    """Record a digest run, replacing any stamp already there.

    Inserted directly below the ``---`` separator when absent, so it sits above
    the papers: ``append`` places new lines after the last paper (or at EOF when
    there are none), and never above the stamp under either branch.
    """
    lines = inbox_text.rstrip("\n").splitlines()
    line = f"last digest: {date}"
    for i, raw in enumerate(lines):
        if STAMP_RE.match(raw.strip()):
            lines[i] = line
            return "\n".join(lines) + "\n"
    at = next((i + 1 for i, r in enumerate(lines) if r.strip() == SEPARATOR),
              len(lines))
    lines[at:at] = [line]
    return "\n".join(lines) + "\n"


def append(inbox_text: str, queue_text: str, entries: list[dict],
           date: str) -> tuple[str, int]:
    """Append papers not already in the inbox or the reading queue.

    ``entries`` are ``{"title": str, "ref": str | None}``. Returns
    ``(new_text, added_count)``.
    """
    known = {identity(p["text"]) for p in papers(inbox_text)}
    for raw in queue_text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        # A queue line may be DONE-prefixed; identity only needs the tail.
        s = re.sub(r"^DONE\s+\d{4}-\d{2}-\d{2}\s+—\s+", "", s)
        known.add(identity(s))

    fresh = []
    for e in entries:
        text = e["title"].strip()
        if e.get("ref"):
            text = f"{text} — {e['ref']}"
        key = identity(text)
        if key in known:
            continue
        known.add(key)
        fresh.append(f"{date} — {text}")
    if not fresh:
        return inbox_text, 0

    lines = inbox_text.rstrip("\n").splitlines()
    last = max((i for i, r in enumerate(lines) if parse_line(r)), default=None)
    at = len(lines) if last is None else last + 1
    lines[at:at] = fresh
    return "\n".join(lines) + "\n", len(fresh)


def sweep(inbox_text: str, today: datetime.date) -> tuple[str, list[str]]:
    """Drop lines past the window. Returns ``(new_text, dropped_lines)``."""
    out, dropped = [], []
    for raw in inbox_text.rstrip("\n").splitlines():
        parsed = parse_line(raw)
        if parsed and days_left(parsed[0], today) == 0:
            dropped.append(raw.strip())
            continue
        out.append(raw)
    return "\n".join(out) + "\n", dropped


def remove(inbox_text: str, line: str) -> tuple[str, str]:
    """Drop one inbox line. Status: ``done`` / ``not-found``."""
    target = line.strip()
    out, status = [], "not-found"
    for raw in inbox_text.rstrip("\n").splitlines():
        if status == "not-found" and raw.strip() == target:
            status = "done"
            continue
        out.append(raw)
    return "\n".join(out) + "\n", status


def add_to_queue(queue_text: str, paper_text: str,
                 section: str) -> tuple[str, str]:
    """Append a paper to ``section`` of the reading queue, unread.

    Status: ``added`` / ``already-there`` / ``no-section``.
    """
    key = identity(paper_text)
    lines = queue_text.rstrip("\n").splitlines()
    start = end = None
    for i, raw in enumerate(lines):
        m = SECTION_RE.match(raw)
        if not m:
            continue
        if start is None and m.group(1) == section:
            start = i
        elif start is not None:
            end = i
            break
    if start is None:
        return queue_text, "no-section"
    end = len(lines) if end is None else end

    for raw in lines[start + 1:end]:
        s = re.sub(r"^DONE\s+\d{4}-\d{2}-\d{2}\s+—\s+", "", raw.strip())
        if s and identity(s) == key:
            return queue_text, "already-there"

    at = end
    while at > start + 1 and not lines[at - 1].strip():
        at -= 1
    lines[at:at] = [paper_text.strip()]
    return "\n".join(lines) + "\n", "added"


# --- issue bodies -------------------------------------------------------------
def parse_body(body: str) -> dict | None:
    """The ``file:`` / ``line:`` / ``section:`` an action issue names."""
    m_line = BODY_LINE_RE.search(body)
    if not m_line:
        return None
    m_file = BODY_FILE_RE.search(body)
    m_section = BODY_SECTION_RE.search(body)
    return {
        "line": m_line.group(1),
        "file": m_file.group(1) if m_file else QUEUE_FILE,
        "section": m_section.group(1) if m_section else INBOX_TARGET_SECTION,
    }


# --- CLI ----------------------------------------------------------------------
def _today(ns) -> datetime.date:
    if ns.date:
        return datetime.date.fromisoformat(ns.date)
    return datetime.datetime.now(datetime.timezone.utc).date()


def _cmd_append(ns) -> tuple[str, int]:
    raw = json.loads(Path(ns.papers_file).read_text(errors="replace"))
    entries = raw["papers"] if isinstance(raw, dict) else raw
    entries = [{"title": e["title"], "ref": e.get("ref") or e.get("id")}
               for e in entries]
    inbox = Path(ns.inbox)
    queue = Path(ns.queue)
    text, n = append(inbox.read_text(errors="replace"),
                     queue.read_text(errors="replace") if queue.exists() else "",
                     entries, _today(ns).isoformat())
    if n:
        inbox.write_text(text)
    return (f"appended:{n}", 0)


def _cmd_stamp(ns) -> tuple[str, int]:
    date = _today(ns).isoformat()
    inbox = Path(ns.inbox)
    inbox.write_text(set_last_digest(inbox.read_text(errors="replace"), date))
    return (f"stamped:{date}", 0)


def _cmd_sweep(ns) -> tuple[str, int]:
    inbox = Path(ns.inbox)
    text, dropped = sweep(inbox.read_text(errors="replace"), _today(ns))
    if dropped:
        inbox.write_text(text)
        for d in dropped:
            print(f"lapsed: {d}", file=sys.stderr)
    return (f"swept:{len(dropped)}", 0)


def _cmd_add(ns) -> tuple[str, int]:
    parsed = parse_body(Path(ns.body_file).read_text(errors="replace"))
    if parsed is None:
        return ("bad-body", 2)
    inbox, queue = Path(ns.inbox), Path(ns.queue)
    line = parsed["line"]
    got = parse_line(line)
    paper_text = got[1] if got else line
    queue_text, status = add_to_queue(queue.read_text(errors="replace"),
                                      paper_text, parsed["section"])
    if status == "no-section":
        return ("no-section", 3)
    if status == "added":
        queue.write_text(queue_text)
    inbox_text, _ = remove(inbox.read_text(errors="replace"), line)
    inbox.write_text(inbox_text)
    return (status, 0)


def _cmd_dismiss(ns) -> tuple[str, int]:
    parsed = parse_body(Path(ns.body_file).read_text(errors="replace"))
    if parsed is None:
        return ("bad-body", 2)
    inbox = Path(ns.inbox)
    text, status = remove(inbox.read_text(errors="replace"), parsed["line"])
    if status == "done":
        inbox.write_text(text)
        return ("dismissed", 0)
    return ("already-gone", 0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scripts/inbox_actions.py",
                                 description=__doc__)
    ap.add_argument("--inbox", default=INBOX_FILE)
    ap.add_argument("--queue", default=QUEUE_FILE)
    ap.add_argument("--date", default=None, help="override today (YYYY-MM-DD)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("append", help="append digest survivors to the inbox")
    p.add_argument("--papers-file", required=True,
                   help="JSON: [{title, ref}] or {\"papers\": [...]}")
    p.set_defaults(fn=_cmd_append)

    p = sub.add_parser("stamp", help="record that the digest ran today")
    p.set_defaults(fn=_cmd_stamp)

    p = sub.add_parser("sweep", help="drop lines past the window")
    p.set_defaults(fn=_cmd_sweep)

    for name, fn, helptext in (("add", _cmd_add, "inbox → reading queue"),
                               ("dismiss", _cmd_dismiss, "drop from the inbox")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--body-file", required=True,
                       help="file holding the action issue body")
        p.set_defaults(fn=fn)

    ns = ap.parse_args(argv)
    status, code = ns.fn(ns)
    print(status)
    return code


if __name__ == "__main__":
    sys.exit(main())
