"""Decoder (decode/tcstring.mjs through Node) and the checks of decoder.py and consent_lists.py,
with the TC strings of tests/tc_fixtures.json (made by decode/fixtures.mjs). Needs Node."""
import json
import shutil
from pathlib import Path

import pytest

import decoder
from consent_lists import check_cmp_id, gvl_check, gvl_series

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node for the decoder")

FIXTURES = json.loads((Path(__file__).parent / "tc_fixtures.json").read_text())
DECODED = dict(zip(FIXTURES, decoder.decode_tc_strings(list(FIXTURES.values())))) if shutil.which("node") else {}

CMP_LIST = {"lastUpdated": "2026-10-22T16:00:21Z", "cmps": {
    "6": {"id": 6, "name": "Sourcepoint Technologies, Inc.", "isCommercial": True},
    "3": {"id": 3, "name": "LiveRamp", "isCommercial": True, "deletedDate": "2024-11-13T14:55:31.549Z"},
    "300": {"id": 300, "name": "Google LLC", "isCommercial": False},
}}
GVL = {"vendorListVersion": 100, "tcfPolicyVersion": 5, "purposes": {str(i): {} for i in range(1, 12)},
       "vendors": {"755": {"id": 755}, "793": {"id": 793, "deletedDate": "2026-01-01T00:00:00Z"}}}


def test_all_ids_explicit():
    # fix of F1: lists of set IDs instead of maxId
    assert DECODED["purposes_1_10"]["purposeConsents"] == [1, 10]
    assert DECODED["purposes_1_10"]["vendorConsents"] == [755]
    assert DECODED["all_purposes"]["purposeConsents"] == list(range(1, 12))
    assert DECODED["all_purposes"]["vendorConsents"] == [755, 793]
    assert DECODED["all_purposes_no_vendors"]["vendorConsents"] == []
    assert DECODED["no_consent"]["purposeConsents"] == []


def test_legitimate_interest_only():
    assert DECODED["li_only"]["purposeConsents"] == []
    assert DECODED["li_only"]["purposeLegitimateInterests"] == [2, 7]
    assert DECODED["li_only"]["vendorLegitimateInterests"] == [755]


def test_forbidden_li_for_purposes_3_to_6_is_not_hidden():
    # the library drops LI 3-6 when encoding, but must keep it when decoding
    decoded = DECODED["li_forbidden_3_to_6"]
    assert decoded["purposeLegitimateInterests"] == [2, 3, 4, 5, 6, 7]
    assert decoder.specification_checks(decoded)["forbidden_li_purposes"] == [3, 4, 5, 6]


def test_disclosed_vendors_segment():
    assert DECODED["all_purposes"]["disclosedVendorsPresent"] is True
    assert DECODED["all_purposes"]["vendorsDisclosed"] == [755, 793]
    assert DECODED["without_disclosed_vendors"]["disclosedVendorsPresent"] is False
    assert DECODED["without_disclosed_vendors"]["segments"] == ["core"]


def test_v23_deadline():
    # without_disclosed_vendors was created on 2026-10-29, after the deadline
    assert decoder.specification_checks(DECODED["without_disclosed_vendors"])["disclosed_vendors_missing_after_v23_deadline"]
    before = {**DECODED["without_disclosed_vendors"], "created": "2026-02-27T00:00:00.000Z"}
    assert not decoder.specification_checks(before)["disclosed_vendors_missing_after_v23_deadline"]
    assert not decoder.specification_checks(DECODED["all_purposes"])["disclosed_vendors_missing_after_v23_deadline"]


def test_policy_version():
    assert DECODED["policy_version_3"]["policyVersion"] == 3
    assert decoder.specification_checks(DECODED["policy_version_3"])["policy_version_outdated"]
    assert not decoder.specification_checks(DECODED["all_purposes"])["policy_version_outdated"]


def test_cmp_ids_0_and_1_are_decoded_and_kept():
    for key, cmp_id in (("cmp_id_0", 0), ("cmp_id_1", 1)):
        assert DECODED[key]["decoded"] is True
        assert DECODED[key]["cmpId"] == cmp_id
        assert DECODED[key]["cmpIdReplacedForDecoding"] is True
        assert DECODED[key]["purposeConsents"] == [1]
    assert DECODED["cmp_id_4095"]["cmpId"] == 4095
    assert DECODED["cmp_id_4095"]["cmpIdReplacedForDecoding"] is False


def test_v1_is_only_marked():
    assert DECODED["v1_specification_example"] == {"tcString": FIXTURES["v1_specification_example"], "version": 1,
                                                   "decoded": False, "reason": "TC string v1: stored raw only"}


def test_garbage_is_not_decoded():
    [decoded] = decoder.decode_tc_strings(["Cxyz"])
    assert decoded["decoded"] is False and decoded["reason"].startswith("decoding failed")


def test_check_cmp_id():
    assert check_cmp_id(6, CMP_LIST)["valid"] is True
    assert check_cmp_id(6, CMP_LIST)["name"] == "Sourcepoint Technologies, Inc."
    for invalid in (0, 1, 4095, 9999):
        assert check_cmp_id(invalid, CMP_LIST)["valid"] is False
    assert check_cmp_id(None, CMP_LIST)["reason"] == "missing"
    # LiveRamp was deleted on 2024-11-13
    assert check_cmp_id(3, CMP_LIST, "2024-10-01T00:00:00.000Z")["valid"] is True
    assert check_cmp_id(3, CMP_LIST, "2025-01-01T00:00:00.000Z") == {
        "cmp_id": 3, "name": "LiveRamp", "deleted_date": "2024-11-13T14:55:31.549Z",
        "valid": False, "reason": "deleted_before_string_created"}


def test_gvl_series_from_policy_version():
    assert gvl_series(5) == "v3" and gvl_series(4) == "v3"
    assert gvl_series(3) == "v2" and gvl_series(None) == "v2"


def test_gvl_check_unknown_and_deleted_vendors():
    decoded = {"policyVersion": 5, "vendorConsents": [755, 793, 1234], "vendorLegitimateInterests": [1234]}
    check = gvl_check(decoded, GVL)
    assert check["unknown_vendor_consents"] == [793, 1234]   # 793 deleted, 1234 not in the GVL
    assert check["unknown_vendor_legitimate_interests"] == [1234]
    assert check["gvl_vendor_list_version"] == 100
    assert gvl_check(decoded, None) == {"gvl_available": False}


def test_analyse_uses_the_gvl_version_of_the_string(monkeypatch):
    requested = []
    monkeypatch.setattr(decoder, "load_gvl", lambda version, policy: requested.append((version, policy)) or GVL)
    [entry] = decoder.analyse([FIXTURES["all_purposes"]], CMP_LIST)
    assert requested == [(100, 5)]                      # vendorListVersion of the string itself
    assert entry["checks"]["gvl_version_used"] == 100
    assert entry["checks"]["cmp"]["name"] == "Google LLC"
    assert entry["checks"]["tcf_version_by_segments"] == "v2.3"
    [v1] = decoder.analyse([FIXTURES["v1_specification_example"]], CMP_LIST)
    assert v1["tc_version"] == 1 and "checks" not in v1
