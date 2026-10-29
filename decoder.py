"""TC strings: decoding (decode/tcstring.mjs through Node) and the checks of each string against
the specification, its own GVL version and the CMP list.

    analyse([tc_string, ...], cmp_list)  ->  one dict per string, all IDs explicit

The version is taken from the string itself: v1 strings are only marked (stored raw).
"""
import json
import subprocess
from datetime import datetime, timezone

import config
from consent_lists import check_cmp_id, gvl_check, load_gvl

DECODER_CLI = config.DECODE_DIR / "cli.mjs"
FORBIDDEN_LI_PURPOSES = (3, 4, 5, 6)              # no legitimate interest since TCF v2.2
MIN_VALID_POLICY_VERSION = 4                      # TCF v2.2; smaller ones invalid since 30.09.2023
DISCLOSED_VENDORS_MANDATORY_FROM = datetime(2026, 3, 1, tzinfo=timezone.utc)   # TCF v2.3, see below


def decode_tc_strings(tc_strings):
    """Decodes all strings in one Node process. Returns one dict per string, in the same order."""
    if not tc_strings:
        return []
    lines = "".join(f"{s}\n" for s in tc_strings)
    result = subprocess.run(["node", str(DECODER_CLI)], input=lines, capture_output=True, text=True, check=True)
    return [json.loads(line) for line in result.stdout.splitlines()]


def specification_checks(decoded):
    """Checks against the specification that need no GVL.

    disclosedVendors: mandatory since TCF v2.3. The specification says strings created before
    March 1, 2026 stay valid without it (IAB Europe names 28.02.2026 as the deadline); the
    Created field only has day precision, so strings from 1 March 2026 on count as "should have it".
    """
    created = datetime.fromisoformat(decoded["created"].replace("Z", "+00:00")) if decoded.get("created") else None
    li = decoded.get("purposeLegitimateInterests", [])
    return {
        "disclosed_vendors_present": decoded.get("disclosedVendorsPresent"),
        "tcf_version_by_segments": "v2.3" if decoded.get("disclosedVendorsPresent") else "v2.2 (without disclosedVendors)",
        "disclosed_vendors_missing_after_v23_deadline":
            bool(created and created >= DISCLOSED_VENDORS_MANDATORY_FROM and not decoded.get("disclosedVendorsPresent")),
        "policy_version_outdated": (decoded.get("policyVersion") or 0) < MIN_VALID_POLICY_VERSION,
        "not_service_specific": decoded.get("isServiceSpecific") is False,
        "forbidden_li_purposes": [p for p in li if p in FORBIDDEN_LI_PURPOSES],
    }


def analyse(tc_strings, cmp_list):
    """Decodes every string and adds the checks. The GVL is the one of the string itself."""
    results = []
    for decoded in decode_tc_strings(tc_strings):
        entry = {"tc_string": decoded.pop("tcString"), "tc_version": decoded.get("version"), "decoded": decoded}
        if decoded.get("decoded"):
            gvl = load_gvl(decoded.get("vendorListVersion"), decoded.get("policyVersion"))
            entry["checks"] = {
                **specification_checks(decoded),
                "gvl_version_used": decoded.get("vendorListVersion"),
                **gvl_check(decoded, gvl),
                "cmp": check_cmp_id(decoded.get("cmpId"), cmp_list, decoded.get("created")),
            }
        results.append(entry)
    return results
