"""tests/test_validate_wikilinks.py — the wikilink ratchet.

What the lint must get right: the documented link forms all resolve (bare slug,
anchor, label, the `sources-<topic>` form, and across sub-wikis), a link with no
page is not an error *by itself*, and a dangling target that is not in the
baseline is. Plus the two things that make the baseline usable: `--list` and
`--write-baseline`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import validate_wikilinks as vw  # noqa: E402


def _page(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def wiki(tmp_path):
    """A two-sub-wiki fixture exercising every documented link form."""
    _page(tmp_path, "wiki/lensing/index.md",
          "# Lensing\n\n- [[mass-sheet-degeneracy]]\n- [[h0licow]]\n")
    _page(tmp_path, "wiki/lensing/concepts/mass-sheet-degeneracy.md",
          "# MSD\n\nSee [[h0licow]] and "
          "[[sources-time-delay#suyu-2017-h0licow]].\n"
          "Across sub-wikis: [[smbh-seeds]].\n"
          "With a label: [[h0licow|the H0LiCOW collaboration]].\n")
    _page(tmp_path, "wiki/lensing/entities/h0licow.md", "# H0LiCOW\n")
    _page(tmp_path, "wiki/lensing/sources/time-delay.md",
          "# Sources: time delay\n\n## Suyu 2017 — H0LiCOW\n"
          "Also reachable as [[time-delay]].\n")
    _page(tmp_path, "wiki/smbh/concepts/smbh-seeds.md",
          "# Seeds\n\nBack to [[mass-sheet-degeneracy]].\n")
    return tmp_path


def _run(root, *argv, baseline=None):
    args = ["--root", str(root), "--baseline",
            str(baseline if baseline else root / "baseline.txt"), *argv]
    return vw.main(args)


# --- resolution ---------------------------------------------------------------
def test_every_documented_form_resolves(wiki, capsys):
    total, counts = vw.unresolved(wiki)
    assert counts == {}
    assert total == 8


def test_a_source_page_answers_to_both_of_its_slugs(wiki):
    slugs = vw.page_slugs(wiki)
    assert {"time-delay", "sources-time-delay"} <= slugs


def test_a_seed_page_answers_to_both_of_its_slugs(tmp_path):
    _page(tmp_path, "wiki/galaxies/seed/stellar-halos.md", "# Seed\n")
    assert {"stellar-halos", "seed-stellar-halos"} <= vw.page_slugs(tmp_path)


def test_the_anchor_is_not_validated(wiki):
    _page(wiki, "wiki/lensing/concepts/anchored.md",
          "# A\n\n[[h0licow#no-such-section]]\n")
    assert vw.unresolved(wiki)[1] == {}


def test_code_is_not_a_reference(wiki):
    _page(wiki, "wiki/lensing/concepts/schema-ish.md",
          "# Schema\n\nUse `[[page-slug]]` like this:\n\n"
          "```\n[[related-concept-1]]\n```\n\nReal one: [[h0licow]].\n")
    total, counts = vw.unresolved(wiki)
    assert counts == {}
    assert total == 9  # only the real one was counted


def test_a_link_wrapped_across_two_lines_is_one_link(wiki):
    _page(wiki, "wiki/lensing/concepts/wrapped.md",
          "# W\n\nThe [[mass-sheet-degeneracy|mass-sheet\ndegeneracy]] again.\n")
    assert vw.unresolved(wiki)[1] == {}


def test_unresolved_targets_are_counted_by_occurrence(wiki):
    _page(wiki, "wiki/lensing/concepts/wanted.md",
          "# W\n\n[[not-written-yet]] and [[not-written-yet]] and [[other]].\n")
    _, counts = vw.unresolved(wiki)
    assert counts == {"not-written-yet": 2, "other": 1}


# --- the ratchet --------------------------------------------------------------
def test_a_clean_wiki_passes(wiki, capsys):
    assert _run(wiki) == 0
    out = capsys.readouterr().out
    assert "8 links, 0 unresolved across 0 targets" in out


def test_a_new_unresolved_target_fails(wiki, capsys):
    _page(wiki, "wiki/lensing/concepts/typo.md", "# T\n\n[[h0licow-typo]]\n")
    assert _run(wiki) == 1
    out = capsys.readouterr().out
    assert "1 unresolved across 1 targets" in out
    assert "- h0licow-typo (1 reference(s))" in out


def test_an_unresolved_target_already_in_the_baseline_passes(wiki, capsys):
    _page(wiki, "wiki/lensing/concepts/wanted.md", "# W\n\n[[weak-lensing]]\n")
    (wiki / "baseline.txt").write_text("weak-lensing\n", encoding="utf-8")
    assert _run(wiki) == 0
    assert "no new unresolved targets" in capsys.readouterr().out


def test_another_reference_to_a_baselined_target_still_passes(wiki):
    _page(wiki, "wiki/lensing/concepts/wanted.md",
          "# W\n\n[[weak-lensing]] [[weak-lensing]] [[weak-lensing]]\n")
    (wiki / "baseline.txt").write_text("weak-lensing\n", encoding="utf-8")
    assert _run(wiki) == 0


def test_one_new_target_fails_even_beside_a_baselined_one(wiki, capsys):
    _page(wiki, "wiki/lensing/concepts/wanted.md",
          "# W\n\n[[weak-lensing]] and [[brand-new]]\n")
    (wiki / "baseline.txt").write_text("weak-lensing\n", encoding="utf-8")
    assert _run(wiki) == 1
    assert "- brand-new" in capsys.readouterr().out


def test_a_resolved_baseline_target_is_reported_not_failed(wiki, capsys):
    (wiki / "baseline.txt").write_text("weak-lensing\n", encoding="utf-8")
    assert _run(wiki) == 0
    assert "1 baseline target(s) now resolve" in capsys.readouterr().out


def test_a_missing_baseline_is_an_empty_one(wiki, capsys):
    _page(wiki, "wiki/lensing/concepts/wanted.md", "# W\n\n[[weak-lensing]]\n")
    assert _run(wiki, baseline=wiki / "nope.txt") == 1


# --- --list / --write-baseline ------------------------------------------------
def test_list_prints_targets_most_referenced_first(wiki, capsys):
    _page(wiki, "wiki/lensing/concepts/wanted.md",
          "# W\n\n[[once]] [[twice]] [[twice]]\n")
    (wiki / "baseline.txt").write_text("once\ntwice\n", encoding="utf-8")
    assert _run(wiki, "--list") == 0
    listed = [line.split()[-1] for line in capsys.readouterr().out.splitlines()
              if line.startswith("  ")]
    assert listed == ["twice", "once"]


def test_write_baseline_records_the_current_state(wiki, capsys):
    _page(wiki, "wiki/lensing/concepts/wanted.md",
          "# W\n\n[[beta]] and [[alpha]]\n")
    assert _run(wiki, "--write-baseline") == 0
    assert (wiki / "baseline.txt").read_text() == "alpha\nbeta\n"
    assert "+2 new, -0 resolved" in capsys.readouterr().out
    assert _run(wiki) == 0


def test_write_baseline_reports_what_it_dropped(wiki, capsys):
    (wiki / "baseline.txt").write_text("gone-now\nalso-gone\n", encoding="utf-8")
    _page(wiki, "wiki/lensing/concepts/wanted.md", "# W\n\n[[still-wanted]]\n")
    assert _run(wiki, "--write-baseline") == 0
    assert "+1 new, -2 resolved" in capsys.readouterr().out
    assert (wiki / "baseline.txt").read_text() == "still-wanted\n"


# --- the real wiki ------------------------------------------------------------
def test_the_checked_in_baseline_holds():
    """The repo's own state passes — the ratchet starts where the wiki is."""
    assert vw.main([]) == 0
