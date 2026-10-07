"""tests/test_catch_up.py — the catch-up harvest (scripts/catch_up.py).

The contract: the cutoff is the newest *real* ingest (a DONE line, or a commit
that adds a bib entry AND touches the scope's sources — never either half
alone); swept suggestion lines come back from git history; whatever memory
already holds (bib id/title, DONE line) is dropped; and the arXiv source is
best-effort — stubbed here, so the suite never touches the network.
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import catch_up  # noqa: E402

QUEUE = """# Reading queue

---

## Strong Lensing
DONE 2026-09-05 — An Old Filed Paper — 2608.00001
__Sub heading__
NOTE a remark, not a paper
An Open Queue Paper — 2609.00010
A Queue Paper Already In The Bib — 2608.27566
A Queue Paper Without A Ref

## SMBHs
DONE 2026-09-20 — A Black Hole Paper — 2609.00020
Open SMBH Paper — 2609.00021
"""

BIB = """@article{Williams2026,
  eprint = {2608.27566},
  title = {{TDCOSMO. XXVII. Something}},
}
@misc{Titled2026,
  title = {{A Paper Known Only By {T}itle}},
}
"""

INBOX_HEAD = "# arXiv inbox\n\n---\nlast digest: {d}\n"


def _git(root: Path, *args: str, date: str | None = None) -> None:
    env = None
    if date:
        import os
        env = {**os.environ, "GIT_AUTHOR_DATE": f"{date}T12:00:00",
               "GIT_COMMITTER_DATE": f"{date}T12:00:00"}
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t",
                    "-c", "user.email=t@t", *args],
                   check=True, capture_output=True, env=env)


def _commit(root: Path, files: dict, msg: str, date: str) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg, date=date)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "mem"
    root.mkdir()
    _git(root, "init", "-q")
    _commit(root, {"reading-queue.md": QUEUE, catch_up.BIB_FILE: BIB,
                   "wiki/lensing/sources/a.md": "a\n",
                   "arxiv-inbox.md": INBOX_HEAD.format(d="2026-09-01")
                   + "2026-09-01 — A Pre-Cutoff Inbox Paper — 2608.99999\n"},
            "seed", "2026-09-01")
    # A real ingest: bib entry + sources page, together.
    _commit(root, {catch_up.BIB_FILE: BIB + "@misc{New2026,\n  eprint = {2609.00005},\n}\n",
                   "wiki/lensing/sources/a.md": "a\nb\n"},
            "queue: file paper", "2026-09-11")
    # Inbox lines that were later swept — only git remembers them.
    _commit(root, {"arxiv-inbox.md": INBOX_HEAD.format(d="2026-09-12")
                   + "2026-09-12 — A Swept Inbox Paper — 2609.11111\n"
                   + "2026-09-12 — An Open Queue Paper — 2609.00010\n"},
            "inbox: appended", "2026-09-12")
    _commit(root, {"arxiv-inbox.md": INBOX_HEAD.format(d="2026-09-20")},
            "inbox: swept", "2026-09-20")
    # A restructure: touches sources, adds no entry. Must NOT move the cutoff.
    _commit(root, {"wiki/lensing/sources/a.md": "a\nb\nc\n"},
            "seed split", "2026-09-17")
    # A bib tidy-up: adds an entry, touches no sources. Must NOT either.
    _commit(root, {catch_up.BIB_FILE: BIB + "@misc{New2026,\n  eprint = {2609.00005},\n}\n"
                   "@misc{Tidy2026,\n  eprint = {2609.00006},\n}\n"},
            "bib tidy", "2026-09-18")
    return root


# --- cutoff ------------------------------------------------------------------------
def test_cutoff_is_the_bib_plus_sources_commit_not_either_half(tmp_path):
    root = _repo(tmp_path)
    ev = catch_up.ingest_evidence("lensing", root)
    assert ev["done"] == "2026-09-05"
    assert ev["bib"]["date"] == "2026-09-11"
    assert ev["last_ingested"] == "2026-09-11"


def test_cutoff_reads_the_scope_sections_only(tmp_path):
    root = _repo(tmp_path)
    # The SMBHs DONE (09-20) is newer but belongs to the interests scope.
    assert catch_up.last_ingested("lensing", root) == "2026-09-11"
    assert catch_up.last_ingested("interests", root) == "2026-09-20"
    assert catch_up.last_ingested("all", root) == "2026-09-20"


def test_no_git_falls_back_to_done_lines(tmp_path):
    (tmp_path / "reading-queue.md").write_text(QUEUE)
    assert catch_up.last_ingested("lensing", tmp_path) == "2026-09-05"


def test_nothing_on_record_is_none(tmp_path):
    assert catch_up.last_ingested("all", tmp_path) is None


def test_parse_ingest_log_takes_the_max_date_not_the_first():
    log = ("\x002026-09-10 aaa\ndiff --git a/bibliography/pyautomemory.bib "
           "b/bibliography/pyautomemory.bib\n+@misc{A,\ndiff --git "
           "a/wiki/lensing/sources/x.md b/wiki/lensing/sources/x.md\n"
           "\x002026-09-11 bbb\ndiff --git a/bibliography/pyautomemory.bib "
           "b/bibliography/pyautomemory.bib\n+@misc{B,\ndiff --git "
           "a/wiki/lensing/sources/y.md b/wiki/lensing/sources/y.md\n")
    assert catch_up.parse_ingest_log(log, ("lensing",)) == {
        "date": "2026-09-11", "commit": "bbb"}
    assert catch_up.parse_ingest_log(log, ("smbh",)) is None


def test_topic_narrows_and_lensing_refuses_one():
    spec = catch_up.resolve_scope("interests", "SMBHs")
    assert spec["sections"] == ("SMBHs",) and spec["domains"] == ("smbh",)
    for bad in (("lensing", "SMBHs"), ("interests", "Cancer"), ("nope", None)):
        try:
            catch_up.resolve_scope(*bad)
        except ValueError:
            continue
        raise AssertionError(bad)


# --- harvests ---------------------------------------------------------------------------
def test_history_lines_parse_and_respect_the_cutoff():
    log = ("+2026-09-12 — A Swept Paper — 2609.11111\n"
           "-2026-09-13 — A Removed Line Is Not An Addition — 2609.22222\n"
           "+2026-09-01 — Too Old — 2608.99999\n"
           "+++ b/arxiv-inbox.md\n+last digest: 2026-09-12\n")
    got = catch_up.parse_history(log, "arxiv-inbox.md", "2026-09-11")
    assert [(h["id"], h["date"]) for h in got] == [("2609.11111", "2026-09-12")]


def test_interests_history_carries_and_filters_by_topic():
    log = ("+2026-09-12 — [SMBHs] A Black Hole — 2609.1\n"
           "+2026-09-12 — [Stats] A Sampler — 2609.00002\n"
           "+2026-09-12 — Untagged Goes To Interests — 2609.00003\n")
    got = catch_up.parse_history(log, "arxiv-interests.md", "2026-09-01", "Stats")
    assert [h["title"] for h in got] == ["A Sampler"]
    got = catch_up.parse_history(log, "arxiv-interests.md", "2026-09-01", "Interests")
    assert [h["topic"] for h in got] == [None]


def test_queue_harvest_skips_done_notes_and_subheads():
    got = catch_up.harvest_queue(QUEUE, ("Strong Lensing",))
    assert [h["title"] for h in got] == [
        "An Open Queue Paper", "A Queue Paper Already In The Bib",
        "A Queue Paper Without A Ref"]


# --- dedup ---------------------------------------------------------------------------------
def test_in_memory_index_reads_bib_ids_titles_and_done_lines():
    ids, titles = catch_up.in_memory_index(BIB, QUEUE)
    assert {"2608.27566", "2608.00001", "2609.00020"} <= ids
    assert catch_up.norm_title("A paper known only by title") in titles
    assert catch_up.norm_title("An Old Filed Paper") in titles


def test_merge_dedups_across_sources_and_drops_what_memory_holds():
    harvests = [
        {"id": "2609.00010", "title": "An Open Queue Paper", "source": "queue"},
        {"id": "2609.00010", "title": "An Open Queue Paper", "source": "history",
         "date": "2026-09-12"},
        {"id": "2609.00010", "title": "An Open Queue Paper", "source": "arxiv",
         "abstract": "We lens.", "authors": ["Ada"]},
        {"id": None, "title": "A paper known only by TITLE", "source": "history"},
        {"id": "2608.27566", "title": "Whatever", "source": "arxiv"},
        {"id": None, "title": "No Ref Here", "source": "queue"},
        {"id": "2609.33333", "title": "no ref here", "source": "arxiv"},
    ]
    ids, titles = catch_up.in_memory_index(BIB, QUEUE)
    got, dropped = catch_up.merge(harvests, ids, titles)
    assert dropped == 2
    by_title = {c["title"]: c for c in got}
    first = by_title["An Open Queue Paper"]
    assert first["source"] == "queue"
    assert first["also_in"] == ["history", "arxiv"]
    assert first["abstract"] == "We lens." and first["first_author"] == "Ada"
    assert first["date"] == "2026-09-12"
    # An id-less queue line meets its arXiv twin through the title.
    assert by_title["No Ref Here"]["id"] == "2609.33333"
    assert len(got) == 2


# --- the whole run, arXiv stubbed -------------------------------------------------------------
class _StubFetch:
    QUERY = "cat:astro-ph.CO"

    def __init__(self):
        self.queries = []

    def fetch(self, query, max_results, start=0):
        self.queries.append(query)
        return b"<feed><entry>stub</entry></feed>"

    def parse(self, raw, band_start, band_end):
        self.band = (band_start, band_end)
        return [{"title": "A Gap Paper The Digest Never Fetched",
                 "authors": ["Grace"], "abstract": "Missed.",
                 "url": "https://arxiv.org/abs/2609.20000v1",
                 "primary_category": "astro-ph.CO",
                 "published": "2026-09-19T10:00:00Z"},
                {"title": "Already filed", "authors": [], "abstract": "",
                 "url": "https://arxiv.org/abs/2609.00005v1",
                 "published": "2026-09-10T10:00:00Z"}]

    def _get(self, params):
        return b"<feed></feed>"


def test_catch_up_end_to_end_with_arxiv_stubbed(tmp_path):
    root = _repo(tmp_path)
    stub = _StubFetch()
    report = catch_up.catch_up("lensing", today=datetime.date(2026, 9, 30),
                               root=root, digests={"arxiv_fetch": stub},
                               pause=0)
    assert report["cutoff"] == "2026-09-11" and report["days_lost"] == 19
    assert "submittedDate:[202609080000 TO 202609302359]" in stub.queries[0]
    ids = {c["id"]: c for c in report["candidates"]}
    assert ids["2609.11111"]["source"] == "history"      # swept, back from git
    assert ids["2609.00010"]["source"] == "queue"
    assert ids["2609.20000"]["source"] == "arxiv"        # the gap fill
    assert ids["2609.20000"]["first_author"] == "Grace"
    assert "2609.00005" not in ids                       # already in the bib
    assert "2608.27566" not in ids
    assert "2608.99999" not in ids                       # before the cutoff
    assert report["warnings"] == []


def test_arxiv_failure_is_a_warning_not_a_crash(tmp_path):
    root = _repo(tmp_path)

    class Boom(_StubFetch):
        def fetch(self, *a, **k):
            raise OSError("HTTP 429")

    report = catch_up.catch_up("lensing", today=datetime.date(2026, 9, 30),
                               root=root, digests={"arxiv_fetch": Boom()},
                               pause=0)
    assert any("429" in w for w in report["warnings"])
    assert report["counts"]["history"] and report["counts"]["arxiv"] == 0


def test_since_overrides_and_offline_skips_the_network(tmp_path):
    root = _repo(tmp_path)
    report = catch_up.catch_up("lensing", since="2026-08-01",
                               today=datetime.date(2026, 9, 30), root=root,
                               offline=True)
    assert report["cutoff_from"] == "--since"
    assert report["arxiv_window"] is None
    assert "2608.99999" in {c["id"] for c in report["candidates"]}


def test_missing_mind_is_a_warning(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(catch_up, "mind_scripts_dir", lambda root=None: None)
    report = catch_up.catch_up("lensing", today=datetime.date(2026, 9, 30),
                               root=root)
    assert any("PyAutoMind not found" in w for w in report["warnings"])


def test_text_render_groups_by_source(tmp_path):
    root = _repo(tmp_path)
    report = catch_up.catch_up("lensing", today=datetime.date(2026, 9, 30),
                               root=root, offline=True)
    text = catch_up.render_text(report)
    assert "cutoff 2026-09-11" in text and "19 days lost" in text
    assert text.index("## queue") < text.index("## history")
