"""tests/test_inbox_actions.py — the arXiv inbox (scripts/inbox_actions.py).

The inbox's contract: the line format round-trips, appending is idempotent and
deduplicates against both the inbox and the reading queue, the window boundary
is exact (a paper lives its full seventh day and lapses on the eighth), and the
four transitions leave both files in a state the board and the queue scripts
still parse.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import inbox_actions as ia  # noqa: E402

TODAY = datetime.date(2026, 8, 24)

INBOX = """# arXiv inbox

Prose header, not papers.

---
2026-08-24 — A model-independent substructure probe — 2608.21253
2026-08-20 — An older suggestion — 2608.11111
"""

QUEUE = """# Reading queue

Prose header.

## Strong Lensing
DONE 2026-08-21 — Something already read — 2607.99999
A paper waiting to be read

## SMBHs
An unrelated paper
"""


def _entry(title, ref=None):
    return {"title": title, "ref": ref}


# --- parsing ------------------------------------------------------------------
def test_parses_only_dated_lines():
    got = ia.papers(INBOX)
    assert [p["ref"] for p in got] == ["2608.21253", "2608.11111"]
    assert got[0]["title"] == "A model-independent substructure probe"
    assert got[0]["added"] == "2026-08-24"


def test_prose_header_is_not_a_paper():
    assert ia.parse_line("# arXiv inbox") is None
    assert ia.parse_line("Prose header, not papers.") is None
    assert ia.parse_line("---") is None


def test_title_keeps_internal_em_dashes():
    """Only a trailing ref is split off — an em dash inside a title stays."""
    title, ref = ia.split_ref("Lensing — a review — 2608.00001")
    assert title == "Lensing — a review"
    assert ref == "2608.00001"
    title, ref = ia.split_ref("Lensing — a review with no ref")
    assert title == "Lensing — a review with no ref"
    assert ref is None


@pytest.mark.parametrize("a,b", [
    ("T — 2608.21253", "Different title — 2608.21253"),
    ("T — arXiv:2608.21253", "T — 2608.21253"),
    ("T — 2608.21253v2", "T — 2608.21253"),
    ("Same  Title", "same title"),
])
def test_identity_collides_for_the_same_paper(a, b):
    assert ia.identity(a) == ia.identity(b)


def test_identity_separates_different_papers():
    assert ia.identity("T — 2608.21253") != ia.identity("T — 2608.20454")


# --- append -------------------------------------------------------------------
def test_append_adds_and_is_idempotent():
    text, n = ia.append(INBOX, QUEUE, [_entry("Brand new", "2608.00002")],
                        "2026-08-24")
    assert n == 1
    again, n2 = ia.append(text, QUEUE, [_entry("Brand new", "2608.00002")],
                          "2026-08-25")
    assert (n2, again) == (0, text)


def test_append_skips_papers_already_in_the_reading_queue():
    _, n = ia.append(INBOX, QUEUE,
                     [_entry("Something already read", "2607.99999")],
                     "2026-08-24")
    assert n == 0


def test_append_skips_a_queued_paper_matched_by_title_alone():
    _, n = ia.append(INBOX, QUEUE, [_entry("A paper waiting to be read")],
                     "2026-08-24")
    assert n == 0


def test_append_lands_after_the_last_paper_not_in_the_header():
    text, _ = ia.append(INBOX, QUEUE, [_entry("Brand new", "2608.00002")],
                        "2026-08-24")
    lines = text.splitlines()
    assert lines[-1].endswith("2608.00002")
    assert lines[0] == "# arXiv inbox"


def test_append_into_an_empty_inbox():
    header = "# arXiv inbox\n\nProse.\n\n---\n"
    text, n = ia.append(header, "", [_entry("First", "2608.00003")],
                        "2026-08-24")
    assert n == 1
    assert ia.papers(text)[0]["title"] == "First"


# --- the window ---------------------------------------------------------------
def test_days_left_counts_down_from_the_window():
    assert ia.days_left("2026-08-24", TODAY) == ia.INBOX_WINDOW_DAYS
    assert ia.days_left("2026-08-23", TODAY) == ia.INBOX_WINDOW_DAYS - 1


def test_window_boundary_is_exact():
    """A paper survives its seventh day and lapses on the eighth."""
    seventh = TODAY - datetime.timedelta(days=ia.INBOX_WINDOW_DAYS - 1)
    eighth = TODAY - datetime.timedelta(days=ia.INBOX_WINDOW_DAYS)
    assert ia.days_left(seventh.isoformat(), TODAY) == 1
    assert ia.days_left(eighth.isoformat(), TODAY) == 0


def test_days_left_never_negative_or_raising():
    assert ia.days_left("2020-01-01", TODAY) == 0
    assert ia.days_left("not-a-date", TODAY) == 0


def test_sweep_drops_only_lapsed_lines_and_keeps_the_header():
    text, dropped = ia.sweep(INBOX, datetime.date(2026, 8, 28))
    assert [d.split(" — ")[1] for d in dropped] == ["An older suggestion"]
    assert ia.papers(text)[0]["ref"] == "2608.21253"
    assert text.startswith("# arXiv inbox")


def test_sweep_is_a_noop_inside_the_window():
    text, dropped = ia.sweep(INBOX, TODAY)
    assert dropped == []
    assert text.rstrip("\n") == INBOX.rstrip("\n")


# --- transitions --------------------------------------------------------------
def test_add_to_queue_appends_unread_in_the_named_section():
    text, status = ia.add_to_queue(QUEUE, "New paper — 2608.00004",
                                   "Strong Lensing")
    assert status == "added"
    lines = text.splitlines()
    section = lines[lines.index("## Strong Lensing") + 1:lines.index("## SMBHs")]
    # last paper of the section, with the blank line before the next header kept
    assert [ln for ln in section if ln.strip()][-1] == "New paper — 2608.00004"
    assert section[-1] == ""
    assert not any(ln.startswith("DONE") and "2608.00004" in ln for ln in section)


def test_add_to_queue_is_idempotent():
    once, _ = ia.add_to_queue(QUEUE, "New paper — 2608.00004", "Strong Lensing")
    _, status = ia.add_to_queue(once, "New paper — 2608.00004", "Strong Lensing")
    assert status == "already-there"


def test_add_to_queue_matches_an_already_read_paper():
    _, status = ia.add_to_queue(QUEUE, "Something already read — 2607.99999",
                                "Strong Lensing")
    assert status == "already-there"


def test_add_to_queue_refuses_an_unknown_section():
    text, status = ia.add_to_queue(QUEUE, "New — 2608.00005", "No Such Section")
    assert (status, text) == ("no-section", QUEUE)


def test_add_does_not_leak_into_the_next_section():
    text, _ = ia.add_to_queue(QUEUE, "New paper — 2608.00004", "Strong Lensing")
    smbh = text.split("## SMBHs")[1]
    assert "2608.00004" not in smbh


def test_remove_drops_one_line_then_reports_not_found():
    line = ia.papers(INBOX)[0]["line"]
    text, status = ia.remove(INBOX, line)
    assert status == "done"
    assert len(ia.papers(text)) == 1
    _, status2 = ia.remove(text, line)
    assert status2 == "not-found"


# --- issue bodies -------------------------------------------------------------
def test_parse_body_reads_file_section_and_line():
    got = ia.parse_body("file: arxiv-inbox.md\nsection: Strong Lensing\n"
                        "line: 2026-08-24 — T — 2608.1\n")
    assert got["file"] == "arxiv-inbox.md"
    assert got["section"] == "Strong Lensing"
    assert got["line"] == "2026-08-24 — T — 2608.1"


def test_parse_body_defaults_to_the_reading_queue():
    got = ia.parse_body("section: Strong Lensing\nline: T — 2608.1\n")
    assert got["file"] == ia.QUEUE_FILE


def test_parse_body_rejects_a_body_with_no_line():
    assert ia.parse_body("section: Strong Lensing\n") is None


# --- CLI ----------------------------------------------------------------------
def _write(tmp_path):
    inbox = tmp_path / "arxiv-inbox.md"
    queue = tmp_path / "reading-queue.md"
    inbox.write_text(INBOX)
    queue.write_text(QUEUE)
    return inbox, queue


def test_cli_add_moves_the_paper_and_clears_the_inbox(tmp_path, capsys):
    inbox, queue = _write(tmp_path)
    line = ia.papers(INBOX)[0]["line"]
    body = tmp_path / "body.txt"
    body.write_text(f"file: arxiv-inbox.md\nsection: Strong Lensing\nline: {line}\n")

    code = ia.main(["--inbox", str(inbox), "--queue", str(queue),
                    "add", "--body-file", str(body)])
    assert code == 0
    assert capsys.readouterr().out.strip() == "added"
    assert "2608.21253" in queue.read_text()
    assert "2608.21253" not in inbox.read_text()
    # the queue line carries no inbox date prefix
    assert "2026-08-24 — A model-independent" not in queue.read_text()


def test_cli_dismiss_clears_the_inbox_only(tmp_path, capsys):
    inbox, queue = _write(tmp_path)
    line = ia.papers(INBOX)[0]["line"]
    body = tmp_path / "body.txt"
    body.write_text(f"file: arxiv-inbox.md\nline: {line}\n")

    assert ia.main(["--inbox", str(inbox), "--queue", str(queue),
                    "dismiss", "--body-file", str(body)]) == 0
    assert capsys.readouterr().out.strip() == "dismissed"
    assert "2608.21253" not in inbox.read_text()
    assert queue.read_text() == QUEUE


def test_cli_dismiss_twice_is_not_an_error(tmp_path, capsys):
    inbox, queue = _write(tmp_path)
    line = ia.papers(INBOX)[0]["line"]
    body = tmp_path / "body.txt"
    body.write_text(f"line: {line}\n")
    args = ["--inbox", str(inbox), "--queue", str(queue),
            "dismiss", "--body-file", str(body)]
    ia.main(args)
    capsys.readouterr()
    assert ia.main(args) == 0
    assert capsys.readouterr().out.strip() == "already-gone"


def test_cli_append_reads_the_digest_shape(tmp_path, capsys):
    inbox, queue = _write(tmp_path)
    papers_file = tmp_path / "survivors.json"
    papers_file.write_text(json.dumps({"papers": [
        {"title": "Fresh one", "id": "2608.31337"},
        {"title": "A model-independent substructure probe", "id": "2608.21253"},
    ]}))
    assert ia.main(["--inbox", str(inbox), "--queue", str(queue),
                    "--date", "2026-08-25",
                    "append", "--papers-file", str(papers_file)]) == 0
    assert capsys.readouterr().out.strip() == "appended:1"
    assert "2026-08-25 — Fresh one — 2608.31337" in inbox.read_text()


def test_cli_sweep_reports_the_count(tmp_path, capsys):
    inbox, queue = _write(tmp_path)
    assert ia.main(["--inbox", str(inbox), "--queue", str(queue),
                    "--date", "2026-08-28", "sweep"]) == 0
    assert capsys.readouterr().out.strip() == "swept:1"


def test_cli_bad_body_exits_two(tmp_path, capsys):
    inbox, queue = _write(tmp_path)
    body = tmp_path / "body.txt"
    body.write_text("nothing useful here\n")
    assert ia.main(["--inbox", str(inbox), "--queue", str(queue),
                    "add", "--body-file", str(body)]) == 2
    assert capsys.readouterr().out.strip() == "bad-body"


def test_add_output_still_parses_as_a_queue_line(tmp_path):
    """The queue scripts must still recognise what the inbox hands them."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import queue_mark_done as qmd

    inbox, queue = _write(tmp_path)
    line = ia.papers(INBOX)[0]["line"]
    body = tmp_path / "body.txt"
    body.write_text(f"file: arxiv-inbox.md\nsection: Strong Lensing\nline: {line}\n")
    ia.main(["--inbox", str(inbox), "--queue", str(queue),
             "add", "--body-file", str(body)])

    queued = ia.parse_line(line)[1]
    text, status = qmd.mark_done(queue.read_text(), "Strong Lensing", queued,
                                 "2026-08-30")
    assert status == "marked"
    assert f"DONE 2026-08-30 — {queued}" in text


# --- the freshness stamp ------------------------------------------------------
# An empty inbox is ambiguous on its own: arXiv was quiet, or the filing broke
# and the papers were lost. The stamp is what separates the two, so its
# contract is that it round-trips, replaces rather than accumulates, and never
# gets in the way of the papers around it.
def test_stamp_round_trips():
    text = ia.set_last_digest(INBOX, "2026-08-25")
    assert ia.last_digest(text) == "2026-08-25"


def test_an_unstamped_inbox_reports_none():
    assert ia.last_digest(INBOX) is None


def test_stamp_lands_below_the_separator_and_above_the_papers():
    lines = ia.set_last_digest(INBOX, "2026-08-25").splitlines()
    assert lines[lines.index("---") + 1] == "last digest: 2026-08-25"
    assert lines.index("last digest: 2026-08-25") < lines.index(
        "2026-08-24 — A model-independent substructure probe — 2608.21253")


def test_stamp_is_replaced_not_accumulated():
    """It is rewritten nightly; a second line would be a slow leak."""
    text = ia.set_last_digest(ia.set_last_digest(INBOX, "2026-08-24"),
                              "2026-08-25")
    assert text.count("last digest:") == 1
    assert ia.last_digest(text) == "2026-08-25"


def test_stamp_is_not_read_back_as_a_paper():
    """Why the line is not date-first: it must never match INBOX_LINE_RE."""
    text = ia.set_last_digest(INBOX, "2026-08-25")
    assert ia.parse_line("last digest: 2026-08-25") is None
    assert [p["ref"] for p in ia.papers(text)] == ["2608.21253", "2608.11111"]


def test_the_sweep_never_ages_the_stamp_out():
    """Unlike a per-day marker line, this one has nothing to expire."""
    text = ia.set_last_digest(INBOX, "2026-08-01")
    swept, dropped = ia.sweep(text, datetime.date(2026, 9, 30))
    assert ia.last_digest(swept) == "2026-08-01"
    assert "last digest: 2026-08-01" not in dropped


def test_append_still_lands_below_a_stamped_empty_inbox():
    """The empty-inbox branch appends at EOF — the stamp must stay on top."""
    empty = ia.set_last_digest("# arXiv inbox\n\nprose\n\n---\n", "2026-08-25")
    text, n = ia.append(empty, "", [_entry("Fresh", "2608.31337")],
                        "2026-08-25")
    assert n == 1
    lines = text.splitlines()
    assert lines.index("last digest: 2026-08-25") < lines.index(
        "2026-08-25 — Fresh — 2608.31337")


def test_append_still_lands_below_a_stamped_populated_inbox():
    text, n = ia.append(ia.set_last_digest(INBOX, "2026-08-25"), "",
                        [_entry("Fresh", "2608.31337")], "2026-08-25")
    assert n == 1
    lines = text.splitlines()
    assert lines.index("last digest: 2026-08-25") < lines.index(
        "2026-08-25 — Fresh — 2608.31337")


# --- weekday arithmetic -------------------------------------------------------
# Calendar days overstate the digest's silence: it only runs Mon-Fri, so a
# Monday board reading Friday's stamp is three days but zero missed runs.
def test_a_weekend_costs_no_weekdays():
    friday, monday = "2026-08-21", datetime.date(2026, 8, 24)
    assert (monday - datetime.date.fromisoformat(friday)).days == 3
    assert ia.weekdays_since(friday, monday) == 1


def test_weekdays_since_counts_the_days_after_the_stamp():
    assert ia.weekdays_since("2026-08-24", datetime.date(2026, 8, 24)) == 0
    assert ia.weekdays_since("2026-08-24", datetime.date(2026, 8, 25)) == 1
    assert ia.weekdays_since("2026-08-24", datetime.date(2026, 8, 28)) == 4


def test_a_malformed_stamp_is_not_arithmetic():
    assert ia.weekdays_since("not-a-date", datetime.date(2026, 8, 25)) == 0


# --- the staleness verdict ----------------------------------------------------
def test_one_missed_weekday_is_not_yet_stale():
    """Cron jitters later by up to ~3 h, so a single day is reachable clean."""
    assert ia.INBOX_STALE_WEEKDAYS == 2
    assert not ia.is_stale("2026-08-24", datetime.date(2026, 8, 25))


def test_two_missed_weekdays_is_stale():
    assert ia.is_stale("2026-08-24", datetime.date(2026, 8, 26))


def test_a_missing_stamp_is_not_stale():
    """spawn.py empties the inbox, so a fresh template has nothing to be late
    for. Absence of evidence is not evidence of breakage."""
    assert not ia.is_stale(None, datetime.date(2026, 8, 26))


def test_cli_stamp_reports_the_date(tmp_path, capsys):
    inbox, queue = _write(tmp_path)
    assert ia.main(["--inbox", str(inbox), "--queue", str(queue),
                    "--date", "2026-08-25", "stamp"]) == 0
    assert capsys.readouterr().out.strip() == "stamped:2026-08-25"
    assert ia.last_digest(inbox.read_text()) == "2026-08-25"
