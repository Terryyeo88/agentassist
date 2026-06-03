"""reasoning/measurement.py — deterministic recall / FP-rate scorer for Reg 26/27 candidates.

Matching is STRUCTURAL on (doc_num, line_index).  Text fields are never compared.
No I/O, no imports of orchestrator/, audit_bundle/, or SAP client.  Pure Python.

Usage::
    from reasoning.measurement import score, validate_fixture_lines
    validate_fixture_lines(labelled_lines)       # raises if determinability missing/invalid
    result = score(artefact["candidates"], labelled_lines)
    print(result["recall"], result["fp_rate"])
"""

from __future__ import annotations

_VALID_DETERMINABILITY: frozenset[str] = frozenset({"determinable", "indeterminate"})


def validate_fixture_lines(lines: list[dict]) -> None:
    """Raise ValueError if any line is missing or has an invalid 'determinability' field.

    Call this wherever a fixture is loaded before passing lines to score().
    Valid values: "determinable" | "indeterminate".
    """
    for line in lines:
        det = line.get("determinability")
        key = f"(doc_num={line.get('doc_num')}, line_index={line.get('line_index')})"
        if det is None:
            raise ValueError(
                f"Fixture line {key} is missing required field 'determinability'. "
                f"Add \"determinability\": \"determinable\" or \"indeterminate\" to every line."
            )
        if det not in _VALID_DETERMINABILITY:
            raise ValueError(
                f"Fixture line {key} has invalid determinability={det!r}; "
                f"must be one of {sorted(_VALID_DETERMINABILITY)}."
            )


def score(
    predicted_candidates: list[dict],
    labelled_lines: list[dict],
) -> dict:
    """Score the reasoning pass output against a set of labelled ground-truth lines.

    Lines are partitioned by the optional ``determinability`` field:

    * ``"determinable"`` (default when field absent): the correct answer can be
      established from the IRAS source documents.  These lines are scored as
      TP / FP / FN / TN using ``expected_candidate`` as the truth label.
    * ``"indeterminate"``: the correct answer cannot be determined from IRAS
      docs alone and requires a human to inspect the underlying invoice.  These
      lines are counted only in ``indeterminate.surface_rate``; they do NOT
      contribute to recall or fp_rate.

    Args:
        predicted_candidates:
            The list of candidate dicts from the judgment artefact
            (``artefact["candidates"]``).  Each entry must have:
            ``doc_num``, ``line_index``, ``suspected_category``.

        labelled_lines:
            Ground-truth lines from the measurement fixture.  Each entry must
            have ``doc_num``, ``line_index``, ``expected_candidate`` (bool).
            Positives additionally carry ``expected_category`` (str).
            Lines without ``determinability`` default to ``"determinable"``.

    Returns a dict with:

    Top-level determinable metrics (over determinable lines only):
        ``tp``, ``fp``, ``fn``, ``tn``      — integer confusion-matrix cells
        ``recall``                           — tp / (tp+fn); **None** when tp+fn==0
        ``fp_rate``                          — fp / (fp+tn); **None** when fp+tn==0
        ``category_accuracy``               — fraction of TPs with correct
                                              ``suspected_category``; 0.0 when
                                              there are no TPs
        ``determinable_support``            — count of determinable lines

    Top-level indeterminate metrics:
        ``indeterminate``                    — dict with:
            ``surface_rate``                — surfaced / total indeterminate;
                                              **None** when total == 0
            ``support``                     — count of indeterminate lines

    Per-line detail:
        ``per_line``                         — one dict per labelled line;
                                              disposition is one of TP/FP/FN/TN/INDET
        ``out_of_fixture_predictions``       — count of candidates whose
                                              (doc_num, line_index) does not
                                              appear in labelled_lines (not scored)

    Per-category breakdown (over each category's DETERMINABLE lines):
        ``per_category``                     — dict keyed by expected_category
                                              (or "n/a" for negatives without one).
                                              Each value has:
            ``tp``, ``fp``, ``fn``
            ``recall``                       — None when sp==0
            ``fp_rate``                      — None when sn==0
            ``support_positive``             — determinable positives in category
            ``support_negative``             — determinable negatives in category
            ``indeterminate_surface_rate``   — None when indet_support==0
            ``indeterminate_support``        — indeterminate lines in category
    """
    # Build a lookup: (doc_num, line_index) → predicted candidate dict
    predicted: dict[tuple[int, int], dict] = {}
    for c in predicted_candidates:
        key = (int(c["doc_num"]), int(c["line_index"]))
        predicted[key] = c

    labelled_keys: set[tuple[int, int]] = set()

    # Determinable overall counters
    tp = fp = fn = tn = 0
    cat_tp_correct = 0
    cat_tp_total = 0

    # Indeterminate overall counters
    indet_surfaced = 0
    indet_total = 0

    # Per-category accumulators: cat → {det_tp, det_fp, det_fn, det_sp, det_sn,
    #                                    indet_surfaced, indet_total}
    _cat: dict[str, dict] = {}

    per_line: list[dict] = []

    for line in labelled_lines:
        key = (int(line["doc_num"]), int(line["line_index"]))
        labelled_keys.add(key)

        det: str = line.get("determinability", "determinable")
        expected_pos: bool = bool(line.get("expected_candidate", False))
        expected_cat_raw: str | None = line.get("expected_category")
        bucket_cat: str = expected_cat_raw or "n/a"
        is_predicted: bool = key in predicted
        pred_dict: dict | None = predicted.get(key)
        pred_cat: str | None = pred_dict.get("suspected_category") if pred_dict else None

        # Ensure bucket exists
        b = _cat.setdefault(bucket_cat, {
            "det_tp": 0, "det_fp": 0, "det_fn": 0,
            "det_sp": 0, "det_sn": 0,
            "indet_surfaced": 0, "indet_total": 0,
        })

        if det == "indeterminate":
            indet_total += 1
            b["indet_total"] += 1
            if is_predicted:
                indet_surfaced += 1
                b["indet_surfaced"] += 1
            disposition = "INDET"
            category_correct: bool | None = None
        else:
            # Determinable: score against expected_candidate
            if expected_pos and is_predicted:
                disposition = "TP"
                tp += 1
                b["det_tp"] += 1
                b["det_sp"] += 1
                cat_tp_total += 1
                if expected_cat_raw is not None and pred_cat == expected_cat_raw:
                    cat_tp_correct += 1
                category_correct = (
                    (pred_cat == expected_cat_raw) if expected_cat_raw is not None else None
                )
            elif expected_pos and not is_predicted:
                disposition = "FN"
                fn += 1
                b["det_fn"] += 1
                b["det_sp"] += 1
                category_correct = None
            elif not expected_pos and is_predicted:
                disposition = "FP"
                fp += 1
                b["det_fp"] += 1
                b["det_sn"] += 1
                category_correct = None
            else:
                disposition = "TN"
                tn += 1
                b["det_sn"] += 1
                category_correct = None

        per_line.append({
            "doc_num": int(line["doc_num"]),
            "line_index": int(line["line_index"]),
            "line_description": str(line.get("line_description", "")),
            "expected_candidate": expected_pos,
            "expected_category": expected_cat_raw,
            "predicted": is_predicted,
            "predicted_category": pred_cat,
            "disposition": disposition,
            "category_correct": category_correct,
        })

    # Count predictions whose (doc_num, line_index) falls outside the labelled set.
    out_of_fixture = sum(1 for key in predicted if key not in labelled_keys)

    # Overall determinable metrics — None for zero denominators (never raises)
    recall: float | None = (
        round(tp / (tp + fn), 6) if (tp + fn) > 0 else None
    )
    fp_rate: float | None = (
        round(fp / (fp + tn), 6) if (fp + tn) > 0 else None
    )
    category_accuracy: float = (
        round(cat_tp_correct / cat_tp_total, 6) if cat_tp_total > 0 else 0.0
    )
    indet_surface_rate: float | None = (
        round(indet_surfaced / indet_total, 6) if indet_total > 0 else None
    )

    # Build per_category
    per_category: dict[str, dict] = {}
    for cat in sorted(_cat):
        b = _cat[cat]
        sp = b["det_sp"]
        sn = b["det_sn"]
        per_category[cat] = {
            "tp": b["det_tp"],
            "fp": b["det_fp"],
            "fn": b["det_fn"],
            "recall": round(b["det_tp"] / sp, 6) if sp > 0 else None,
            "fp_rate": round(b["det_fp"] / sn, 6) if sn > 0 else None,
            "support_positive": sp,
            "support_negative": sn,
            "indeterminate_surface_rate": (
                round(b["indet_surfaced"] / b["indet_total"], 6)
                if b["indet_total"] > 0 else None
            ),
            "indeterminate_support": b["indet_total"],
        }

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "recall": recall,
        "fp_rate": fp_rate,
        "category_accuracy": category_accuracy,
        "determinable_support": tp + fp + fn + tn,
        "indeterminate": {
            "surface_rate": indet_surface_rate,
            "support": indet_total,
        },
        "per_line": per_line,
        "out_of_fixture_predictions": out_of_fixture,
        "per_category": per_category,
    }
