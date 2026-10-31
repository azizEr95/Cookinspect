"""The violation functions with real TC strings (tests/tc_fixtures.json, made by decode/fixtures.mjs),
decoded and stored as in a crawl and read back with site_data.load_tc_strings. Needs Node."""
import json
import shutil
from pathlib import Path

import pytest

import database
import decoder
import site_data
import violations as v
from test_violations import automatic, phase, semi

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node for the decoder")

FIXTURES = json.loads((Path(__file__).parent / "tc_fixtures.json").read_text())
CMP_LIST = {"lastUpdated": "2026-10-22T16:00:21Z", "cmps": {"300": {"id": 300, "name": "Google LLC"}}}
ALL = list(range(1, 12))


@pytest.fixture(scope="module")
def strings():
    """{fixture name: TC string as site_data reads it}"""
    original = decoder.load_gvl
    decoder.load_gvl = lambda version, policy: None   # no download in tests
    try:
        conn = database.connect(":memory:")
        ids = database.store_tc_strings(conn, list(FIXTURES.values()), CMP_LIST)
        loaded = site_data.load_tc_strings(conn)
    finally:
        decoder.load_gvl = original
    return {name: loaded[ids[value]] for name, value in FIXTURES.items() if ids.get(value) in loaded}


def test_fixtures_are_read_as_expected(strings):
    assert strings["purposes_1_10"]["purposes"] == {1, 10}
    assert strings["all_purposes"]["purposes"] == set(ALL)
    assert strings["all_purposes_no_vendors"]["vendors"] == set()
    assert strings["policy_version_3"]["policy_version"] == 3


def test_v1_with_purposes_1_and_10_is_not_all_purposes(strings):
    result = v.v1(automatic(phase(strings["purposes_1_10"]), phase(strings["purposes_1_10"])))
    assert (result["value"], result["purposes_min"], result["all_purposes"]) == (v.YES, 2, False)
    assert v.v1(automatic(phase(strings["all_purposes"]), phase(strings["all_purposes"])))["all_purposes"] is True


def test_v1_matte_variant_without_vendors(strings):
    site = automatic(phase(strings["all_purposes_no_vendors"]), phase(strings["all_purposes_no_vendors"]))
    assert v.v1(site)["value"] == v.YES
    assert v.v1(site, matte_variant=True)["value"] == v.NO


def test_v4_variants_with_real_strings(strings):
    accept = phase(strings["all_purposes"])
    ignored_no_vendor = semi(phase(strings["all_purposes_no_vendors"]), accept)
    assert [v.v4(ignored_no_vendor, k)["value"] for k in ("strict", "matte", "lax", "all11")] == [v.YES, v.NO, v.YES, v.YES]
    assert v.v4_rank(ignored_no_vendor) == v.V4_ORDER.index("streng ohne Vendor-Consent")
    partly = semi(phase(strings["purposes_1_10"]), accept)
    assert [v.v4(partly, k)["value"] for k in ("strict", "lax", "all10")] == [v.NO, v.YES, v.NO]
    assert v.v4_rank(partly) == v.V4_ORDER.index("nur locker")
    respected = semi(phase(strings["no_consent"]), accept)
    assert v.v4_rank(respected) == v.V4_ORDER.index("kein Verstoß")


def test_li_after_reject_only_li_and_forbidden_3_to_6(strings):
    accept = phase(strings["all_purposes"])
    only_li = v.li_after_reject(semi(phase(strings["li_only"]), accept), lambda version, policy: None)
    assert (only_li["purpose_li"], only_li["purpose_li_3_6"], only_li["vendor_li"]) == ([2, 7], [], 1)
    forbidden = v.li_after_reject(semi(phase(strings["li_forbidden_3_to_6"]), accept), lambda version, policy: None)
    assert forbidden["purpose_li_3_6"] == [3, 4, 5, 6]
    # LI is not V4: no purpose consent after rejecting
    assert v.v4(semi(phase(strings["li_forbidden_3_to_6"]), accept), "lax")["value"] == v.NO


def test_e5_without_disclosed_vendors_is_not_evaluable(strings):
    assert v.undisclosed_consent(phase(strings["without_disclosed_vendors"]))["value"] == v.NA
    assert v.undisclosed_consent(phase(strings["purposes_1_10"]))["value"] == v.NO   # 755 is disclosed


def test_policy_version_3_has_10_purposes(strings):
    assert v.all_purposes(strings["policy_version_3"]) == v.PURPOSES_V2_1
    assert v.all_purposes(strings["all_purposes"]) == v.PURPOSES_V2_2
    result = v.v1(automatic(phase(strings["policy_version_3"]), phase(strings["policy_version_3"])))
    assert (result["value"], result["all_purposes"]) == (v.YES, False)
