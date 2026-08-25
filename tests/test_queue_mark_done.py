"""tests/test_queue_mark_done.py — the queue-read issue processor.

The contract: the exact line named by a `queue-read` issue body gets a
`DONE <date> — ` prefix inside its own section only, the transform is
idempotent (already-DONE is a success), and anything unmatched is reported —
never guessed at.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import queue_mark_done as qmd  # noqa: E402

QUEUE = ("# Reading queue\n\nintro\n\n"
         "## Alpha\n\nShared Title\nOther Paper — 2406.01234\n"
         "DONE 2026-06-01 — Old Title\n\n"
         "## Beta\n\nShared Title\n")


def test_marks_only_the_named_section():
    new, status = qmd.mark_done(QUEUE, "Beta", "Shared Title", "2026-08-21")
    assert status == "marked"
    assert new.count("DONE 2026-08-21 — Shared Title") == 1
    # Alpha's identical title is untouched
    alpha = new.split("## Beta")[0]
    assert "DONE 2026-08-21" not in alpha


def test_ref_suffixed_line_matches_verbatim():
    new, status = qmd.mark_done(QUEUE, "Alpha", "Other Paper — 2406.01234",
                                "2026-08-21")
    assert status == "marked"
    assert "DONE 2026-08-21 — Other Paper — 2406.01234" in new


def test_already_done_is_idempotent():
    once, _ = qmd.mark_done(QUEUE, "Alpha", "Shared Title", "2026-08-21")
    twice, status = qmd.mark_done(once, "Alpha", "Shared Title", "2026-08-22")
    assert status == "already-done" and twice == once


def test_unknown_line_or_section_is_not_found():
    assert qmd.mark_done(QUEUE, "Alpha", "No Such Paper", "2026-08-21")[1] \
        == "not-found"
    assert qmd.mark_done(QUEUE, "Gamma", "Shared Title", "2026-08-21")[1] \
        == "not-found"


def test_parse_body_round_trip():
    body = ("Mark this reading-queue paper as read without filing it.\n\n"
            "section: Alpha\nline: Other Paper — 2406.01234\n\n"
            "Processed automatically by queue_actions.yml.")
    assert qmd.parse_body(body) == ("Alpha", "Other Paper — 2406.01234")
    assert qmd.parse_body("no structured fields here") is None
