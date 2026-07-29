"""documents/provider.py — DocumentProvider protocol and implementations (T2.8).

Public API:
    DocumentProvider        — Protocol: get_document(doc_num) -> Path | None
    FixtureDocumentProvider — maps doc_num -> tests/fixtures/documents/INV-<n>.pdf
    B1AttachmentProvider    — fetches via SAP B1 Attachments2 Service Layer endpoint
    UploadProvider          — serves from a caller-supplied upload directory
    CompositeProvider       — tries a list of providers; returns first non-None result

Containment:
    No imports from orchestrator/, audit_bundle/, boxes, gates, or calculate.
    No module-level anthropic import.

SAP attachment lookup path (B1AttachmentProvider):
    GET /PurchaseInvoices?$filter=DocNum eq {n}&$select=DocEntry,AttachmentEntry
        → AttachmentEntry (null → no attachment)
    GET /Attachments2({AttachmentEntry})
        → Attachments2_Lines[]: FileName, FileExtension, LineNum
    GET /Attachments2({AttachmentEntry})/Attachments2_Lines({LineNum})/$value
        → binary PDF bytes

Runtime is read-only: no POST/PATCH/DELETE to SAP in any provider.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import requests
import urllib3

if TYPE_CHECKING:
    from config.loader import ClientConfig

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class DocumentProvider(Protocol):
    """Locate and return the invoice PDF for a given SAP document number.

    The provider translates a doc_num to a file-system path.  Returning None
    signals that no PDF is available; run_documents_pass skips that doc_num
    silently rather than raising an error.
    """

    def get_document(self, doc_num: int) -> Path | None:
        """Return path to the invoice PDF for doc_num, or None if unavailable."""
        ...


# ---------------------------------------------------------------------------
# FixtureDocumentProvider (tests / offline)
# ---------------------------------------------------------------------------

class FixtureDocumentProvider:
    """Maps doc_num to the Prompt-1 fixture PDFs in tests/fixtures/documents/.

    Fixture PDFs follow the naming convention INV-<doc_num>.pdf.  Returns None
    when the file does not exist so the documents pass silently skips doc_nums
    that have no associated test fixture.
    """

    def __init__(self, fixture_dir: Path | str) -> None:
        self._dir = Path(fixture_dir)

    def get_document(self, doc_num: int) -> Path | None:
        p = self._dir / f"INV-{doc_num}.pdf"
        return p if p.exists() else None


# ---------------------------------------------------------------------------
# B1AttachmentProvider — live SAP B1 Service Layer
# ---------------------------------------------------------------------------

class B1AttachmentProvider:
    """Fetches invoice PDFs via the SAP B1 Attachments2 Service Layer endpoint.

    Lookup path (all GET, no writes):
      1. PurchaseInvoices?$filter=DocNum eq {n} → AttachmentEntry (int or null)
      2. Attachments2({AttachmentEntry}) → Attachments2_Lines (FileName, FileExtension)
      3. First PDF line: Attachments2({att})/Attachments2_Lines({lineNum})/$value
      4. Write bytes to a temp file; return its Path.

    Returns None when:
      - The document has no attachment (AttachmentEntry is null or -1).
      - No line has FileExtension='pdf'.
      - The Service Layer returns a non-200 at any step (e.g. server-side
        attachment folder misconfiguration, network error).

    Never raises from get_document() — all errors are converted to None.
    Creates a new session per call; each call logs in and out of SAP.
    """

    def __init__(self, cfg: "ClientConfig") -> None:
        self._url = cfg.service_layer_url.rstrip("/")
        self._db = cfg.company_db
        self._user = cfg.username
        self._pwd = cfg.password
        self._verify = cfg.ssl_verify

    def get_document(self, doc_num: int) -> Path | None:
        """Return a temp-file Path containing the PDF bytes, or None."""
        session = self._make_session()
        try:
            if not self._login(session):
                return None
            return self._fetch(session, doc_num)
        except Exception:  # network error, JSON decode failure, etc.
            return None
        finally:
            self._logout(session)

    # -- Private helpers -------------------------------------------------------

    def _make_session(self) -> requests.Session:
        s = requests.Session()
        s.verify = self._verify
        s.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
        return s

    def _login(self, session: requests.Session) -> bool:
        resp = session.post(
            f"{self._url}/Login",
            json={"CompanyDB": self._db, "UserName": self._user, "Password": self._pwd},
            timeout=15,
        )
        return resp.status_code == 200

    def _logout(self, session: requests.Session) -> None:
        try:
            session.post(f"{self._url}/Logout", timeout=5)
        except Exception:
            pass

    def _fetch(self, session: requests.Session, doc_num: int) -> Path | None:
        # Step 1: DocNum → AttachmentEntry
        r1 = session.get(
            f"{self._url}/PurchaseInvoices",
            params={
                "$filter": f"DocNum eq {doc_num}",
                "$select": "DocEntry,AttachmentEntry",
                "$top": "1",
            },
            timeout=15,
        )
        if r1.status_code != 200:
            return None
        docs = r1.json().get("value", [])
        if not docs:
            return None
        att_entry = docs[0].get("AttachmentEntry")
        if not att_entry or att_entry == -1:
            return None

        # Step 2: AttachmentEntry → Attachments2_Lines
        r2 = session.get(f"{self._url}/Attachments2({att_entry})", timeout=15)
        if r2.status_code != 200:
            return None
        lines = r2.json().get("Attachments2_Lines", [])
        pdf_line = next(
            (ln for ln in lines if (ln.get("FileExtension") or "").lower() == "pdf"),
            None,
        )
        if pdf_line is None:
            return None
        line_num = pdf_line.get("LineNum", 0)

        # Step 3: download bytes
        r3 = session.get(
            f"{self._url}/Attachments2({att_entry})/Attachments2_Lines({line_num})/$value",
            headers={"Accept": "application/octet-stream"},
            timeout=30,
        )
        if r3.status_code != 200:
            return None

        # Write to a named temp file; caller owns the file after this returns.
        fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix=f"b1att_{doc_num}_")
        import os
        os.close(fd)
        Path(tmp_path).write_bytes(r3.content)
        return Path(tmp_path)


# ---------------------------------------------------------------------------
# UploadProvider — caller-supplied directory
# ---------------------------------------------------------------------------

class UploadProvider:
    """Returns invoice PDFs from a caller-supplied upload directory.

    Maps doc_num to {upload_dir}/INV-{doc_num}.pdf.  Returns None when the
    file does not exist so run_documents_pass silently skips that doc_num.

    This provider is intended for the manual-upload workflow: an operator
    places a PDF named INV-<doc_num>.pdf into the upload directory before
    running the agent, and the agent picks it up here.
    """

    def __init__(self, upload_dir: Path | str) -> None:
        self._dir = Path(upload_dir)

    def get_document(self, doc_num: int) -> Path | None:
        p = self._dir / f"INV-{doc_num}.pdf"
        return p if p.exists() else None


# ---------------------------------------------------------------------------
# MappedDocumentProvider — uploaded review documents, full-reference keyed
# ---------------------------------------------------------------------------

class MappedDocumentProvider:
    """Serves uploaded source documents by FULL reference string (T-E(1), D-36/D-42).

    Resolves through ``documents_dir/document_map.json`` ({reference: sha256}) and
    returns ``documents_dir/<sha256>.pdf``. The reference is looked up VERBATIM —
    never parsed, stripped, or pattern-matched: one resolver spanning two naming
    conventions is what produced the D-34 cross-corpus substitution. Deliberately
    DISTINCT from UploadProvider, which serves the SAP corpus's INV-<doc_num>.pdf
    convention from a flat directory. The map is re-read per call, so documents
    uploaded after construction are visible. Returns None on any miss — absent map,
    unreadable map, unmapped reference, or missing blob — never raises.
    """

    def __init__(self, documents_dir: Path | str) -> None:
        self._dir = Path(documents_dir)

    def get_by_reference(self, reference: str) -> Path | None:
        map_path = self._dir / "document_map.json"
        if not map_path.is_file():
            return None
        try:
            mapping = json.loads(map_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        sha = mapping.get(reference)
        if not isinstance(sha, str):
            return None
        p = self._dir / f"{sha}.pdf"
        return p if p.is_file() else None


# ---------------------------------------------------------------------------
# CompositeProvider — ordered fallthrough
# ---------------------------------------------------------------------------

class CompositeProvider:
    """Tries a sequence of providers and returns the first non-None result.

    Iterates through providers in order and returns the first Path returned
    by get_document().  If all providers return None, returns None.

    Intended usage (B1 first, upload fallback):
        CompositeProvider([B1AttachmentProvider(cfg), UploadProvider(upload_dir)])
    """

    def __init__(self, providers: list) -> None:
        self._providers = list(providers)

    def get_document(self, doc_num: int) -> Path | None:
        for provider in self._providers:
            result = provider.get_document(doc_num)
            if result is not None:
                return result
        return None
