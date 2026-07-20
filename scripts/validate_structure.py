"""Validate the PyAutoMemory repository layout.

The repo has exactly two content homes — `wiki/` (sub-wikis) and
`bibliography/` (canonical BibTeX) — plus a small allowlisted set of root
files and tooling folders. This lint fails on the historical failure modes:
loose `.bib` files outside `bibliography/`, committed papers (PDF/HTML blobs,
with or without a file extension), and unrecognised top-level entries.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ALLOWED_TOP_DIRS = {
    ".git",
    ".github",
    "bibliography",
    "scripts",
    "tests",
    "wiki",
}
ALLOWED_TOP_FILES = {
    ".gitignore",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "Makefile",
    "README.md",
    "SPAWNED_FROM",  # provenance marker stamped into spawned templates
    "index.md",
    "logo.png",
    "reading-queue.md",
}
BANNED_SUFFIXES = {".pdf", ".htm", ".html"}
BINARY_MAGIC = (b"%PDF-",)
BINARY_EXEMPT = {"logo.png"}


def iter_repo_files(root: Path):
    """Yield the repo's content files — git-tracked when git is available.

    Validating `git ls-files` (not the raw filesystem) keeps untracked local
    scratch — caches, in-progress downloads — out of scope: the contract is
    about what gets committed. Outside a git checkout (e.g. a freshly spawned
    template before `git init`) fall back to walking the tree.
    """
    try:
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        ).stdout.decode()
        for rel in sorted(filter(None, tracked.split("\0"))):
            path = root / rel
            if path.is_file():
                yield path
        return
    except (OSError, subprocess.CalledProcessError):
        pass
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts:
            continue
        if path.is_file():
            yield path


def validate_structure(root: Path) -> list[str]:
    errors: list[str] = []
    top_level = {p.relative_to(root).parts[0] for p in iter_repo_files(root)}

    for entry in sorted(root.iterdir()):
        name = entry.name
        if name == ".git" or name not in top_level:
            continue  # untracked local scratch (caches, downloads) is out of scope
        if entry.is_dir():
            if name not in ALLOWED_TOP_DIRS:
                errors.append(
                    f"unexpected top-level directory: {name}/ "
                    "(content belongs under wiki/ or bibliography/)"
                )
        elif name not in ALLOWED_TOP_FILES:
            errors.append(
                f"unexpected top-level file: {name} "
                "(allowlist lives in scripts/validate_structure.py)"
            )

    for path in iter_repo_files(root):
        rel = path.relative_to(root)
        if path.suffix == ".bib" and rel.parts[0] != "bibliography":
            errors.append(f"loose .bib file outside bibliography/: {rel}")
        if path.suffix.lower() in BANNED_SUFFIXES:
            errors.append(f"committed paper artifact (source PDFs live off-repo): {rel}")
        elif rel.name not in BINARY_EXEMPT:
            try:
                head = path.open("rb").read(8)
            except OSError:
                head = b""
            if head.startswith(BINARY_MAGIC):
                errors.append(f"committed PDF content (source PDFs live off-repo): {rel}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    errors = validate_structure(args.root.resolve())
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print(f"Repository structure is invalid ({len(errors)} problem(s)).")
        return 1
    print("Repository structure is valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
