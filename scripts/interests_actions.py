"""scripts/interests_actions.py — the arXiv interests list: append, stamp, sweep, clear, add, dismiss.

The **second** suggestion tier, sibling of ``inbox_actions.py``. The arXiv
inbox is strong lensing only; this one is everything else the human reads for —
black holes, dark matter, galaxy formation, statistics — as the day's ten most
relevant non-lensing papers, written by PyAutoMind's ``arxiv_interests.yml``.

It is a **day-batched backlog**, and the batch is the one real difference from
the inbox — the granularity of everything, the window included:

* The inbox is a flat list on a seven-day timer: act on a line or it lapses.
* This list is the same timer applied to a **day at a time**. Each run appends
  one dated batch, the Dashboard shows the **oldest un-cleared batch only**, and
  one 🧹 *clear* button drops that whole day and reveals the next — but a batch
  nobody clears lapses in its own right after :data:`inbox_actions.INBOX_WINDOW_DAYS`
  days, whole, exactly as an un-acted inbox line does.

  It did not always. The list was built as "a backlog, not a timer — nothing
  here lapses", on the reasoning that a fortnight away should be a fortnight of
  batches to cycle through rather than a fortnight of lost recommendations. The
  measurement said otherwise: of 123 papers appended, **2 were promoted to the
  reading queue and 1 batch was cleared** — a 1.6 % clearance rate, with 114
  entries sitting unread in 11 day-batches. A backlog nobody walks forward
  through is not a backlog, it is a pile that makes the oldest batch (the one
  the Dashboard shows) the least relevant thing on the board. Seven days is how
  long a suggestion is worth looking at; after that the recommendation has aged
  out whether or not anyone tapped 🧹.

Nothing else differs. The line format is the inbox's (``<date> — <text>``) with
one addition — an optional ``[Topic]`` naming the reading-queue section the
➕ button files into, because these papers span domains where the inbox's all
route to "Strong Lensing". The per-paper actions are the same four, and the
freshness stamp is the same line, parsed by the same code: this module imports
``inbox_actions`` rather than restating any of it — the window and ``days_left``
included, so there is no second literal to drift.

A cleared or swept batch is not lost — git history holds it, exactly as for a
swept inbox line, and for the same reason: a suggestion nobody acted on is not
reading history.

Each subcommand prints exactly one status token on stdout.

Usage:
    python scripts/interests_actions.py append --papers-file picks.json
    python scripts/interests_actions.py stamp
    python scripts/interests_actions.py sweep
    python scripts/interests_actions.py clear   --date 2026-08-25
    python scripts/interests_actions.py add     --body-file /tmp/issue_body.txt
    python scripts/interests_actions.py dismiss --body-file /tmp/issue_body.txt
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inbox_actions  # noqa: E402

INTERESTS_FILE = "arxiv-interests.md"
QUEUE_FILE = inbox_actions.QUEUE_FILE

#: How many papers one day's batch holds. The digest picks them; this is the
#: guard on its output, so a prompt that miscounts cannot flood a day.
BATCH_SIZE = 10

#: Where a paper goes when its ``[Topic]`` names no section in the reading
#: queue — or when a hand-written line carries no topic at all. A real section
#: rather than an error: the topic is a routing hint from a nightly prompt, and
#: a hint that misses should still land the paper somewhere retrievable.
FALLBACK_SECTION = "Interests"

#: ``<YYYY-MM-DD> — [Topic] <title>[ — <ref>]``. The topic is optional and the
#: rest is queue-shaped, so ``board.py`` hands it to its own ``_parse_paper``
#: exactly as it does an inbox line.
LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\s+—\s+(?:\[([^\]]+)\]\s+)?(\S.*)$")

BODY_DATE_RE = re.compile(r"^date:\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)


# --- parsing ------------------------------------------------------------------
def parse_line(raw: str) -> tuple[str, str | None, str] | None:
    """``(added_date, topic | None, paper_text)`` for a paper line, else None."""
    m = LINE_RE.match(raw.strip())
    if not m:
        return None
    topic = (m.group(2) or "").strip() or None
    return (m.group(1), topic, m.group(3))


def format_line(date: str, topic: str | None, text: str) -> str:
    """The inverse of :func:`parse_line` — the one place a line is written."""
    tag = f"[{topic.strip()}] " if topic and topic.strip() else ""
    return f"{date} — {tag}{text.strip()}"


def papers(text: str) -> list[dict]:
    """Every paper line in the list, in file order (oldest batch first)."""
    out = []
    for raw in text.splitlines():
        parsed = parse_line(raw)
        if not parsed:
            continue
        added, topic, rest = parsed
        title, ref = inbox_actions.split_ref(rest)
        out.append({"added": added, "topic": topic, "title": title, "ref": ref,
                    "text": rest, "line": raw.strip()})
    return out


def batches(text: str) -> list[tuple[str, list[dict]]]:
    """The list grouped into day batches, oldest first.

    Grouped by date rather than taken in file order: a re-run that appends to a
    date already present must extend that batch, not open a second one.
    """
    grouped: dict[str, list[dict]] = {}
    for p in papers(text):
        grouped.setdefault(p["added"], []).append(p)
    return [(d, grouped[d]) for d in sorted(grouped)]


def current_batch(text: str) -> tuple[str, list[dict]] | None:
    """The oldest un-cleared batch — what the Dashboard shows. None if empty.

    Oldest, not newest: the backlog is a queue the human walks forward through,
    so clearing today's ten would skip the ones already waiting.
    """
    got = batches(text)
    return got[0] if got else None


def section_for(paper: dict) -> str:
    """The reading-queue section a paper's ➕ files into."""
    return paper.get("topic") or FALLBACK_SECTION


# --- transitions --------------------------------------------------------------
def append(interests_text: str, known_texts: list[str], entries: list[dict],
           date: str, limit: int = BATCH_SIZE) -> tuple[str, int]:
    """Append a day's batch, skipping papers already known anywhere.

    ``entries`` are ``{"title": str, "ref": str | None, "topic": str | None}``.
    ``known_texts`` are the other files a paper may already live in — the
    reading queue and the strong-lensing inbox — so a paper never arrives here
    while it is already waiting somewhere else. Returns ``(new_text, added)``.
    """
    known = {inbox_actions.identity(p["text"]) for p in papers(interests_text)}
    for text in known_texts:
        for raw in text.splitlines():
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            # The other two files each carry their own prefixes; identity only
            # needs the tail, so strip whichever is present.
            got = inbox_actions.parse_line(s)
            if got:
                s = got[1]
            s = re.sub(r"^DONE\s+\d{4}-\d{2}-\d{2}\s+—\s+", "", s)
            known.add(inbox_actions.identity(s))

    fresh = []
    for e in entries:
        if limit is not None and len(fresh) >= limit:
            break
        text = e["title"].strip()
        if e.get("ref"):
            text = f"{text} — {e['ref']}"
        key = inbox_actions.identity(text)
        if key in known:
            continue
        known.add(key)
        fresh.append(format_line(date, e.get("topic"), text))
    if not fresh:
        return interests_text, 0

    lines = interests_text.rstrip("\n").splitlines()
    last = max((i for i, r in enumerate(lines) if parse_line(r)), default=None)
    at = len(lines) if last is None else last + 1
    lines[at:at] = fresh
    return "\n".join(lines) + "\n", len(fresh)


def days_left(date: str, today: datetime.date) -> int:
    """Days a batch has left before it lapses — the inbox's window, unchanged.

    A one-line passthrough on purpose: the window and the arithmetic have one
    owner (``inbox_actions``), and callers that want a batch's days-left (the
    board's column, the sweep below) should not have to know that.
    """
    return inbox_actions.days_left(date, today)


def sweep(interests_text: str,
          today: datetime.date) -> tuple[str, list[tuple[str, int]]]:
    """Drop every batch past the window. Returns ``(new_text, lapsed)``.

    ``lapsed`` is ``[(date, papers_dropped)]``, oldest first. A **whole day**
    goes or none of it does: the 🧹 button acts on a day, so the day is the unit
    the human works in and the unit that ages out. Like the inbox's sweep this
    is idempotent — a second run finds nothing left to drop — and what it drops
    stays in git history.
    """
    lapsed = [(date, len(batch)) for date, batch in batches(interests_text)
              if days_left(date, today) == 0]
    if not lapsed:
        return interests_text, []
    dead = {date for date, _ in lapsed}
    out = []
    for raw in interests_text.rstrip("\n").splitlines():
        parsed = parse_line(raw)
        if parsed and parsed[0] in dead:
            continue
        out.append(raw)
    return "\n".join(out) + "\n", lapsed


def clear(interests_text: str, date: str) -> tuple[str, int]:
    """Drop a whole day's batch. Returns ``(new_text, dropped_count)``.

    Clearing a date that is not there is zero dropped, not an error: the button
    is a one-tap issue and the same day can be tapped twice.
    """
    out, dropped = [], 0
    for raw in interests_text.rstrip("\n").splitlines():
        parsed = parse_line(raw)
        if parsed and parsed[0] == date:
            dropped += 1
            continue
        out.append(raw)
    return "\n".join(out) + "\n", dropped


def remove(interests_text: str, line: str) -> tuple[str, str]:
    """Drop one line. Status: ``done`` / ``not-found``."""
    return inbox_actions.remove(interests_text, line)


def add_to_queue(queue_text: str, paper_text: str,
                 section: str) -> tuple[str, str]:
    """File a paper into the reading queue, falling back when the topic misses.

    The topic is a nightly prompt's guess at a section name; a guess that names
    nothing real must not strand the paper, so it lands in
    :data:`FALLBACK_SECTION` instead. Only a queue with no fallback section
    either still returns ``no-section``.
    """
    text, status = inbox_actions.add_to_queue(queue_text, paper_text, section)
    if status == "no-section" and section != FALLBACK_SECTION:
        return inbox_actions.add_to_queue(queue_text, paper_text,
                                          FALLBACK_SECTION)
    return text, status


# --- issue bodies -------------------------------------------------------------
def parse_body(body: str) -> dict | None:
    """The ``file:`` / ``line:`` / ``section:`` / ``date:`` an action names.

    A per-paper action (➕ ✖️) names a ``line:``; the 🧹 clear action names a
    ``date:`` and no line. Either is enough; neither is None.
    """
    parsed = inbox_actions.parse_body(body)
    m_date = BODY_DATE_RE.search(body)
    if parsed is None:
        if not m_date:
            return None
        parsed = {"line": None, "file": INTERESTS_FILE}
    # inbox_actions defaults a missing section to ITS target ("Strong
    # Lensing"), which is the one section these papers are never for. An
    # absent section here means "use the line's own topic" instead.
    m_section = inbox_actions.BODY_SECTION_RE.search(body)
    parsed["section"] = m_section.group(1).strip() if m_section else None
    parsed["date"] = m_date.group(1) if m_date else None
    return parsed


# --- CLI ----------------------------------------------------------------------
def _today(ns) -> datetime.date:
    if ns.date_override:
        return datetime.date.fromisoformat(ns.date_override)
    return datetime.datetime.now(datetime.timezone.utc).date()


def _read(path: str) -> str:
    p = Path(path)
    return p.read_text(errors="replace") if p.exists() else ""


def _cmd_append(ns) -> tuple[str, int]:
    raw = json.loads(Path(ns.papers_file).read_text(errors="replace"))
    entries = raw["papers"] if isinstance(raw, dict) else raw
    entries = [{"title": e["title"], "ref": e.get("ref") or e.get("id"),
                "topic": e.get("topic")} for e in entries]
    interests = Path(ns.interests)
    text, n = append(interests.read_text(errors="replace"),
                     [_read(ns.queue), _read(ns.inbox)],
                     entries, _today(ns).isoformat(), limit=ns.limit)
    if n:
        interests.write_text(text)
    return (f"appended:{n}", 0)


def _cmd_stamp(ns) -> tuple[str, int]:
    date = _today(ns).isoformat()
    interests = Path(ns.interests)
    interests.write_text(
        inbox_actions.set_last_digest(
            interests.read_text(errors="replace"), date))
    return (f"stamped:{date}", 0)


def _cmd_sweep(ns) -> tuple[str, int]:
    interests = Path(ns.interests)
    text, lapsed = sweep(interests.read_text(errors="replace"), _today(ns))
    if lapsed:
        interests.write_text(text)
        for date, n in lapsed:
            print(f"lapsed: {date} ({n} paper{'s' if n != 1 else ''})",
                  file=sys.stderr)
    return (f"swept:{sum(n for _, n in lapsed)}", 0)


def _cmd_clear(ns) -> tuple[str, int]:
    interests = Path(ns.interests)
    text = interests.read_text(errors="replace")
    date = ns.batch_date
    if date is None:
        parsed = parse_body(Path(ns.body_file).read_text(errors="replace")) \
            if ns.body_file else None
        if parsed is None or not parsed.get("date"):
            return ("bad-body", 2)
        date = parsed["date"]
    new_text, n = clear(text, date)
    if n:
        interests.write_text(new_text)
        return (f"cleared:{n}", 0)
    return ("already-clear", 0)


def _cmd_add(ns) -> tuple[str, int]:
    parsed = parse_body(Path(ns.body_file).read_text(errors="replace"))
    if parsed is None or not parsed.get("line"):
        return ("bad-body", 2)
    interests, queue = Path(ns.interests), Path(ns.queue)
    line = parsed["line"]
    got = parse_line(line)
    paper_text = got[2] if got else line
    section = parsed.get("section") or (got[1] if got else None) \
        or FALLBACK_SECTION
    queue_text, status = add_to_queue(queue.read_text(errors="replace"),
                                      paper_text, section)
    if status == "no-section":
        return ("no-section", 3)
    if status == "added":
        queue.write_text(queue_text)
    interests_text, _ = remove(interests.read_text(errors="replace"), line)
    interests.write_text(interests_text)
    return (status, 0)


def _cmd_dismiss(ns) -> tuple[str, int]:
    parsed = parse_body(Path(ns.body_file).read_text(errors="replace"))
    if parsed is None or not parsed.get("line"):
        return ("bad-body", 2)
    interests = Path(ns.interests)
    text, status = remove(interests.read_text(errors="replace"),
                          parsed["line"])
    if status == "done":
        interests.write_text(text)
        return ("dismissed", 0)
    return ("already-gone", 0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scripts/interests_actions.py",
                                 description=__doc__)
    ap.add_argument("--interests", default=INTERESTS_FILE)
    ap.add_argument("--queue", default=QUEUE_FILE)
    ap.add_argument("--inbox", default=inbox_actions.INBOX_FILE)
    # `--today`, not inbox_actions' `--date`: this module's `clear` takes a
    # `--date` of its own (the batch), and two flags spelled the same meaning
    # different things is a trap in a workflow's shell.
    ap.add_argument("--today", dest="date_override", default=None,
                    help="override today (YYYY-MM-DD)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("append", help="append a day's batch")
    p.add_argument("--papers-file", required=True,
                   help="JSON: [{title, ref, topic}] or {\"papers\": [...]}")
    p.add_argument("--limit", type=int, default=BATCH_SIZE,
                   help=f"most papers one batch may hold (default {BATCH_SIZE})")
    p.set_defaults(fn=_cmd_append)

    p = sub.add_parser("stamp", help="record that the digest ran today")
    p.set_defaults(fn=_cmd_stamp)

    p = sub.add_parser("sweep", help="drop whole batches past the window")
    p.set_defaults(fn=_cmd_sweep)

    p = sub.add_parser("clear", help="drop a whole day's batch")
    p.add_argument("--date", dest="batch_date", default=None,
                   help="the batch to clear (YYYY-MM-DD)")
    p.add_argument("--body-file", default=None,
                   help="file holding the clear issue body (names the date)")
    p.set_defaults(fn=_cmd_clear)

    for name, fn, helptext in (("add", _cmd_add, "interests → reading queue"),
                               ("dismiss", _cmd_dismiss, "drop one line")):
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
