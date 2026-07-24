"""tests/test_working_paper_download.py — C2: GET /working-paper download route.

The route is read-only and path-safe: it serves a PDF only when the resolved candidate
(1) ends in .pdf, (2) exists as a file, AND (3) resolves INSIDE one of the allowlisted
output roots (``api.app._WORKING_PAPER_ROOTS``). Any failure is a flat 404 — no path
echo, no directory listing. These tests monkeypatch the allowlist to a tmp root so they
never touch the real DEFAULT_OUTPUT_DIR / audit / t1.4-reports directories.

Coverage:
  * G1 — a valid .pdf INSIDE the allowlisted root -> 200 + content-type application/pdf.
  * G2 — a .pdf OUTSIDE the allowlisted roots -> 404 (containment guard).
  * G3 — a ../ traversal path that resolves outside the root -> 404 (resolve() + containment
         defeat traversal even though the target file really exists).
  * G4 — a non-.pdf name INSIDE the root -> 404 (suffix guard).

The route signs nothing; it only serves bytes produced by the sign routes. No sign route
is exercised or modified here.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.app as app_module

client = TestClient(app_module.app)


@pytest.fixture
def wp_root(tmp_path, monkeypatch):
    """A tmp allowlist root; api.app._WORKING_PAPER_ROOTS is pinned to it for the test."""
    root = tmp_path / "wp"
    root.mkdir()
    monkeypatch.setattr(app_module, "_WORKING_PAPER_ROOTS", (root.resolve(),))
    return root


def _write_pdf(p: Path) -> Path:
    # A minimal valid-enough PDF header; the route serves bytes, it does not parse them.
    p.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return p


def test_valid_pdf_inside_root_returns_200_pdf(wp_root):
    """G1: a .pdf that exists inside the allowlisted root is served with the PDF media type."""
    pdf = _write_pdf(wp_root / "working-paper.pdf")
    resp = client.get("/working-paper", params={"path": str(pdf)})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content == b"%PDF-1.4\n%%EOF\n"


def test_pdf_outside_roots_returns_404(wp_root, tmp_path):
    """G2: a real .pdf that lives OUTSIDE every allowlisted root is refused."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    pdf = _write_pdf(outside / "leak.pdf")
    resp = client.get("/working-paper", params={"path": str(pdf)})
    assert resp.status_code == 404


def test_traversal_path_returns_404(wp_root, tmp_path):
    """G3: `{root}/../secret.pdf` really exists (tmp_path is root.parent) but resolves OUTSIDE
    the root, so resolve() + the containment check turn it into a 404 — traversal is neutralized."""
    _write_pdf(tmp_path / "secret.pdf")  # sits in root.parent, so it is a real file
    traversal = f"{wp_root}/../secret.pdf"
    resp = client.get("/working-paper", params={"path": traversal})
    assert resp.status_code == 404


def test_non_pdf_inside_root_returns_404(wp_root):
    """G4: a non-.pdf file inside the root is refused by the suffix guard."""
    txt = wp_root / "notes.txt"
    txt.write_text("not a pdf")
    resp = client.get("/working-paper", params={"path": str(txt)})
    assert resp.status_code == 404
