"""tests/test_interests_actions.py — the arXiv interests list.

The list's contract, and specifically the thing that makes it NOT the
strong-lensing inbox: it is grouped into day batches with the oldest one
current, so `clear` and `sweep` both act on a whole day where the inbox acts on
a line. The window itself is the inbox's — a batch nobody clears lapses after
`INBOX_WINDOW_DAYS`. Everything else — line format, dedup, the add/dismiss
transitions — is the inbox's contract, tested here because this module owns the
`[Topic]` the inbox lines do not carry.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import inbox_actions as ib  # noqa: E402
import interests_actions as ia  # noqa: E402

LIST = """# arXiv interests

Prose header, not papers.

---
last digest: 2026-08-27
2026-08-25 — [SMBHs] A tidal disruption event — 2608.30001
2026-08-25 — [Dark Matter] Ultra-light dark matter from streams — 2608.30002
2026-08-26 — [Stats] Simulation-based inference — 2608.30004
"""

QUEUE = """# Reading queue

Prose header.

## SMBHs
A black hole paper already queued — 2608.10001

## Dark Matter
DONE 2026-08-21 — Something already read — 2607.99999

## Interests
NOTE the fallback section.
"""

INBOX = """# arXiv inbox

---
last digest: 2026-08-27
2026-08-25 — A strong lensing paper — 2608.22222
"""


def _entry(title, ref=None, topic=None):
    return {"title": title, "ref": ref, "topic": topic}


# --- parsing ------------------------------------------------------------------
def test_parses_date_topic_and_paper():
    got = ia.papers(LIST)
    assert [p["ref"] for p in got] == ["2608.30001", "2608.30002", "2608.30004"]
    assert got[0]["topic"] == "SMBHs"
    assert got[0]["title"] == "A tidal disruption event"
    assert got[0]["added"] == "2026-08-25"


def test_topic_is_optional():
    got = ia.parse_line("2026-08-25 — A paper with no topic — 2608.10001")
    assert got == ("2026-08-25", None, "A paper with no topic — 2608.10001")


def test_prose_and_stamp_are_not_papers():
    assert ia.parse_line("# arXiv interests") is None
    assert ia.parse_line("last digest: 2026-08-27") is None
    assert ia.parse_line("") is None


def test_format_line_round_trips():
    line = ia.format_line("2026-08-25", "Stats", "A title — 2608.10001")
    assert line == "2026-08-25 — [Stats] A title — 2608.10001"
    assert ia.parse_line(line) == ("2026-08-25", "Stats", "A title — 2608.10001")


def test_format_line_omits_an_empty_topic():
    assert ia.format_line("2026-08-25", None, "A title") == "2026-08-25 — A title"
    assert ia.format_line("2026-08-25", "  ", "A title") == "2026-08-25 — A title"


def test_a_title_containing_brackets_is_not_read_as_a_topic():
    # The topic marker is anchored at the start; a bracket later in the title
    # (or a title that merely opens with one mid-sentence) must survive.
    line = "2026-08-25 — [Stats] Errors [sic] in inference — 2608.10001"
    assert ia.parse_line(line)[2] == "Errors [sic] in inference — 2608.10001"


# --- batches ------------------------------------------------------------------
def test_batches_group_by_date_oldest_first():
    got = ia.batches(LIST)
    assert [d for d, _ in got] == ["2026-08-25", "2026-08-26"]
    assert [len(b) for _, b in got] == [2, 1]


def test_current_batch_is_the_oldest():
    date, batch = ia.current_batch(LIST)
    assert date == "2026-08-25"
    assert len(batch) == 2


def test_current_batch_of_an_empty_list_is_none():
    assert ia.current_batch("# arXiv interests\n\n---\n") is None


def test_batches_regroup_out_of_order_lines():
    # A hand edit (or a re-run) can leave a date's lines split apart; a batch
    # is the date, not a run of adjacent lines.
    text = LIST + "2026-08-25 — [Stats] A late arrival — 2608.30009\n"
    assert [len(b) for _, b in ia.batches(text)] == [3, 1]


# --- append -------------------------------------------------------------------
def test_append_writes_the_topic_and_the_ref():
    text, n = ia.append(LIST, [], [_entry("A new paper", "2608.50001", "Stats")],
                        "2026-08-27")
    assert n == 1
    assert text.rstrip().endswith("2026-08-27 — [Stats] A new paper — 2608.50001")


def test_append_dedupes_against_itself():
    text, n = ia.append(LIST, [],
                        [_entry("Whatever title", "2608.30001", "Stats")],
                        "2026-08-27")
    assert (n, text) == (0, LIST)


def test_append_dedupes_against_the_queue_and_the_inbox():
    entries = [_entry("A black hole paper already queued", "2608.10001"),
               _entry("Something already read", "2607.99999"),
               _entry("A strong lensing paper", "2608.22222"),
               _entry("Genuinely new", "2608.77777", "Stats")]
    text, n = ia.append(LIST, [QUEUE, INBOX], entries, "2026-08-27")
    assert n == 1
    assert "Genuinely new" in text


def test_append_caps_the_batch():
    entries = [_entry(f"Paper {i}", f"2608.9{i:04d}", "Stats") for i in range(15)]
    text, n = ia.append(LIST, [], entries, "2026-08-27", limit=10)
    assert n == 10
    assert len(ia.batches(text)[-1][1]) == 10


def test_append_extends_a_date_already_present():
    text, _ = ia.append(LIST, [], [_entry("Another 25th paper", "2608.50001")],
                        "2026-08-25")
    assert [len(b) for _, b in ia.batches(text)] == [3, 1]


def test_append_keeps_the_stamp_above_the_papers():
    text, _ = ia.append(LIST, [], [_entry("A new paper", "2608.50001")],
                        "2026-08-27")
    lines = text.splitlines()
    assert lines.index("last digest: 2026-08-27") < lines.index(
        "2026-08-27 — A new paper — 2608.50001")


def test_append_into_an_empty_list_lands_below_the_separator():
    empty = "# arXiv interests\n\nProse.\n\n---\nlast digest: 2026-08-27\n"
    text, n = ia.append(empty, [], [_entry("First ever", "2608.10001", "Stats")],
                        "2026-08-27")
    assert n == 1
    assert ia.current_batch(text)[1][0]["title"] == "First ever"


# --- clear --------------------------------------------------------------------
def test_clear_drops_exactly_one_day():
    text, n = ia.clear(LIST, "2026-08-25")
    assert n == 2
    assert [d for d, _ in ia.batches(text)] == ["2026-08-26"]


def test_clear_reveals_the_next_day():
    text, _ = ia.clear(LIST, "2026-08-25")
    assert ia.current_batch(text)[0] == "2026-08-26"


def test_clear_is_idempotent():
    text, _ = ia.clear(LIST, "2026-08-25")
    again, n = ia.clear(text, "2026-08-25")
    assert (n, again) == (0, text)


def test_clear_keeps_the_prose_and_the_stamp():
    text, _ = ia.clear(LIST, "2026-08-25")
    assert "# arXiv interests" in text
    assert "last digest: 2026-08-27" in text



# --- sweep --------------------------------------------------------------------
def _day(iso):
    return datetime.date.fromisoformat(iso)


def test_days_left_is_the_inboxs_window_unchanged():
    # One owner for the number. If the inbox's window moves, this moves with it.
    today = _day("2026-08-27")
    assert ia.days_left("2026-08-25", today) == ib.days_left("2026-08-25", today)
    assert ia.days_left("2026-08-25", today) == ib.INBOX_WINDOW_DAYS - 2


def test_sweep_drops_only_batches_past_the_window():
    # 2026-08-25 is seven days old on 2026-09-01; 2026-08-26 has a day left.
    text, lapsed = ia.sweep(LIST, _day("2026-09-01"))
    assert lapsed == [("2026-08-25", 2)]
    assert [p["added"] for p in ia.papers(text)] == ["2026-08-26"]


def test_sweep_takes_the_whole_batch_never_part_of_one():
    text, lapsed = ia.sweep(LIST, _day("2026-09-03"))
    assert lapsed == [("2026-08-25", 2), ("2026-08-26", 1)]
    assert ia.papers(text) == []
    # The prose header and the freshness stamp are not papers and must survive.
    assert "Prose header, not papers." in text
    assert "last digest: 2026-08-27" in text


def test_sweep_leaves_a_fresh_list_untouched():
    text, lapsed = ia.sweep(LIST, _day("2026-08-27"))
    assert lapsed == []
    assert text == LIST


def test_sweep_is_idempotent():
    once, first = ia.sweep(LIST, _day("2026-09-01"))
    twice, second = ia.sweep(once, _day("2026-09-01"))
    assert second == []
    assert twice == once


# --- remove / add_to_queue ----------------------------------------------------
def test_remove_takes_the_line_as_written():
    line = "2026-08-25 — [SMBHs] A tidal disruption event — 2608.30001"
    text, status = ia.remove(LIST, line)
    assert status == "done"
    assert line not in text


def test_add_to_queue_uses_the_named_section():
    text, status = ia.add_to_queue(QUEUE, "A new SMBH paper — 2608.50001", "SMBHs")
    assert status == "added"
    smbh = text.split("## SMBHs")[1].split("##")[0]
    assert "A new SMBH paper" in smbh


def test_add_to_queue_falls_back_when_the_topic_names_nothing():
    text, status = ia.add_to_queue(QUEUE, "An exoplanet paper — 2608.50001",
                                   "Exoplanets")
    assert status == "added"
    fallback = text.split("## Interests")[1]
    assert "An exoplanet paper" in fallback


def test_add_to_queue_reports_no_section_without_a_fallback():
    queue = "# Reading queue\n\n## SMBHs\nA paper\n"
    _, status = ia.add_to_queue(queue, "An exoplanet paper", "Exoplanets")
    assert status == "no-section"


# --- issue bodies -------------------------------------------------------------
def test_parse_body_reads_a_per_paper_action():
    body = ("file: arxiv-interests.md\nsection: SMBHs\n"
            "line: 2026-08-25 — [SMBHs] A tidal disruption event — 2608.30001\n")
    got = ia.parse_body(body)
    assert got["file"] == "arxiv-interests.md"
    assert got["section"] == "SMBHs"
    assert got["line"].startswith("2026-08-25 — [SMBHs]")
    assert got["date"] is None


def test_parse_body_reads_a_clear_action():
    got = ia.parse_body("file: arxiv-interests.md\ndate: 2026-08-25\n")
    assert got["date"] == "2026-08-25"
    assert got["line"] is None


def test_parse_body_never_defaults_the_section_to_strong_lensing():
    # inbox_actions.parse_body does; inheriting that would file every
    # topic-less interests paper into the one section it is never for.
    got = ia.parse_body("line: 2026-08-25 — A paper — 2608.10001\n")
    assert got["section"] is None


def test_parse_body_rejects_a_body_naming_neither():
    assert ia.parse_body("nothing useful here") is None


# --- CLI ----------------------------------------------------------------------
@pytest.fixture
def repo(tmp_path):
    (tmp_path / "arxiv-interests.md").write_text(LIST)
    (tmp_path / "reading-queue.md").write_text(QUEUE)
    (tmp_path / "arxiv-inbox.md").write_text(INBOX)
    return tmp_path


def _run(repo, *argv):
    return ia.main(["--interests", str(repo / "arxiv-interests.md"),
                    "--queue", str(repo / "reading-queue.md"),
                    "--inbox", str(repo / "arxiv-inbox.md"), *argv])


def test_cli_append_and_stamp(repo, capsys):
    picks = repo / "picks.json"
    picks.write_text(json.dumps({"papers": [
        {"title": "A new paper", "id": "2608.50001", "topic": "Stats"}]}))
    assert _run(repo, "--today", "2026-08-28", "append",
                "--papers-file", str(picks)) == 0
    assert capsys.readouterr().out.strip() == "appended:1"
    assert _run(repo, "--today", "2026-08-28", "stamp") == 0
    assert capsys.readouterr().out.strip() == "stamped:2026-08-28"
    text = (repo / "arxiv-interests.md").read_text()
    assert "last digest: 2026-08-28" in text
    assert "2026-08-28 — [Stats] A new paper — 2608.50001" in text


def test_cli_sweep_drops_lapsed_batches(repo, capsys):
    assert _run(repo, "--today", "2026-09-01", "sweep") == 0
    out = capsys.readouterr()
    assert out.out.strip() == "swept:2"
    assert "lapsed: 2026-08-25 (2 papers)" in out.err
    text = (repo / "arxiv-interests.md").read_text()
    assert "2608.30001" not in text
    assert "2608.30004" in text


def test_cli_sweep_reports_a_quiet_run_without_touching_the_file(repo, capsys):
    before = (repo / "arxiv-interests.md").read_text()
    assert _run(repo, "--today", "2026-08-27", "sweep") == 0
    assert capsys.readouterr().out.strip() == "swept:0"
    assert (repo / "arxiv-interests.md").read_text() == before


def test_cli_clear_by_date_then_by_body(repo, capsys):
    assert _run(repo, "clear", "--date", "2026-08-25") == 0
    assert capsys.readouterr().out.strip() == "cleared:2"
    body = repo / "body.txt"
    body.write_text("file: arxiv-interests.md\ndate: 2026-08-26\n")
    assert _run(repo, "clear", "--body-file", str(body)) == 0
    assert capsys.readouterr().out.strip() == "cleared:1"
    assert ia.current_batch((repo / "arxiv-interests.md").read_text()) is None


def test_cli_add_routes_by_the_lines_own_topic(repo, capsys):
    body = repo / "body.txt"
    body.write_text(
        "file: arxiv-interests.md\n"
        "line: 2026-08-25 — [SMBHs] A tidal disruption event — 2608.30001\n")
    assert _run(repo, "add", "--body-file", str(body)) == 0
    assert capsys.readouterr().out.strip() == "added"
    queue = (repo / "reading-queue.md").read_text()
    assert "A tidal disruption event — 2608.30001" in queue.split(
        "## SMBHs")[1].split("##")[0]
    assert "2608.30001" not in (repo / "arxiv-interests.md").read_text()


def test_cli_dismiss_leaves_the_queue_alone(repo, capsys):
    body = repo / "body.txt"
    body.write_text(
        "file: arxiv-interests.md\n"
        "line: 2026-08-26 — [Stats] Simulation-based inference — 2608.30004\n")
    before = (repo / "reading-queue.md").read_text()
    assert _run(repo, "dismiss", "--body-file", str(body)) == 0
    assert capsys.readouterr().out.strip() == "dismissed"
    assert (repo / "reading-queue.md").read_text() == before
    assert "2608.30004" not in (repo / "arxiv-interests.md").read_text()


def test_cli_reports_a_body_it_cannot_read(repo, capsys):
    body = repo / "body.txt"
    body.write_text("nothing useful\n")
    assert _run(repo, "add", "--body-file", str(body)) == 2
    assert capsys.readouterr().out.strip() == "bad-body"
