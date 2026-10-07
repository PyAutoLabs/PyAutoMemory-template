"""scripts/arxiv_refs.py — the arXiv ref grammar, in one place.

A reading-queue / arXiv-inbox paper line is a bare title, optionally followed
by ` — <arXiv id or URL>`. That trailing **ref** is what turns a queue line
into a one-tap paper on the Dashboard: with it the board can link the arXiv
*abstract* page and, next to it, the PDF itself — the whole point being that a
phone can collect the PDFs before a flight without a search-results detour.
Without a ref the board can only offer an arXiv title *search*, which costs a
page load and a tap per paper and never reaches a PDF.

So this module holds two things, and nothing else:

* **The grammar (pure, offline).** Every ref shape the queue has ever carried —
  ``2103.16254``, ``arXiv:2103.16254v2``, ``https://arxiv.org/abs/2103.16254``,
  ``https://arxiv.org/pdf/2103.16254.pdf``, the pre-2007 ``astro-ph/0601001`` —
  normalises to one canonical id, from which :func:`abs_url` and :func:`pdf_url`
  follow. A ref that is not an arXiv paper (a journal DOI, a PDF on a group
  page) stays exactly as written: it is still a link, just not one with a
  derivable PDF sibling.
* **The lookup (networked).** :func:`resolve_title` asks the arXiv API for the
  id of a bare title. It is used only by ``scripts/backfill_arxiv_refs.py``,
  which is what fills in the refs the historical bulk-pasted queue lines never
  had. The board itself never calls it — the board stays fully local, rendered
  from the checkout with no network (see ``scripts/board.py``).

``scripts/board.py`` and ``scripts/inbox_actions.py`` keep their own
``…REF_RE`` line-splitting regexes: those answer "where does the title end",
which is a *line* question. This module answers "what paper is that ref", which
is an *arXiv* question. They are deliberately separate.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ATOM = "{http://www.w3.org/2005/Atom}"

#: Post-2007 identifiers: ``YYMM.NNNNN``, optionally versioned.
NEW_ID = r"\d{4}\.\d{4,5}"
#: Pre-2007 identifiers: ``archive[.subject]/YYMMNNN``, e.g. ``astro-ph/0601001``.
OLD_ID = r"[a-z-]+(?:\.[A-Z]{2})?/\d{7}"

_ID_RE = re.compile(rf"^(?:arxiv:)?({NEW_ID}|{OLD_ID})(?:v\d+)?$", re.I)
_URL_RE = re.compile(
    rf"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf|format|ps)/"
    rf"({NEW_ID}|{OLD_ID})(?:v\d+)?(?:\.pdf)?/?$",
    re.I,
)

ABS_BASE = "https://arxiv.org/abs/"
PDF_BASE = "https://arxiv.org/pdf/"
SEARCH_BASE = "https://arxiv.org/search/?searchtype=title&query="

API_URL = "https://export.arxiv.org/api/query"
#: arXiv asks for one request every few seconds; the backfill honours this.
API_DELAY_SECONDS = 3.0
USER_AGENT = (
    "PyAutoMemory reading-queue backfill "
    "(+https://github.com/PyAutoLabs/PyAutoMemory)"
)
ACCEPT = "application/atom+xml"
RETRY_DELAYS = (5, 15, 45, 90, 180)
RETRY_STATUSES = {406, 429, 500, 502, 503, 504}
TRANSIENT = (urllib.error.URLError, TimeoutError, ConnectionError)
_CURL_STATUS_MARKER = b"\n__PYAUTO_HTTP_STATUS__:"


class ArxivAPIError(RuntimeError):
    """The arXiv API could not answer a lookup reliably."""


def arxiv_id(ref: str | None) -> str | None:
    """The canonical, version-stripped arXiv id in `ref`, or None.

    Accepts a bare id, an ``arXiv:``-prefixed id, or any arxiv.org abs/pdf URL.
    Anything else — a DOI, a publisher link, a PDF hosted elsewhere — is not an
    arXiv paper as far as this repo is concerned, and returns None.
    """
    if not ref:
        return None
    ref = ref.strip()
    for pattern in (_ID_RE, _URL_RE):
        m = pattern.match(ref)
        if m:
            return m.group(1).lower() if "/" in m.group(1) else m.group(1)
    return None


def abs_url(ref: str | None) -> str | None:
    """The arXiv abstract page for `ref`, or None when it is not an arXiv id.

    The abstract page — never the PDF — because it is the page that carries the
    authors, the abstract and arXiv's own download links; the direct PDF is
    offered beside it, as its own button.
    """
    aid = arxiv_id(ref)
    return ABS_BASE + aid if aid else None


def pdf_url(ref: str | None) -> str | None:
    """The direct PDF for `ref`, or None when it is not an arXiv id.

    No ``.pdf`` suffix: arXiv serves the extensionless form and phones open it
    in the built-in viewer, from which "save to Files" is one more tap.
    """
    aid = arxiv_id(ref)
    return PDF_BASE + aid if aid else None


def search_url(title: str) -> str:
    """The arXiv title search for `title` — the fallback for a ref-less line.

    Strictly worse than a real ref (a results page, not a paper, and no PDF to
    tap), which is why ``backfill_arxiv_refs.py`` exists to retire it.
    """
    return SEARCH_BASE + urllib.parse.quote(title, safe="")


# --- title matching -----------------------------------------------------------
_PUNCT_RE = re.compile(r"[^a-z0-9]+")
#: A LaTeX control sequence: ``\leq``, ``\Lambda``, ``\rm``, ``\,``.
_LATEX_CMD_RE = re.compile(r"\\[A-Za-z]+|\\.")


def normalise_title(title: str) -> str:
    """A title reduced to its comparable core: lowercase ASCII alphanumerics.

    arXiv, the digest and a hand-pasted queue line disagree constantly about
    LaTeX (``$z=2.48$``), dashes (``-``/``–``/``—``), accents and double spaces,
    and none of that disagreement is about *which paper it is*. Stripping it all
    lets the backfill demand an exact match on what remains, rather than a fuzzy
    match on what does not — a wrong id is worse than no id, because it links
    the reader confidently to somebody else's paper.

    The one disagreement that needs more than stripping is **maths**, because
    the two sides spell it differently rather than merely punctuate it
    differently: arXiv's metadata carries the LaTeX source (``$0.5\\leq
    z<1.0$``, ``$\\Lambda$CDM``, ``$M_\\star$``) while a title pasted off the
    abstract page carries the rendered glyphs (``0.5≤z<1.0``, ``ΛCDM``,
    ``M⋆``). Neither survives a plain punctuation strip into the same string.

    So both are erased rather than reconciled: LaTeX control sequences go, and
    so does every non-ASCII character left after accent folding. ``\\leq`` and
    ``≤`` both become nothing, and the two spellings meet in the middle —
    ``05z10`` from either side. Erasing is deliberately preferred to a
    ``\\leq``→``≤`` translation table, which would need every symbol
    astronomers use and would silently mismatch the day it missed one. The
    reduction is lossier, and the uniqueness rule in :func:`match_entries` is
    what keeps that safe: a title that reduces onto two arXiv papers matches
    neither.

    Accented Latin is *kept* (``Ekström`` → ``ekstrom``): NFKD splits the accent
    off as a combining mark and the base letter is ASCII, so it survives the
    non-ASCII drop that removes Greek and maths.
    """
    folded = unicodedata.normalize("NFKD", title)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = _LATEX_CMD_RE.sub(" ", folded)
    folded = folded.encode("ascii", "ignore").decode("ascii")
    return _PUNCT_RE.sub("", folded.lower())


def _curl_get(url: str) -> bytes:
    """Alternate transport for the Fastly 406 seen from urllib clients."""
    try:
        result = subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--location",
                "--connect-timeout",
                "20",
                "--max-time",
                "60",
                "--user-agent",
                USER_AGENT,
                "--header",
                f"Accept: {ACCEPT}",
                "--write-out",
                _CURL_STATUS_MARKER.decode() + "%{http_code}",
                url,
            ],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as e:
        raise urllib.error.URLError("curl is not installed") from e

    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise urllib.error.URLError(detail or f"curl exited {result.returncode}")

    body, marker, status_raw = result.stdout.rpartition(_CURL_STATUS_MARKER)
    if not marker:
        raise urllib.error.URLError("curl returned no HTTP status marker")
    try:
        status = int(status_raw.strip())
    except ValueError as e:
        raise urllib.error.URLError(
            f"curl returned invalid HTTP status {status_raw!r}"
        ) from e
    if not 200 <= status < 300:
        raise urllib.error.HTTPError(
            url, status, f"curl HTTP {status}", {}, None
        )
    return body


def _request_once(url: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": ACCEPT}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code != 406:
            raise
        print(
            "  arXiv API urllib HTTP 406 — retrying this request with curl",
            file=sys.stderr,
        )
        return _curl_get(url)


def _api_query(params: dict, *, delays: tuple | None = None) -> bytes:
    """Query arXiv with retry/backoff and make transport failure explicit.

    September 2026 exposed two independent failure modes: arXiv can throttle
    shared runners with 429/406, and Fastly can reject Python's stdlib client
    fingerprint with a persistent 406 while curl succeeds. The latter gets one
    immediate alternate-transport attempt; real throttling still backs off.
    """
    if delays is None:
        delays = RETRY_DELAYS
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    attempts = len(delays) + 1
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return _request_once(url)
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code not in RETRY_STATUSES or attempt == attempts:
                break
            wait = delays[attempt - 1]
            retry_after = (e.headers or {}).get("Retry-After")
            if retry_after and str(retry_after).strip().isdigit():
                wait = max(wait, min(int(retry_after), max(delays)))
            reason = f"HTTP {e.code}"
        except TRANSIENT as e:
            last_error = e
            if attempt == attempts:
                break
            wait = delays[attempt - 1]
            reason = f"{type(e).__name__}: {e}"

        print(
            f"  arXiv API {reason} (attempt {attempt}/{attempts}) — "
            f"retrying in {wait}s",
            file=sys.stderr,
        )
        time.sleep(wait)

    raise ArxivAPIError(
        f"arXiv API unavailable after {attempts} attempt(s): {last_error}"
    ) from last_error


def parse_api_entries(raw: bytes) -> list[dict]:
    """``[{'id': …, 'title': …}, …]`` from an arXiv Atom response."""
    entries = []
    for entry in ET.fromstring(raw).findall(f"{ATOM}entry"):
        ident = (entry.findtext(f"{ATOM}id") or "").strip()
        title = " ".join((entry.findtext(f"{ATOM}title") or "").split())
        aid = arxiv_id(ident)
        if aid and title:
            entries.append({"id": aid, "title": title})
    return entries


def match_entries(title: str, entries: list[dict]) -> str | None:
    """The id of the one entry whose title matches `title`, or None.

    "One" is literal: a title that normalises onto two different arXiv papers
    (v1 cross-lists, a comment sharing its parent's title, two genuinely
    identically-titled papers) is left for a human. Silence is the safe answer.
    """
    want = normalise_title(title)
    hits = {e["id"] for e in entries if normalise_title(e["title"]) == want}
    return hits.pop() if len(hits) == 1 else None


#: A phrase shorter than this is too generic to be worth searching on.
MIN_PHRASE_WORDS = 3


def query_phrase(title: str) -> str:
    """The longest run of plain alphabetic words in `title`.

    What gets *sent* to arXiv, as opposed to what gets compared afterwards.
    The two are different problems and conflating them was a real bug: a title
    carrying maths used to be flattened word-by-word into the phrase search, so
    ``…galaxies at 0.5≤z<1.0`` was sent as ``ti:"…galaxies at 0 5 z 1 0"``.
    arXiv indexes ``$0.5\\leq z<1.0$``, matches none of that, and returns
    nothing — at which point no amount of clever comparison in
    :func:`match_entries` has anything to compare.

    So the query drops the maths instead of mangling it, and searches on the
    longest stretch of ordinary words the title contains — the part both sides
    spell the same way. That is a *broader* search, not a looser match: it only
    decides which candidates come back, and every one of them still has to
    survive the exact, unique-title check afterwards.

    Falls back to every ASCII word when no run is long enough
    (``MIN_PHRASE_WORDS``), since a two-word phrase would drown the result set.
    """
    # `flags=re.ASCII` so `\w` stops treating Greek as a word character: `Λ`
    # became a literal `Λ` in the query string before, which arXiv cannot match
    # against its own `$\Lambda$` source.
    tokens = re.sub(r"[^\w\s]", " ", title, flags=re.ASCII).split()
    best: list[str] = []
    run: list[str] = []
    for token in tokens:
        if token.isalpha():
            run.append(token)
            if len(run) > len(best):
                best = list(run)
        else:
            run = []
    return " ".join(best if len(best) >= MIN_PHRASE_WORDS else tokens)


def resolve_title(title: str, max_results: int = 50,
                  query: object = _api_query) -> str | None:
    """Look `title` up on the arXiv API and return its id, or None.

    Networked — the Dashboard never calls this; only the backfill does.
    `query` is injected so the matching can be tested without arXiv.

    `max_results` is generous because :func:`query_phrase` deliberately searches
    on part of a title rather than all of it: more candidates come back, and
    picking among them costs nothing — the choice is made locally, by exact
    match, and an ambiguous set still resolves to nothing.
    """
    phrase = query_phrase(title)
    if not phrase:
        return None
    try:
        raw = query({"search_query": f'ti:"{phrase}"',
                     "start": 0, "max_results": max_results})
    except ArxivAPIError:
        raise
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        # Injected query functions in tests and alternate callers may not use
        # _api_query(), so normalise their transport failures to the same
        # explicit signal. None remains reserved for a real arXiv answer that
        # contains no unique exact title match.
        raise ArxivAPIError(f"arXiv API lookup failed: {e}") from e
    return match_entries(title, parse_api_entries(raw))
