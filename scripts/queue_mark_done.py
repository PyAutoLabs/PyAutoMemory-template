"""scripts/queue_mark_done.py — mark a reading-queue paper as read.

Consumed by ``.github/workflows/queue_actions.yml``: the dashboard's per-paper
✅ button opens a prefilled ``queue-read`` issue whose body names the section
and the exact queue line; this script prefixes that line with
``DONE <date> — `` (the reading-history convention — lines are never deleted).
Stdlib-only and idempotent: an already-DONE line is a success, not an error.

Prints exactly one status token on stdout — ``marked`` / ``already-done``
(exit 0), ``bad-body`` (exit 2), ``not-found`` (exit 3).

Usage:
    python scripts/queue_mark_done.py --queue reading-queue.md \
        --body-file /tmp/issue_body.txt [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
BODY_SECTION_RE = re.compile(r"^section:\s*(.+?)\s*$", re.MULTILINE)
BODY_LINE_RE = re.compile(r"^line:\s*(.+?)\s*$", re.MULTILINE)


def parse_body(body: str) -> tuple[str, str] | None:
    """The (section, line) named by a queue-action issue body, or None."""
    m_section = BODY_SECTION_RE.search(body)
    m_line = BODY_LINE_RE.search(body)
    if not (m_section and m_line):
        return None
    return m_section.group(1), m_line.group(1)


def mark_done(text: str, section: str, line: str, date: str) -> tuple[str, str]:
    """Prefix the paper's line with ``DONE <date> — `` inside its section.

    Returns (new_text, status) with status in marked / already-done /
    not-found. Only the named section is searched, so the same title in two
    sections never cross-marks.
    """
    out, in_section, status = [], False, "not-found"
    done_form = re.compile(
        r"DONE \d{4}-\d{2}-\d{2} — " + re.escape(line.strip()))
    for raw in text.splitlines():
        m = SECTION_RE.match(raw)
        if m:
            in_section = m.group(1) == section
        elif in_section and status == "not-found":
            s = raw.strip()
            if s == line.strip():
                out.append(f"DONE {date} — {s}")
                status = "marked"
                continue
            if done_form.fullmatch(s):
                status = "already-done"
        out.append(raw)
    new_text = "\n".join(out)
    if text.endswith("\n"):
        new_text += "\n"
    return new_text, status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scripts/queue_mark_done.py",
                                 description=__doc__)
    ap.add_argument("--queue", required=True, help="path to reading-queue.md")
    ap.add_argument("--body-file", required=True,
                    help="file holding the issue body")
    ap.add_argument("--date", default=None, help="override today (YYYY-MM-DD)")
    ns = ap.parse_args(argv)

    parsed = parse_body(Path(ns.body_file).read_text(errors="replace"))
    if parsed is None:
        print("bad-body")
        return 2
    section, line = parsed

    date = ns.date or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    queue = Path(ns.queue)
    new_text, status = mark_done(queue.read_text(errors="replace"),
                                 section, line, date)
    if status == "marked":
        queue.write_text(new_text)
    print(status)
    return {"marked": 0, "already-done": 0}.get(status, 3)


if __name__ == "__main__":
    sys.exit(main())
