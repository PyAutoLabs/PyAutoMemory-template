"""scripts/catch_up.py — everything memory missed while nobody was filing.

The suggestion tiers are built for a human who looks every day. ``arxiv-inbox.md``
and ``arxiv-interests.md`` lapse after :data:`inbox_actions.INBOX_WINDOW_DAYS`,
the reading queue only grows, and the nightly digest itself has gaps (it never
ran 2026-09-17→22 or 09-24→28, so for most of that fortnight nothing was even
fetched). After time away there is no single place that says *what did I miss*.
This script is that place; the ``/catch_up`` skill (``skills/catch_up/``) is the
curation and filing on top of it.

It answers two questions, both per **scope** (:data:`SCOPES`):

1. **When did memory last take a paper in?** — :func:`last_ingested`. The
   newest of (a) a ``DONE <date>`` line in the scope's reading-queue sections
   and (b) a commit that adds an ``@type{key,`` entry to
   ``bibliography/pyautomemory.bib`` *and* touches the scope's
   ``wiki/<domain>/sources/``. Both halves, because either alone lies: a bib
   commit with no sources page is a citation tidy-up, and a sources commit
   with no new entry is a restructure (the 2026-09-17 seed split touched every
   lensing sources page and ingested nothing). Merges are diffed against their
   first parent, so a ``queue-filing/`` branch counts on the day it landed on
   ``main``. The dashboard banner reads this too — git-only, never network.

2. **What arrived since?** — three harvests, deduped by arXiv id (else a
   normalised title), minus anything already in memory (id or title in the
   ``.bib``, or a ``DONE`` line anywhere in the queue):

   * ``history`` — every line ever *added* to the scope's suggestion file, read
     from ``git log -p``. A swept line is not lost, git holds it; this is where
     it comes back from.
   * ``queue`` — the open paper lines of the scope's reading-queue sections
     (``DONE``/``NOTE``/``__sub-heading__`` lines are not papers; ``board.py``'s
     ``_parse_paper`` decides, so there is one grammar).
   * ``arxiv`` — the Mind digest's own query re-run over the whole window, which
     is what fills the digest's gaps. The query and the fetch/parse are imported
     from ``PyAutoMind/.github/scripts/`` rather than copied, so "strong
     lensing" means the same thing here as it does at 02:00 UTC. Anything
     harvested without an abstract is then looked up by id in one request, so
     the curating agent reads abstracts rather than titles.

The network half is best-effort by design: Mind missing, arXiv refusing, a
timeout — each is a ``warnings`` entry on stderr and the source is skipped. A
catch-up that crashes because arXiv 429'd would lose the git harvest too.

**Interests volume.** The interests query is *categories* (a few hundred papers
a day), so over weeks it is thousands. It is capped at :data:`INTERESTS_ARXIV_CAP`
most-recent results, ranked by the Mind digest's own interest scorer, and the
cap is reported as ``truncated`` — interests curation leans on the interests
file's history, and ``--topic`` narrows the query to that topic's terms.

Pure functions + a thin CLI, stdlib only. ``--json`` is the skill's input.

Usage:
    python scripts/catch_up.py --scope lensing [--json]
    python scripts/catch_up.py --scope interests --topic SMBHs
    python scripts/catch_up.py --scope all --since 2026-09-01 --offline
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arxiv_refs  # noqa: E402
import inbox_actions  # noqa: E402
import interests_actions  # noqa: E402

MEMORY_HOME = Path(__file__).resolve().parents[1]
BIB_FILE = "bibliography/pyautomemory.bib"

#: What each scope means on disk: the reading-queue sections it owns, the
#: sub-wikis whose ``sources/`` count as an ingest, the suggestion file whose
#: history is harvested, and which Mind digest's query fills the gaps.
#: Section names are ``reading-queue.md`` headers verbatim. "Interests" is the
#: interests list's fallback section (``interests_actions.FALLBACK_SECTION``),
#: so a paper ➕'d from it is caught. Project sections (SETI, Cancer, KetJU)
#: are deliberately out of every scope — they are not arXiv-fed reading.
SCOPES = {
    "lensing": {
        "sections": ("Strong Lensing",),
        "domains": ("lensing",),
        "suggestions": inbox_actions.INBOX_FILE,
        "digest": "arxiv_fetch",
    },
    "interests": {
        "sections": ("SMBHs", "Galaxy Formation / Evolution", "Dark Matter",
                     "Stats", interests_actions.FALLBACK_SECTION),
        "domains": ("smbh", "galaxies", "methods"),
        "suggestions": interests_actions.INTERESTS_FILE,
        "digest": "arxiv_interests",
    },
}
#: The sub-wiki a single interests topic files into, for ``--topic``. A topic
#: with no sub-wiki of its own (Dark Matter) is dated by its DONE lines alone.
TOPIC_DOMAINS = {"SMBHs": ("smbh",), "Galaxy Formation / Evolution": ("galaxies",),
                 "Stats": ("methods",), "Dark Matter": (), "Interests": ()}

#: Submission lead before the cutoff. A paper *announced* on the cutoff day was
#: submitted one to three days earlier (a weekend band is three), so the arXiv
#: window opens that far back; anything already filed dedups away.
ANNOUNCE_LAG_DAYS = 3
#: The lensing query is ~1.5 papers a day; pages are a runaway guard.
LENSING_PAGE_SIZE = 100
LENSING_MAX_PAGES = 5
#: The interests query is whole categories. Most-recent-first, so the cap keeps
#: the newest days whole and loses the oldest — reported, never silent.
INTERESTS_ARXIV_CAP = 300
INTERESTS_PAGE_SIZE = 100
#: arXiv's API terms ask for 3 s between requests.
ARXIV_PAUSE_S = 3.0
#: One id_list lookup fills abstracts for harvested ids; the API pages at ~200.
ENRICH_BATCH = 100

SOURCE_ORDER = ("queue", "history", "arxiv")

BIB_ENTRY_ADD_RE = re.compile(r"^\+@\w+\{")
BIB_ID_RE = re.compile(
    r"^\s*(?:eprint|arxivid|url|doi)\s*=\s*[{\"](.*?)[}\"]\s*,?\s*$",
    re.IGNORECASE)
BIB_TITLE_RE = re.compile(r"^\s*title\s*=\s*\{(.*)\}\s*,?\s*$", re.IGNORECASE)
ARXIV_NUM_RE = re.compile(r"(\d{4}\.\d{4,5})")
DONE_DATE_RE = re.compile(r"^DONE\s+(\d{4}-\d{2}-\d{2})\b")
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")


# --- keys ----------------------------------------------------------------------
def norm_title(title: str | None) -> str:
    """A title reduced to what survives BibTeX bracing, LaTeX and re-typing.

    Stronger than ``inbox_actions.identity``'s case-fold: a bib title arrives as
    ``{{TDCOSMO XXVIII. … J1537$-$3010 …}}`` and a queue line as plain text, so
    only letters and digits are compared.
    """
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())


def paper_id(ref: str | None) -> str | None:
    """The bare arXiv number in a queue/inbox ref, or None."""
    return arxiv_refs.arxiv_id(ref) if ref else None


# --- scope ----------------------------------------------------------------------
def resolve_scope(scope: str, topic: str | None = None) -> dict:
    """The sections/domains/suggestion files a scope (and topic) covers.

    ``all`` is the union. A ``topic`` narrows interests to one section; naming a
    topic under ``lensing`` is an error rather than a silent no-op.
    """
    if scope == "all":
        parts = [SCOPES["lensing"], SCOPES["interests"]]
    elif scope in SCOPES:
        parts = [SCOPES[scope]]
    else:
        raise ValueError(f"unknown scope {scope!r} (lensing|interests|all)")
    if topic:
        if scope == "lensing":
            raise ValueError("--topic narrows the interests scope only")
        if topic not in SCOPES["interests"]["sections"]:
            raise ValueError(f"unknown topic {topic!r}: one of "
                             + ", ".join(SCOPES["interests"]["sections"]))
    sections, domains, files = [], [], []
    for p in parts:
        is_interests = p is SCOPES["interests"]
        sec = (topic,) if (topic and is_interests) else p["sections"]
        dom = TOPIC_DOMAINS.get(topic, ()) if (topic and is_interests) else p["domains"]
        sections += sec
        domains += dom
        files.append((p["suggestions"], p["digest"]))
    return {"scope": scope, "topic": topic, "sections": tuple(sections),
            "domains": tuple(domains), "files": files}


# --- the queue ------------------------------------------------------------------
def queue_sections(queue_text: str) -> dict[str, list[dict]]:
    """``{section: [parsed line, …]}`` via ``board._parse_paper`` — one grammar.

    Imported lazily: ``board`` imports this module for the banner, and a
    module-level import in both directions is a cycle.
    """
    import board  # noqa: PLC0415
    out: dict[str, list[dict]] = {}
    section = None
    for line in queue_text.splitlines():
        m = SECTION_RE.match(line)
        if m and not m.group(1).startswith("#"):
            section = m.group(1)
            out.setdefault(section, [])
        elif section is not None and line.strip():
            out[section].append(board._parse_paper(line.strip()))
    return out


def last_done(queue_text: str, sections) -> str | None:
    """The newest ``DONE <date>`` in the named sections (all when None)."""
    best = None
    for sec, lines in queue_sections(queue_text).items():
        if sections is not None and sec not in sections:
            continue
        for p in lines:
            d = p.get("done_date")
            if d and (best is None or d > best):
                best = d
    return best


# --- git -------------------------------------------------------------------------
def _git(root: Path, *args: str) -> str | None:
    """stdout of a git command in ``root``, or None when git/the repo is absent."""
    try:
        got = subprocess.run(["git", "-C", str(root), *args],
                             capture_output=True, text=True, errors="replace",
                             timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return got.stdout if got.returncode == 0 else None


def parse_ingest_log(log: str, domains) -> dict | None:
    """The newest ingest commit in a ``git log -p`` of bib + sources.

    ``log`` is ``git log --format=%x00%cs %h --unified=0 -p`` output: commits
    separated by NUL. A commit is an ingest when it adds a bib entry AND touches
    one of ``domains``' ``sources/``. Max by date, not first-seen: merge commits
    and their branch commits interleave out of date order.
    """
    prefixes = tuple(f"wiki/{d}/sources/" for d in domains)
    best = None
    for chunk in log.split("\x00"):
        if not chunk.strip():
            continue
        head, _, body = chunk.partition("\n")
        date, _, sha = head.strip().partition(" ")
        current, adds, touched = None, False, False
        for line in body.splitlines():
            if line.startswith("diff --git "):
                current = line.rsplit(" b/", 1)[-1]
                if prefixes and current.startswith(prefixes):
                    touched = True
            elif current == BIB_FILE and BIB_ENTRY_ADD_RE.match(line):
                adds = True
        if adds and touched and (best is None or date > best["date"]):
            best = {"date": date, "commit": sha}
    return best


def last_bib_ingest(root: Path, domains) -> dict | None:
    if not domains:
        return None
    # A shallow clone (CI's default checkout) diffs its one commit against
    # nothing, so every bib entry looks added today and the banner would never
    # show. No history, no evidence: the DONE half stands alone.
    if (_git(root, "rev-parse", "--is-shallow-repository") or "").strip() == "true":
        return None
    paths = [BIB_FILE] + [f"wiki/{d}/sources" for d in domains]
    log = _git(root, "log", "--diff-merges=first-parent", "--unified=0",
               "--format=%x00%cs %h", "-p", "--", *paths)
    return parse_ingest_log(log, domains) if log else None


def ingest_evidence(scope: str = "all", root: Path | None = None,
                    topic: str | None = None) -> dict:
    """Both halves of the cutoff, for reporting: DONE date and ingest commit."""
    root = root or MEMORY_HOME
    spec = resolve_scope(scope, topic)
    queue = root / inbox_actions.QUEUE_FILE
    text = queue.read_text(errors="replace") if queue.exists() else ""
    done = last_done(text, spec["sections"])
    bib = last_bib_ingest(root, spec["domains"])
    dates = [d for d in (done, bib and bib["date"]) if d]
    return {"done": done, "bib": bib, "last_ingested": max(dates) if dates else None}


def last_ingested(scope: str = "all", root: Path | None = None,
                  topic: str | None = None) -> str | None:
    """The date memory last took a paper in, for ``scope``. Git + files only."""
    return ingest_evidence(scope, root, topic)["last_ingested"]


# --- in-memory index -----------------------------------------------------------------
def in_memory_index(bib_text: str, queue_text: str) -> tuple[set, set]:
    """``(ids, titles)`` already in memory: the bib, plus every DONE line."""
    ids, titles = set(), set()
    for line in bib_text.splitlines():
        m = BIB_ID_RE.match(line)
        if m:
            ids |= set(ARXIV_NUM_RE.findall(m.group(1)))
            continue
        m = BIB_TITLE_RE.match(line)
        if m:
            titles.add(norm_title(m.group(1)))
    for lines in queue_sections(queue_text).values():
        for p in lines:
            if p.get("done") and p.get("kind") == "paper":
                pid = paper_id(p.get("ref"))
                if pid:
                    ids.add(pid)
                titles.add(norm_title(p.get("title")))
    titles.discard("")
    return ids, titles


# --- harvests --------------------------------------------------------------------
def parse_history(log: str, suggestions_file: str, since: str,
                  topic: str | None = None) -> list[dict]:
    """Paper lines ever added to a suggestion file, dated on or after ``since``.

    ``log`` is ``git log -p`` of the file; only ``+`` lines are read, so a line
    later swept or dismissed still comes back. The line's own date is the
    anchor (the announcement date), not the commit's.
    """
    interests = suggestions_file == interests_actions.INTERESTS_FILE
    out = []
    for raw in log.splitlines():
        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        line = raw[1:]
        if interests:
            got = interests_actions.parse_line(line)
            if not got:
                continue
            added, tag, rest = got
        else:
            got = inbox_actions.parse_line(line)
            if not got:
                continue
            (added, rest), tag = got, None
        if added < since:
            continue
        if topic and (tag or interests_actions.FALLBACK_SECTION) != topic:
            continue
        title, ref = inbox_actions.split_ref(rest)
        out.append({"id": paper_id(ref), "title": title, "ref": ref,
                    "date": added, "topic": tag, "source": "history"})
    return out


def harvest_history(root: Path, suggestions_file: str, since: str,
                    topic: str | None = None) -> list[dict]:
    log = _git(root, "log", "-p", "--format=", "--", suggestions_file) or ""
    # The working copy too: an uncommitted local line is still a suggestion.
    path = root / suggestions_file
    if path.exists():
        log += "\n" + "\n".join("+" + ln for ln in
                                path.read_text(errors="replace").splitlines())
    return parse_history(log, suggestions_file, since, topic)


def harvest_queue(queue_text: str, sections) -> list[dict]:
    """Open paper lines of the named sections, in file order."""
    out = []
    for sec, lines in queue_sections(queue_text).items():
        if sec not in sections:
            continue
        for p in lines:
            if p.get("kind") != "paper" or p.get("done"):
                continue
            out.append({"id": paper_id(p.get("ref")), "title": p["title"],
                        "ref": p.get("ref"), "date": None, "section": sec,
                        "source": "queue"})
    return out


# --- arXiv (network, best-effort) -------------------------------------------------------
def mind_scripts_dir(root: Path | None = None) -> Path | None:
    """PyAutoMind's ``.github/scripts``: ``$PYAUTO_MIND``, else the Brain resolver.

    The Brain's ``agents/_repo_paths.py`` is the one place that knows how a
    workspace lays repos out (flat, family dirs, task bundles); it is found by
    walking up from this checkout. A sibling ``PyAutoMind`` is the last resort.
    """
    root = root or MEMORY_HOME
    cands = []
    if os.environ.get("PYAUTO_MIND"):
        cands.append(Path(os.environ["PYAUTO_MIND"]))
    for parent in (root, *root.parents):
        resolver = None
        for brain in (parent / "organs" / "PyAutoBrain", parent / "PyAutoBrain"):
            if (brain / "agents" / "_repo_paths.py").is_file():
                resolver = brain / "agents" / "_repo_paths.py"
                break
        if resolver:
            try:
                mod = _load(resolver, "_pyauto_repo_paths")
                cands.append(Path(mod.repo_path(parent, "PyAutoMind")))
            except Exception:  # noqa: BLE001 — a resolver fault is a fallback
                pass
            break
    cands.append(root.parent / "PyAutoMind")
    for c in cands:
        d = c / ".github" / "scripts"
        if (d / "arxiv_fetch.py").is_file():
            return d
    return None


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_digests(scripts_dir: Path) -> dict:
    """``{"arxiv_fetch": mod, "arxiv_interests": mod}`` from Mind, by file path.

    ``arxiv_interests`` does ``import arxiv_fetch`` itself, so the scripts dir
    goes on ``sys.path`` for the duration.
    """
    sys.path.insert(0, str(scripts_dir))
    try:
        fetch = _load(scripts_dir / "arxiv_fetch.py", "arxiv_fetch")
        interests = _load(scripts_dir / "arxiv_interests.py", "arxiv_interests")
    finally:
        sys.path.remove(str(scripts_dir))
    return {"arxiv_fetch": fetch, "arxiv_interests": interests}


def window_query(query: str, start: datetime.date, end: datetime.date) -> str:
    """The digest's query restricted to a submission window (UTC, inclusive)."""
    return (f"({query}) AND submittedDate:[{start:%Y%m%d}0000 TO "
            f"{end:%Y%m%d}2359]")


def _band(start: datetime.date, end: datetime.date):
    """``parse``'s half-open band, wide enough to keep the whole window."""
    utc = datetime.timezone.utc
    lo = datetime.datetime(start.year, start.month, start.day, tzinfo=utc)
    hi = datetime.datetime(end.year, end.month, end.day, tzinfo=utc)
    return lo - datetime.timedelta(seconds=1), hi + datetime.timedelta(days=1)


def _to_candidate(paper: dict, source: str = "arxiv") -> dict:
    aid = arxiv_refs.arxiv_id(paper["url"])
    return {"id": aid, "title": paper["title"], "ref": aid,
            "date": (paper.get("published") or "")[:10] or None,
            "authors": paper.get("authors") or [],
            "abstract": paper.get("abstract"),
            "primary_category": paper.get("primary_category"),
            "topic": paper.get("topic"), "source": source}


def harvest_arxiv(digests: dict, digest: str, start: datetime.date,
                  end: datetime.date, topic: str | None = None,
                  pause: float = ARXIV_PAUSE_S) -> tuple[list[dict], bool]:
    """One paged sequence of the digest's query over the window.

    Returns ``(candidates, truncated)``. Lensing pages to the end of the window;
    interests stops at :data:`INTERESTS_ARXIV_CAP`, ranks with the digest's own
    scorer, keeps the scope's topic(s), and drops what the lensing net catches
    (that is the other scope's paper).
    """
    fetch = digests["arxiv_fetch"]
    if digest == "arxiv_fetch":
        query, size, pages = fetch.QUERY, LENSING_PAGE_SIZE, LENSING_MAX_PAGES
    else:
        mod = digests["arxiv_interests"]
        query = mod.QUERY
        if topic and topic in getattr(mod, "INTERESTS", {}):
            terms = mod.INTERESTS[topic]
            query = (f"({query}) AND ("
                     + " OR ".join(f'abs:"{t}"' for t in terms) + ")")
        size = INTERESTS_PAGE_SIZE
        pages = -(-INTERESTS_ARXIV_CAP // size)
    q = window_query(query, start, end)
    lo, hi = _band(start, end)
    got, seen, truncated = [], set(), True
    for page in range(pages):
        if page:
            time.sleep(pause)
        raw = fetch.fetch(q, size, start=page * size)
        batch = fetch.parse(raw, lo, hi)
        n_entries = raw.count(b"<entry>") if isinstance(raw, bytes) else len(batch)
        for p in batch:
            if p["url"] not in seen:
                seen.add(p["url"])
                got.append(p)
        if n_entries < size:
            truncated = False
            break
    if digest == "arxiv_fetch":
        return [_to_candidate(p) for p in got], truncated
    mod = digests["arxiv_interests"]
    ranked, _ = mod.rank(got, cap=len(got) or 1)
    keep = SCOPES["interests"]["sections"] if not topic else (topic,)
    out = [_to_candidate(p) for p in ranked
           if not p.get("strong_lensing") and (p.get("topic") or "Interests") in keep]
    return out, truncated


def enrich(digests: dict, ids: list[str], pause: float = ARXIV_PAUSE_S) -> dict:
    """``{id: arXiv record}`` for ids harvested without an abstract."""
    fetch = digests["arxiv_fetch"]
    lo = datetime.datetime(1991, 1, 1, tzinfo=datetime.timezone.utc)
    hi = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=2)
    out = {}
    for i in range(0, len(ids), ENRICH_BATCH):
        if i:
            time.sleep(pause)
        chunk = ids[i:i + ENRICH_BATCH]
        raw = fetch._get({"id_list": ",".join(chunk), "max_results": len(chunk)})
        for p in fetch.parse(raw, lo, hi):
            c = _to_candidate(p)
            if c["id"]:
                out[c["id"]] = c
    return out


# --- merge -------------------------------------------------------------------------
def merge(harvests: list[dict], ids_in_memory: set, titles_in_memory: set
          ) -> tuple[list[dict], int]:
    """Dedup across sources and drop what memory already holds.

    Keyed by arXiv id, falling back to the normalised title (and an id-less
    line still meets its id'd twin through the title). The first source in
    :data:`SOURCE_ORDER` owns the record; later ones land in ``also_in`` and
    fill any field the owner lacked (the abstract, usually). Returns
    ``(candidates, dropped_as_in_memory)``.
    """
    rank = {s: i for i, s in enumerate(SOURCE_ORDER)}
    by_id: dict[str, dict] = {}
    by_title: dict[str, dict] = {}
    records: list[dict] = []
    dropped: set = set()
    for h in sorted(harvests, key=lambda h: rank.get(h["source"], 99)):
        nt = norm_title(h.get("title"))
        key = h.get("id") or nt
        if (h.get("id") and h["id"] in ids_in_memory) or (nt and nt in titles_in_memory):
            dropped.add(key)
            continue
        rec = (by_id.get(h["id"]) if h.get("id") else None) or (by_title.get(nt) if nt else None)
        if rec is None:
            rec = {"id": None, "title": None, "ref": None, "date": None,
                   "authors": [], "abstract": None, "section": None,
                   "topic": None, "primary_category": None,
                   "source": h["source"], "also_in": []}
            records.append(rec)
        elif h["source"] != rec["source"] and h["source"] not in rec["also_in"]:
            rec["also_in"].append(h["source"])
        for k, v in h.items():
            if k in ("source",):
                continue
            if v and not rec.get(k):
                rec[k] = v
        if rec.get("id"):
            by_id[rec["id"]] = rec
        if nt:
            by_title[nt] = rec
    for rec in records:
        rec["first_author"] = rec["authors"][0] if rec.get("authors") else None
        rec["url"] = f"https://arxiv.org/abs/{rec['id']}" if rec.get("id") else None
    return records, len(dropped)


# --- the whole run ----------------------------------------------------------------------
def catch_up(scope: str = "lensing", topic: str | None = None,
             since: str | None = None, today: datetime.date | None = None,
             root: Path | None = None, offline: bool = False,
             digests: dict | None = None, pause: float = ARXIV_PAUSE_S) -> dict:
    """The report the CLI prints and the skill curates. ``digests`` stubs arXiv."""
    root = root or MEMORY_HOME
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    spec = resolve_scope(scope, topic)
    evidence = ingest_evidence(scope, root, topic)
    warnings: list[str] = []
    cutoff = since or evidence["last_ingested"]
    cutoff_from = "--since" if since else "last_ingested"
    if not cutoff:
        cutoff_from = "oldest_suggestion"
        # Never ingested (the interests sub-wikis were imported, not filed):
        # everything the digest ever suggested is "missed", so the cutoff is
        # the oldest suggestion on record — else one inbox window back.
        ever = [h["date"] for fname, _ in spec["files"]
                for h in harvest_history(root, fname, "0000-00-00")]
        cutoff = min(ever) if ever else (
            today - datetime.timedelta(days=inbox_actions.INBOX_WINDOW_DAYS)
        ).isoformat()
        warnings.append(f"no ingest on record for scope {scope!r}; cutoff set "
                        f"to the oldest suggestion, {cutoff}")

    queue_path = root / inbox_actions.QUEUE_FILE
    queue_text = queue_path.read_text(errors="replace") if queue_path.exists() else ""
    bib_path = root / BIB_FILE
    bib_text = bib_path.read_text(errors="replace") if bib_path.exists() else ""

    harvests: list[dict] = []
    for fname, _ in spec["files"]:
        t = topic if fname == interests_actions.INTERESTS_FILE else None
        harvests += harvest_history(root, fname, cutoff, t)
    harvests += harvest_queue(queue_text, spec["sections"])

    start = datetime.date.fromisoformat(cutoff) - datetime.timedelta(days=ANNOUNCE_LAG_DAYS)
    truncated = {}
    if not offline:
        if digests is None:
            sdir = mind_scripts_dir(root)
            if sdir is None:
                warnings.append("PyAutoMind not found (set PYAUTO_MIND); arXiv "
                                "gap-fill skipped")
            else:
                try:
                    digests = load_digests(sdir)
                except Exception as e:  # noqa: BLE001
                    warnings.append(f"could not load the Mind digest scripts: {e}")
        if digests is not None:
            for _, digest in spec["files"]:
                t = topic if digest == "arxiv_interests" else None
                try:
                    got, cut = harvest_arxiv(digests, digest, start, today, t, pause)
                    harvests += got
                    truncated[digest] = cut
                    if cut:
                        warnings.append(
                            f"{digest}: window truncated at "
                            f"{INTERESTS_ARXIV_CAP if digest == 'arxiv_interests' else LENSING_PAGE_SIZE * LENSING_MAX_PAGES}"
                            " most-recent results — the oldest days are missing")
                except Exception as e:  # noqa: BLE001 — network is best-effort
                    warnings.append(f"{digest}: arXiv query failed ({e}); skipped")

    ids_mem, titles_mem = in_memory_index(bib_text, queue_text)
    candidates, dropped = merge(harvests, ids_mem, titles_mem)

    if digests is not None and not offline:
        need = [c["id"] for c in candidates if c["id"] and not c.get("abstract")]
        if need:
            try:
                time.sleep(pause)
                found = enrich(digests, need, pause)
                for c in candidates:
                    f = found.get(c["id"]) if c["id"] else None
                    if f:
                        for k in ("abstract", "authors", "primary_category"):
                            if not c.get(k):
                                c[k] = f[k]
                        c["date"] = c["date"] or f["date"]
                        c["first_author"] = c["first_author"] or (
                            f["authors"][0] if f["authors"] else None)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"abstract lookup failed ({e}); titles only")

    counts = {s: sum(1 for c in candidates if c["source"] == s) for s in SOURCE_ORDER}
    harvested = {s: sum(1 for h in harvests if h["source"] == s) for s in SOURCE_ORDER}
    return {
        "scope": scope, "topic": topic, "today": today.isoformat(),
        "cutoff": cutoff, "cutoff_from": cutoff_from,
        "evidence": evidence,
        "days_lost": (today - datetime.date.fromisoformat(cutoff)).days,
        "arxiv_window": None if offline else [start.isoformat(), today.isoformat()],
        "truncated": truncated,
        "harvested": harvested, "counts": counts,
        "dropped_in_memory": dropped, "warnings": warnings,
        "candidates": candidates,
    }


def render_text(report: dict, abstract_chars: int = 280) -> str:
    ev = report["evidence"]
    bib = ev.get("bib") or {}
    lines = [f"catch-up · scope {report['scope']}"
             + (f" / {report['topic']}" if report["topic"] else ""),
             f"cutoff {report['cutoff']} ({report['cutoff_from']}: last DONE "
             f"{ev.get('done')}, last bib+sources ingest {bib.get('date')} "
             f"{bib.get('commit') or ''}) → {report['days_lost']} days lost",
             f"arXiv window {report['arxiv_window']} · "
             f"{len(report['candidates'])} candidates "
             + " · ".join(f"{s} {n}" for s, n in report["counts"].items())
             + f" · {report['dropped_in_memory']} already in memory"]
    for s in SOURCE_ORDER:
        group = [c for c in report["candidates"] if c["source"] == s]
        if not group:
            continue
        lines += ["", f"## {s} ({len(group)})", ""]
        for c in group:
            also = f" [+{','.join(c['also_in'])}]" if c["also_in"] else ""
            lines.append(f"- {c['id'] or '—':<11} {c['date'] or '':<10} "
                         f"{c['title']} — {c['first_author'] or '?'}{also}")
            if c.get("abstract"):
                a = c["abstract"]
                lines.append("    " + (a[:abstract_chars] + "…"
                                       if len(a) > abstract_chars else a))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scripts/catch_up.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scope", choices=("lensing", "interests", "all"),
                    default="lensing")
    ap.add_argument("--topic", default=None,
                    help="narrow interests to one reading-queue section")
    ap.add_argument("--since", default=None, help="override the cutoff (YYYY-MM-DD)")
    ap.add_argument("--today", default=None, help="override today (YYYY-MM-DD)")
    ap.add_argument("--offline", action="store_true", help="git harvests only")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    try:
        report = catch_up(ns.scope, ns.topic, ns.since,
                          datetime.date.fromisoformat(ns.today) if ns.today else None,
                          offline=ns.offline)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for w in report["warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    print(json.dumps(report, indent=2) if ns.json else render_text(report), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
