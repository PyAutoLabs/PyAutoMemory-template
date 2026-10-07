"""tests/test_board.py — the PyAutoMemory Dashboard (scripts/board.py).

The board's contract: counts are computed correctly from a synthetic tree,
every fmt renders, the work-queue prompts reference the repo's documented
workflow, the html is self-contained (no external assets), and — the privacy
guarantee — outputs are CONTENTS-LEVEL only: page titles and counts, never
page body text.
"""

from __future__ import annotations

import datetime
import json
import pytest
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from urllib.parse import unquote  # noqa: E402

import board  # noqa: E402
import inbox_actions  # noqa: E402
import interests_actions  # noqa: E402

BODY_MARKER = "the-secret-claim-text-that-must-never-leak"


def test_theme_finds_grouped_brain_from_outer_workspace(tmp_path, monkeypatch):
    brain_board = tmp_path / "organs" / "PyAutoBrain" / "board"
    brain_board.mkdir(parents=True)
    (brain_board / "_theme.py").write_text("GROUPED_THEME = True\n")
    monkeypatch.setenv("PYAUTO_ROOT", str(tmp_path))
    monkeypatch.delenv("PYAUTO_BRAIN", raising=False)
    monkeypatch.setattr(board, "MEMORY_HOME", tmp_path / "PyAutoMemory")
    monkeypatch.delitem(sys.modules, "_theme", raising=False)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    try:
        assert board.theme().GROUPED_THEME
    finally:
        sys.modules.pop("_theme", None)


def test_workspace_root_marker_stays_at_outer_root(tmp_path, monkeypatch):
    memory = tmp_path / "organs" / "PyAutoMemory"
    memory.mkdir(parents=True)
    (tmp_path / ".pyauto-root").touch()
    monkeypatch.delenv("PYAUTO_ROOT", raising=False)
    monkeypatch.setattr(board, "MEMORY_HOME", memory)
    assert board._workspace_root() == tmp_path

# The freshness/staleness banners are computed against `snapshot["generated"]`,
# so a fixture with fixed dates and a live clock ages out of its own window and
# the suite goes red on a calendar day rather than on a code change (it did, on
# 2026-08-28: the two-day-old stamp below turned stale and the assertions that
# expected a quiet day started reading the "filing may be broken" banner). Pin
# the clock to the day the tree below is written for; `_inbox` already does the
# same with its own calibrated date.
FIXTURE_NOW = "2026-08-26T09:00:00+00:00"


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
        "DONE 2026-06-01 — Old Title\n\n## Other Things\n\nTitle Three\n"
        "Title Four — https://arxiv.org/pdf/2201.00042.pdf\n"
        "__A Sub Heading__\nNOTE — just a remark\n"
        "https://example.org/not-a-paper\n"
        "https://arxiv.org/abs/2202.00099\n")
    (tmp_path / "arxiv-inbox.md").write_text(
        "# arXiv inbox\n\nintro prose\n\n---\n"
        "2026-08-24 — Suggested One — 2608.00001\n"
        "2026-08-24 — Suggested Two\n")
    # Two day batches, oldest first: the board must show only the first.
    (tmp_path / "arxiv-interests.md").write_text(
        "# arXiv interests\n\nintro prose\n\n---\n"
        "last digest: 2026-08-26\n"
        "2026-08-25 — [Demo Papers] Interest One — 2608.10001\n"
        "2026-08-25 — [Nowhere] Interest Two — 2608.10002\n"
        "2026-08-26 — [Demo Papers] Interest Three — 2608.10003\n")
    return tmp_path


def _snap_with_remote(tmp_path):
    """A synthetic snapshot with repo identity, as a live checkout has."""
    snap = board.collect(_tree(tmp_path))
    snap["owner"], snap["repo"] = "PyAutoLabs", "PyAutoMemory"
    snap["generated"] = FIXTURE_NOW
    snap["lensing_ingest_evidence"] = {"last_ingested": FIXTURE_NOW[:10], "done": FIXTURE_NOW[:10], "bib": None}
    return snap


def test_seed_pages_are_counted_apart_from_sources(tmp_path):
    # `seed/` is the unverified import; a sub-wiki row that folded it into
    # `sources` would read as if those pages were verified claim support.
    root = _tree(tmp_path)
    seed = root / "wiki" / "demo" / "seed"
    seed.mkdir()
    (seed / "unverified.md").write_text(
        "---\ntitle: Seed\ntype: sources\nstatus: stub\n---\n\n"
        "## One\n**Canonical BibTeX key:** TODO — no unique match found.\n")
    (w,) = board.collect(root)["wikis"]
    assert (w["sources"], w["seed"], w["pages"]) == (1, 1, 4)
    assert "1 seed" in board.render(board.collect(root), "html")


def test_counts_from_a_synthetic_tree(tmp_path):
    snap = board.collect(_tree(tmp_path))
    (w,) = snap["wikis"]
    assert w["name"] == "demo" and w["pages"] == 3
    assert w["concepts"] == 1 and w["sources"] == 1
    assert w["statuses"] == {"drafted": 1, "stub": 1}
    assert w["sections"] == 2 and w["todo"] == 1 and w["resolved_keys"] == 1
    assert snap["bib_entries"] == 2
    def _paper(kind, title, ref, line, done=False, done_date=None):
        return {"kind": kind, "title": title, "ref": ref, "done": done,
                "done_date": done_date, "line": line}

    assert snap["queue"] == [
        {"section": "Demo Papers", "count": 2, "done": 1, "papers": [
            _paper("paper", "Title One", None, "Title One"),
            _paper("paper", "Title Two", "2406.01234",
                   "Title Two — 2406.01234"),
            _paper("paper", "Old Title", None, "DONE 2026-06-01 — Old Title",
                   done=True, done_date="2026-06-01")]},
        # count is 3, not 6: the heading, the remark and the non-arXiv link are
        # carried in file order but are not queue work.
        {"section": "Other Things", "count": 3, "done": 0, "papers": [
            _paper("paper", "Title Three", None, "Title Three"),
            _paper("paper", "Title Four",
                   "https://arxiv.org/pdf/2201.00042.pdf",
                   "Title Four — https://arxiv.org/pdf/2201.00042.pdf"),
            _paper("subhead", "A Sub Heading", None, "__A Sub Heading__"),
            _paper("note", "just a remark", None, "NOTE — just a remark"),
            _paper("note", "https://example.org/not-a-paper", None,
                   "https://example.org/not-a-paper"),
            # a bare arXiv link IS a paper — the title was just never written,
            # so the id in the line stands in for it
            _paper("paper", "arXiv:2202.00099",
                   "https://arxiv.org/abs/2202.00099",
                   "https://arxiv.org/abs/2202.00099")]}]
    # alpha exists; beta/gamma are wanted
    assert snap["links"]["wanted"] == 2


def test_every_fmt_renders(tmp_path):
    snap = board.collect(_tree(tmp_path))
    for fmt in ("md", "md-brief", "html", "badge", "state", "json"):
        assert board.render(snap, fmt)


def test_contents_level_only_no_body_text_leaks(tmp_path):
    snap = board.collect(_tree(tmp_path))
    for fmt in ("md", "md-brief", "html", "badge", "state", "json"):
        assert BODY_MARKER not in board.render(snap, fmt)


def test_work_queue_prompts_reference_the_documented_workflow(tmp_path):
    snap = board.collect(_tree(tmp_path))
    html = board.render(snap, "html")
    assert "data-cmd=" in html  # the shared copy handler's payload hook
    assert "reading-queue.md" in html          # file-the-next-paper prompt
    assert "make validate" in html             # every prompt ends at the gate
    assert "Use the memory skill. demo" in html              # the recall chip
    assert "wiki/AGENTS.md" in html            # the schema anchor


def test_paper_links_and_issue_actions(tmp_path):
    html = board.render(_snap_with_remote(tmp_path), "html")
    # the header links the markdown twin and the repository front door
    assert '<a href="dashboard.md">markdown version</a>' in html
    assert ('<a href="https://github.com/PyAutoLabs/PyAutoMemory/blob/main/'
            'README.md">GitHub Page</a>') in html
    # ref'd paper → its abstract page; bare title → an arXiv title search
    assert "https://arxiv.org/abs/2406.01234" in html
    assert ("https://arxiv.org/search/?searchtype=title&amp;query=Title%20One"
            in html)
    # a ref written as a /pdf/ URL still titles onto the abstract page, so
    # every paper row reads the same way
    assert "https://arxiv.org/abs/2201.00042" in html
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
    # The one-tap script names the link shape it intercepts; that is not a
    # button, so judge the markup with the script stripped out.
    markup = re.sub(r"<script>.*</script>", "", html, flags=re.DOTALL)
    assert "issues/new" not in markup
    assert "arxiv.org/search" in markup  # paper links still work


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
    # no repo identity in this snapshot → the GitHub Page segment drops out
    assert "GitHub Page" not in out
    assert "src=" not in out and "<link" not in out.lower()
    # The one network call the page may make is the GitHub API, and only
    # from a tap in one-tap mode — never a load-time fetch of an asset.
    assert "XMLHttpRequest" not in out
    script = re.search(r"<script>(.*)</script>", out, re.DOTALL).group(1)
    assert out.count("fetch(") == script.count("fetch(") == 1
    assert "fetch(API+" in script and "API='https://api.github.com'" in script
    stripped = re.sub(r'data-cmd="[^"]*"', "", out.replace(script, ""))
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


def _family_without_memory() -> list[str]:
    """The canonical board family, in the order `PyAutoBrain/config/policy.yaml`
    `board: boards:` declares it, minus this board (`memory`).

    Derived from the Brain — the same `_theme.board_links` read the renderer
    makes — never written out here. A literal in this file pinned the
    six-board family and went red once the Eyes, the Nerves and the Gut got
    boards (PyAutoMind#450); the next organ birth must not re-break it.
    """
    return list(board.theme().board_links("", board.BOARD_KEY))


def _footer(tmp_path) -> str:
    # The synthetic tree has no git remote, so `collect` finds no owner and
    # the footer (rightly) renders empty. Name a fake one — this file carries
    # no instance facts.
    snap = board.collect(_tree(tmp_path))
    snap["owner"] = "SomeOrg"
    html = board.render(snap, "html")
    return re.search(r'<ul class="boards">.*?</ul>', html, re.S).group(0)


def test_the_family_footer_carries_the_cortex_in_the_canonical_order(tmp_path):
    """The footer's membership is the Brain's config, not a tuple in here.

    It used to be a tuple in here — written before the Cortex had a board —
    so this page linked five siblings in an ad-hoc order and silently missed
    the sixth. Reading `_theme.board_links` means adding a board to
    `config/policy.yaml` lights it in every footer at once.
    """
    footer = _footer(tmp_path)
    family = _family_without_memory()
    assert "cortex" in family and board.BOARD_KEY not in family
    assert re.findall(r'data-organ="(\w+)"', footer) == family
    assert "https://someorg.github.io/PyAutoCortex/" in footer


def test_the_footer_never_links_the_page_it_is_on(tmp_path):
    footer = _footer(tmp_path)
    assert f'data-organ="{board.BOARD_KEY}"' not in footer


def test_the_footer_falls_back_when_the_brain_checkout_predates_the_helper():
    """An older PyAutoBrain beside this repo has no `board_links`. The page
    must still render its footer — from the legacy tuple — rather than lose
    the whole board over a nav strip."""
    class _Older:
        def __init__(self, real):
            self.boards_footer = real.boards_footer

    real = board.theme()
    saved = board._boards_nav.__globals__["theme"]
    board._boards_nav.__globals__["theme"] = lambda: _Older(real)
    try:
        footer = board._boards_nav({"owner": "SomeOrg"})
    finally:
        board._boards_nav.__globals__["theme"] = saved
    assert re.findall(r'data-organ="(\w+)"', footer) == [
        k for k, _ in board.BOARD_FAMILY]


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


# --- the inbox's freshness line -----------------------------------------------
# The point of the stamp is that an EMPTY inbox stops being ambiguous. These
# cover the three empty states (quiet / never run / suspect) plus the populated
# one, on both renderers.
def _inbox(tmp_path, stamp=None, papers=()):
    # A fresh subdirectory per call: _tree() builds the tree with mkdir() and
    # cannot be re-run over one it already made.
    base = tmp_path / f"t{len(list(tmp_path.iterdir()))}"
    base.mkdir()
    root = _tree(base)
    text = "# arXiv inbox\n\nintro prose\n\n---\n" + "".join(
        f"{line}\n" for line in papers)
    if stamp:
        text = inbox_actions.set_last_digest(text, stamp)
    (root / "arxiv-inbox.md").write_text(text)
    # The page carries two stamped tiers; blank the other one so these assert
    # about the inbox's freshness and not the interests list's.
    (root / "arxiv-interests.md").write_text(
        "# arXiv interests\n\nintro prose\n\n---\n")
    snap = board.collect(root)
    snap["owner"], snap["repo"] = "PyAutoLabs", "PyAutoMemory"
    snap["generated"] = "2026-08-25T09:00:00+00:00"  # calibrated to this helper's dates
    return snap


def test_the_stamp_is_collected(tmp_path):
    assert _inbox(tmp_path, "2026-08-24")["inbox_last_digest"] == "2026-08-24"
    assert _inbox(tmp_path)["inbox_last_digest"] is None


def test_a_quiet_day_says_the_digest_ran(tmp_path):
    """The state the old wording could not distinguish from a broken run."""
    md = board._render_md(_inbox(tmp_path, "2026-08-25"))
    assert "the last digest ran 2026-08-25; nothing is waiting" in md
    assert "⚠" not in md


def test_a_stale_inbox_says_the_filing_may_be_broken(tmp_path):
    for render in (board._render_md, board._render_html):
        out = render(_inbox(tmp_path, "2026-08-19"))
        assert "no digest since 2026-08-19" in out
        assert "the nightly filing may be broken" in out


def test_a_never_run_inbox_does_not_cry_wolf(tmp_path):
    """spawn.py ships the template with an empty inbox and no stamp."""
    for render in (board._render_md, board._render_html):
        out = render(_inbox(tmp_path))
        assert "no run recorded yet" in out
        assert "may be broken" not in out


def test_a_populated_inbox_still_carries_the_date(tmp_path):
    snap = _inbox(tmp_path, "2026-08-25", ["2026-08-25 — One — 2608.00001"])
    assert "last digest 2026-08-25" in board._render_md(snap)
    assert "last digest 2026-08-25" in board._render_html(snap)


# --- the client-side contract -------------------------------------------------
# knowledge_board.yml republishes on pushes to arxiv-inbox.md, which is what
# stops happening when filing breaks — so the published page freezes and a
# render-time warning could never fire. The date is rendered; the verdict is
# recomputed in the browser. These tests pin the handshake between the two.
def test_the_html_hands_the_browser_what_it_needs(tmp_path):
    html = board._render_html(_inbox(tmp_path, "2026-08-25"))
    assert "data-last-digest='2026-08-25'" in html
    assert (f"data-stale-weekdays='{inbox_actions.INBOX_STALE_WEEKDAYS}'"
            in html)
    assert "{n}" in html, "the warning template must keep its placeholder"
    assert "freshness()" in html


def test_a_page_rendered_while_stale_warns_without_js(tmp_path):
    html = board._render_html(_inbox(tmp_path, "2026-08-19"))
    assert "class='meta stale fresh'" in html


def test_an_unstamped_inbox_hands_the_browser_nothing_to_check(tmp_path):
    # The attribute-with-value form: the script's own selector text mentions
    # the bare attribute name and is always present.
    assert "data-last-digest='" not in board._render_html(_inbox(tmp_path))


def test_a_reffed_paper_carries_a_one_tap_pdf_button(tmp_path):
    """The 📄 button: the PDF itself, no search and no abstract page first.

    The reason the queue wants refs at all — a phone collecting a stack of
    papers before a flight taps once per paper, not three times.
    """
    snap = _snap_with_remote(tmp_path)
    html = board.render(snap, "html")
    md = board.render(snap, "md")
    for fmt in (html, md):
        assert "https://arxiv.org/pdf/2406.01234" in fmt   # bare-id ref
        assert "https://arxiv.org/pdf/2201.00042" in fmt   # /pdf/ URL ref
        assert "https://arxiv.org/pdf/2608.00001" in fmt   # inbox paper
    # it opens away from the board, so collecting a stack does not lose the page
    assert "class='act pdf'" in html and "rel='noopener'" in html


def test_no_pdf_button_where_there_is_no_ref(tmp_path):
    """A button that cannot work is never rendered — a search is not a PDF."""
    snap = _snap_with_remote(tmp_path)
    for fmt in ("html", "md"):
        out = board.render(snap, fmt)
        # Title One / Title Three / Suggested Two are ref-less, and the
        # heading and the two annotations are not papers at all; the only PDF
        # links on the page belong to the six papers that carry a ref — four
        # in the queue and inbox, plus the current interests batch's two.
        assert out.count("arxiv.org/pdf/") == 6
    bare = {"title": "Title One", "ref": None}
    assert board.paper_pdf_url(bare) == ""
    # a non-arXiv ref is still a link, but there is no PDF to derive from it
    assert board.paper_url({"title": "T", "ref": "https://doi.org/10.1/x"}) == \
        "https://doi.org/10.1/x"
    assert board.paper_pdf_url({"title": "T", "ref": "https://doi.org/10.1/x"}) == ""


def test_headings_and_notes_render_as_themselves_not_as_papers(tmp_path):
    """A `__Bold__` grouping and a `NOTE ` annotation are structure, not work.

    Before line kinds the board rendered both as papers: a search link, three
    issue buttons and a slot in the "N waiting" count, for a line that is a
    heading or a remark.
    """
    snap = _snap_with_remote(tmp_path)
    html = board.render(snap, "html")
    md = board.render(snap, "md")

    assert "<li class='subhead'>A Sub Heading</li>" in html
    assert "- **A Sub Heading**" in md
    assert "just a remark" in html and "- _just a remark_" in md

    # neither carries a paper's buttons
    for fragment in ("A Sub Heading", "just a remark"):
        i = html.index(fragment)
        assert "class='act'" not in html[i:html.index("</li>", i)]
        assert "issues/new" not in html[i:html.index("</li>", i)]

    # and neither inflates the count: 3 papers waiting in Other Things, not 6
    other = next(q for q in snap["queue"] if q["section"] == "Other Things")
    assert other["count"] == 3
    assert "Other Things: 3 waiting" in md


def test_a_bare_link_is_a_paper_only_when_it_points_at_arxiv(tmp_path):
    snap = _snap_with_remote(tmp_path)
    html = board.render(snap, "html")
    # the arXiv one becomes a real paper, labelled by its id, with a PDF button
    assert "arXiv:2202.00099" in html
    assert "https://arxiv.org/pdf/2202.00099" in html
    # the other stays an annotation: still clickable, but no paper buttons,
    # and labelled by host rather than a wall of URL
    assert "<li class='note'><a href=\"https://example.org/not-a-paper\"" in html
    assert "example.org →" in html
    i = html.index("example.org →")
    assert "issues/new" not in html[i:html.index("</li>", i)]


# --- the arXiv interests list -------------------------------------------------
# The sibling suggestion tier. What is tested here is only what makes it
# DIFFERENT from the inbox: it is a backlog of day batches with the oldest one
# current, the 🧹 button clears that whole day, and its papers route by their
# own topic rather than to one section. The per-paper actions themselves are
# the inbox's, already covered above.
def _interests(tmp_path, lines, stamp=None):
    base = tmp_path / f"t{len(list(tmp_path.iterdir()))}"
    base.mkdir()
    root = _tree(base)
    text = "# arXiv interests\n\nintro prose\n\n---\n" + "".join(
        f"{line}\n" for line in lines)
    if stamp:
        text = inbox_actions.set_last_digest(text, stamp)
    (root / "arxiv-interests.md").write_text(text)
    (root / "arxiv-inbox.md").write_text(
        "# arXiv inbox\n\nintro prose\n\n---\n")
    snap = board.collect(root)
    snap["owner"], snap["repo"] = "PyAutoLabs", "PyAutoMemory"
    snap["generated"] = FIXTURE_NOW
    return snap


def test_only_the_oldest_batch_is_collected(tmp_path):
    snap = _snap_with_remote(tmp_path)
    assert snap["interests_date"] == "2026-08-25"
    assert [p["title"] for p in snap["interests"]] == ["Interest One",
                                                       "Interest Two"]
    assert snap["interests_batches"] == 2
    assert snap["interests_backlog"] == 3


def test_a_missing_interests_file_is_not_an_error(tmp_path):
    root = _tree(tmp_path)
    (root / "arxiv-interests.md").unlink()
    snap = board.collect(root)
    assert snap["interests"] == []
    assert snap["interests_date"] is None
    for fmt in ("md", "html", "json", "badge", "md-brief"):
        board.render({**snap, "owner": "o", "repo": "r"}, fmt)


def test_interests_papers_carry_the_same_five_actions(tmp_path):
    snap = _snap_with_remote(tmp_path)
    html = board._render_html(snap)
    for label in ("interests-add", "queue-intake", "queue-cite",
                  "interests-dismiss"):
        assert label in html, label
    assert "arxiv.org/pdf/2608.10001" in html


def test_interests_actions_name_the_interests_file(tmp_path):
    snap = _snap_with_remote(tmp_path)
    body = unquote(board._queue_issue_url(
        snap, "Demo Papers", snap["interests"][0], "add",
        source=interests_actions.INTERESTS_FILE))
    assert "file: arxiv-interests.md" in body
    assert "line: 2026-08-25 — [Demo Papers] Interest One — 2608.10001" in body


def test_interests_filing_actions_warn_there_is_no_queue_line(tmp_path):
    snap = _snap_with_remote(tmp_path)
    body = unquote(board._queue_issue_url(
        snap, "Demo Papers", snap["interests"][0], "intake",
        source=interests_actions.INTERESTS_FILE))
    assert "NOT in the reading queue yet" in body
    assert "arxiv-interests.md" in body
    assert "arxiv-inbox.md" not in body


def test_a_paper_routes_to_its_own_topic(tmp_path):
    snap = _snap_with_remote(tmp_path)
    assert snap["interests"][0]["section"] == "Demo Papers"
    body = unquote(board._queue_issue_url(
        snap, snap["interests"][0]["section"], snap["interests"][0], "add",
        source=interests_actions.INTERESTS_FILE))
    assert "section: Demo Papers" in body


def test_a_topicless_paper_falls_back_rather_than_stranding(tmp_path):
    snap = _interests(tmp_path, ["2026-08-25 — No topic here — 2608.10001"])
    assert snap["interests"][0]["section"] == interests_actions.FALLBACK_SECTION


def test_the_clear_button_names_the_batch_date(tmp_path):
    snap = _snap_with_remote(tmp_path)
    html = board._render_html(snap)
    assert "interests-clear" in html
    url = board._interests_clear_url(snap, "2026-08-25", 2)
    body = unquote(url)
    assert "file: arxiv-interests.md" in body
    assert "date: 2026-08-25" in body
    # A batch clear is not a per-paper action: it must not carry a line.
    assert "line:" not in body


def test_no_clear_button_without_a_remote(tmp_path):
    snap = board.collect(_tree(tmp_path))
    assert board._interests_clear_url(snap, "2026-08-25", 2) == ""
    assert "interests-clear" not in board.render(snap, "html")


def test_interests_render_between_the_inbox_and_the_queue(tmp_path):
    """The human asked for it under strong lensing: inbox, then this, then
    the backlog it feeds."""
    snap = _snap_with_remote(tmp_path)
    for text in (board._render_md(snap), board._render_html(snap)):
        assert text.index("arXiv inbox") < text.index("arXiv interests")
        assert text.index("arXiv interests") < text.index("Reading queue")


def test_the_backlog_depth_is_on_the_page(tmp_path):
    """A day cleared is a day revealed — the human needs to know how many are
    behind the one they are looking at."""
    snap = _snap_with_remote(tmp_path)
    assert "1 more day behind it" in board._render_html(snap)
    assert "2 days of backlog" in board._render_html(snap)
    assert "1 more day behind it" in board._render_md(snap)


def test_the_backlog_depth_survives_the_stale_banner(tmp_path):
    """A late digest is when the depth matters most. The stale text replaces
    the summary wholesale — server-side here, and client-side via
    `data-stale-text` — so it has to carry the depth too."""
    snap = _snap_with_remote(tmp_path)
    snap["interests_last_digest"] = "2026-08-14"     # stale against FIXTURE_NOW
    html = board._render_html(snap)
    assert "the nightly filing may be broken" in html
    assert html.count("1 more day behind it") == 2   # rendered + data-stale-text


def test_an_empty_interests_list_says_which_kind_of_empty(tmp_path):
    quiet = _interests(tmp_path, [], stamp="2026-08-26")
    assert "the last digest ran 2026-08-26" in board._render_md(quiet)
    never = _interests(tmp_path, [])
    assert "no run recorded yet" in board._render_md(never)


def test_the_two_tiers_carry_their_own_stamps(tmp_path):
    """One digest can break while the other keeps running; the page must not
    report the healthy one's date for the broken one."""
    snap = _snap_with_remote(tmp_path)
    snap["inbox_last_digest"] = "2026-08-25"
    snap["interests_last_digest"] = "2026-08-20"
    html = board._render_html(snap)
    assert "data-last-digest='2026-08-25'" in html
    assert "data-last-digest='2026-08-20'" in html



# --- filings awaiting merge ---------------------------------------------------
def test_a_synthetic_tree_has_no_pending_filings(tmp_path):
    """Only the live checkout asks the remote; a synthetic root never does."""
    assert board.collect(_tree(tmp_path))["filings"] == []


def test_pending_filings_are_parsed_from_ls_remote(monkeypatch):
    import types
    out = ("ab3b\trefs/heads/queue-filing/issue-91\n"
           "ad7d\trefs/heads/queue-filing/issue-72\n"
           "ffff\trefs/heads/feature/queue-filing-not-a-filing\n")
    monkeypatch.setattr(board.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout=out))
    assert board._pending_filings() == [
        {"issue": 72, "branch": "queue-filing/issue-72"},
        {"issue": 91, "branch": "queue-filing/issue-91"},
    ]


def test_a_failed_ls_remote_is_an_empty_list_not_an_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("no git here")
    monkeypatch.setattr(board.subprocess, "run", boom)
    assert board._pending_filings() == []


def test_pending_filings_render_above_the_inbox_with_a_pr_link(tmp_path):
    """A filing on a branch is not in memory: the board says so, first, and
    hands out the one tap that finishes it."""
    snap = _snap_with_remote(tmp_path)
    snap["filings"] = [{"issue": 91, "branch": "queue-filing/issue-91"}]
    for text in (board._render_md(snap), board._render_html(snap)):
        assert "Filings awaiting merge" in text
        assert "compare/main...queue-filing/issue-91?expand=1" in text
        assert "/issues/91" in text
        if '<!doctype html>' in text:
            assert text.index("id='filings'") < text.index("id='arxiv-inbox'")
        else:
            assert text.index("Filings awaiting merge") < text.index("arXiv inbox")


def test_no_filings_section_when_nothing_waits(tmp_path):
    snap = _snap_with_remote(tmp_path)
    assert snap["filings"] == []
    for text in (board._render_md(snap), board._render_html(snap)):
        assert "Filings awaiting merge" not in text


def test_pending_filings_without_a_remote_still_name_the_branch(tmp_path):
    snap = board.collect(_tree(tmp_path))
    snap["filings"] = [{"issue": 7, "branch": "queue-filing/issue-7"}]
    for text in (board._render_md(snap), board._render_html(snap)):
        assert "queue-filing/issue-7" in text
        assert "compare/main" not in text


# --- one-tap mode ---------------------------------------------------------------
def test_one_tap_mode_is_wired_only_with_a_remote(tmp_path):
    """The chip, the API's owner/repo and the toast slot all hang off the repo
    identity; a spawned template with no remote renders none of them."""
    snap = _snap_with_remote(tmp_path)
    html = board._render_html(snap)
    assert 'data-repo="PyAutoLabs/PyAutoMemory"' in html
    assert "id='onetap'" in html and 'id="toast"' in html
    snap["owner"] = snap["repo"] = ""
    bare = board._render_html(snap)
    assert "data-repo=" not in bare and "id='onetap'" not in bare


def test_one_tap_reads_the_request_back_out_of_the_link(tmp_path):
    """No second copy of the issue in the markup: the script parses title,
    body and label from the prefilled link every button already carries, so
    the workflows see exactly the issue the link would have opened."""
    html = board._render_html(_snap_with_remote(tmp_path))
    assert "searchParams.get('body')" in html
    assert "searchParams.get('labels')" in html
    assert "/^(?:line|date): (.*)$/m" in html  # the row's hide key
    assert "restoreHidden();keyChip();" in html


def test_one_tap_never_touches_the_page_without_a_token(tmp_path):
    html = board._render_html(_snap_with_remote(tmp_path))
    assert "if(!a||!token()||!repo())return;" in html


# --- the organ-cockpit feed (state.json, contract v1) ---------------------------
# The contract is owned by the Brain (board/_state.py); these tests copy its
# required-keys/enum check rather than importing it, so the Memory suite never
# depends on a sibling checkout for its own feed's shape. CI runs the real
# validator on the published file.
STATE_REQUIRED = ("schema_version", "organ", "repo", "status", "headline",
                  "updated", "pages_url", "items")
STATE_STATUSES = ("green", "yellow", "red", "stale", "grey")
STATE_SEVERITIES = ("red", "yellow", "info")


def _assert_state_shape(state):
    assert all(k in state for k in STATE_REQUIRED)
    assert state["schema_version"] == 1 and state["organ"] == "memory"
    assert state["status"] in STATE_STATUSES
    assert state["headline"].strip() and "\n" not in state["headline"]
    assert state["pages_url"].strip()
    for item in state["items"]:
        assert item["severity"] in STATE_SEVERITIES
        assert item["text"].strip() and len(item["text"]) <= 160


def _state_snap(tmp_path):
    snap = board.collect(_tree(tmp_path))
    snap["owner"], snap["repo"] = "SomeOrg", "MemRepo"
    snap["generated"] = FIXTURE_NOW
    snap["inbox_last_digest"] = snap["interests_last_digest"] = FIXTURE_NOW[:10]
    snap["lensing_ingest_evidence"] = {"last_ingested": FIXTURE_NOW[:10], "done": FIXTURE_NOW[:10], "bib": None}
    return snap


def test_state_has_the_contract_shape(tmp_path):
    state = board.to_state(_state_snap(tmp_path))
    _assert_state_shape(state)
    assert state["repo"] == "MemRepo"
    assert state["pages_url"] == "https://someorg.github.io/MemRepo/"
    assert state["updated"] == "2026-08-26T09:00:00Z"
    assert datetime.datetime.fromisoformat(state["updated"][:-1] + "+00:00")


def test_state_updated_is_whole_second_utc_z():
    # naive → read as UTC; unparseable → now, still a valid Z stamp
    assert board._iso_z("2026-08-26T09:00:00.123456") == "2026-08-26T09:00:00Z"
    assert board._iso_z("2026-08-26T10:00:00+01:00") == "2026-08-26T09:00:00Z"
    now = board._iso_z("not a date")
    assert now.endswith("Z") and datetime.datetime.fromisoformat(now[:-1])


def test_state_stubs_and_todos_become_info_rows_with_prompts(tmp_path):
    state = board.to_state(_state_snap(tmp_path))
    assert state["status"] == "yellow"
    assert state["headline"].startswith("stubs/todos waiting · ")
    assert "50% cited" in state["headline"]
    (row,) = [i for i in state["items"] if i["text"].startswith("demo:")]
    assert row["severity"] == "info" and row["text"] == "demo: 1 stub, 1 todo"
    assert row["prompt"] == board._todo_prompt(_state_snap(tmp_path / "x"),
                                               "demo")
    assert row["url"] == "https://github.com/SomeOrg/MemRepo/tree/main/wiki/demo"


def test_state_inbox_papers_are_capped_info_rows(tmp_path):
    snap = _state_snap(tmp_path)
    snap["inbox"] = [dict(snap["inbox"][0], title=f"Paper {n}")
                     for n in range(8)]
    rows = [i for i in board.to_state(snap)["items"]
            if i["text"].startswith("inbox:")]
    assert len(rows) == 5
    assert all(r["severity"] == "info" and "issues/new" in r["url"]
               for r in rows)


def test_state_is_green_with_nothing_waiting(tmp_path):
    snap = _state_snap(tmp_path)
    for w in snap["wikis"]:
        w["statuses"], w["todo"] = {"drafted": w["pages"]}, 0
    snap["inbox"] = []
    state = board.to_state(snap)
    assert state["status"] == "green" and state["items"] == []
    assert state["headline"] == board.badge_endpoint(snap)["message"]


def test_a_stale_inbox_turns_the_state_yellow(tmp_path):
    snap = _inbox(tmp_path, "2026-08-19")
    for w in snap["wikis"]:
        w["statuses"], w["todo"] = {"drafted": w["pages"]}, 0
    state = board.to_state(snap)
    _assert_state_shape(state)
    assert state["status"] == "yellow"
    assert state["headline"].startswith("arXiv inbox digest stale")
    assert state["items"][0]["severity"] == "yellow"
    assert "no digest since 2026-08-19" in state["items"][0]["reason"]


def test_pending_filings_turn_the_state_yellow(tmp_path):
    snap = _state_snap(tmp_path)
    snap["filings"] = [{"issue": 7, "branch": "queue-filing/issue-7"}]
    state = board.to_state(snap)
    assert state["status"] == "yellow"
    assert state["items"][0]["url"].endswith(
        "/compare/main...queue-filing/issue-7?expand=1")


def test_an_empty_tree_is_grey_never_green(tmp_path):
    (tmp_path / "wiki").mkdir()
    state = board.to_state(board.collect(tmp_path))
    _assert_state_shape(state)
    assert state["status"] == "grey" and state["items"] == []
    # no remote: the feed still names a page — the board beside it
    assert state["pages_url"] == "./"


def test_render_state_is_valid_json(tmp_path):
    state = json.loads(board.render(_state_snap(tmp_path), "state"))
    _assert_state_shape(state)


# --- the catch-up banner -------------------------------------------------------------
# Legacy all-scope activity and scoped lensing evidence stay distinct; each test
# below pins both it and the snapshot's own clock, so no wall clock is read.
def _banner_snap(tmp_path, last, now="2026-09-30T09:00:00+00:00"):
    snap = _state_snap(tmp_path)
    snap["last_ingested"], snap["generated"] = last, now
    snap["lensing_ingest_evidence"] = {"last_ingested": last, "done": last, "bib": None}
    return snap


def test_last_ingested_is_collected_from_a_scope_section(tmp_path):
    root = _tree(tmp_path)
    # `_tree`'s DONE sits in "Demo Papers", which no catch-up scope owns.
    assert board.collect(root)["last_ingested"] is None
    q = root / "reading-queue.md"
    q.write_text(q.read_text() + "\n## Strong Lensing\nDONE 2026-09-01 — X\n")
    assert board.collect(root)["last_ingested"] == "2026-09-01"


def test_no_banner_under_the_threshold(tmp_path):
    snap = _banner_snap(tmp_path, "2026-09-24")  # 6 days
    assert board._days_since_ingest(snap) == 6
    assert "lost for a while" not in board.render(snap, "md")
    assert "class='catchup'" not in board.render(snap, "html")
    assert board.to_state(snap)["days_since_ingest"] == 6


def test_banner_at_the_threshold_carries_the_day_count(tmp_path):
    snap = _banner_snap(tmp_path, "2026-09-23")  # exactly CATCH_UP_DAYS
    assert board.CATCH_UP_DAYS == 7
    md = board.render(snap, "md")
    assert "**Strong-lensing catch-up due**" in md
    assert "2026-09-23 (7 days ago)" in md
    assert "after 7 days" in md
    assert "`Read PyAutoMemory/skills/catch_up/SKILL.md and follow the catch_up skill with arguments: lensing.`" in md
    # Top of the markdown: before the contents line.
    assert md.index("Strong-lensing catch-up due") < md.index("_Contents")


def test_catchup_html_follows_banner_and_navigation_with_a_copy_button(tmp_path):
    snap = _banner_snap(tmp_path, "2026-09-11")
    page = board.render(snap, "html")
    assert "<em>…so… I&#x27;ve been lost for a while</em>" in page
    assert "2026-09-11 (19 days ago)" in page
    assert 'data-cmd="Read PyAutoMemory/skills/catch_up/SKILL.md and follow the catch_up skill with arguments: lensing."' in page
    assert page.index('class="hero"') < page.index('class="board-nav"') < page.index("class='catchup'")
    assert board.to_state(snap)["days_since_ingest"] == 19


def test_unknown_banner_when_nothing_is_on_record(tmp_path):
    snap = _banner_snap(tmp_path, None)
    assert board._days_since_ingest(snap) is None
    assert "lost for a while" not in board.render(snap, "md")
    assert "Strong-lensing freshness unknown" in board.render(snap, "html")
    assert board.to_state(snap)["days_since_ingest"] is None


@pytest.mark.parametrize("age,expected", [(6, "healthy"), (7, "stale"), (8, "stale")])
def test_lensing_catch_up_threshold_has_one_model_for_every_surface(tmp_path, age, expected):
    cutoff = (datetime.date(2026, 9, 30) - datetime.timedelta(days=age)).isoformat()
    snap = _banner_snap(tmp_path, cutoff)
    model = board._lensing_catch_up(snap)
    state = board.to_state(snap)
    assert state["lensing_catch_up"] == model
    assert model["state"] == expected and model["threshold_days"] == 7
    assert model["age_days"] == age
    rows = [i for i in state["items"] if i.get("id") == model["id"]]
    if expected == "healthy":
        assert not rows
    else:
        assert len(rows) == 1 and rows[0]["reason"] == model["reason"]
        assert model["reason"] in board.render(snap, "md")
        assert model["reason"] in board.render(snap, "html")
        assert rows[0]["actions"][0]["target"] == "Read PyAutoMemory/skills/catch_up/SKILL.md and follow the catch_up skill with arguments: lensing."
        assert rows[0]["actions"][0]["safety"] == "scientific_judgement"
        assert "requires_human_decision" not in rows[0]  # No invented choice.


def test_non_lensing_activity_cannot_mask_lensing_staleness(tmp_path):
    root = _tree(tmp_path)
    q = root / "reading-queue.md"
    q.write_text(q.read_text() + "\n## Strong Lensing\nDONE 2026-09-01 — Lens\n\n## SMBHs\nDONE 2026-09-30 — BH\n")
    snap = board.collect(root)
    snap["generated"] = "2026-09-30T09:00:00Z"
    assert snap["last_ingested"] == "2026-09-30"  # Legacy all-scope field.
    assert board._lensing_catch_up(snap)["last_activity"] == "2026-09-01"
    assert board._lensing_catch_up(snap)["state"] == "stale"


def test_read_completion_is_not_misreported_as_verified_ingestion(tmp_path):
    snap = _banner_snap(tmp_path, "2026-09-23")
    model = board._lensing_catch_up(snap)
    assert model["last_ingestion"] is None
    assert model["last_completed"] == "2026-09-23"
    snap["lensing_ingest_evidence"]["bib"] = {"date": "2026-09-21", "commit": "abc123"}
    model = board._lensing_catch_up(snap)
    assert model["last_ingestion"] == {"date": "2026-09-21", "commit": "abc123"}
    assert model["last_activity"] == "2026-09-23"
    assert any(e["url"].endswith("/commit/abc123") for e in model["evidence"])
    assert any("reading-queue.md#strong-lensing" in e["url"] for e in model["evidence"])


@pytest.mark.parametrize("last", [None, "invalid", "2026-10-02"])
def test_missing_invalid_and_future_activity_is_unknown(tmp_path, last):
    snap = _banner_snap(tmp_path, last)
    model = board._lensing_catch_up(snap)
    assert model["state"] == "unknown" and model["age_days"] is None
    row = next(i for i in board.to_state(snap)["items"] if i.get("id") == model["id"])
    assert row["state"] == "unknown"
    assert "freshness unknown" in row["text"]


def test_invalid_snapshot_clock_is_unknown(tmp_path):
    model = board._lensing_catch_up(_banner_snap(tmp_path, "2026-09-23", "invalid"))
    assert model["state"] == "unknown" and model["checked_at"] is None


def test_unknown_collector_evidence_does_not_fall_back_to_other_topics(tmp_path, monkeypatch):
    def failed(*args, **kwargs):
        raise OSError("unavailable")
    monkeypatch.setattr(board.catch_up, "ingest_evidence", failed)
    snap = board.collect(_tree(tmp_path))
    snap["last_ingested"] = "2026-09-30"
    snap["generated"] = "2026-09-30T09:00:00Z"
    assert board._lensing_catch_up(snap)["state"] == "unknown"


def test_cutoff_requires_matching_scoped_evidence(tmp_path):
    snap = _banner_snap(tmp_path, "2026-09-29")
    snap["lensing_ingest_evidence"]["done"] = "2026-09-01"
    assert board._lensing_catch_up(snap)["state"] == "unknown"
    snap["lensing_ingest_evidence"]["done"] = None
    assert board._lensing_catch_up(snap)["state"] == "unknown"


@pytest.mark.parametrize('today,age,state', [
    ('2026-08-21', 0, 'healthy'), ('2026-08-23', 0, 'healthy'),
    ('2026-08-24', 1, 'healthy'), ('2026-08-25', 2, 'stale'),
])
def test_digest_weekday_boundary(tmp_path, today, age, state):
    snap = _state_snap(tmp_path)
    snap.update(generated=today + 'T09:00:00Z', inbox_last_digest='2026-08-21')
    fresh = board._inbox_freshness(snap)
    assert (fresh['weekdays'], fresh['state']) == (age, state)
    assert fresh['threshold_weekdays'] == 2
    assert fresh['last_recorded'] == '2026-08-21'


@pytest.mark.parametrize('stamp', [None, '', 'bad', '2026-02-30',
                                  '2026-08-27', '20260826', 123])
def test_untrustworthy_digest_stamp_is_unknown(tmp_path, stamp):
    snap = _state_snap(tmp_path)
    snap['inbox_last_digest'] = stamp
    fresh = board.to_state(snap)['digests']['lensing']
    assert fresh['state'] == 'unknown'
    assert fresh['last_recorded'] is None and fresh['weekdays'] is None
    row = next(r for r in board.to_state(snap)['items']
               if r.get('id') == 'memory:digest:lensing')
    assert row['state'] == 'unknown' and row['reason'] == fresh['reason']
    assert "data-last-digest='bad'" not in board._render_html(snap)
    assert fresh['reason'] in board._render_md(snap)


@pytest.mark.parametrize('clock', [None, 'bad', '2026-08-26T09:00:00'])
def test_digest_requires_a_valid_observation_time(tmp_path, clock):
    snap = _state_snap(tmp_path)
    snap['generated'] = clock
    fresh = board._inbox_freshness(snap)
    assert fresh['state'] == 'unknown' and fresh['checked_at'] is None


def test_digest_scopes_share_feed_evidence_and_explicit_actions(tmp_path):
    snap = _state_snap(tmp_path)
    snap['inbox_last_digest'] = '2026-08-21'
    state = board.to_state(snap)
    assert state['digests']['interests']['state'] == 'healthy'
    assert state['digests']['lensing']['state'] == 'stale'
    rows = [r for r in state['items'] if r.get('id', '').startswith('memory:digest:')]
    assert len(rows) == 1
    row = rows[0]
    fresh = state['digests']['lensing']
    assert fresh == board._inbox_freshness(snap)
    assert row['actions'] == fresh['actions']
    assert row['recommended_action_id'] == 'inspect-workflow'
    assert fresh['workflow_url'].endswith('/PyAutoMind/actions/workflows/arxiv_papers.yml')
    assert fresh['evidence_url'].endswith('/MemRepo/blob/main/arxiv-inbox.md')
    assert state['digests']['interests']['workflow_url'].endswith('/arxiv_interests.yml')
    assert state['digests']['interests']['evidence_url'].endswith('/arxiv-interests.md')
    assert all(a['safety'] == ('read_only' if a['kind'] == 'link' else 'requires_approval')
               for a in row['actions'])
    assert row['prompt'].startswith('Use the bug skill. investigate')


def test_quiet_digest_and_backlog_have_same_freshness(tmp_path):
    snap = _state_snap(tmp_path)
    populated = board.to_state(snap)['digests']
    snap['inbox'], snap['interests'] = [], []
    assert board.to_state(snap)['digests'] == populated
    assert all(f['state'] == 'healthy' for f in populated.values())
    assert not any(r.get('id', '').startswith('memory:digest:')
                   for r in board.to_state(snap)['items'])


def test_digest_without_remote_offers_manual_investigation(tmp_path):
    snap = _state_snap(tmp_path)
    snap['owner'], snap['repo'] = None, None
    fresh = board._inbox_freshness(snap)
    assert fresh['workflow_url'] is None and fresh['evidence_url'] is None
    assert [a['id'] for a in fresh['actions']] == ['investigate']
    assert fresh['recommended_action_id'] == 'investigate'


def test_invalid_digest_is_escaped_and_never_given_to_browser_clock(tmp_path):
    snap = _state_snap(tmp_path)
    snap['inbox_last_digest'] = '<script>oops</script>'
    html = board._render_html(snap)
    assert '<script>oops</script>' not in html
    assert 'digest date is invalid or in the future' in html
    assert "data-last-digest='<" not in html


def test_orchestration_preview_targets_memory_and_preserves_paper_actions(tmp_path):
    import html as html_module

    snap = {**_snap_with_remote(tmp_path), "owner": "SomeOrg", "repo": "MemoryWork"}
    page = board.render(snap, "html")
    preview = re.search(r'<textarea id="orchestration-memory-prompt"[^>]*>(.*?)</textarea>',
                        page, re.S).group(1)
    assert html_module.unescape(preview) == (
        board.CHECKIN_PROMPT + "\n\nWork on GitHub:\n"
        "- MemoryWork: https://github.com/SomeOrg/MemoryWork")
    assert page.index('class="hero"') < page.index('id="orchestration-memory"')
    assert page.index('id="orchestration-memory"') < page.index('id="catch-up"')
    assert board.theme().prompt_heading("memory", heading_id="orchestration-memory-heading") in page
    assert 'data-repo="SomeOrg/MemoryWork"' in page
    assert board._EXTRA_JS in page
    assert "https://github.com/SomeOrg/MemoryWork/issues/new?" in page
    assert 'data-orchestration-copy' in page


def test_orchestration_without_memory_remote_is_explicit(tmp_path):
    snap = {**_snap_with_remote(tmp_path), "owner": None, "repo": None}
    page = board.render(snap, "html")
    assert "Work repository unavailable in this snapshot." in page
    assert "https://github.com/None/None" not in page


def test_panel_refresh_uses_capture_not_ingest_date(tmp_path, monkeypatch):
    theme = board.theme()
    calls = []
    monkeypatch.setattr(theme, "orchestration_panel", lambda *a, **kw: calls.append(kw) or "")
    snap = {**_snap_with_remote(tmp_path), "owner": "SomeOrg", "repo": "MemoryWork"}
    board.render(snap, "html")
    assert calls[0]["refreshed_at"] == snap["generated"]
    assert calls[0]["refresh_url"] == "https://github.com/SomeOrg/MemoryWork/actions/workflows/knowledge_board.yml"
