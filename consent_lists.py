"""Global Vendor List (GVL) and CMP list of the IAB.

GVL: every TC string is evaluated against the GVL version written in the string itself
(vendorListVersion), not against the current one. Strings with TcfPolicyVersion >= 4 (TCF v2.2
and later) use the GVL v3 archive; older strings the GVL v2 archive (the version numbers of the
two series overlap, so the policy version decides). Downloaded files are kept in data/gvl/.

CMP list: one snapshot per run (data/cmp-list/), its lastUpdated goes into the run metadata. A
CMP ID is valid if it is in the list and was not deleted before the string was created. Matte
et al. (2020, Appendix F) found the invalid IDs 0, 1 and 4095.
"""
import hashlib
import json
import urllib.request
from datetime import datetime

import config

GVL_LATEST_URL = "https://vendor-list.consensu.org/v3/vendor-list.json"
GVL_ARCHIVE_URL = "https://vendor-list.consensu.org/{series}/archives/vendor-list-v{version}.json"
CMP_LIST_URL = "https://cmplist.consensu.org/v2/cmp-list.json"
GVL_DIR = config.DATA_DIR / "gvl"
CMP_LIST_DIR = config.DATA_DIR / "cmp-list"


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": config.HTTP_USER_AGENT})
    with urllib.request.urlopen(request, timeout=config.HTTP_TIMEOUT * 3) as response:
        return response.read()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# --- GVL

def gvl_series(policy_version):
    """'v3' for TcfPolicyVersion >= 4 (TCF v2.2 and later), 'v2' before."""
    return "v3" if policy_version is not None and policy_version >= 4 else "v2"


def gvl_path(series, version):
    return GVL_DIR / series / f"vendor-list-v{version}.json"


def load_gvl(version, policy_version):
    """The GVL with this vendorListVersion, from the cache or the IAB archive. None if it does
    not exist (e.g. version 0 or a version newer than the latest)."""
    if not version:
        return None
    series = gvl_series(policy_version)
    path = gvl_path(series, version)
    if not path.exists():
        try:
            data = download(GVL_ARCHIVE_URL.format(series=series, version=version))
        except Exception:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return json.loads(path.read_text())


def latest_gvl():
    """Downloads the current GVL v3, keeps it under its version number, returns its metadata."""
    data = download(GVL_LATEST_URL)
    gvl = json.loads(data)
    path = gvl_path("v3", gvl["vendorListVersion"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"url": GVL_LATEST_URL, "vendorListVersion": gvl["vendorListVersion"],
            "tcfPolicyVersion": gvl["tcfPolicyVersion"], "gvlSpecificationVersion": gvl["gvlSpecificationVersion"],
            "lastUpdated": gvl["lastUpdated"], "vendors": len(gvl["vendors"]), "sha256": sha256(data),
            "path": str(path)}


def gvl_check(decoded, gvl):
    """What the GVL of the string says about its vendors: IDs that are not in that GVL version
    (or deleted in it) cannot have been disclosed to the user."""
    if gvl is None:
        return {"gvl_available": False}
    vendors = gvl.get("vendors", {})
    known = {int(v) for v, info in vendors.items() if not info.get("deletedDate")}
    return {
        "gvl_available": True,
        "gvl_series": gvl_series(decoded.get("policyVersion")),
        "gvl_vendor_list_version": gvl.get("vendorListVersion"),
        "gvl_tcf_policy_version": gvl.get("tcfPolicyVersion"),
        "gvl_purposes": len(gvl.get("purposes", {})),
        "unknown_vendor_consents": [v for v in decoded.get("vendorConsents", []) if v not in known],
        "unknown_vendor_legitimate_interests": [v for v in decoded.get("vendorLegitimateInterests", []) if v not in known],
    }


# --- CMP list

def latest_cmp_list():
    """Downloads the current CMP list as the snapshot of this run, returns it and its metadata."""
    data = download(CMP_LIST_URL)
    cmp_list = json.loads(data)
    stamp = cmp_list["lastUpdated"].replace(":", "-")
    path = CMP_LIST_DIR / f"cmp-list-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    metadata = {"url": CMP_LIST_URL, "lastUpdated": cmp_list["lastUpdated"], "cmps": len(cmp_list["cmps"]),
                "sha256": sha256(data), "path": str(path)}
    return cmp_list, metadata


def parse_date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def check_cmp_id(cmp_id, cmp_list, created=None):
    """Is the CMP ID of a string valid? created: creation date of the string (ISO), if known."""
    if cmp_id is None:
        return {"cmp_id": None, "valid": False, "reason": "missing"}
    entry = cmp_list["cmps"].get(str(cmp_id))
    if entry is None:
        reason = {0: "not_in_cmp_list (0: no CMP)", 4095: "not_in_cmp_list (4095: largest 12-bit value)"}
        return {"cmp_id": cmp_id, "valid": False, "reason": reason.get(cmp_id, "not_in_cmp_list")}
    deleted = parse_date(entry.get("deletedDate"))
    result = {"cmp_id": cmp_id, "name": entry["name"].strip(), "deleted_date": entry.get("deletedDate")}
    if deleted and created and parse_date(created) > deleted:
        return {**result, "valid": False, "reason": "deleted_before_string_created"}
    if deleted:
        return {**result, "valid": True, "reason": "deleted_after_string_created" if created else "deleted"}
    return {**result, "valid": True, "reason": None}
