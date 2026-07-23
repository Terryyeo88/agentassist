"""Failing-first tests for the seal run_ts collision fix (Phase 2, NOT YET BUILT).

These tests pin the behaviour Phase 2 will introduce and MUST FAIL today for the
right reason.  What Phase 2 changes:

  1. audit_bundle/seal.py run_ts gains fixed-width microseconds:
        dt.strftime("%Y%m%d-%H%M%S-%f")     (today: "%Y%m%d-%H%M%S", seal.py:264)
     run_ts is derived from the CALLER's run_started_at isoformat (seal.py:261).
  2. On a true name collision (identical run_started_at -> identical base run_ts),
     a bounded -N suffix fallback selects a fresh directory via mkdir(exist_ok=False):
     the second seal gets "<run_ts>-2", the third "<run_ts>-3", etc.  The CHOSEN name
     (suffix included) flows into BOTH the directory name AND engagement.run_ts in the
     manifest (seal.py:336), so the documented dir == engagement.run_ts invariant
     (seal.py:192-193) holds for every bundle.
  3. Exhaustion of the bounded suffix range raises a LOUD RuntimeError (never hangs,
     never silently reuses a dir).  The bound is a module-level constant in
     audit_bundle/seal.py, referenced here as _MAX_SAME_TS_SEALS.  The constant does
     NOT exist yet, so the T5 monkeypatch uses raising=False and must not error on
     its absence.
  4. ui/sign.py sign_working_paper's PDF filename timestamp gains the same %f append
     (ui/sign.py:121), so two signs in the same second produce two DISTINCT PDFs.

Hermetic: no SAP, no network, no model.  Everything under tmp_path.  Mirrors the
minimal builders of tests/test_audit_seal_verify.py (fixture/cfg/gate/pdf/monkeypatch
of audit_bundle.seal._AUDIT_ROOT).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

import audit_bundle.seal as _seal_mod
from audit_bundle.seal import seal_bundle
from audit_bundle.verify import verify_bundle
from config.loader import ClientConfig

import ui.sign as _sign_mod
from ui.engine_seam import MockEngine
from ui.sign import sign_working_paper

# --- mirrored from tests/test_audit_seal_verify.py -------------------------------
FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_COMPLETED = "2026-06-02T00:00:30+00:00"
_PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}

# A run_started_at with NO microseconds: %f renders "000000", so two seals sharing
# this string produce an identical base run_ts and force the -N collision fallback.
_COLLIDE_TS = "2026-06-02T00:00:00+00:00"

# Two run_started_at strings differing ONLY in the microsecond field: the %f fix
# differentiates them WITHOUT any -N suffix.
_MICRO_TS_A = "2026-06-02T00:00:01.111111+00:00"
_MICRO_TS_B = "2026-06-02T00:00:01.222222+00:00"

# A single microsecond-bearing run_started_at for the format regression pin (T7).
_MICRO_TS_SINGLE = "2026-06-02T00:00:05.123456+00:00"


def _make_cfg(**overrides) -> ClientConfig:
    defaults = dict(
        client_id="testclient",
        client_name="Test Client Pte Ltd",
        gst_registration_number="M90000001A",
        applicable_gst_rate=0.09,
        service_layer_url="https://10.0.0.1:50000/b1s/v2",
        company_db="TESTDB",
        username="sap_user",
        password="HUNTER2_TEST",
        ssl_verify=False,
        fiscal_year_start_month=1,
        custom_vat_groups={},
        completeness_threshold=0.10,
        reviewer_name="Jane Tan",
        firm_name="Tan & Associates",
    )
    defaults.update(overrides)
    return ClientConfig(**defaults)


def _gate_results() -> dict:
    return {
        "all_passed": True,
        "gates": [
            {
                "gate": 1,
                "name": "record-count",
                "after_step": "fetch",
                "status": "WARN_PASS",
                "passed": True,
                "checked": {"sap_inline_count": None, "fetched_count": 73},
                "message": "SAP $inlinecount unavailable",
            },
        ],
    }


def _dummy_pdf(tmp_path: Path, name: str = "dummy_report") -> Path:
    p = tmp_path / f"{name}.pdf"
    p.write_bytes(b"%PDF-1.4 dummy one-page test pdf for seal run_ts collision tests")
    return p


def _seal(tmp_path, monkeypatch, run_started_at, *, pdf_name="dummy_report"):
    """Seal one bundle under the tmp_path audit root with the given run_started_at.

    Callers keep the SAME monkeypatched _AUDIT_ROOT across seals so that identical
    run_started_at strings collide on the same directory (the scenario under test).
    """
    monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")
    compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return seal_bundle(
        client_config=_make_cfg(),
        period=_PERIOD,
        compile_output=compile_output,
        gate_results=_gate_results(),
        report_pdf_path=_dummy_pdf(tmp_path, pdf_name),
        run_started_at=run_started_at,
        run_completed_at=_COMPLETED,
    )


# ---------------------------------------------------------------------------
# T1 — same-second collision yields two DISTINCT bundle dirs
# ---------------------------------------------------------------------------

def test_T1_same_second_collision_distinct_bundles(tmp_path, monkeypatch):
    """Two seals with the IDENTICAL run_started_at must land in two distinct,
    sibling bundle directories (base and base + '-2'), neither overwriting the other.

    FAILS TODAY: run_ts = strftime("%Y%m%d-%H%M%S") (seal.py:264) so both seals derive
    the identical name "20260602-000000" and mkdir(exist_ok=True) reuses the first
    directory.  The second seal then re-writes config.json (seal.py:273 -> :115), which
    the first seal marked read-only (seal.py:150), raising PermissionError on Windows.
    The very call to the second seal_bundle raises before any assertion is reached —
    that PermissionError IS the failing-first signal.
    """
    b1 = _seal(tmp_path, monkeypatch, _COLLIDE_TS, pdf_name="a")
    b2 = _seal(tmp_path, monkeypatch, _COLLIDE_TS, pdf_name="b")

    assert b1 != b2, "collision fallback must return a distinct directory"
    assert b1.exists() and b2.exists(), "both bundle directories must exist"
    assert b1.parent == b2.parent, "the two bundles must be siblings under period_tag"
    assert b1.name in b2.name, "the second dir name must contain the base run_ts"
    assert b2.name == b1.name + "-2", (
        f"second same-ts seal must get the '-2' suffix; got {b2.name!r} vs {b1.name!r}"
    )


# ---------------------------------------------------------------------------
# T2 — both colliding bundles verify clean
# ---------------------------------------------------------------------------

def test_T2_both_collision_bundles_verify_clean(tmp_path, monkeypatch):
    """After the same-second collision fallback, BOTH bundles must verify cleanly
    (each has its own self-consistent manifest.json / root_hash).

    FAILS TODAY: the second seal_bundle raises PermissionError (see T1), so b2 is never
    produced and there is nothing to verify — the failing-first reason is the same
    seconds-resolution collision.
    """
    b1 = _seal(tmp_path, monkeypatch, _COLLIDE_TS, pdf_name="a")
    b2 = _seal(tmp_path, monkeypatch, _COLLIDE_TS, pdf_name="b")

    ok1, problems1 = verify_bundle(b1)
    ok2, problems2 = verify_bundle(b2)
    assert ok1 is True and problems1 == [], f"bundle 1 failed verify: {problems1}"
    assert ok2 is True and problems2 == [], f"bundle 2 failed verify: {problems2}"


# ---------------------------------------------------------------------------
# T3 — dir name == engagement.run_ts for BOTH bundles (suffix flows through)
# ---------------------------------------------------------------------------

def test_T3_dir_name_equals_engagement_run_ts_for_both(tmp_path, monkeypatch):
    """The documented invariant (seal.py:192-193) is that the directory name equals
    engagement.run_ts.  The collision suffix must flow into the manifest so this holds
    for the '-2' bundle too, not just the base bundle.

    FAILS TODAY: the second seal raises PermissionError before writing a manifest (see
    T1); even absent the crash, seal.py:336 records the un-suffixed run_ts, so a
    suffixed directory would violate dir == engagement.run_ts.
    """
    b1 = _seal(tmp_path, monkeypatch, _COLLIDE_TS, pdf_name="a")
    b2 = _seal(tmp_path, monkeypatch, _COLLIDE_TS, pdf_name="b")

    for bundle in (b1, b2):
        manifest = json.loads((bundle / "manifest.json").read_bytes())
        assert manifest["engagement"]["run_ts"] == bundle.name, (
            "engagement.run_ts must equal the bundle directory name "
            f"(dir={bundle.name!r}, run_ts={manifest['engagement']['run_ts']!r})"
        )


# ---------------------------------------------------------------------------
# T4 — microsecond differentiation WITHOUT any -N suffix
# ---------------------------------------------------------------------------

def test_T4_microsecond_differentiation_no_suffix(tmp_path, monkeypatch):
    """Two seals whose run_started_at differ ONLY in microseconds must land in two
    distinct directories, each named with a 6-digit microsecond field and NO -N suffix
    (the timestamps already differ, so no collision-arbiter fallback is used).

    FAILS TODAY: strftime("%Y%m%d-%H%M%S") drops the microsecond field (seal.py:264),
    so both map to "20260602-000001" and collide; the second seal raises PermissionError.
    """
    b1 = _seal(tmp_path, monkeypatch, _MICRO_TS_A, pdf_name="a")
    b2 = _seal(tmp_path, monkeypatch, _MICRO_TS_B, pdf_name="b")

    assert b1 != b2, "distinct microseconds must produce distinct directories"
    pat = re.compile(r"^\d{8}-\d{6}-\d{6}$")
    assert pat.match(b1.name), f"bundle 1 name must be YYYYMMDD-HHMMSS-ffffff, no suffix: {b1.name!r}"
    assert pat.match(b2.name), f"bundle 2 name must be YYYYMMDD-HHMMSS-ffffff, no suffix: {b2.name!r}"
    assert b1.name.endswith("111111"), f"bundle 1 must carry microsecond field 111111: {b1.name!r}"
    assert b2.name.endswith("222222"), f"bundle 2 must carry microsecond field 222222: {b2.name!r}"


# ---------------------------------------------------------------------------
# T5 — bounded suffix exhaustion raises a LOUD RuntimeError
# ---------------------------------------------------------------------------

def test_T5_bounded_exhaustion_is_loud(tmp_path, monkeypatch):
    """With the collision bound lowered to 3, exactly three same-ts seals succeed
    (base, -2, -3); the fourth must raise a LOUD RuntimeError naming the run_ts —
    never hang, never silently reuse a directory.

    The bound constant (_MAX_SAME_TS_SEALS) does NOT exist yet, so the monkeypatch uses
    raising=False and does not error on its absence.

    FAILS TODAY (correct failing-first reason): the constant is absent (the setattr is a
    no-op relative to the code path), and the SECOND same-ts seal raises PermissionError
    before any bound is ever consulted.  That PermissionError propagates out of the loop
    below — outside the pytest.raises(RuntimeError) block — so the test fails today on the
    second seal, not on the RuntimeError assertion.
    """
    monkeypatch.setattr("audit_bundle.seal._MAX_SAME_TS_SEALS", 3, raising=False)

    # Three same-ts seals must succeed (base, base-2, base-3).
    for i in range(3):
        _seal(tmp_path, monkeypatch, _COLLIDE_TS, pdf_name=f"ok{i}")

    # The fourth same-ts seal exhausts the bound and must raise, mentioning run_ts.
    with pytest.raises(RuntimeError, match=r"20260602-000000"):
        _seal(tmp_path, monkeypatch, _COLLIDE_TS, pdf_name="overflow")


# ---------------------------------------------------------------------------
# T6 — two same-second signs produce two DISTINCT working-paper PDFs
# ---------------------------------------------------------------------------

def test_T6_sign_same_second_distinct_pdfs(tmp_path, monkeypatch):
    """Two sign_working_paper calls landing in the SAME wall-clock second must emit two
    distinct PDFs, neither overwritten.

    To make this deterministic (rather than relying on flaky real back-to-back timing
    that could straddle a second boundary), ui.sign.datetime.now is stubbed to return two
    timestamps within the SAME second that differ only in the microsecond field — exactly
    the collision the %f fix (ui/sign.py:121) is meant to resolve.

    FAILS TODAY: the filename uses strftime("%Y%m%d-%H%M%S") (ui/sign.py:121), which drops
    the microsecond field, so both calls compute the identical out_path and the second
    render overwrites the first — the same Path is returned and the distinct-paths
    assertion fails.  The %f fix makes now()-based collision practically impossible for
    sequential real calls.
    """
    base = datetime(2026, 6, 2, 0, 0, 7, tzinfo=timezone.utc)

    class _SameSecondClock:
        """now() returns two timestamps in the SAME second, differing only in microseconds."""

        def __init__(self):
            self._n = 0

        def now(self, tz=None):
            us = self._n * 222222  # 0 -> 000000, 1 -> 222222; both within second :07
            self._n += 1
            return base.replace(microsecond=us)

    monkeypatch.setattr(_sign_mod, "datetime", _SameSecondClock())

    rr = MockEngine().review()
    p1 = sign_working_paper(rr, reviewer_name="Jane Tan", firm_name="Tan & Co", out_dir=tmp_path)
    p2 = sign_working_paper(rr, reviewer_name="Jane Tan", firm_name="Tan & Co", out_dir=tmp_path)

    assert p1 != p2, "same-second signs must produce distinct PDF paths (no overwrite)"
    assert p1.exists() and p2.exists(), "both signed working-paper PDFs must exist"


# ---------------------------------------------------------------------------
# T7 — format regression pin: dir name carries the microsecond field
# ---------------------------------------------------------------------------

def test_T7_run_ts_format_has_microseconds(tmp_path, monkeypatch):
    """A single seal's directory name must match ^\\d{8}-\\d{6}-\\d{6}$
    (YYYYMMDD-HHMMSS-ffffff), pinning the fixed-width microsecond field.

    FAILS TODAY: run_ts = strftime("%Y%m%d-%H%M%S") (seal.py:264) produces
    "20260602-000005", which matches only ^\\d{8}-\\d{6}$ — the trailing -\\d{6}
    microsecond group is absent.
    """
    bundle = _seal(tmp_path, monkeypatch, _MICRO_TS_SINGLE, pdf_name="single")
    assert re.match(r"^\d{8}-\d{6}-\d{6}$", bundle.name), (
        f"bundle dir must be YYYYMMDD-HHMMSS-ffffff; got {bundle.name!r}"
    )
    assert bundle.name.endswith("123456"), (
        f"bundle dir must carry the microsecond field 123456; got {bundle.name!r}"
    )
