"""tests/test_board.py — the PyAutoMemory Dashboard (scripts/board.py).

The board's contract: counts are computed correctly from a synthetic tree,
every fmt renders, the work-queue prompts reference the repo's documented
workflow, the html is self-contained (no external assets), and — the privacy
guarantee — outputs are CONTENTS-LEVEL only: page titles and counts, never
page body text.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from urllib.parse import unquote  # noqa: E402

import board  # noqa: E402
import inbox_actions  # noqa: E402

BODY_MARKER = "the-secret-claim-text-that-must-never-leak"


def _tree(tmp_path: Path) -> Path:
    w = tmp_path / "wiki" / "demo"
    (w / "concepts").mkdir(parents=True)
    (w / "sources").mkdir()
    (w / "concepts" / "alpha.md").write_text(
        f"---\ntitle: Alpha\ntype: concept\nstatus: drafted\n---\n\n"
        f"{BODY_MARKER} with a [[beta]] link and a [[gamma]] link.\n")
    (w / "sources" / "papers.md").write_text(
        "---\ntitle: Papers\ntype: sources\nstatus: stub\n---\n\n"
        "## One\n**Canonical BibTeX key:** `Key2020`\n\n"
        "## Two\n**Canonical BibTeX key:** TODO — no unique match found.\n")
    (w / "index.md").write_text("# Demo index\n- [[alpha]]\n")
    bib = tmp_path / "bibliography"
    bib.mkdir()
    (bib / "demo.bib").write_text("@article{Key2020,\n title={T}\n}\n"
                                  "@book{Other2021,\n title={U}\n}\n")
    (tmp_path / "reading-queue.md").write_text(
        "# Reading queue\n\nintro prose\n\n---\n\n"
        "## Demo Papers\n\nTitle One\nTitle Two — 2406.01234\n"
        "DONE 2026-06-01 — Old Title\n\n## Other Things\n\nTitle Three\n")
    (tmp_path / "arxiv-inbox.md").write_text(
        "# arXiv inbox\n\nintro prose\n\n---\n"
        "2026-08-24 — Suggested One — 2608.00001\n"
        "2026-08-24 — Suggested Two\n")
    return tmp_path


def _snap_with_remote(tmp_path):
    """A synthetic snapshot with repo identity, as a live checkout has."""
    snap = board.collect(_tree(tmp_path))
    snap["owner"], snap["repo"] = "PyAutoLabs", "PyAutoMemory"
    return snap


def test_counts_from_a_synthetic_tree(tmp_path):
    snap = board.collect(_tree(tmp_path))
    (w,) = snap["wikis"]
    assert w["name"] == "demo" and w["pages"] == 3
    assert w["concepts"] == 1 and w["sources"] == 1
    assert w["statuses"] == {"drafted": 1, "stub": 1}
    assert w["sections"] == 2 and w["todo"] == 1 and w["resolved_keys"] == 1
    assert snap["bib_entries"] == 2
    assert snap["queue"] == [
        {"section": "Demo Papers", "count": 2, "done": 1, "papers": [
            {"title": "Title One", "ref": None, "done": False,
             "done_date": None, "line": "Title One"},
            {"title": "Title Two", "ref": "2406.01234", "done": False,
             "done_date": None, "line": "Title Two — 2406.01234"},
            {"title": "Old Title", "ref": None, "done": True,
             "done_date": "2026-06-01",
             "line": "DONE 2026-06-01 — Old Title"}]},
        {"section": "Other Things", "count": 1, "done": 0, "papers": [
            {"title": "Title Three", "ref": None, "done": False,
             "done_date": None, "line": "Title Three"}]}]
    # alpha exists; beta/gamma are wanted
    assert snap["links"]["wanted"] == 2


def test_every_fmt_renders(tmp_path):
    snap = board.collect(_tree(tmp_path))
    for fmt in ("md", "md-brief", "html", "badge", "json"):
        assert board.render(snap, fmt)


def test_contents_level_only_no_body_text_leaks(tmp_path):
    snap = board.collect(_tree(tmp_path))
    for fmt in ("md", "md-brief", "html", "badge", "json"):
        assert BODY_MARKER not in board.render(snap, fmt)


def test_work_queue_prompts_reference_the_documented_workflow(tmp_path):
    snap = board.collect(_tree(tmp_path))
    html = board.render(snap, "html")
    assert "data-cmd=" in html  # the shared copy handler's payload hook
    assert "reading-queue.md" in html          # file-the-next-paper prompt
    assert "make validate" in html             # every prompt ends at the gate
    assert "/memory demo" in html              # the recall chip
    assert "wiki/CLAUDE.md" in html            # the schema anchor


def test_paper_links_and_issue_actions(tmp_path):
    html = board.render(_snap_with_remote(tmp_path), "html")
    # ref'd paper → its abstract page; bare title → an arXiv title search
    assert "https://arxiv.org/abs/2406.01234" in html
    assert ("https://arxiv.org/search/?searchtype=title&amp;query=Title%20One"
            in html)
    # both prefilled-issue actions, on the repo's own issue tracker
    assert "https://github.com/PyAutoLabs/PyAutoMemory/issues/new?" in html
    assert "labels=queue-read" in html and "labels=queue-intake" in html
    assert "labels=queue-cite" in html
    # a DONE paper renders as history, with no action buttons on its line
    assert "DONE 2026-06-01 — Old Title" in html
    assert "reading history (1)" in html
    # the issue body round-trips the exact queue line for queue_mark_done.py
    from urllib.parse import quote
    assert quote("line: Title Two — 2406.01234", safe="") in html


def test_no_issue_links_without_a_remote(tmp_path):
    """A spawned-template checkout (no remote) renders without dead buttons."""
    html = board.render(board.collect(_tree(tmp_path)), "html")
    assert "issues/new" not in html
    assert "arxiv.org/search" in html  # paper links still work


def test_md_lists_papers(tmp_path):
    md = board.render(_snap_with_remote(tmp_path), "md")
    assert "<details><summary>Demo Papers: 2 waiting, 1 read</summary>" in md
    assert "[Title One](https://arxiv.org/search/" in md
    assert "labels=queue-read" in md and "labels=queue-intake" in md
    assert "labels=queue-cite" in md


def test_read_trend_from_done_history(tmp_path):
    snap = board.collect(_tree(tmp_path))
    # fixture DONE date is 2026-06-01; pin "now" via the generated stamp
    snap["generated"] = "2026-06-10T00:00:00+00:00"
    trend = board._read_trend(snap)
    assert trend == {"d7": 0, "d30": 1,
                     "weeks": [0, 0, 0, 0, 0, 0, 1, 0]}  # age 9d → bucket 6
    html = board.render(snap, "html")
    assert "0 read last 7d · 1 last 30d" in html
    assert "class='spark'" in html
    assert "1 in the last 30." in board.render(snap, "md")


def test_filter_box_markup(tmp_path):
    html = board.render(board.collect(_tree(tmp_path)), "html")
    assert "id='pfilter'" in html and "function flt(" in html


def test_md_brief_is_one_line(tmp_path):
    out = board.render(board.collect(_tree(tmp_path)), "md-brief")
    assert "\n" not in out and "pages" in out


def test_badge_shape(tmp_path):
    badge = json.loads(board.render(board.collect(_tree(tmp_path)), "badge"))
    assert badge["schemaVersion"] == 1 and badge["label"] == "knowledge"
    assert "50% cited" in badge["message"]


def test_html_is_self_contained(tmp_path):
    out = board.render(board.collect(_tree(tmp_path)), "html")
    assert out.lstrip().startswith("<!doctype html>")
    assert "src=" not in out and "<link" not in out.lower()
    assert "fetch(" not in out and "XMLHttpRequest" not in out
    stripped = re.sub(r'data-cmd="[^"]*"', "", out)
    for m in re.finditer(r"(?:http|https)://", stripped):
        before = stripped[max(0, m.start() - 30):m.start()]
        assert 'href="' in before or "href='" in before, f"non-href URL at {m.start()}"


def test_live_repo_statuses_are_schema_valid():
    """The schema allows stub|drafted|reviewed; anything else is drift."""
    snap = board.collect()
    seen = set()
    for w in snap["wikis"]:
        seen |= set(w["statuses"])
    assert seen <= {"stub", "drafted", "reviewed"}, f"schema-invalid statuses: {seen}"


def test_html_wears_the_shared_family_theme(tmp_path):
    # The look is the Brain's `board/_theme.py`, not a stylesheet copied in
    # here: the page must carry this board's hero (mark, wordmark, tagline)
    # and its accent, or it has silently fallen out of the family.
    t = board.theme()
    html = board.render(board.collect(_tree(tmp_path)), "html")
    assert t.MARKS[board.BOARD_KEY] in html
    assert t.ORGANS[board.BOARD_KEY]["tagline"] in html
    assert t.ORGANS[board.BOARD_KEY]["ink_dark"] in html
    assert "#58a6ff" not in html  # the old hard-coded GitHub blue


# --- the arXiv inbox ----------------------------------------------------------
def test_inbox_is_collected_with_days_left(tmp_path):
    snap = board.collect(_tree(tmp_path))
    assert [p["title"] for p in snap["inbox"]] == ["Suggested One", "Suggested Two"]
    assert snap["inbox"][0]["ref"] == "2608.00001"
    assert snap["inbox"][1]["ref"] is None
    # dates in the fixture are fixed, so only the invariant is asserted
    assert all(0 <= p["days_left"] <= inbox_actions.INBOX_WINDOW_DAYS
               for p in snap["inbox"])


def test_a_missing_inbox_is_not_an_error(tmp_path):
    root = _tree(tmp_path)
    (root / "arxiv-inbox.md").unlink()
    snap = board.collect(root)
    assert snap["inbox"] == []
    assert "nothing waiting" in board._render_md(snap)
    assert "nothing waiting" in board._render_html(snap)


def test_inbox_papers_carry_all_four_actions(tmp_path):
    snap = _snap_with_remote(tmp_path)
    html = board._render_html(snap)
    for label in ("queue-add", "queue-intake", "queue-cite", "queue-dismiss"):
        assert label in html, label


def test_inbox_actions_name_the_inbox_file_not_the_queue(tmp_path):
    """The workflows branch on `file:` — an inbox tap must say so."""
    snap = _snap_with_remote(tmp_path)
    url = board._queue_issue_url(snap, "Demo Papers", snap["inbox"][0], "add",
                                 source=inbox_actions.INBOX_FILE)
    body = unquote(url)
    assert "file: arxiv-inbox.md" in body
    assert "line: 2026-08-24 — Suggested One — 2608.00001" in body


def test_reading_queue_actions_still_name_the_queue_file(tmp_path):
    snap = _snap_with_remote(tmp_path)
    paper = snap["queue"][0]["papers"][0]
    body = unquote(board._queue_issue_url(snap, "Demo Papers", paper, "read"))
    assert "file: reading-queue.md" in body


def test_inbox_filing_actions_warn_there_is_no_queue_line(tmp_path):
    snap = _snap_with_remote(tmp_path)
    body = unquote(board._queue_issue_url(
        snap, "Demo Papers", snap["inbox"][0], "intake",
        source=inbox_actions.INBOX_FILE))
    assert "NOT in the reading queue yet" in body
    queue_body = unquote(board._queue_issue_url(
        snap, "Demo Papers", snap["queue"][0]["papers"][0], "intake"))
    assert "NOT in the reading queue yet" not in queue_body


def test_inbox_renders_before_the_reading_queue(tmp_path):
    """The inbox is the thing to act on; it sits above the backlog."""
    snap = _snap_with_remote(tmp_path)
    for text in (board._render_md(snap), board._render_html(snap)):
        assert text.index("arXiv inbox") < text.index("Reading queue")
