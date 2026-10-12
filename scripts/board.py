"""scripts/board.py — the PyAutoMemory Dashboard.

A phone-readable, MANAGEMENT-FIRST view of the repo's knowledge: what is
waiting to be read, which paper sections still need a canonical BibTeX key,
how mature each sub-wiki is — each work queue carrying a one-tap 📋 copy
block holding a paste-ready AI assistant prompt that executes this repo's own
documented workflow (``bibliography/README.md`` "Adding a paper",
``wiki/AGENTS.md``'s schema) — plus contents cards with ``Use the memory skill. <domain>``
recall chips. Reading-queue sections expand to the individual papers: each
title links out to the arXiv abstract page (or, when the line carries no ref,
a title search — see ``scripts/arxiv_refs.py``), carries a 📄 button onto the
PDF itself so a phone can collect a stack of papers without a detour through
search, and carries three prefilled-GitHub-issue actions — 📥 intake-into-memory
(really interesting: full filing), 📑 make-citeable (worth citing, not
pivotal: bib entry + minimal sources section), both open work items carrying
the human's free-text notes, and ✅ read-don't-file (processed automatically
by ``queue_actions.yml`` via ``queue_mark_done.py``). Nothing changes state
until the human submits the issue.

Above the queue sits the **arXiv inbox** (``arxiv-inbox.md``): what the nightly
digest suggested overnight, each line showing how many days it has left before
it lapses and carrying the same 📄 PDF button plus two further actions —
➕ add-to-the-queue and ✖️ dismiss.
The inbox's format, window and transitions live in ``scripts/inbox_actions.py``;
this module reads them rather than re-deriving them.

Below the inbox sits the **arXiv interests list** (``arxiv-interests.md``):
the same overnight machinery pointed at everything that is *not* strong
lensing — black holes, dark matter, galaxy formation, statistics — as one
day-batch of ten. It renders the same five actions per paper, plus one 🧹
*clear* button on the batch itself: the board shows the OLDEST un-cleared day
only and clearing it reveals the next. That batch carries a days-left count of
its own, because it lapses on the inbox's window if nobody clears it — whole,
a day at a time. ``scripts/interests_actions.py`` owns that format and those
transitions.

Both suggestion tiers also carry a **freshness line**: the date of the last digest run,
so an empty inbox says *which* kind of empty it is — arXiv was quiet, or the
filing broke. The date is rendered into the page, but the "this looks broken"
warning is computed in the reader's browser (see ``_EXTRA_JS``), because the
page freezes at its last good render in exactly the failure the warning is for.

A queue section is not a flat list of papers: a `__Bold__` line is a
sub-heading the human wrote, and a `NOTE `-prefixed line (or a bare non-arXiv
link) is an annotation. Both render as themselves — no link, no buttons, no
slot in the "N waiting" count — because a heading is not a paper you can
download. `_parse_paper` decides which is which; see `reading-queue.md`.

**Contents-level only.** The board shows titles and counts, never claim text
or summaries — the knowledge itself stays in the wiki pages.

**Fully local.** Everything renders from the checkout (no network):
frontmatter statuses, ``**Canonical BibTeX key:**`` markers, bib entry
counts, reading-queue sections, wikilink totals. Repo identity (for links)
derives from ``git remote`` — nothing is hardcoded, so the script travels
into spawned templates unchanged.

Published by ``.github/workflows/knowledge_board.yml`` (Pages + badge.json +
state.json, the organ-cockpit feed, + the README ``memory:begin/end`` strip).
Nothing is committed — ``validate_structure.py`` bans ``.html`` and gates the root allowlist, so the
board is rendered fresh in CI, the Heart pattern.

Usage:
    python scripts/board.py [--md | --md-brief | --html | --badge | --state | --json]
"""

from __future__ import annotations

import datetime
import html as _html
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote as _quote

MEMORY_HOME = Path(__file__).resolve().parents[1]

# The arXiv inbox owns its own line format, window and transitions; the
# board reads them rather than re-deriving them (scripts/inbox_actions.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import arxiv_refs  # noqa: E402
import inbox_actions  # noqa: E402
import interests_actions  # noqa: E402
import catch_up  # noqa: E402

#: How many days without an ingest before the board asks for a catch-up. A week:
#: the suggestion tiers lapse on the same seven days
#: (``inbox_actions.INBOX_WINDOW_DAYS``), so past it the inbox alone no longer
#: holds everything that was missed — git history does, which is exactly what
#: ``scripts/catch_up.py`` reads back.
CATCH_UP_DAYS = 7
CATCH_UP_LYRIC = "…so… I've been lost for a while"  # Fred again..
CATCH_UP_CMD = "Read PyAutoMemory/skills/catch_up/SKILL.md and follow the catch_up skill with arguments: lensing."

# The family look lives once, in the Brain (``board/_theme.py``): the
# stylesheet, the hero that redraws this organ's logo as a mark, and the
# cross-board footer. Imported rather than copied, so the look moves for the
# whole family at once — knowledge_board.yml checks PyAutoBrain out beside
# this repo, and a local run finds the sibling checkout the way the other
# PyAuto tools resolve each other.
BOARD_KEY = "memory"  # this board's entry in the Brain's palette table


def _workspace_root() -> Path:
    """Find the workspace containing the sibling PyAuto checkouts.

    The org's own directory name is an instance fact, so it is never written
    here — a workspace that does not follow the default sets `$PYAUTO_ROOT`
    (the same variable the dev-flow doors read).
    """
    if os.environ.get("PYAUTO_ROOT"):
        return Path(os.environ["PYAUTO_ROOT"])
    for parent in (MEMORY_HOME, *MEMORY_HOME.parents):
        if (parent / ".pyauto-root").is_file():
            return parent
    return Path.home() / "Code"


def theme():
    """The shared theme module, or a RuntimeError naming the fix.

    Only the html path needs it; ``--md``/``--badge``/``--json`` never call
    here, so the digest keeps working with no PyAutoBrain in reach.
    """
    for cand in (os.environ.get("PYAUTO_BRAIN"), MEMORY_HOME / "PyAutoBrain",
                 MEMORY_HOME.parent / "PyAutoBrain",
                 _workspace_root() / "organs" / "PyAutoBrain",
                 _workspace_root() / "PyAutoBrain"):
        if not cand:
            continue
        board = Path(cand) / "board"
        if (board / "_theme.py").is_file():
            if str(board) not in sys.path:
                sys.path.insert(0, str(board))
            import _theme
            return _theme
    raise RuntimeError(
        "the shared board theme (PyAutoBrain/board/_theme.py) is not in reach "
        "— check PyAutoBrain out beside this repo or set PYAUTO_BRAIN")

KEY_MARK = "**Canonical BibTeX key:**"
STATUS_RE = re.compile(r"^status:\s*(\S+)", re.MULTILINE)
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
BIB_ENTRY_RE = re.compile(r"^@\w+\{", re.MULTILINE)
RESOLVED_KEY_RE = re.compile(r"\*\*Canonical BibTeX key:\*\* `([^`]+)`")
# Queue sections are real `## ` headers (the 2026-08 restructure, #35); a
# consumed paper stays in place as a `DONE <date> — <title>` line, so the
# queue is also the reading history.
QUEUE_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
QUEUE_DONE_RE = re.compile(r"^DONE\b")
QUEUE_DONE_LINE_RE = re.compile(r"^DONE\s+(\d{4}-\d{2}-\d{2})\s*—\s*(.*)$")
# A paper line may end ` — <arXiv id or URL>`; anything else after an em dash
# is part of the title.
QUEUE_REF_RE = re.compile(
    r"^(.*\S)\s+—\s+((?:arXiv:)?\d{4}\.\d{4,5}(?:v\d+)?|https?://\S+)$")
# Not every line under a `## Section` is a paper. Two kinds are not, and saying
# so is what stops the board rendering a search button for a heading and the
# backfill spending an arXiv lookup on one every night:
#   `__Dark Matter__`  a bold sub-heading the human wrote to group the papers
#                      below it — structure, rendered as structure.
#   `NOTE <text>`      an annotation: a free-text remark, a link that is not a
#                      paper, a stray line of pasted prose. Sibling of the
#                      `DONE ` prefix — same shape, same never-delete rule, and
#                      the marker `backfill_arxiv_refs.py --mark-unresolved`
#                      writes so a line it cannot identify is asked about once
#                      and then left alone.
QUEUE_SUBHEAD_RE = re.compile(r"^__(.+?)__$")
QUEUE_NOTE_RE = re.compile(r"^NOTE\b\s*(?:—\s*)?(.*)$")
#: A line that is nothing but a URL. An arXiv one is a paper whose title was
#: never written (the ref is the whole line); anything else is an annotation.
QUEUE_BARE_URL_RE = re.compile(r"^https?://\S+$")


def _owner_repo() -> tuple[str, str]:
    out = subprocess.run(
        ["git", "-C", str(MEMORY_HOME), "remote", "get-url", "origin"],
        capture_output=True, text=True,
    ).stdout.strip()
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", out)
    return (m.group(1), m.group(2)) if m else ("", "")


# queue_filing.yml pushes each filing to `queue-filing/issue-<n>`; the PR
# that merges it is a human's (and needs a repo setting to be opened by the
# workflow at all — see the workflow's header).
FILING_BRANCH_RE = re.compile(r"refs/heads/queue-filing/issue-(\d+)$")


def _pending_filings() -> list[dict]:
    """Filing branches on the remote that nobody has merged yet.

    A 📥/📑 tap ends on a branch, not on main: until its PR is merged the
    paper is *not* in memory, and nothing on the page said so — three such
    branches sat unnoticed for a week (2026-09-01 → 09-10) while their
    papers were re-tapped into the reading queue instead. One `ls-remote`
    against origin; any failure (no remote, offline, no git) is an empty
    list, never an error, so a spawned template or a laptop on a train
    still renders.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(MEMORY_HOME), "ls-remote", "--heads", "origin",
             "refs/heads/queue-filing/*"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines():
        m = FILING_BRANCH_RE.search(line.strip())
        if m:
            n = int(m.group(1))
            found.append({"issue": n, "branch": f"queue-filing/issue-{n}"})
    return sorted(found, key=lambda f: f["issue"])


# --- collect (local files only) ----------------------------------------------
def collect(root: Path | None = None) -> dict:
    root = root or MEMORY_HOME
    owner, repo = _owner_repo() if root == MEMORY_HOME else ("", "")
    snapshot: dict = {
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "owner": owner,
        "repo": repo,
        "wikis": [],
        "bib_entries": 0,
        "queue": [],
        "inbox": [],
        "inbox_last_digest": None,
        # The interests list is day-batched: `interests` is the oldest
        # un-cleared batch (what the board shows), and `interests_batches` /
        # `interests_backlog` are how much is queued behind it.
        "interests": [],
        "interests_date": None,
        "interests_days_left": None,
        "interests_batches": 0,
        "interests_backlog": 0,
        "interests_last_digest": None,
        "links": {"total": 0, "unique": 0, "wanted": 0},
        # Filings that reached a `queue-filing/issue-<n>` branch but not
        # main — the one thing on the page that is a human's merge to make.
        "filings": _pending_filings() if root == MEMORY_HOME else [],
        # When memory last took a paper in (any scope): git + files, never the
        # network. None when nothing is on record or git is unavailable.
        "last_ingested": None,
        "lensing_ingest_evidence": None,
    }
    try:
        snapshot["last_ingested"] = catch_up.last_ingested("all", root)
    except Exception:  # noqa: BLE001 — the banner is advisory, never fatal
        snapshot["last_ingested"] = None
    try:
        snapshot["lensing_ingest_evidence"] = catch_up.ingest_evidence("lensing", root)
    except Exception:  # advisory: failed observation is unknown, never fresh
        snapshot["lensing_ingest_evidence"] = None

    stems: set[str] = set()
    all_slugs: list[str] = []
    wiki_root = root / "wiki"
    for wdir in sorted(d for d in wiki_root.glob("*") if d.is_dir()):
        pages = sorted(wdir.rglob("*.md"))
        stems |= {p.stem for p in pages}
        statuses: dict[str, int] = {}
        # `seed/` is the 2026-05 import's unverified half, split out of
        # `sources/`; counted separately so the sub-wiki row does not
        # read as if those pages were verified claim support.
        kinds = {"concepts": 0, "entities": 0, "sources": 0, "seed": 0}
        sections = 0
        todo = 0
        resolved: set[str] = set()
        for p in pages:
            text = p.read_text(errors="replace")
            m = STATUS_RE.search(text)
            if m:
                statuses[m.group(1)] = statuses.get(m.group(1), 0) + 1
            if p.parent.name in kinds:
                kinds[p.parent.name] += 1
            n_marks = text.count(KEY_MARK)
            sections += n_marks
            keys = RESOLVED_KEY_RE.findall(text)
            resolved |= set(keys)
            todo += n_marks - len(keys)
            all_slugs += WIKILINK_RE.findall(text)
        snapshot["wikis"].append({
            "name": wdir.name,
            "pages": len(pages),
            **kinds,
            "statuses": statuses,
            "sections": sections,
            "todo": todo,
            "resolved_keys": len(resolved),
        })

    for bib in sorted((root / "bibliography").glob("*.bib")):
        snapshot["bib_entries"] += len(BIB_ENTRY_RE.findall(
            bib.read_text(errors="replace")))

    queue = root / "reading-queue.md"
    if queue.exists():
        section, papers = None, []
        def _flush():
            if section is not None:
                snapshot["queue"].append({
                    "section": section,
                    # Headings and annotations are carried in `papers` so the
                    # section renders in file order, but they are not work:
                    # counting them would inflate every "N waiting" on the board.
                    "count": sum(1 for p in papers
                                 if p["kind"] == "paper" and not p["done"]),
                    "done": sum(1 for p in papers if p["done"]),
                    "papers": papers,
                })
        for line in queue.read_text(errors="replace").splitlines():
            m = QUEUE_SECTION_RE.match(line)
            if m and not m.group(1).startswith("#"):
                _flush()
                section, papers = m.group(1), []
            elif section is not None and line.strip():
                papers.append(_parse_paper(line.strip()))
        _flush()

    today = datetime.datetime.now(datetime.timezone.utc).date()

    inbox = root / inbox_actions.INBOX_FILE
    if inbox.exists():
        inbox_text = inbox.read_text(errors="replace")
        snapshot["inbox_last_digest"] = inbox_actions.last_digest(inbox_text)
        for entry in inbox_actions.papers(inbox_text):
            snapshot["inbox"].append({
                "title": entry["title"],
                "ref": entry["ref"],
                "line": entry["line"],
                "added": entry["added"],
                "days_left": inbox_actions.days_left(entry["added"], today),
                "done": False,
                "done_date": None,
            })

    interests = root / interests_actions.INTERESTS_FILE
    if interests.exists():
        text = interests.read_text(errors="replace")
        snapshot["interests_last_digest"] = inbox_actions.last_digest(text)
        every = interests_actions.batches(text)
        snapshot["interests_batches"] = len(every)
        snapshot["interests_backlog"] = sum(len(b) for _, b in every)
        current = interests_actions.current_batch(text)
        if current:
            snapshot["interests_date"] = current[0]
            # The batch is what lapses, so the days-left is the batch's, not
            # each paper's — every line in it carries the same date. Kept on
            # the papers too so an interests paper renders like an inbox one.
            snapshot["interests_days_left"] = interests_actions.days_left(
                current[0], today)
            for entry in current[1]:
                snapshot["interests"].append({
                    "title": entry["title"],
                    "ref": entry["ref"],
                    "line": entry["line"],
                    "added": entry["added"],
                    "days_left": interests_actions.days_left(entry["added"],
                                                             today),
                    "topic": entry["topic"],
                    "section": interests_actions.section_for(entry),
                    "done": False,
                    "done_date": None,
                })

    slugs = [s.split("|")[0].strip() for s in all_slugs]
    uniq = set(slugs)
    snapshot["links"] = {
        "total": len(slugs),
        "unique": len(uniq),
        "wanted": len({s for s in uniq if s not in stems}),
    }
    return snapshot


# --- pure helpers --------------------------------------------------------------
def _parse_paper(text: str) -> dict:
    """One queue line → {kind, title, ref, done, done_date, line}.

    `line` is the line as written — the token every issue button round-trips.
    `kind` is what the line *is*: a `paper`, a `subhead` (a `__Bold__` grouping
    the human wrote), or a `note` (a `NOTE `-prefixed annotation, or a bare
    non-arXiv link). Only a `paper` is counted, given buttons, or looked up on
    arXiv; the other two are carried through and rendered as themselves, which
    is the whole point — a heading is not a paper you can download.
    """
    raw, done_date = text, None
    m = QUEUE_DONE_LINE_RE.match(text)
    if m:
        done_date, text = m.group(1), m.group(2)
    elif QUEUE_DONE_RE.match(text):
        done_date, text = "", text[4:].lstrip(" —-")

    def _built(kind, title, ref=None):
        return {"kind": kind, "title": title, "ref": ref,
                "done": done_date is not None,
                "done_date": done_date or None, "line": raw}

    # Checked before the ref split: a heading or an annotation has no ref to
    # find, and `NOTE https://…` must not be read as a titleless paper.
    m = QUEUE_SUBHEAD_RE.match(text)
    if m:
        return _built("subhead", m.group(1).strip())
    m = QUEUE_NOTE_RE.match(text)
    if m:
        return _built("note", m.group(1).strip())

    ref = None
    m = QUEUE_REF_RE.match(text)
    if m:
        text, ref = m.group(1), m.group(2)
    elif QUEUE_BARE_URL_RE.match(text):
        # A line that is only a URL. If it points at arXiv the human did write a
        # paper — just as a link instead of a title — so it earns its abstract
        # page and its PDF button, labelled by the identifier the line already
        # contains rather than by a hundred characters of raw URL. (No title is
        # invented: the id is read out of the line, and the line itself is what
        # every issue button still round-trips.) Any other bare link is an
        # annotation.
        aid = arxiv_refs.arxiv_id(text)
        if not aid:
            return _built("note", text)
        return _built("paper", f"arXiv:{aid}", text)
    return _built("paper", text, ref)


def _url_host(url: str) -> str:
    """`https://sub.example.org/a/b?c` → `sub.example.org` (the url if unparsable)."""
    m = re.match(r"^https?://([^/?#]+)", url)
    return m.group(1) if m else url


def paper_url(paper: dict) -> str:
    """Where to read the paper: its abstract page, or an arXiv title search.

    An arXiv ref in any shape — bare id, ``arXiv:``-prefixed, an abs URL, a
    ``/pdf/…pdf`` URL — resolves to the *abstract* page, so every queue line
    lands on the same kind of page and the PDF is a separate, explicit button
    (:func:`paper_pdf_url`). A non-arXiv ref is a link the human wrote and is
    followed verbatim. A line with no ref at all can only be searched for; the
    search is the fallback, not the design (``scripts/arxiv_refs.py``).
    """
    ref = paper.get("ref")
    if ref:
        return arxiv_refs.abs_url(ref) or ref
    return arxiv_refs.search_url(paper.get("title", ""))


def paper_pdf_url(paper: dict) -> str:
    """The paper's direct PDF, or "" when the line carries no arXiv ref.

    Empty is a rendering instruction: no ref, no 📄 button — the board never
    shows a button that cannot work. Retiring those empties is the backfill's
    job (``scripts/backfill_arxiv_refs.py``), not the renderer's.
    """
    return arxiv_refs.pdf_url(paper.get("ref")) or ""


def _queue_issue_url(snapshot: dict, section: str, paper: dict,
                     action: str,
                     source: str = inbox_actions.QUEUE_FILE) -> str:
    """A prefilled new-issue URL for a per-paper action.

    Five tiers — 'intake' (really interesting: full wiki filing), 'cite'
    (worth citing, not pivotal: bib entry + a minimal sources section), 'read'
    (done with it: DONE-mark only), and, for the suggestion tiers
    (arXiv-inbox, arXiv-interests), 'add' (into the reading queue) and
    'dismiss' (not for me). All but intake/cite are
    processed automatically by queue_actions.yml. Nothing changes state until
    the human submits the issue on GitHub; intake/cite issues stay open as the
    filing work item, and their `notes:` field is free text the human edits
    before submitting. Empty when the checkout has no remote (spawned
    templates).

    `source` names the file the line lives in. It is emitted for every tier,
    including the reading-queue ones, so the workflows never have to guess —
    the older scripts ignore the extra key.
    """
    repo_url = _repo_url(snapshot)
    if not repo_url:
        return ""
    # Two of the three sources are *suggestion* tiers: a paper there has no
    # reading-queue line yet, which is what the ➕/✖️ actions and the filing
    # NOTE below both turn on. Naming that once keeps the interests list from
    # being a second special case bolted beside the inbox.
    staged = source != inbox_actions.QUEUE_FILE
    whose, tier = {
        inbox_actions.INBOX_FILE: ("arXiv-inbox", "the arXiv inbox"),
        interests_actions.INTERESTS_FILE: ("arXiv-interests",
                                           "the arXiv interests list"),
    }.get(source, ("reading-queue", "the reading queue"))
    where = f"file: {source}\nsection: {section}\nline: {paper['line']}"
    notes = ("notes: (optional — replace this with why you added it or "
             "what was noteworthy, in your own words; whoever files the "
             "paper folds it in)")
    from_interests = source == interests_actions.INTERESTS_FILE
    if action == "add":
        issue_title = f"queue add: {paper['title']}"[:200]
        label = "interests-add" if from_interests else "queue-add"
        body = (f"Move this {whose} paper into the reading queue "
                f"(section: {section}) — worth reading, not yet read.\n\n"
                f"{where}\n\n"
                "Processed automatically by queue_actions.yml.")
    elif action == "dismiss":
        issue_title = f"queue dismiss: {paper['title']}"[:200]
        label = "interests-dismiss" if from_interests else "queue-dismiss"
        body = (f"Drop this paper from {tier} — not one for me. The "
                "line is removed rather than DONE-marked: an un-acted "
                "suggestion is not reading history, and git history holds it "
                "either way.\n\n"
                f"{where}\n\n"
                "Processed automatically by queue_actions.yml.")
    elif action == "read":
        issue_title = f"queue read: {paper['title']}"[:200]
        label = "queue-read"
        body = (f"Mark this {whose} paper as read without filing it "
                "(the line stays, DONE-prefixed — the reading history).\n\n"
                f"{where}\n\n"
                "Processed automatically by queue_actions.yml.")
    elif action == "cite":
        issue_title = f"queue cite: {paper['title']}"[:200]
        label = "queue-cite"
        body = (f"Make this {whose} paper citeable — read, worth "
                "citing, but not pivotal enough for full wiki treatment.\n\n"
                f"{where}\n\n"
                f"{notes}\n\n"
                "Workflow (bibliography/README.md \"Adding a paper\", "
                "wiki/AGENTS.md): verify the paper against an authoritative "
                "record, add its canonical entry to the bibliography/ BibTeX "
                "file, add a minimal section to the matching "
                "wiki/<domain>/sources/ page — canonical key plus the notes "
                "above, nothing deeper — mark its queue line "
                "'DONE <date> — <title>' in reading-queue.md, and run "
                "make validate.")
    else:
        issue_title = f"queue intake: {paper['title']}"[:200]
        label = "queue-intake"
        body = (f"File this {whose} paper into memory.\n\n"
                f"{where}\n\n"
                f"{notes}\n\n"
                "Workflow (bibliography/README.md \"Adding a paper\", "
                "wiki/AGENTS.md): verify the paper against an authoritative "
                "record, add its canonical entry to the bibliography/ BibTeX "
                "file, stub it in the matching wiki/<domain>/sources/ page — "
                "incorporating the notes above — mark its queue line "
                "'DONE <date> — <title>' in reading-queue.md, and run "
                "make validate.")
    if staged and action not in ("add", "dismiss", "read"):
        # A suggestion-tier paper has no reading-queue line to DONE-mark:
        # filing it creates that line, already read, and clears the tier one.
        body += (f"\n\nNOTE: this paper is in {source} and is NOT in the "
                 "reading queue yet, so there is no line to mark. Instead "
                 f"append it to the '{section}' section of reading-queue.md "
                 "already DONE-prefixed (it is being filed now, not queued to "
                 f"read later) and remove its {source} line.")
    return (f"{repo_url}/issues/new?title={_quote(issue_title, safe='')}"
            f"&body={_quote(body, safe='')}&labels={_quote(label, safe='')}")


def _interests_clear_url(snapshot: dict, date: str, count: int) -> str:
    """The 🧹 button: a prefilled issue that drops one whole interests batch.

    The only board action that is not per-paper, because the list is not a
    per-paper decision: the human walks a backlog of days, taking what they
    want out of a day and clearing the rest of it in one tap. Everything still
    goes through the same gate — an issue, submitted by hand, processed by
    queue_actions.yml — so nothing changes state on a mis-tap.
    """
    repo_url = _repo_url(snapshot)
    if not repo_url:
        return ""
    title = f"interests clear: {date}"
    body = (f"Clear the {date} batch ({count} paper(s)) from "
            f"{interests_actions.INTERESTS_FILE} — done with this day, show "
            "the next one.\n\n"
            f"file: {interests_actions.INTERESTS_FILE}\n"
            f"date: {date}\n\n"
            "The lines are removed rather than DONE-marked: an un-acted "
            "suggestion is not reading history, and git history holds the "
            "batch either way.\n\n"
            "Processed automatically by queue_actions.yml.")
    return (f"{repo_url}/issues/new?title={_quote(title, safe='')}"
            f"&body={_quote(body, safe='')}"
            f"&labels={_quote('interests-clear', safe='')}")


def _read_trend(snapshot: dict) -> dict:
    """Read counts from the DONE history, relative to the snapshot's
    `generated` timestamp (pure — no wall clock): papers read in the last
    7/30 days plus eight weekly buckets, oldest first."""
    trend = {"d7": 0, "d30": 0, "weeks": [0] * 8}
    try:
        now = datetime.date.fromisoformat(str(snapshot.get("generated"))[:10])
    except ValueError:
        return trend
    for q in snapshot.get("queue") or []:
        for p in q.get("papers") or []:
            if not p.get("done_date"):
                continue
            try:
                age = (now - datetime.date.fromisoformat(p["done_date"])).days
            except ValueError:
                continue
            if age < 0:
                continue
            if age < 7:
                trend["d7"] += 1
            if age < 30:
                trend["d30"] += 1
            if age < 56:
                trend["weeks"][7 - age // 7] += 1
    return trend


def _days_since_ingest(snapshot: dict) -> int | None:
    """Days from ``last_ingested`` to the snapshot's ``generated`` date.

    Pure like :func:`_read_trend` — relative to the snapshot, not the wall
    clock — so a fixture renders the same banner on any calendar day. None when
    either date is missing or unparseable.
    """
    try:
        now = datetime.date.fromisoformat(str(snapshot.get("generated"))[:10])
        last = datetime.date.fromisoformat(str(snapshot.get("last_ingested")))
    except ValueError:
        return None
    return max(0, (now - last).days)


def _lensing_catch_up(snapshot: dict) -> dict:
    """Owner's existing seven-day cutoff, with its evidence and manual action.

    DONE can mean read-without-filing. Keep the actual bib+sources ingestion
    separate; never call a queue completion a successful ingestion.
    """
    evidence = snapshot.get("lensing_ingest_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    repo = _repo_url(snapshot)
    runbook = f"{repo}/blob/main/skills/catch_up/catch_up.md" if repo else None
    queue = f"{repo}/blob/main/reading-queue.md#strong-lensing" if repo else None
    bib = evidence.get("bib") if isinstance(evidence.get("bib"), dict) else None
    result = {
        "id": "memory:lensing-catch-up", "scope": "lensing", "state": "unknown",
        "last_activity": evidence.get("last_ingested"),
        "last_completed": evidence.get("done"), "last_ingestion": bib,
        "age_days": None, "threshold_days": CATCH_UP_DAYS, "due_at": None,
        "checked_at": None, "evidence": [],
        "reason": "No lensing paper activity is on record; freshness is unknown.",
        "actions": [{"id": "catch-up", "label": "Copy lensing catch-up prompt",
                     "kind": "prompt", "target": CATCH_UP_CMD,
                     "safety": "scientific_judgement"}],
        "recommended_action_id": "catch-up",
    }
    if queue and evidence.get("done"):
        result["evidence"].append({"kind": "queue_completion", "date": evidence["done"], "url": queue})
    if bib and repo and bib.get("commit"):
        result["evidence"].append({"kind": "ingestion_commit", "date": bib.get("date"),
                                   "url": f"{repo}/commit/{bib['commit']}"})
    if runbook:
        result["actions"].append({"id": "runbook", "label": "Catch-up procedure",
                                  "kind": "link", "target": runbook, "safety": "read_only"})
    try:
        now = datetime.datetime.fromisoformat(str(snapshot.get("generated")))
        if now.tzinfo is None:
            raise ValueError("missing timezone")
        today = now.astimezone(datetime.timezone.utc).date()
        result["checked_at"] = _iso_z(snapshot["generated"])
    except ValueError:
        result["reason"] = "The snapshot time is missing or invalid; lensing freshness is unknown."
        return result
    dates = [evidence.get("last_ingested"), evidence.get("done"), bib and bib.get("date")]
    if all(d is None for d in dates):
        return result
    try:
        parsed = [datetime.date.fromisoformat(str(d)) for d in dates if d is not None]
        cutoff = datetime.date.fromisoformat(str(evidence.get("last_ingested")))
        if any(d > today for d in parsed):
            raise ValueError("future evidence")
        sources = [datetime.date.fromisoformat(str(d)) for d in dates[1:] if d is not None]
        if not sources or cutoff != max(sources):
            raise ValueError("inconsistent cutoff")
    except ValueError:
        result["reason"] = "Lensing activity dates are invalid, inconsistent or in the future; verify the evidence."
        return result
    days = (today - cutoff).days
    result.update(age_days=days, state="stale" if days >= CATCH_UP_DAYS else "healthy",
                  due_at=(cutoff + datetime.timedelta(days=CATCH_UP_DAYS)).isoformat() + "T00:00:00Z")
    result["reason"] = (f"Last recorded lensing paper activity: {cutoff} ({days} days ago); "
                        f"catch-up is due after {CATCH_UP_DAYS} days. "
                        "Activity includes queue completion or verified ingestion; paper selection remains human-reviewed.")
    return result


def _catch_up_due(snapshot: dict) -> int | None:
    model = _lensing_catch_up(snapshot)
    return model["age_days"] if model["state"] == "stale" else None


def _catch_up_md(snapshot: dict) -> list[str]:
    model = _lensing_catch_up(snapshot)
    if model["state"] == "healthy":
        return []
    title = "Strong-lensing catch-up due" if model["state"] == "stale" else "Strong-lensing freshness unknown"
    return [f"> **{title}**", f"> {model['reason']}",
            f"> Next: `{CATCH_UP_CMD}` — human-reviewed paper selection.", ""]


def _catch_up_html(snapshot: dict) -> str:
    model = _lensing_catch_up(snapshot)
    if model["state"] == "healthy":
        return ""
    title = "Strong-lensing catch-up due" if model["state"] == "stale" else "Strong-lensing freshness unknown"
    lyric = (f"<p class='lyric'><em>{_html.escape(CATCH_UP_LYRIC)}</em></p>"
             if model["state"] == "stale" else "")
    return (f"<section class='catchup'>{lyric}<p><strong>{title}</strong></p>"
            f"<p>{_html.escape(model['reason'])}</p>"
            f"<p><code>{_html.escape(CATCH_UP_CMD)}</code> "
            f"{_copy_btn(CATCH_UP_CMD, 'copy: catch up on strong lensing')} "
            "<span class='muted'>Human-reviewed paper selection</span></p></section>")


def _totals(snapshot: dict) -> dict:
    wikis = snapshot.get("wikis") or []
    statuses: dict[str, int] = {}
    for w in wikis:
        for k, v in (w.get("statuses") or {}).items():
            statuses[k] = statuses.get(k, 0) + v
    sections = sum(w.get("sections", 0) for w in wikis)
    todo = sum(w.get("todo", 0) for w in wikis)
    return {
        "pages": sum(w.get("pages", 0) for w in wikis),
        "statuses": statuses,
        "sections": sections,
        "todo": todo,
        "resolved": sections - todo,
        "queued": sum(q.get("count", 0) for q in snapshot.get("queue") or []),
    }


def pages_url(snapshot: dict) -> str:
    owner = str(snapshot.get("owner") or "").lower()
    repo = snapshot.get("repo") or ""
    return f"https://{owner}.github.io/{repo}/" if owner and repo else ""


def _repo_url(snapshot: dict) -> str:
    owner, repo = snapshot.get("owner"), snapshot.get("repo")
    return f"https://github.com/{owner}/{repo}" if owner and repo else ""


CHECKIN_PROMPT = (
    "Use this chat as an ongoing place to work with PyAutoMemory: retrieve existing "
    "knowledge, discuss papers and improve the knowledge base. Read PyAutoMemory/AGENTS.md, "
    "its index and the relevant domain indexes. Start with a small selection of relevant "
    "pages and expand as the question requires.\n\n"
    "When I give no particular direction, review the reading queue, arXiv inbox and "
    "interests, digest freshness, citation work, incomplete pages and filings awaiting merge. "
    "Summarize what needs attention and suggest useful next steps, distinguishing new "
    "material from work already processed.\n\n"
    "When I supply a paper, topic, question or idea, make that the main focus. Help me find "
    "prior knowledge, recall recorded decisions, understand a paper, compare methods or "
    "identify gaps in existing coverage. Bring in related material where useful; do not "
    "repeat the full queue review on every follow-up.\n\n"
    "Ground answers in cited sources. Distinguish what a paper establishes, what our existing "
    "notes say and any interpretation you offer. Make uncertainty and conflicting evidence "
    "explicit. Discuss connections to our work without treating a published claim as "
    "something we have independently verified.\n\n"
    "Help me select what to read, work through a paper in depth, develop notes or plan "
    "improvements to wiki pages and citations. Follow the existing reading, catch-up and "
    "filing procedures. Agree the selection before bulk processing, and avoid duplicating "
    "existing entries.\n\n"
    "When I ask you to preserve knowledge, update the appropriate canonical pages, "
    "bibliography or queue records through the repository’s workflow. Keep source attribution "
    "and distinguish proposed ideas from accepted project decisions. Do not commit source "
    "PDFs.\n\n"
    "Carry clearly authorized work through its workflow, retaining approvals already given in "
    "this conversation. After changes, report what was recorded, where it lives and what "
    "remains to read or resolve."
)


# The one-tap board family — the cross-board footer nav every board carries,
# each board skipping its own entry.
#
# Membership and order are NOT decided here: they live once, in the Brain's
# `config/policy.yaml` `board: boards:`, and `_theme.board_links` is the read.
# This file used to keep its own tuple, written before the Cortex had a board
# — so this footer was short a chip and out of the family's order, and nothing
# noticed. The tuple below survives only as the fallback for an older
# PyAutoBrain checkout whose theme predates the helper; it is deliberately the
# old list, because a fallback that guessed at the current one would drift the
# same way. Owner still comes from the snapshot.
BOARD_FAMILY = (("mind", "PyAutoMind"), ("brain", "PyAutoBrain"),
                ("heart", "PyAutoHeart"), ("hands", "PyAutoHands"),
                ("organism", "PyAutoScientist"))


def _boards_nav(snapshot: dict) -> str:
    """The cross-board footer — one chip per sibling, each in its own organ's
    colour (the theme owns the chip palette AND the family's membership; this
    board owns only its owner and which page it is)."""
    owner = str(snapshot.get("owner") or "").lower()
    if not owner:
        return ""
    t_ = theme()
    base = f"https://{owner}.github.io"
    links = getattr(t_, "board_links", None)
    links = (links(base, BOARD_KEY) if links else
             {key: f"{base}/{repo}/" for key, repo in BOARD_FAMILY})
    return t_.boards_footer(links, BOARD_KEY)


def _read_prompt(snapshot: dict, section: str) -> str:
    repo = snapshot.get("repo") or "the memory repo"
    return (f"Work through the next paper in the '## {section}' section of "
            f"{repo}/reading-queue.md: verify it against an authoritative "
            f"record, add its canonical entry to the bibliography/ BibTeX "
            f"file, stub it in the matching wiki/<domain>/sources/ page per "
            f"wiki/AGENTS.md, mark its queue line 'DONE <date> — <title>', "
            f"and run make validate.")


def _todo_prompt(snapshot: dict, wiki: str) -> str:
    repo = snapshot.get("repo") or "the memory repo"
    return (f"Resolve TODO canonical BibTeX keys in {repo}/wiki/{wiki}/sources/: "
            f"for each '{KEY_MARK} TODO' section, search the bibliography/ "
            f"BibTeX file by DOI, arXiv ID and title, set the canonical key "
            f"per bibliography/README.md, and run make validate. Work through "
            f"a handful, then stop for review.")


def _stub_prompt(snapshot: dict, wiki: str) -> str:
    repo = snapshot.get("repo") or "the memory repo"
    return (f"Upgrade one stub page in {repo}/wiki/{wiki}/ to drafted: verify "
            f"its claims against the cited sources, expand it per the schema "
            f"in wiki/AGENTS.md, set status: drafted, and run make validate.")


# The existing Mind producers write independent date stamps in these files.
DIGESTS = {
    "inbox_last_digest": ("lensing", "arXiv inbox", "arxiv-inbox.md", "arxiv_papers.yml"),
    "interests_last_digest": ("interests", "arXiv interests", "arxiv-interests.md", "arxiv_interests.yml"),
}


def _inbox_freshness(snapshot: dict, key: str = "inbox_last_digest") -> dict:
    """One owner policy for both board renderers and the cockpit feed.

    A filing stamp is evidence of a recorded digest, not a GitHub run ID or
    proof that every step of that workflow succeeded. Empty queues do not
    change freshness: a quiet-day stamp is just as valid as a populated one.
    """
    scope, label, filename, workflow = DIGESTS[key]
    stamp = snapshot.get(key)
    repo = _repo_url(snapshot)
    evidence_url = f"{repo}/blob/main/{filename}" if repo else None
    owner = snapshot.get("owner")
    workflow_url = (f"https://github.com/{owner}/PyAutoMind/actions/workflows/{workflow}"
                    if owner else None)
    prompt = (f"Use the bug skill. investigate {label} digest freshness; inspect the recorded "
              f"date in {filename} and the {workflow} workflow before choosing a remedy")
    if workflow_url:
        prompt += f" — {workflow_url}"
    actions = []
    if workflow_url:
        actions.append({"id": "inspect-workflow", "label": "Inspect workflow", "kind": "link",
                        "target": workflow_url, "safety": "read_only"})
    if evidence_url:
        actions.append({"id": "view-stamp", "label": "View digest stamp", "kind": "link",
                        "target": evidence_url, "safety": "read_only"})
    actions.append({"id": "investigate", "label": "Copy investigation prompt", "kind": "prompt",
                    "target": prompt, "safety": "requires_approval"})
    result = {"id": f"memory:digest:{scope}", "scope": scope, "label": label,
              "stamp": stamp, "last_recorded": None, "checked_at": None,
              "weekdays": None, "threshold_weekdays": inbox_actions.INBOX_STALE_WEEKDAYS,
              "state": "unknown", "stale": False, "evidence_url": evidence_url,
              "workflow_url": workflow_url, "actions": actions,
              "recommended_action_id": "inspect-workflow" if workflow_url else "investigate",
              "reason": "no run recorded yet — digest freshness unknown"}
    try:
        now = datetime.datetime.fromisoformat(str(snapshot.get("generated")))
        if now.tzinfo is None:
            raise ValueError("missing timezone")
        today = now.astimezone(datetime.timezone.utc).date()
        result["checked_at"] = _iso_z(snapshot["generated"])
    except (TypeError, ValueError):
        result["reason"] = "snapshot time is missing or invalid — digest freshness unknown"
        return result
    if stamp is None:
        return result
    try:
        parsed = datetime.date.fromisoformat(stamp)
        if parsed.isoformat() != stamp or parsed > today:
            raise ValueError("future or noncanonical date")
    except (TypeError, ValueError):
        result["reason"] = "digest date is invalid or in the future — freshness unknown; inspect the stamp"
        return result
    weekdays = inbox_actions.weekdays_since(stamp, today)
    stale = inbox_actions.is_stale(stamp, today)
    result.update(last_recorded=stamp, weekdays=weekdays, stale=stale,
                  state="stale" if stale else "healthy")
    result["reason"] = (f"no digest since {stamp} ({weekdays} weekdays) — the nightly filing may be broken; "
                        f"threshold: {inbox_actions.INBOX_STALE_WEEKDAYS} weekdays" if stale else
                        f"digest recorded {stamp}; {weekdays} weekdays elapsed, below the "
                        f"{inbox_actions.INBOX_STALE_WEEKDAYS}-weekday threshold")
    return result


def _inbox_empty_note(fresh: dict) -> str:
    """Why a tier is empty without inferring the number of papers fetched."""
    if fresh["state"] != "healthy":
        return fresh["reason"]
    return f"the last digest ran {fresh['stamp']}; nothing is waiting"


# --- renderers ------------------------------------------------------------------
def _render_md(snapshot: dict) -> str:
    t = _totals(snapshot)
    lines = ["# PyAutoMemory Dashboard", "", *_catch_up_md(snapshot),
             "_Contents and work queues — the knowledge itself lives in the "
             "wiki pages._", "",
             f"**{t['pages']} pages** across {len(snapshot.get('wikis') or [])} "
             f"sub-wikis · **{t['resolved']}/{t['sections']}** paper sections "
             f"cite a resolved key · **{snapshot.get('bib_entries', 0)}** "
             f"bibliography entries · **{t['queued']}** papers queued", ""]
    lines += ["| Wiki | Pages | Stub | Drafted | Reviewed | Key TODOs |",
              "|---|---|---|---|---|---|"]
    for w in snapshot.get("wikis") or []:
        s = w.get("statuses") or {}
        lines.append(f"| {w['name']} | {w['pages']} | {s.get('stub', 0)} | "
                     f"{s.get('drafted', 0)} | {s.get('reviewed', 0)} | "
                     f"{w.get('todo', 0)} |")
    filings = snapshot.get("filings") or []
    if filings:
        repo_url = _repo_url(snapshot)
        lines += ["", "## Filings awaiting merge", "",
                  f"_{len(filings)} filing{'s' if len(filings) != 1 else ''} "
                  "reached a branch but not `main` — a paper is not in memory "
                  "until its PR is merged._", ""]
        for f in filings:
            if repo_url:
                lines.append(
                    f"- #{f['issue']} — [issue]({repo_url}/issues/{f['issue']}) · "
                    f"[open the PR →]({repo_url}/compare/main...{f['branch']}"
                    f"?expand=1)")
            else:
                lines.append(f"- #{f['issue']} — `{f['branch']}`")
        lines.append("")
    lines += ["", "## arXiv inbox", ""]
    inbox = snapshot.get("inbox") or []
    fresh = _inbox_freshness(snapshot)
    if inbox:
        digest = (f"last digest {fresh['last_recorded']} · " if fresh["last_recorded"] else "")
        if fresh["state"] != "healthy":
            digest += fresh["reason"] + " · "
        warn = ("⚠ " if fresh["stale"] else "")
        lines += [f"_{len(inbox)} waiting · {warn}{digest}un-acted suggestions "
                  f"lapse after {inbox_actions.INBOX_WINDOW_DAYS} days._", ""]
        for p in inbox:
            label = p["title"].replace("[", "\\[").replace("]", "\\]")
            bits = [f"- [{label}]({paper_url(p)}) — _{p['days_left']}d left_"]
            pdf = paper_pdf_url(p)
            if pdf:
                bits.append(f"[pdf 📄]({pdf})")
            for action, chip in (("add", "queue ➕"), ("intake", "intake 📥"),
                                 ("cite", "cite 📑"), ("dismiss", "dismiss ✖️")):
                u = _queue_issue_url(snapshot, inbox_actions.INBOX_TARGET_SECTION,
                                     p, action, source=inbox_actions.INBOX_FILE)
                if u:
                    bits.append(f"[{chip}]({u})")
            lines.append(" · ".join(bits))
        lines.append("")
    else:
        warn = ("⚠ " if fresh["stale"] else "")
        lines += [f"- _(nothing waiting — {warn}{_inbox_empty_note(fresh)})_", ""]

    lines += ["", "## arXiv interests", ""]
    interests = snapshot.get("interests") or []
    ifresh = _inbox_freshness(snapshot, "interests_last_digest")
    if interests:
        lines += [f"_{ifresh['reason']}_", ""]
        date = snapshot.get("interests_date") or "?"
        left = max(0, (snapshot.get("interests_batches") or 1) - 1)
        backlog = (f" · {left} more day{'s' if left != 1 else ''} behind it"
                   if left else " · nothing behind it")
        clear_url = _interests_clear_url(snapshot, date, len(interests))
        clear = f" · [clear this day \U0001f9f9]({clear_url})" if clear_url else ""
        # The batch's days-left, beside the inbox's per-line one: a batch
        # nobody clears is swept whole on the same window.
        dleft = snapshot.get("interests_days_left")
        left_bit = f" · {dleft}d left" if dleft is not None else ""
        lines += [f"_{date} · {len(interests)} "
                  f"paper{'s' if len(interests) != 1 else ''}{left_bit}"
                  f"{backlog}{clear}_",
                  ""]
        for p_ in interests:
            label = p_["title"].replace("[", "\\[").replace("]", "\\]")
            bits = [f"- [{label}]({paper_url(p_)})"]
            if p_.get("topic"):
                bits.append(f"_{p_['topic']}_")
            pdf = paper_pdf_url(p_)
            if pdf:
                bits.append(f"[pdf 📄]({pdf})")
            for action, chip in (("add", "queue ➕"), ("intake", "intake 📥"),
                                 ("cite", "cite 📑"), ("dismiss", "dismiss ✖️")):
                u = _queue_issue_url(snapshot, p_["section"], p_, action,
                                     source=interests_actions.INTERESTS_FILE)
                if u:
                    bits.append(f"[{chip}]({u})")
            lines.append(" · ".join(bits))
        lines.append("")
    else:
        warn = ("⚠ " if ifresh["stale"] else "")
        lines += [f"- _(no batch waiting — {warn}{_inbox_empty_note(ifresh)})_",
                  ""]

    lines += ["## Reading queue", ""]
    trend = _read_trend(snapshot)
    if sum(q.get("done", 0) for q in snapshot.get("queue") or []):
        lines += [f"_{trend['d7']} read in the last 7 days · "
                  f"{trend['d30']} in the last 30._", ""]
    for q in snapshot.get("queue") or []:
        done = f", {q['done']} read" if q.get("done") else ""
        lines += [f"<details><summary>{q['section']}: {q['count']} "
                  f"waiting{done}</summary>", ""]
        for p in q.get("papers") or []:
            if p["done"]:
                continue
            label = p["title"].replace("[", "\\[").replace("]", "\\]")
            if p["kind"] == "subhead":
                lines.append(f"- **{label}**")
                continue
            if p["kind"] == "note":
                if QUEUE_BARE_URL_RE.match(p["title"]):
                    label = f"[{_url_host(p['title'])} →]({p['title']})"
                lines.append(f"- _{label}_")
                continue
            bits = [f"- [{label}]({paper_url(p)})"]
            pdf = paper_pdf_url(p)
            if pdf:
                bits.append(f"[pdf 📄]({pdf})")
            for action, chip in (("intake", "intake 📥"), ("cite", "cite 📑"),
                                 ("read", "read ✅")):
                u = _queue_issue_url(snapshot, q["section"], p, action)
                if u:
                    bits.append(f"[{chip}]({u})")
            lines.append(" · ".join(bits))
        lines += ["", "</details>"]
    if not snapshot.get("queue"):
        lines.append("- _(queue empty or unavailable)_")
    url = pages_url(snapshot)
    if url:
        lines += ["", f"[Dashboard]({url}) — one-tap 📋 work prompts"]
    return "\n".join(lines)


def _render_md_brief(snapshot: dict) -> str:
    t = _totals(snapshot)
    pct = round(100 * t["resolved"] / t["sections"]) if t["sections"] else 0
    bits = [f"🧠 **{t['pages']} pages** · {t['statuses'].get('drafted', 0)} drafted",
            f"{pct}% of {t['sections']} paper sections cite a resolved key",
            f"{t['queued']} papers queued"]
    url = pages_url(snapshot)
    if url:
        bits.append(f"[dashboard →]({url})")
    return " · ".join(bits)


def _copy_btn(payload: str, label: str = "copy") -> str:
    return (f"<button class='copy' type='button' "
            f"title='{_html.escape(label, quote=True)}' "
            f"data-cmd=\"{_html.escape(payload, quote=True)}\">📋</button>")


def _bar(statuses: dict) -> str:
    stub = statuses.get("stub", 0)
    drafted = statuses.get("drafted", 0)
    reviewed = statuses.get("reviewed", 0)
    total = max(1, stub + drafted + reviewed)
    seg = lambda n, cls: (f"<span class='seg {cls}' style='width:{100 * n / total:.0f}%'></span>"
                          if n else "")
    return f"<span class='bar'>{seg(reviewed, 'ok')}{seg(drafted, 'mid')}{seg(stub, 'lo')}</span>"


# The lede, and the page-specific shapes the shared sheet has no opinion on:
# the citation bar, the collapsible queue sections, the paper list and its
# filter, the read-rate sparkline. All written against the theme's variables,
# so this board follows the family accent instead of setting a second palette.
_LEDE = ("What the organism knows, and what it still owes a citation. On a "
         "paper: \U0001f4e5 intake · \U0001f4d1 cite · \u2705 mark read — each opens a "
         "prefilled issue (add notes, submit to act). \U0001f9f9 clears a whole "
         "interests day. \U0001f4cb copies an AI assistant prompt.")

_EXTRA_CSS = """
.bar{display:inline-block;width:90px;height:8px;border-radius:4px;
 overflow:hidden;background:var(--btn);vertical-align:middle;
 border:1px solid var(--line)}
.seg{display:inline-block;height:8px;float:left}
.seg.ok{background:var(--ok)}
.seg.mid{background:var(--accent)}
.seg.lo{background:var(--muted)}
details.qsec{border-top:1px solid var(--line);padding:.5rem .25rem}
details.qsec>summary{cursor:pointer;list-style:none}
details.qsec>summary::-webkit-details-marker{display:none}
details.qsec>summary .name::before{content:"\u25b8 ";color:var(--accent)}
details.qsec[open]>summary .name::before{content:"\u25be "}
.name{font-weight:600}
ul.papers{margin:.5rem 0 .25rem;padding-left:1.3rem}
ul.papers li{margin:.4rem 0}
ul.papers li.done{color:var(--muted)}
/* A heading the human wrote inside a section, and a line that is not a paper:
   both render as themselves — no link, no buttons, nothing to tap. */
ul.papers li.subhead{list-style:none;margin:.7rem 0 .2rem -1.3rem;
 font-weight:600;letter-spacing:.02em}
ul.papers li.note{color:var(--muted);font-style:italic}
a.act{margin-left:.35rem;padding:.05rem .4rem;font-size:.85rem;
 border:1px solid var(--line);border-radius:6px;background:var(--btn)}
a.act:hover{background:var(--tint);border-color:var(--accent);
 text-decoration:none}
a.act.pdf{border-color:var(--accent)}
/* The one batch-level action: it clears a whole day, so it is worded rather
   than an icon alone — a mis-tap here costs ten papers, not one. */
a.act.clear{border-color:var(--warn);color:var(--warn);font-weight:600}
a.act.clear:hover{background:var(--warn);color:var(--bg);border-color:var(--warn)}
.topic{color:var(--muted);font-size:.82em;margin-left:.4rem;
 padding:.05rem .35rem;border:1px solid var(--line);border-radius:6px}
details.hist{margin:.25rem 0 .25rem 1.3rem}
details.hist>summary{cursor:pointer}
#pfilter{width:100%;padding:.45rem .6rem;margin:.25rem 0 .5rem;
 background:var(--btn);color:var(--fg);border:1px solid var(--line);
 border-radius:8px;font:inherit}
#pfilter:focus{outline:none;border-color:var(--accent)}
.spark{display:inline-flex;align-items:flex-end;gap:2px;height:12px;
 margin-left:.45rem}
.spark .sb{width:5px;background:var(--accent);border-radius:1px;
 display:inline-block}
.fresh.stale{color:var(--warn);font-weight:600}
table.recent td.name{white-space:nowrap}
footer{margin-top:2rem;color:var(--muted);font-size:.82em}
/* One-tap mode (see the script): the 🔑 chip, the inline notes box a 📥/📑
   tap opens, a busy button, and the toast that says what just happened. */
#onetap{font:inherit;font-size:.9em;padding:.1rem .5rem;border:1px solid var(--line);
 border-radius:6px;background:var(--btn);color:var(--fg);cursor:pointer}
#onetap:hover{border-color:var(--accent)}
#onetap.on{border-color:var(--ok);color:var(--ok)}
.notes{margin:.4rem 0 .2rem;padding:.5rem;border:1px solid var(--line);
 border-radius:8px;background:var(--btn)}
.notes textarea{width:100%;box-sizing:border-box;font:inherit;padding:.4rem;
 border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
.notes textarea:focus{outline:none;border-color:var(--accent)}
.notes button{margin-top:.35rem;font:inherit;padding:.25rem .6rem;
 border:1px solid var(--line);border-radius:6px;background:var(--bg);
 color:var(--fg);cursor:pointer}
.notes button.go{border-color:var(--accent);font-weight:600}
a.act.busy{opacity:.5;pointer-events:none}
#toast{position:fixed;left:50%;bottom:1.2rem;transform:translateX(-50%);
 max-width:90vw;padding:.5rem .9rem;border-radius:8px;background:var(--fg);
 color:var(--bg);opacity:0;transition:opacity .2s;pointer-events:none;z-index:9}
#toast.show{opacity:1}
#toast.bad{background:var(--warn)}
.catchup{border-left:3px solid var(--warn);padding:.4em .9em;margin:0 0 1em}
.catchup p{margin:.25em 0}
.catchup .lyric{color:var(--warn)}
"""

# The shared copy handler is delegated, so a chip inside a <summary> would
# also toggle its section. Swallow that one default; the filter is this
# board's own behaviour and stays here.
#
# freshness() is the inbox's staleness warning, and it runs HERE rather than in
# the renderer on purpose. knowledge_board.yml re-publishes on pushes to
# arxiv-inbox.md — which is precisely what stops happening when the nightly
# filing breaks. The page then freezes at its last good render, so a warning
# baked in at render time would sit at "0 weekdays" forever and never fire in
# the one failure it exists for. The rendered date is a fact and survives the
# freeze; the verdict is recomputed against the reader's own clock.
_EXTRA_JS = r"""
function freshness(){
 var els=document.querySelectorAll('.fresh[data-last-digest]');
 for(var i=0;i<els.length;i++){var el=els[i];
  var p=el.getAttribute('data-last-digest').split('-');
  var d=new Date(Date.UTC(+p[0],+p[1]-1,+p[2]));
  var now=new Date();
  var today=Date.UTC(now.getUTCFullYear(),now.getUTCMonth(),now.getUTCDate());
  var n=0,guard=0;
  while(d.getTime()<today&&guard++<400){
   d.setUTCDate(d.getUTCDate()+1);
   var w=d.getUTCDay(); if(w>0&&w<6){n++;}}
  if(n>=+el.getAttribute('data-stale-weekdays')){
   el.textContent=el.getAttribute('data-stale-text').replace('{n}',n);
   el.classList.add('stale');}}}
freshness();
document.addEventListener("click",function(e){
  var b=e.target.closest("button.copy");
  if(b&&b.closest("summary")){e.preventDefault();}},true);
function flt(q){q=q.toLowerCase();
 var secs=document.querySelectorAll('details.qsec');
 for(var i=0;i<secs.length;i++){var d=secs[i],any=false,histHit=false;
  var lis=d.querySelectorAll('ul.papers li');
  for(var j=0;j<lis.length;j++){var li=lis[j];
   var hit=!q||li.textContent.toLowerCase().indexOf(q)>=0;
   li.style.display=hit?'':'none';
   if(hit){any=true;if(li.className==='done')histHit=true;}}
  var openByDefault=d.classList.contains('inbox')||
                    d.classList.contains('interests');
  if(q){d.style.display=any?'':'none';d.open=any;}
  else{d.style.display='';d.open=openByDefault;}
  var h=d.querySelector('details.hist');
  if(h){h.style.display=(q&&!histHit)?'none':'';h.open=!!q&&histHit;}}}
/* --- one-tap mode ----------------------------------------------------------
   Every action button is a prefilled new-issue link, and that stays the
   fallback. With a fine-grained token pasted into the 🔑 chip (stored in this
   browser only), a tap creates that same issue from here through the GitHub
   API instead of leaving the page: same title, body and label, read back out
   of the link itself, so the workflows behind it see no difference. The row
   disappears at once and stays hidden across reloads until the re-render no
   longer carries it (or a day passes with it still there, which means the
   action failed and it comes back). 📥/📑 open an inline notes box first —
   the notes are the one thing the link could not carry filled in. */
var TOK='memory-board-token',HID='memory-board-hidden',API='https://api.github.com';
function repo(){return document.body.getAttribute('data-repo')||'';}
function token(){try{return localStorage.getItem(TOK)||'';}catch(e){return '';}}
function hiddenMap(){try{return JSON.parse(localStorage.getItem(HID)||'{}');}catch(e){return {};}}
function saveHidden(h){try{localStorage.setItem(HID,JSON.stringify(h));}catch(e){}}
function toast(msg,bad){var t=document.getElementById('toast');if(!t)return;
 t.textContent=msg;t.className=bad?'show bad':'show';
 clearTimeout(toast.h);toast.h=setTimeout(function(){t.className='';},bad?7000:4000);}
function request(a){var u;try{u=new URL(a.href);}catch(e){return null;}
 if(u.pathname.indexOf('/issues/new')<0)return null;
 var body=u.searchParams.get('body')||'';
 var m=body.match(/^(?:line|date): (.*)$/m);
 return {title:u.searchParams.get('title')||'',body:body,
  label:u.searchParams.get('labels')||'',key:m?m[1]:'',
  row:a.closest('li')||a.closest('details.qsec')};}
function gh(path,opts,tok){opts=opts||{};opts.headers={
  'Authorization':'Bearer '+(tok||token()),'Accept':'application/vnd.github+json',
  'Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28'};
 return fetch(API+'/repos/'+repo()+path,opts);}
async function createIssue(req){
 var r=await gh('/issues',{method:'POST',body:JSON.stringify(
  {title:req.title,body:req.body,labels:req.label?[req.label]:[]})});
 if(!r.ok){throw new Error('GitHub said '+r.status+
  (r.status===401||r.status===403||r.status===404?
   ' \u2014 check the token: Issues read & write on '+repo():''));}
 return (await r.json()).number;}
function hideRow(req){if(req.row)req.row.hidden=true;
 if(req.key){var h=hiddenMap();h[req.key]=Date.now();saveHidden(h);}}
function restoreHidden(){var h=hiddenMap(),seen={},now=Date.now(),changed=false;
 var as=document.querySelectorAll("a.act[href*='/issues/new']");
 for(var i=0;i<as.length;i++){var req=request(as[i]);if(!req||!req.key)continue;
  seen[req.key]=true;var ts=h[req.key];if(!ts)continue;
  if(now-ts<86400000){if(req.row)req.row.hidden=true;}
  else{delete h[req.key];changed=true;}}
 for(var k in h){if(!seen[k]){delete h[k];changed=true;}}
 if(changed)saveHidden(h);}
async function run(a,req){a.classList.add('busy');
 try{var n=await createIssue(req);hideRow(req);
  toast('queued as #'+n+' \u2014 the board re-renders itself in a minute');}
 catch(e){toast(e.message,true);}
 a.classList.remove('busy');}
function notesForm(a,req){var old=document.querySelector('.notes');if(old)old.remove();
 var f=document.createElement('div');f.className='notes';
 f.innerHTML="<textarea rows='3' placeholder='notes (optional): why this paper, "+
  "what was noteworthy \u2014 folded into the filing'></textarea><div>"+
  "<button type='button' class='go'>"+(req.label==='queue-cite'?
  '\ud83d\udcd1 make citeable':'\ud83d\udce5 intake into memory')+
  "</button> <button type='button' class='no'>cancel</button></div>";
 (a.closest('li')||a.parentNode).appendChild(f);
 var ta=f.querySelector('textarea');ta.focus();
 f.querySelector('.no').onclick=function(){f.remove();};
 f.querySelector('.go').onclick=function(){var n=ta.value.trim();
  if(n){req.body=req.body.replace(/^notes: \(optional[^\n]*$/m,
   'notes: '+n.replace(/\s*\n\s*/g,' '));}
  f.remove();run(a,req);};}
document.addEventListener('click',function(e){
 var a=e.target.closest("a.act[href*='/issues/new']");
 if(!a||!token()||!repo())return;
 var req=request(a);if(!req)return;
 e.preventDefault();
 if(req.label==='queue-intake'||req.label==='queue-cite')notesForm(a,req);
 else run(a,req);});
function keyChip(){var c=document.getElementById('onetap');if(!c)return;
 var on=!!token();c.textContent=on?'\ud83d\udd11 one-tap on \u00b7 sign out':
  '\ud83d\udd11 set up one-tap';c.className=on?'on':'';
 c.onclick=async function(){
  if(token()){try{localStorage.removeItem(TOK);}catch(e){}keyChip();
   toast('one-tap off \u2014 the buttons open GitHub again');return;}
  var t=prompt('One-tap mode: paste a fine-grained GitHub token with Issues: '+
   'read & write on '+repo()+'. It is stored only in this browser and used '+
   'only to open the queue issues from here.');
  if(!t)return;t=t.trim();
  try{var r=await gh('',{},t);if(!r.ok)throw new Error('GitHub said '+r.status);
   var j=await r.json();
   if(!(j.permissions&&j.permissions.push))throw new Error(
    'that token cannot write to '+repo());
   localStorage.setItem(TOK,t);keyChip();
   toast('one-tap on \u2014 every button now files from here');}
  catch(e){toast(e.message,true);}};}
restoreHidden();keyChip();
"""


def _pdf_act(paper: dict) -> str:
    """The 📄 chip: the paper's PDF, one tap from the board.

    First in the row on purpose — the filing actions (📥 📑 ✅) decide what to do
    *after* reading, and this is the one that gets the paper onto the phone in
    the first place. ``rel='noopener'`` + ``target='_blank'`` so collecting a
    dozen PDFs before a flight does not keep navigating the board away.
    """
    url = paper_pdf_url(paper)
    if not url:
        return ""
    hint = ("download the PDF: opens arXiv's PDF directly — no search, no "
            "abstract page in between")
    return (f"<a class='act pdf' href=\"{_html.escape(url, quote=True)}\" "
            f"target='_blank' rel='noopener' "
            f"title='{_html.escape(hint, quote=True)}'>\U0001f4c4</a>")


def _render_html(snapshot: dict) -> str:
    t_ = theme()
    t = _totals(snapshot)
    pct = round(100 * t["resolved"] / t["sections"]) if t["sections"] else 0
    repo_url = _repo_url(snapshot)

    queue_blocks = []
    for q in snapshot.get("queue") or []:
        done = (f" · {q['done']} read" if q.get("done") else "")
        items = []
        hist_items = []
        for p in q.get("papers") or []:
            if p["done"]:
                hist_items.append(
                    f"<li class='done'>DONE {_html.escape(p.get('done_date') or '?')}"
                    f" — {_html.escape(p['title'])}</li>")
                continue
            if p["kind"] == "subhead":
                items.append(f"<li class='subhead'>"
                             f"{_html.escape(p['title'])}</li>")
                continue
            if p["kind"] == "note":
                text = _html.escape(p["title"])
                if QUEUE_BARE_URL_RE.match(p["title"]):
                    # A saved link is still a link: render it clickable, just
                    # without the paper buttons it cannot honour. Labelled by
                    # host — a tracking-wrapped URL is hundreds of characters
                    # of noise on a phone, and the line itself keeps the whole
                    # thing.
                    text = (f"<a href=\"{_html.escape(p['title'], quote=True)}\" "
                            f"target='_blank' rel='noopener'>"
                            f"{_html.escape(_url_host(p['title']))} →</a>")
                items.append(f"<li class='note'>{text}</li>")
                continue
            acts = [_pdf_act(p)]
            for action, icon, hint in (
                    ("intake", "📥", "intake into memory: really interesting — "
                                     "opens a prefilled issue (add your notes) "
                                     "that becomes the full filing work item"),
                    ("cite", "📑", "make citeable: worth citing, not pivotal — "
                                   "opens a prefilled issue (add your notes) "
                                   "for a bib entry + minimal sources section"),
                    ("read", "✅", "read — don't file: opens a prefilled issue; "
                                   "submitting marks this line DONE")):
                u = _queue_issue_url(snapshot, q["section"], p, action)
                if u:
                    acts.append(f"<a class='act' href=\"{_html.escape(u, quote=True)}\" "
                                f"title='{_html.escape(hint, quote=True)}'>{icon}</a>")
            items.append(
                f"<li><a href=\"{_html.escape(paper_url(p), quote=True)}\">"
                f"{_html.escape(p['title'])}</a>{''.join(acts)}</li>")
        hist = (f"<details class='hist'><summary class='meta'>reading history "
                f"({len(hist_items)})</summary><ul class='papers'>"
                f"{''.join(hist_items)}</ul></details>" if hist_items else "")
        queue_blocks.append(
            f"<details class='qsec'><summary><span class='name'>"
            f"{_html.escape(q['section'])}</span> <span class='meta'>"
            f"{q['count']} waiting{done}</span> "
            f"{_copy_btn(_read_prompt(snapshot, q['section']), 'copy: file the next paper')}"
            f"</summary><ul class='papers'>{''.join(items)}</ul>{hist}</details>")
    if not queue_blocks:
        queue_blocks.append("<p class='meta'>queue empty or unavailable</p>")

    inbox = snapshot.get("inbox") or []
    inbox_items = []
    for p in inbox:
        acts = [_pdf_act(p)]
        for action, icon, hint in (
                ("add", "➕", "add to the reading queue: worth reading — opens "
                              "a prefilled issue; submitting files the line"),
                ("intake", "📥", "intake into memory: really interesting — "
                                 "opens a prefilled issue (add your notes) "
                                 "that becomes the full filing work item"),
                ("cite", "📑", "make citeable: worth citing, not pivotal — "
                               "opens a prefilled issue (add your notes) for a "
                               "bib entry + minimal sources section"),
                ("dismiss", "✖️", "not for me: opens a prefilled issue; "
                                  "submitting drops the line from the inbox")):
            u = _queue_issue_url(snapshot, inbox_actions.INBOX_TARGET_SECTION,
                                 p, action, source=inbox_actions.INBOX_FILE)
            if u:
                acts.append(f"<a class='act' href=\"{_html.escape(u, quote=True)}\" "
                            f"title='{_html.escape(hint, quote=True)}'>{icon}</a>")
        inbox_items.append(
            f"<li><a href=\"{_html.escape(paper_url(p), quote=True)}\">"
            f"{_html.escape(p['title'])}</a> "
            f"<span class='meta'>{p['days_left']}d left</span>{''.join(acts)}</li>")
    # The date goes into the page; the "this looks broken" verdict is left to
    # the reader's browser (_EXTRA_JS). A stale render is exactly the case the
    # warning exists for, and a stale render cannot warn about itself.
    fresh = _inbox_freshness(snapshot)
    stale_tmpl = (f"⚠ no digest since {fresh['stamp']} ({{n}} weekdays) — the "
                  f"nightly filing may be broken") if fresh["stamp"] else ""

    def _fresh_span(fresh: dict, now_text: str, stale_text: str,
                    cls: str = "meta") -> str:
        """`fresh` is explicit because the page renders two tiers, each with
        its own digest, its own stamp and its own way of going silent."""
        if fresh["state"] == "unknown":
            if fresh["reason"] not in now_text:
                now_text += " · " + fresh["reason"]
            return f"<span class='{cls}'>{_html.escape(now_text)}</span>"
        if fresh["stale"]:
            # Already stale at render time: show the warning now, so a reader
            # with JS off still sees it. The script recomputes `n` regardless.
            now_text = stale_text.replace("{n}", str(fresh["weekdays"]))
            cls += " stale"
        return (f"<span class='{cls} fresh' data-last-digest='{fresh['stamp']}' "
                f"data-stale-weekdays='{inbox_actions.INBOX_STALE_WEEKDAYS}' "
                f"data-stale-text=\"{_html.escape(stale_text, quote=True)}\">"
                f"{_html.escape(now_text)}</span>")

    if inbox_items:
        digest = f" · last digest {fresh['stamp']}" if fresh["stamp"] else ""
        meta = _fresh_span(
            fresh,
            f"{len(inbox_items)} waiting{digest} · lapse after "
            f"{inbox_actions.INBOX_WINDOW_DAYS}d",
            f"{len(inbox_items)} waiting · {stale_tmpl}")
        inbox_block = (
            f"<details class='qsec inbox' open><summary><span class='name'>"
            f"arXiv inbox</span> {meta}</summary>"
            f"<ul class='papers'>{''.join(inbox_items)}</ul></details>")
    else:
        note = _inbox_empty_note(fresh)
        inbox_block = ("<p>" + _fresh_span(
            fresh,
            f"nothing waiting — {note}",
            f"nothing waiting — {stale_tmpl}") + "</p>")

    interests = snapshot.get("interests") or []
    interest_items = []
    for p in interests:
        acts = [_pdf_act(p)]
        for action, icon, hint in (
                ("add", "\u2795", "add to the reading queue: worth reading — opens "
                              "a prefilled issue; submitting files the line"),
                ("intake", "\U0001f4e5", "intake into memory: really interesting — "
                                 "opens a prefilled issue (add your notes) "
                                 "that becomes the full filing work item"),
                ("cite", "\U0001f4d1", "make citeable: worth citing, not pivotal — "
                               "opens a prefilled issue (add your notes) for a "
                               "bib entry + minimal sources section"),
                ("dismiss", "\u2716\ufe0f", "not for me: opens a prefilled issue; "
                                  "submitting drops the line from this batch")):
            u = _queue_issue_url(snapshot, p["section"], p, action,
                                 source=interests_actions.INTERESTS_FILE)
            if u:
                acts.append(f"<a class='act' href=\"{_html.escape(u, quote=True)}\" "
                            f"title='{_html.escape(hint, quote=True)}'>{icon}</a>")
        topic = (f" <span class='topic'>{_html.escape(p['topic'])}</span>"
                 if p.get("topic") else "")
        interest_items.append(
            f"<li><a href=\"{_html.escape(paper_url(p), quote=True)}\">"
            f"{_html.escape(p['title'])}</a>{topic}{''.join(acts)}</li>")
    ifresh = _inbox_freshness(snapshot, "interests_last_digest")
    istale_tmpl = (f"\u26a0 no digest since {ifresh['stamp']} ({{n}} weekdays) — "
                   f"the nightly filing may be broken") if ifresh["stamp"] else ""
    if interest_items:
        idate = snapshot.get("interests_date") or "?"
        left = max(0, (snapshot.get("interests_batches") or 1) - 1)
        behind = (f" · {left} more day{'s' if left != 1 else ''} behind it"
                  if left else "")
        # The one non-per-paper action on the board. It sits in the <summary>
        # beside the count, because that is what it acts on: the day, not a
        # paper. No click handling needed, unlike the 📋 buttons beside it: a
        # link navigates away from the board, so whether the section also
        # toggles on the way out is not observable.
        clear_url = _interests_clear_url(snapshot, idate, len(interest_items))
        clear = (f"<a class='act clear' href=\"{_html.escape(clear_url, quote=True)}\" "
                 f"title='clear this whole day: opens a prefilled issue; "
                 f"submitting drops the {len(interest_items)} paper(s) left in "
                 f"the {idate} batch and reveals the next day'>"
                 f"\U0001f9f9 clear</a>" if clear_url else "")
        # `behind` rides on BOTH texts. A late digest is exactly when the
        # backlog depth matters most, and dropping it from the stale variant
        # hid it twice over: on a render that is already stale, and on a fresh
        # render the moment _EXTRA_JS swaps in `data-stale-text`.
        # The batch's days-left rides on both texts too, for the same reason
        # `behind` does: a late digest is exactly when it matters that the day
        # on screen is about to be swept.
        idleft = snapshot.get("interests_days_left")
        ileft = f" · {idleft}d left" if idleft is not None else ""
        imeta = _fresh_span(
            ifresh,
            f"{len(interest_items)} paper"
            f"{'s' if len(interest_items) != 1 else ''}{ileft}{behind}",
            f"{len(interest_items)} paper(s){ileft}{behind} · {istale_tmpl}")
        # The batch's date IS its name — this is a backlog of days, and which
        # day you are looking at is the first thing to know.
        interests_block = (
            f"<details class='qsec interests' open><summary><span class='name'>"
            f"{_html.escape(idate)}</span> {imeta} {clear}</summary>"
            f"<ul class='papers'>{''.join(interest_items)}</ul></details>")
    else:
        interests_block = ("<p>" + _fresh_span(
            ifresh,
            f"no batch waiting — {_inbox_empty_note(ifresh)}",
            f"no batch waiting — {istale_tmpl}") + "</p>")

    trend = _read_trend(snapshot)
    total_done = sum(q.get("done", 0) for q in snapshot.get("queue") or [])
    trend_bits = f"{t['queued']} papers waiting"
    spark = ""
    if total_done:
        trend_bits += (f" · {trend['d7']} read last 7d · "
                       f"{trend['d30']} last 30d")
        if sum(trend["weeks"]):
            mx = max(trend["weeks"])
            bars = "".join(
                f"<span class='sb' style='height:{max(2, round(12 * w / mx))}px'"
                f" title='{w}'></span>" for w in trend["weeks"])
            spark = (f" <span class='spark' title='papers read per week, "
                     f"last 8 weeks'>{bars}</span>")
    filter_box = ""
    if t["queued"]:
        filter_box = (f"<input id='pfilter' type='search' "
                      f"placeholder='filter {t['queued']} papers…' "
                      f"oninput='flt(this.value)'>")

    todo_rows = []
    for w in snapshot.get("wikis") or []:
        if not w.get("todo"):
            continue
        todo_rows.append(
            f"<tr><td class='name'>{_html.escape(w['name'])}</td>"
            f"<td>{w['todo']} of {w['sections']} sections "
            f"{_copy_btn(_todo_prompt(snapshot, w['name']), 'copy: resolve canonical keys')}"
            f"</td></tr>")
    if not todo_rows:
        todo_rows.append("<tr><td colspan='2'>every paper section cites a resolved key</td></tr>")

    wiki_rows = []
    for w in snapshot.get("wikis") or []:
        s = w.get("statuses") or {}
        link = (f"<a href=\"{_html.escape(repo_url + '/blob/main/wiki/' + w['name'] + '/index.md', quote=True)}\">"
                f"{_html.escape(w['name'])}</a>" if repo_url else _html.escape(w["name"]))
        wiki_rows.append(
            f"<tr><td class='name'>{link}</td>"
            f"<td>{w['pages']} pages · {w.get('concepts', 0)}c/"
            f"{w.get('entities', 0)}e/{w.get('sources', 0)}s"
            f"{('/' + str(w['seed']) + ' seed') if w.get('seed') else ''}</td>"
            f"<td>{_bar(s)} <span class='meta'>{s.get('stub', 0)} stub · "
            f"{s.get('drafted', 0)} drafted</span> "
            f"{_copy_btn(_stub_prompt(snapshot, w['name']), 'copy: upgrade a stub')} "
            f"{_copy_btn('Use the memory skill. ' + w['name'], 'copy: recall this domain')}"
            f"</td></tr>")

    n_batches = snapshot.get("interests_batches") or 0
    interests_backlog_note = (
        f"; {n_batches} day{'s' if n_batches != 1 else ''} of backlog, "
        f"{snapshot.get('interests_backlog') or 0} papers"
        if n_batches else "")

    filings = snapshot.get("filings") or []
    filing_items = []
    for f in filings:
        if repo_url:
            issue_link = (f"<a href=\"{repo_url}/issues/{f['issue']}\">"
                          f"#{f['issue']}</a>")
            pr = (f"<a class='act' href=\"{repo_url}/compare/main..."
                  f"{_html.escape(f['branch'], quote=True)}?expand=1\" "
                  f"title='open the PR that merges this filing into memory'>"
                  f"\U0001f500 open PR</a>")
        else:
            issue_link, pr = f"#{f['issue']}", ""
        filing_items.append(
            f"<li>{issue_link} <span class='meta'>"
            f"{_html.escape(f['branch'])}</span>{pr}</li>")
    # Above everything else when present, absent otherwise: it is the one
    # section that is a human's merge, and an empty "nothing waiting" line
    # would only teach the eye to skip it.
    filings_block = (
        f"<h2 id='filings'>Filings awaiting merge <span class=\"muted\">({len(filing_items)} "
        f"on a branch, not yet in memory — merge the PR to finish the "
        f"intake)</span></h2><ul class='papers'>{''.join(filing_items)}</ul>"
        if filing_items else "")

    navigation = [
        {"href": "#arxiv-inbox", "label": "arXiv inbox"},
        {"href": "#arxiv-interests", "label": "arXiv interests"},
        {"href": "#reading-queue", "label": "Reading queue", "count": t["queued"]},
        {"href": "#citation-work", "label": "To cite", "count": t["todo"]},
        {"href": "#sub-wikis", "label": "Pages", "count": t["pages"], "context": f"{pct}% cited"},
    ]
    if _catch_up_html(snapshot):
        navigation.insert(0, {"href": "#catch-up", "label": "Catch up"})
    if filing_items:
        navigation.insert(0, {"href": "#filings", "label": "Filings awaiting merge", "count": len(filing_items)})
    hero = t_.hero(BOARD_KEY, "Dashboard", _LEDE, navigation=navigation)
    repo_url = _repo_url(snapshot)
    panel = t_.orchestration_panel(
        "memory", "", "", CHECKIN_PROMPT,
        work_links=([{"label": snapshot["repo"], "href": repo_url}] if repo_url else []),
        organ="memory", refreshed_at=snapshot.get("generated"),
        refresh_url=(repo_url + "/actions/workflows/knowledge_board.yml" if repo_url else None))
    # One-tap mode needs the API's owner/repo and a place to turn it on; both
    # drop out with the repo identity, like every other GitHub-facing chip.
    owner, repo = snapshot.get("owner"), snapshot.get("repo")
    body_attrs = (f' data-repo="{_html.escape(owner + "/" + repo, quote=True)}"'
                  if repo_url else "")
    onetap = (" · <button type='button' id='onetap' title='one-tap mode: file "
              "every button from this page instead of opening GitHub — paste "
              "a fine-grained token once, kept in this browser only'>"
              "\U0001f511 set up one-tap</button>" if repo_url else "")
    return t_.section_layout(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PyAutoMemory Dashboard</title>
<style>{t_.css(BOARD_KEY)}{_EXTRA_CSS}</style>
</head>
<body{body_attrs}>
{hero}
{panel}
<section id="catch-up">{_catch_up_html(snapshot)}</section>
<p class="muted mdsrc"><a href="dashboard.md">markdown version</a>{onetap}</p>
<div id="toast"></div>
{filings_block}
<h2 id='arxiv-inbox'>arXiv inbox <span class="muted">(suggested overnight — un-acted papers
 lapse after {inbox_actions.INBOX_WINDOW_DAYS} days)</span></h2>
{inbox_block}
<h2 id='arxiv-interests'>arXiv interests <span class="muted">(everything that is not strong
 lensing — one day's ten at a time; \U0001f9f9 clears the day and shows the
 next; un-cleared batches lapse after {inbox_actions.INBOX_WINDOW_DAYS} days
{interests_backlog_note})</span></h2>
{interests_block}
<h2 id='reading-queue'>Reading queue <span class="muted">({trend_bits})</span>{spark}</h2>
{filter_box}
{''.join(queue_blocks)}
<h2 id='citation-work'>Citation work queue <span class="muted">({t['todo']} sections need a
 canonical key)</span></h2>
<table class="recent">{''.join(todo_rows)}</table>
<h2 id='sub-wikis'>Sub-wikis <span class="muted">({snapshot.get('bib_entries', 0)} bibliography
 entries · {snapshot.get('links', {}).get('wanted', 0)} wanted pages)</span></h2>
<table class="recent">{''.join(wiki_rows)}</table>
{_boards_nav(snapshot)}
<footer>Rendered by <code>scripts/board.py</code> from the checkout —
nothing here is committed; generated
{_html.escape(str(snapshot.get('generated') or '?'))}.</footer>
<script>{t_.JS}{_EXTRA_JS}</script>
</body></html>
""")


def badge_endpoint(snapshot: dict) -> dict:
    t = _totals(snapshot)
    if not t["pages"]:
        return {"schemaVersion": 1, "label": "knowledge",
                "message": "unknown", "color": "lightgrey"}
    pct = round(100 * t["resolved"] / t["sections"]) if t["sections"] else 0
    return {"schemaVersion": 1, "label": "knowledge",
            "message": f"{t['pages']} pages · {pct}% cited", "color": "blueviolet"}


# --- the organ-cockpit feed (state.json, contract v1) ---------------------------
# One small, schema-pinned document per organ that the Brain's cockpit polls
# (``state.json`` on Pages, beside badge.json). It is a PROJECTION of the same
# snapshot every other surface renders, so the cockpit can never disagree with
# this board; the contract is owned by the Brain (``board/state_schema.json``,
# validated by ``board/_state.py`` in CI) and the Memory only ever emits it —
# it never imports the Brain to do so, so the script still travels into
# spawned templates that have no Brain beside them.
STATE_SCHEMA_VERSION = 1
STATE_STATUSES = ("green", "yellow", "red", "stale", "grey")
_STATE_TEXT_MAX = 160
# The inbox can hold dozens of suggestions; the cockpit is a glance, not the
# queue, so only the first few become rows — the board page holds the rest.
_STATE_INBOX_CAP = 5


def _iso_z(ts) -> str:
    """``ts`` as ISO-8601 UTC with a ``Z`` suffix, whole seconds.

    ``collect`` stamps ``datetime.now(utc).isoformat()`` (``+00:00`` with
    microseconds) and a hand-built snapshot may be naive; the cockpit compares
    ages across organs on one clock, so both are normalised (naive is read as
    UTC). An unparseable or empty stamp becomes *now* — the moment this feed
    was written — rather than a string the validator would reject.
    """
    try:
        t = datetime.datetime.fromisoformat(str(ts)) if ts else None
    except ValueError:
        t = None
    if t is None:
        t = datetime.datetime.now(datetime.timezone.utc)
    elif t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)
    return t.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clip(text, limit: int = _STATE_TEXT_MAX) -> str:
    """One line of at most ``limit`` chars — the contract's row width."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def to_state(snapshot: dict) -> dict:
    """The organ-cockpit feed (fmt='state'): contract v1 of PyAutoBrain#416.

    status: grey when no wiki pages were observed (nothing read is never
    green — a spawned template or a broken checkout must not look fine);
    yellow when a suggestion digest has gone stale, a filing waits on a merge,
    or any sub-wiki still carries stub pages or TODO BibTeX keys; else green.
    There is deliberately NO red: the Memory holds knowledge, nothing in it can
    break or block a release — the worst it can be is behind.

    The headline is the badge message (so the cockpit and the README badge say
    the same thing), prefixed with the first reason when yellow. Items are the
    rows that ask something of a human, most urgent first, each carrying the
    same copy-for-assistant prompt or issue link the board page offers.
    """
    t = _totals(snapshot)
    repo_url = _repo_url(snapshot)
    # A remote-less checkout (spawned template, test tree) has no Pages URL;
    # state.json is published beside index.html, so "./" is the board itself.
    page = pages_url(snapshot) or "./"
    state = {
        "schema_version": STATE_SCHEMA_VERSION,
        "organ": BOARD_KEY,
        "repo": snapshot.get("repo") or "PyAutoMemory",
        "status": "grey",
        "headline": "no wiki pages observed",
        "updated": _iso_z(snapshot.get("generated")),
        "pages_url": page,
        "items": [],
        # Days since memory last ingested a paper (None: nothing on record).
        "days_since_ingest": _days_since_ingest(snapshot),
        "lensing_catch_up": _lensing_catch_up(snapshot),
        "digests": {spec[0]: _inbox_freshness(snapshot, key) for key, spec in DIGESTS.items()},
    }
    if not t["pages"]:
        return state

    yellow: list[dict] = []
    info: list[dict] = []
    reasons: list[str] = []
    for fresh in state["digests"].values():
        if fresh["state"] != "healthy":
            label = fresh["label"]
            text = f"{label} digest stale" if fresh["stale"] else f"{label} digest freshness unknown"
            reasons.append(text)
            prompt = next(a["target"] for a in fresh["actions"] if a["id"] == "investigate")
            yellow.append({
                "id": fresh["id"], "state": fresh["state"],
                "severity": "yellow" if fresh["stale"] else "info",
                "text": _clip(text), "reason": fresh["reason"],
                "url": fresh["evidence_url"], "prompt": prompt,
                "actions": fresh["actions"],
                "recommended_action_id": fresh["recommended_action_id"],
            })
    filings = snapshot.get("filings") or []
    if filings:
        reasons.append("filings awaiting merge")
        for f in filings:
            yellow.append({
                "severity": "yellow",
                "text": _clip(f"filing #{f['issue']} reached {f['branch']} "
                              f"but not main — open and merge its PR"),
                "url": (f"{repo_url}/compare/main...{f['branch']}?expand=1"
                        if repo_url else None),
                "prompt": None})
    waiting = False
    for w in snapshot.get("wikis") or []:
        stubs = (w.get("statuses") or {}).get("stub", 0)
        todos = w.get("todo", 0)
        if not (stubs or todos):
            continue
        waiting = True
        # One row per wiki, but its prompt names the bigger job first: TODO
        # keys block citation, stubs only block maturity.
        prompt = (_todo_prompt(snapshot, w["name"]) if todos
                  else _stub_prompt(snapshot, w["name"]))
        info.append({
            "severity": "info",
            "text": _clip(f"{w['name']}: {stubs} stub{'s' if stubs != 1 else ''}"
                          f", {todos} todo{'s' if todos != 1 else ''}"),
            "url": (f"{repo_url}/tree/main/wiki/{w['name']}" if repo_url
                    else None),
            "prompt": prompt})
    if waiting:
        reasons.append("stubs/todos waiting")
    for p in (snapshot.get("inbox") or [])[:_STATE_INBOX_CAP]:
        info.append({
            "severity": "info",
            "text": _clip(f"inbox: {p['title']} ({p.get('days_left')}d left)"),
            "url": _queue_issue_url(snapshot,
                                    inbox_actions.INBOX_TARGET_SECTION, p,
                                    "add", source=inbox_actions.INBOX_FILE)
            or None,
            "prompt": None})

    catchup = state["lensing_catch_up"]
    if catchup["state"] != "healthy":
        stale = catchup["state"] == "stale"
        text = "Strong-lensing catch-up due" if stale else "Strong-lensing freshness unknown"
        reasons.append(text)
        yellow.append({
            "id": catchup["id"], "severity": "yellow" if stale else "info",
            "state": catchup["state"], "text": text, "reason": catchup["reason"],
            "url": catchup["evidence"][0]["url"] if catchup["evidence"] else page,
            "prompt": CATCH_UP_CMD, "actions": catchup["actions"],
            "recommended_action_id": catchup["recommended_action_id"],
        })

    badge = badge_endpoint(snapshot)["message"]
    state.update(
        status="yellow" if reasons else "green",
        headline=_clip(f"{reasons[0]} · {badge}" if reasons else badge),
        items=yellow + info)
    return state


def render(snapshot: dict, fmt: str = "md") -> str:
    if fmt == "md":
        return _render_md(snapshot)
    if fmt == "md-brief":
        return _render_md_brief(snapshot)
    if fmt == "html":
        return _render_html(snapshot)
    if fmt == "badge":
        return json.dumps(badge_endpoint(snapshot))
    if fmt == "state":
        return json.dumps(to_state(snapshot), indent=2)
    if fmt == "json":
        return json.dumps({**snapshot, "pages_url": pages_url(snapshot)},
                          indent=2, sort_keys=True)
    raise ValueError(f"unknown board fmt: {fmt!r}")


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="scripts/board.py", description=__doc__)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--md", action="store_true", help="markdown board (default)")
    g.add_argument("--md-brief", action="store_true", help="the README strip")
    g.add_argument("--html", action="store_true", help="the Pages page")
    g.add_argument("--badge", action="store_true", help="shields endpoint JSON")
    g.add_argument("--state", action="store_true",
                   help="organ-cockpit state.json feed (Brain contract v1)")
    g.add_argument("--json", action="store_true", help="the machine surface")
    ns = ap.parse_args(argv)
    snap = collect()
    fmt = "md"
    for name, label in (("md", "md"), ("md_brief", "md-brief"),
                        ("html", "html"), ("badge", "badge"), ("json", "json"),
                        ("state", "state")):
        if getattr(ns, name):
            fmt = label
            break
    print(render(snap, fmt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
