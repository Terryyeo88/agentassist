"""
tests/test_loader_login_error_hint.py — SAP B1 login-error message hardening.

The T5.3-V environment debugging showed the generic "check company_db / username /
password" hint sent us down the password path for a -304, which is actually an
SLD/CompanyDB error (a wrong password returns -301). These hermetic tests pin the
code-tailored hints + the robust error parser. No network, no SAP.
"""
from __future__ import annotations

from config.loader import _login_error_hint, _parse_sap_login_error


class _FakeResp:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


# --------------------------------------------------------------------------- #
# _parse_sap_login_error — robust across SL response shapes
# --------------------------------------------------------------------------- #

def test_parse_message_as_plain_string():
    # The shape this SBODEMOSG appliance returns: error.message is a plain string.
    resp = _FakeResp({"error": {"code": "-304", "message": "Fail to NONE-SSO login from SLD."}})
    code, msg = _parse_sap_login_error(resp)
    assert code == "-304"
    assert msg == "Fail to NONE-SSO login from SLD."


def test_parse_message_as_value_dict():
    # Other SL builds nest message under .value.
    resp = _FakeResp({"error": {"code": "-301", "message": {"value": "Invalid user/password"}}})
    code, msg = _parse_sap_login_error(resp)
    assert code == "-301"
    assert msg == "Invalid user/password"


def test_parse_falls_back_to_text_on_bad_json():
    resp = _FakeResp(payload=None, text="<html>502 Bad Gateway</html>")
    code, msg = _parse_sap_login_error(resp)
    assert code is None
    assert "502" in msg


# --------------------------------------------------------------------------- #
# _login_error_hint — code-tailored remediation
# --------------------------------------------------------------------------- #

def test_hint_304_points_at_companydb_not_password():
    hint = _login_error_hint("-304")
    assert "-304" in hint
    assert "CompanyDB" in hint or "company_db" in hint
    assert "schema" in hint.lower()           # HANA schema-name guidance
    assert "NOT a bad password" in hint


def test_hint_301_points_at_credentials():
    hint = _login_error_hint("-301")
    assert "-301" in hint
    assert "password" in hint.lower()
    assert "$" in hint                        # the dotenv-expansion warning


def test_hint_unknown_code_is_generic():
    hint = _login_error_hint(None)
    assert "company_db" in hint and "password" in hint
