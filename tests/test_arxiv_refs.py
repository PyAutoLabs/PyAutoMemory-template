"""tests/test_arxiv_refs.py — the arXiv ref grammar and the queue backfill.

Two contracts. ``arxiv_refs``: every ref shape the queue has ever carried
normalises to one id, from which the abstract page and the PDF follow, and a
non-arXiv ref yields neither. ``backfill_arxiv_refs``: it only ever touches
lines the board renders as ref-less papers, and it only writes an id when
exactly one arXiv title matches — the guard that keeps a wrong id out of the
queue. Neither test touches the network: the resolver's HTTP call is injected.
"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import arxiv_refs  # noqa: E402
import backfill_arxiv_refs as backfill  # noqa: E402


def _atom(*papers) -> bytes:
    entries = "".join(
        f"<entry><id>http://arxiv.org/abs/{i}v1</id><title>{t}</title></entry>"
        for i, t in papers)
    return (f"<feed xmlns='http://www.w3.org/2005/Atom'>{entries}"
            f"</feed>").encode()


# --- the grammar --------------------------------------------------------------
def test_every_ref_shape_normalises_to_one_id():
    for ref in ("2103.16254", "arXiv:2103.16254", "2103.16254v3",
                "https://arxiv.org/abs/2103.16254",
                "https://arxiv.org/pdf/2103.16254.pdf",
                "https://arxiv.org/pdf/2103.16254v2",
                "http://www.arxiv.org/abs/2103.16254"):
        assert arxiv_refs.arxiv_id(ref) == "2103.16254", ref


def test_pre_2007_identifiers_still_resolve():
    assert arxiv_refs.arxiv_id("astro-ph/0601001") == "astro-ph/0601001"
    assert arxiv_refs.abs_url("https://arxiv.org/abs/astro-ph/0601001") == (
        "https://arxiv.org/abs/astro-ph/0601001")


def test_a_non_arxiv_ref_has_no_derivable_urls():
    for ref in ("https://doi.org/10.1093/mnras/stab123",
                "https://example.org/papers/thesis.pdf", "", None):
        assert arxiv_refs.arxiv_id(ref) is None
        assert arxiv_refs.abs_url(ref) is None
        assert arxiv_refs.pdf_url(ref) is None


def test_abs_and_pdf_are_siblings_of_the_same_id():
    assert arxiv_refs.abs_url("arXiv:2608.23534") == \
        "https://arxiv.org/abs/2608.23534"
    # extensionless: phones open it in the built-in viewer
    assert arxiv_refs.pdf_url("arXiv:2608.23534") == \
        "https://arxiv.org/pdf/2608.23534"


def test_search_url_escapes_the_title():
    url = arxiv_refs.search_url("A Title: with / punctuation")
    assert url.startswith(arxiv_refs.SEARCH_BASE)
    assert " " not in url and "/" not in url.removeprefix(arxiv_refs.SEARCH_BASE)


# --- title matching -----------------------------------------------------------
def test_normalise_title_ignores_the_disagreements_that_are_not_about_identity():
    same = ["VENUS: A Strongly Lensed Clumpy Galaxy at $z=2.48$",
            "VENUS - A Strongly Lensed Clumpy Galaxy at z = 2.48",
            "VENUS:  a strongly  lensed clumpy galaxy at z=2.48"]
    assert len({arxiv_refs.normalise_title(t) for t in same}) == 1


def test_latex_source_and_rendered_glyphs_reduce_to_the_same_title():
    """arXiv carries the LaTeX; a pasted line carries the rendered glyphs.

    Every pair below is one paper written two ways, and every pair failed to
    match before maths was erased rather than punctuated away.
    """
    for latex, rendered in [
            (r"$0.5\leq z<1.0$",                    "0.5≤z<1.0"),
            (r"$\Lambda$CDM Model",                 "ΛCDM Model"),
            (r"the local $M_{\rm BH}-M_\star$ relation",
             "the local MBH-M⋆ relation"),
            (r"$2.2\times10^{-21}$eV",              "2.2×10−21eV"),
            (r"galaxies at $z\sim3$",               "galaxies at z∼3"),
            (r"SLICE -- Combining X-ray in AC\,114", "SLICE - Combining X-ray in AC 114")]:
        assert arxiv_refs.normalise_title(latex) == \
            arxiv_refs.normalise_title(rendered), latex


def test_accented_latin_survives_but_greek_does_not():
    """NFKD splits the accent off a Latin letter, so the ASCII base remains."""
    assert arxiv_refs.normalise_title("Ekström") == "ekstrom"
    assert arxiv_refs.normalise_title("Muñoz-Darias") == "munozdarias"
    # Greek has no ASCII base and is erased on both sides alike
    assert arxiv_refs.normalise_title("ΛCDM") == arxiv_refs.normalise_title(r"$\Lambda$CDM")


def test_erasing_maths_still_keeps_different_papers_apart():
    """The reduction is lossier — it must not collapse unrelated titles."""
    a = arxiv_refs.normalise_title(r"Dark matter at $z\sim3$ in dwarf galaxies")
    b = arxiv_refs.normalise_title(r"Dark energy at $z\sim3$ in dwarf galaxies")
    assert a != b


def test_a_match_needs_exactly_one_arxiv_paper():
    entries = arxiv_refs.parse_api_entries(
        _atom(("2608.00001", "The Koi Pond"), ("2608.00002", "Another Paper")))
    assert arxiv_refs.match_entries("The Koi Pond", entries) == "2608.00001"
    # near-misses never match: a wrong id is worse than a search box
    assert arxiv_refs.match_entries("The Koi Ponds", entries) is None
    # two papers with the same title → a human decides, not this code
    ambiguous = arxiv_refs.parse_api_entries(
        _atom(("2608.00003", "Shared Title"), ("2608.00004", "Shared  title")))
    assert arxiv_refs.match_entries("Shared Title", ambiguous) is None


def test_the_query_drops_maths_instead_of_mangling_it():
    """The bug this fixes: maths was flattened into the phrase search.

    `…galaxies at 0.5≤z<1.0` went out as `ti:"…galaxies at 0 5 z 1 0"`, which
    matches nothing arXiv indexes — so no candidates came back and the exact
    matcher had nothing to work on.
    """
    assert arxiv_refs.query_phrase(
        "Photometric properties of classical bulge and pseudo-bulge "
        "galaxies at 0.5≤z<1.0") == (
        "Photometric properties of classical bulge and pseudo bulge "
        "galaxies at")
    assert arxiv_refs.query_phrase(
        "Dwarf galaxies imply dark matter is heavier than 2.2×10−21eV") == \
        "Dwarf galaxies imply dark matter is heavier than"
    # Greek is not a word character to arXiv's index either — before, `Λ` went
    # into the query string literally
    assert "Λ" not in arxiv_refs.query_phrase(
        "Review of solutions to the Cusp-core problem of the ΛCDM Model")


def test_the_query_takes_the_longest_clean_run_wherever_it_falls():
    # maths in the middle: the longer side wins, not merely the leading one
    assert arxiv_refs.query_phrase("A z=3 study of the formation of dwarf "
                                   "galaxies in clusters") == \
        "study of the formation of dwarf galaxies in clusters"


def test_a_title_with_no_usable_run_still_sends_something():
    """Better a mangled query than no query: `match_entries` is the safety net."""
    phrase = arxiv_refs.query_phrase("M87 z=6 3C273")
    assert phrase and len(phrase.split()) >= 1


def test_resolve_title_searches_on_the_phrase_not_the_raw_title():
    sent = {}

    def fake(params):
        sent.update(params)
        return _atom(("2401.00001", "Dwarf galaxies imply dark matter is "
                                    r"heavier than $2.2\times10^{-21}$eV"))

    got = arxiv_refs.resolve_title(
        "Dwarf galaxies imply dark matter is heavier than 2.2×10−21eV",
        query=fake)
    # the phrase went out clean...
    assert sent["search_query"] == \
        'ti:"Dwarf galaxies imply dark matter is heavier than"'
    # ...and the full title still had to match exactly to be accepted
    assert got == "2401.00001"


def test_a_broader_query_does_not_mean_a_looser_match():
    """The phrase only chooses candidates; the title check is unchanged."""
    def fake(params):
        return _atom(("2401.00002", "Dwarf galaxies imply dark matter is "
                                    "heavier than something else entirely"))

    assert arxiv_refs.resolve_title(
        "Dwarf galaxies imply dark matter is heavier than 2.2×10−21eV",
        query=fake) is None


def test_resolve_title_is_injectable_and_reports_a_dead_api():
    calls = []

    def fake(params):
        calls.append(params)
        return _atom(("2608.12345", "A Lensed Quasar Survey"))

    assert arxiv_refs.resolve_title("A Lensed Quasar Survey", query=fake) == \
        "2608.12345"
    assert "ti:" in calls[0]["search_query"]

    def dead(params):
        raise OSError("arxiv is down")

    with pytest.raises(arxiv_refs.ArxivAPIError):
        arxiv_refs.resolve_title("Anything", query=dead)


def test_api_query_falls_back_to_curl_on_urllib_406(monkeypatch):
    def rejected(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://export.arxiv.org/api/query", 406, "edge refusal", {}, None
        )

    seen = []
    monkeypatch.setattr(arxiv_refs.urllib.request, "urlopen", rejected)
    monkeypatch.setattr(
        arxiv_refs, "_curl_get",
        lambda url: seen.append(url) or b"<feed/>",
    )

    assert arxiv_refs._api_query({"search_query": "all:test"}, delays=()) == b"<feed/>"
    assert len(seen) == 1


# --- the backfill -------------------------------------------------------------
QUEUE = ("# Reading queue\n\nprose that is not a paper\n\n---\n\n"
         "## Strong Lensing\n"
         "Bare Title\n"
         "Already Reffed — 2406.01234\n"
         "DONE 2026-06-01 — Old Title\n"
         "\n## Methods\n"
         "Another Bare Title\n")
INBOX = ("# arXiv inbox\n\nprose\n\n---\nlast digest: 2026-08-25\n"
         "2026-08-25 — Inbox Bare Title\n"
         "2026-08-25 — Inbox Reffed — 2608.00001\n")


def test_candidates_are_only_the_ref_less_unread_papers():
    got = backfill.candidates(QUEUE, "reading-queue.md")
    assert [t for _, t in got] == ["Bare Title", "Another Bare Title"]
    assert [t for _, t in backfill.candidates(INBOX, "arxiv-inbox.md")] == \
        ["Inbox Bare Title"]


def _tree(tmp_path: Path) -> Path:
    (tmp_path / "reading-queue.md").write_text(QUEUE)
    (tmp_path / "arxiv-inbox.md").write_text(INBOX)
    return tmp_path


def test_backfill_appends_refs_without_disturbing_the_rest_of_the_line(tmp_path):
    root = _tree(tmp_path)
    refs = {"Bare Title": "2608.11111", "Inbox Bare Title": "2608.22222"}
    stats = backfill.backfill(root, write=True, limit=10,
                              resolve=refs.get, sleep=lambda _: None,
                              log=lambda *a: None)
    assert stats["matched"] == 2 and stats["unmatched"] == 1
    queue = (root / "reading-queue.md").read_text()
    assert "Bare Title — 2608.11111" in queue
    assert "Another Bare Title\n" in queue          # unresolved, untouched
    assert "DONE 2026-06-01 — Old Title" in queue   # history, untouched
    assert "Already Reffed — 2406.01234" in queue   # idempotent
    assert "prose that is not a paper" in queue
    # the inbox keeps its date stamp; the ref is appended after the title
    assert "2026-08-25 — Inbox Bare Title — 2608.22222" in \
        (root / "arxiv-inbox.md").read_text()


def test_backfill_writes_nothing_without_write(tmp_path):
    root = _tree(tmp_path)
    before = (root / "reading-queue.md").read_text()
    backfill.backfill(root, write=False, limit=10,
                      resolve=lambda t: "2608.11111", sleep=lambda _: None,
                      log=lambda *a: None)
    assert (root / "reading-queue.md").read_text() == before


def test_backfill_limit_caps_the_arxiv_calls(tmp_path):
    root = _tree(tmp_path)
    seen = []

    def resolve(title):
        seen.append(title)
        return None

    backfill.backfill(root, write=True, limit=2, resolve=resolve,
                      sleep=lambda _: None, log=lambda *a: None)
    assert len(seen) == 2


def test_backfill_reports_transport_failure_without_marking(tmp_path):
    root = _tree(tmp_path)
    before_queue = (root / "reading-queue.md").read_text()

    def failed(_title):
        raise arxiv_refs.ArxivAPIError("HTTP 406 after retries")

    stats = backfill.backfill(
        root,
        write=True,
        limit=10,
        mark_unresolved=True,
        resolve=failed,
        sleep=lambda _: None,
        log=lambda *a: None,
    )

    assert stats["api_failed"] == 1
    assert stats["unmatched"] == 0
    assert stats["marked"] == 0
    assert (root / "reading-queue.md").read_text() == before_queue


def test_main_exits_nonzero_when_the_api_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        backfill,
        "backfill",
        lambda *args, **kwargs: {
            "scanned": 3,
            "matched": 0,
            "unmatched": 0,
            "api_failed": 1,
            "marked": 0,
            "files": [],
        },
    )
    assert backfill.main(["--root", str(tmp_path)]) == 1


def test_backfill_is_idempotent(tmp_path):
    root = _tree(tmp_path)
    kw = dict(write=True, limit=10, resolve=lambda t: "2608.11111",
              sleep=lambda _: None, log=lambda *a: None)
    backfill.backfill(root, **kw)
    once = (root / "reading-queue.md").read_text()
    stats = backfill.backfill(root, **kw)
    assert stats["scanned"] == 0
    assert (root / "reading-queue.md").read_text() == once


# --- line kinds: what the backfill refuses to look up -------------------------
KINDED = ("# Reading queue\n\nprose\n\n---\n\n## Strong Lensing\n"
          "__A Bold Heading__\n"
          "Bare Title\n"
          "NOTE a stray remark someone pasted\n"
          "NOTE — https://example.org/not-a-paper\n"
          "https://example.org/also-not-a-paper\n"
          "https://arxiv.org/abs/2202.00099\n")


def test_headings_notes_and_non_arxiv_links_are_never_looked_up():
    """The marker's whole purpose: these lines cost zero arXiv calls, forever."""
    got = [t for _, t in backfill.candidates(KINDED, "reading-queue.md")]
    assert got == ["Bare Title"]   # the bare arXiv link already has its ref


def test_mark_unresolved_line_prefixes_without_touching_the_text():
    assert backfill.mark_unresolved_line("Some Prose Line") == \
        "NOTE Some Prose Line"
    # indentation survives; the text is never rewritten
    assert backfill.mark_unresolved_line("   Indented  ") == "   NOTE Indented"


def test_mark_unresolved_retires_a_line_from_all_future_runs(tmp_path):
    (tmp_path / "reading-queue.md").write_text(
        "# Q\n\n---\n\n## S\nResolves Fine\nNever Resolves\n")
    (tmp_path / "arxiv-inbox.md").write_text("# I\n\n---\n")
    kw = dict(write=True, limit=10, sleep=lambda _: None, log=lambda *a: None,
              resolve=lambda t: "2608.11111" if t == "Resolves Fine" else None)

    stats = backfill.backfill(tmp_path, mark_unresolved=True, **kw)
    assert stats["matched"] == 1 and stats["marked"] == 1
    text = (tmp_path / "reading-queue.md").read_text()
    assert "Resolves Fine — 2608.11111" in text
    assert "NOTE Never Resolves" in text

    # the next run has nothing left to ask arXiv about
    assert backfill.backfill(tmp_path, mark_unresolved=True, **kw)["scanned"] == 0


def test_the_nightly_never_marks_on_its_own(tmp_path):
    """Default off: an unresolved title is usually a real paper with a mangled
    line, and retrying it after a human fixes the line is the right behaviour."""
    (tmp_path / "reading-queue.md").write_text(
        "# Q\n\n---\n\n## S\nNever Resolves\n")
    (tmp_path / "arxiv-inbox.md").write_text("# I\n\n---\n")
    stats = backfill.backfill(tmp_path, write=True, limit=10,
                              resolve=lambda t: None, sleep=lambda _: None,
                              log=lambda *a: None)
    assert stats["marked"] == 0
    assert (tmp_path / "reading-queue.md").read_text().endswith("Never Resolves\n")

