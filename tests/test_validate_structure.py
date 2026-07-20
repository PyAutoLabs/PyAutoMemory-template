import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_structure import validate_structure


def _minimal_repo(tmp_path: Path) -> Path:
    (tmp_path / "wiki" / "example" / "sources").mkdir(parents=True)
    (tmp_path / "bibliography").mkdir()
    (tmp_path / "bibliography" / "pyautomemory.bib").write_text("", encoding="utf-8")
    (tmp_path / "README.md").write_text("# readme\n", encoding="utf-8")
    return tmp_path


def test_clean_layout_passes(tmp_path):
    root = _minimal_repo(tmp_path)
    assert validate_structure(root) == []


def test_unexpected_top_level_entries_fail(tmp_path):
    root = _minimal_repo(tmp_path)
    (root / "DarkMatterModels").mkdir()
    (root / "DarkMatterModels" / "Navarro1996").write_text("", encoding="utf-8")
    (root / "euclid.sty").write_text("", encoding="utf-8")
    errors = validate_structure(root)
    assert any("DarkMatterModels" in e for e in errors)
    assert any("euclid.sty" in e for e in errors)


def test_loose_bib_outside_bibliography_fails(tmp_path):
    root = _minimal_repo(tmp_path)
    (root / "wiki" / "example" / "library.bib").write_text("", encoding="utf-8")
    errors = validate_structure(root)
    assert any("loose .bib" in e for e in errors)


def test_committed_pdf_content_fails_even_without_extension(tmp_path):
    root = _minimal_repo(tmp_path)
    (root / "wiki" / "example" / "Hubble1926.321H").write_bytes(b"%PDF-1.5 fake")
    (root / "wiki" / "example" / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    errors = validate_structure(root)
    assert sum("off-repo" in e for e in errors) == 2


def test_actual_repository_layout_is_valid():
    repo_root = Path(__file__).resolve().parents[1]
    assert validate_structure(repo_root) == []
