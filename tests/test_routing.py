"""
Tests for report/routing.py.
Pure unit tests — no fixture, no I/O.
"""
from report.constants import APPENDIX1_WORDING
from report.routing import appendix1_for, route


class TestRoute:
    # ── E1 ────────────────────────────────────────────────────────────────────

    def test_e1_routes_to_template_2(self):
        assert route("E1", "SR")["number"] == 2

    def test_e1_ds_routes_to_template_2(self):
        assert route("E1", "DS")["number"] == 2

    # ── E2 ───────────────────────────────────────────────────────────────────

    def test_e2_bl_routes_to_template_6(self):
        assert route("E2", "BL")["number"] == 6

    def test_e2_nr_routes_to_template_6(self):
        assert route("E2", "NR")["number"] == 6

    def test_e2_zr_routes_to_template_3(self):
        assert route("E2", "ZR")["number"] == 3

    def test_e2_os_routes_to_template_3(self):
        assert route("E2", "OS")["number"] == 3

    def test_e2_zp_routes_to_template_3(self):
        # T2.21b / T2.20 Section 0 finding #2: ZP is zero-rated and belongs in
        # _ZERO_RATED_VGS alongside ZR/OS. Expected to fail today: _ZERO_RATED_VGS
        # is frozenset({"ZR", "OS"}), so "ZP" falls through to the Template 1
        # default in _template_number.
        assert route("E2", "ZP")["number"] == 3

    def test_e2_es33_defaults_to_template_5(self):
        assert route("E2", "ES33")["number"] == 5

    def test_e2_es33_routes_to_template_4_when_actively_makes_exempt(self):
        assert route("E2", "ES33", actively_makes_exempt=True)["number"] == 4

    def test_e2_esn33_defaults_to_template_5(self):
        assert route("E2", "ESN33")["number"] == 5

    def test_e2_esn33_routes_to_template_4_when_actively_makes_exempt(self):
        assert route("E2", "ESN33", actively_makes_exempt=True)["number"] == 4

    # ── E3 / E4 ──────────────────────────────────────────────────────────────

    def test_e3_sr_routes_to_template_2(self):
        assert route("E3", "SR")["number"] == 2

    def test_e3_ds_routes_to_template_2(self):
        assert route("E3", "DS")["number"] == 2

    def test_e3_tx_routes_to_template_6(self):
        assert route("E3", "TX")["number"] == 6

    def test_e4_sr_routes_to_template_2(self):
        assert route("E4", "SR")["number"] == 2

    def test_e4_tx_routes_to_template_6(self):
        assert route("E4", "TX")["number"] == 6

    # ── NO_GST_REG / COMPLETENESS / unknown ──────────────────────────────────

    def test_no_gst_reg_routes_to_template_6(self):
        assert route("NO_GST_REG", None)["number"] == 6

    def test_completeness_routes_to_template_1(self):
        assert route("COMPLETENESS", None)["number"] == 1

    def test_unknown_code_routes_to_template_1(self):
        assert route("UNKNOWN_CODE", "ZZ")["number"] == 1

    # ── TemplateRef shape ────────────────────────────────────────────────────

    def test_template_ref_label_is_non_empty(self):
        ref = route("E1", "SR")
        assert ref["label"] != ""

    def test_template_ref_label_for_e1_mentions_standard_rated(self):
        ref = route("E1", "SR")
        assert "3A" in ref["label"] or "Standard-rated" in ref["label"]

    def test_none_vat_group_does_not_raise(self):
        # Route with None vat_group should fall back gracefully
        ref = route("E1", None)
        assert ref["number"] == 2


class TestAppendix1For:
    # ── E1 ────────────────────────────────────────────────────────────────────

    def test_e1_returns_wrong_classification_string(self):
        result = appendix1_for("E1", "SR")
        assert result == APPENDIX1_WORDING["E1"]
        assert "Wrong classification" in result

    # ── E2 — zero-rated ───────────────────────────────────────────────────────

    def test_e2_zr_returns_e2_zr_wording(self):
        assert appendix1_for("E2", "ZR") == APPENDIX1_WORDING["E2_ZR"]

    def test_e2_os_also_returns_e2_zr_wording(self):
        # OS shares the zero-rated key
        assert appendix1_for("E2", "OS") == APPENDIX1_WORDING["E2_ZR"]

    def test_e2_zr_and_os_return_identical_string(self):
        assert appendix1_for("E2", "ZR") == appendix1_for("E2", "OS")

    def test_e2_zp_returns_e2_zr_wording(self):
        # T2.21b / T2.20 Section 0 finding #2: ZP shares the zero-rated
        # Appendix 1 wording with ZR/OS. Expected to fail today:
        # _appendix1_key falls through to "UNKNOWN_VATGROUP" for ZP.
        assert appendix1_for("E2", "ZP") == APPENDIX1_WORDING["E2_ZR"]

    # ── E2 — exempt ──────────────────────────────────────────────────────────

    def test_e2_es33_returns_exempt_wording(self):
        assert appendix1_for("E2", "ES33") == APPENDIX1_WORDING["E2_EXEMPT"]

    def test_e2_esn33_returns_exempt_wording(self):
        assert appendix1_for("E2", "ESN33") == APPENDIX1_WORDING["E2_EXEMPT"]

    def test_e2_es33_and_esn33_return_identical_string(self):
        assert appendix1_for("E2", "ES33") == appendix1_for("E2", "ESN33")

    # ── NO_GST_REG ───────────────────────────────────────────────────────────

    def test_no_gst_reg_returns_non_registered_wording(self):
        result = appendix1_for("NO_GST_REG", None)
        assert result == APPENDIX1_WORDING["NO_GST_REG"]
        assert "non-GST registered" in result

    # ── Fallback: never KeyError ──────────────────────────────────────────────

    def test_e2_unknown_vatgroup_returns_unknown_vatgroup_wording(self):
        result = appendix1_for("E2", "ZZ")
        assert result == APPENDIX1_WORDING["UNKNOWN_VATGROUP"]

    def test_unresolved_never_raises_keyerror(self):
        result = appendix1_for("E2", "ZZ")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_completely_unknown_code_returns_unknown_vatgroup_wording(self):
        result = appendix1_for("E99", "XX")
        assert result == APPENDIX1_WORDING["UNKNOWN_VATGROUP"]
