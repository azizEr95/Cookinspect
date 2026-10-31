"""The violations as exchangeable functions (CLAUDE.md, Definitionen der Verstöße). They take the
plain dicts of site_data.py and return a result {"value": "ja" | "nein" | "nicht auswertbar",
"reason": ..., ...}; nothing is stored. Main figure: channel 1 only (site_data.MAIN_CHANNELS);
variant "Matte-Kanäle": a violation if any channel shows it (site_data.MATTE_CHANNELS).

V4 is computed on the snapshots after the reload (CLAUDE.md); moment="action" gives the same on
the snapshots right after the action, shown separately.
"""
from site_data import MAIN_CHANNELS, session_of

YES, NO, NA = "ja", "nein", "nicht auswertbar"

# Purpose 11 exists since TCF v2.2 (policy version 4)
PURPOSES_V2_1 = frozenset(range(1, 11))
PURPOSES_V2_2 = frozenset(range(1, 12))
LI_NOT_ALLOWED = frozenset({3, 4, 5, 6})   # no legitimate interest for purposes 3-6 since v2.2

COOKIEWALL_HANDLINGS = ("exclude", "count_as_v2")
COOKIEWALL_TEXT = {"exclude": "w ausgeschlossen", "count_as_v2": "w als V2"}


def result(value, reason=None, **details):
    return {"value": value, "reason": reason, **details}


def all_purposes(tc_string):
    return PURPOSES_V2_2 if (tc_string["policy_version"] or 0) >= 4 else PURPOSES_V2_1


# --- what a phase shows

def strings_of(phase, channels):
    """Decoded v2 TC strings of the phase in these channels."""
    if phase is None:
        return []
    return [o["tc_string"] for o in phase["observations"]
            if o["channel"] in channels and o["status"] == "measured" and o["tc_string"]
            and o["tc_string"]["decoded"] and o["tc_string"]["tc_version"] == 2]


def consent(phase, channels):
    """(evaluable, purposes, vendors) of the phase: union over all strings of the channels.
    Not evaluable without any decoded string (e.g. channel 1 with empty tcData, E7)."""
    strings = strings_of(phase, channels)
    purposes = set().union(*(s["purposes"] for s in strings)) if strings else set()
    vendors = set().union(*(s["vendors"] for s in strings)) if strings else set()
    return bool(strings), purposes, vendors


def why_not_evaluable(phase, channels):
    if phase is None:
        return "Snapshot fehlt"
    statuses = sorted({o["status"] for o in phase["observations"] if o["channel"] in channels})
    return "kein TC-String (" + ", ".join(statuses or ["keine Beobachtung"]) + ")"


# --- V1 consent before the choice (automatic mode, both sessions)

def v1(automatic, channels=MAIN_CHANNELS, matte_variant=False):
    """Yes only if both snapshots "before" show >= 1 purpose consent (Matte variant: and >= 1
    vendor consent). Not evaluable if a session has no snapshot or no TC string (E7)."""
    if automatic is None:
        return result(NA, "kein automatischer Modus")
    before = [s["phases"].get("before") for s in automatic["sessions"]]
    if len(before) < 2 or None in before:
        return result(NA, "weniger als zwei Vorher-Snapshots (nicht geladen?)")
    blocked = [s["number"] for s in automatic["sessions"] if s["blocked"]]
    seen = [consent(phase, channels) for phase in before]
    if not all(evaluable for evaluable, _, _ in seen):
        reasons = [f"Sitzung {n}: {why_not_evaluable(phase, channels)}"
                   for n, (phase, (evaluable, _, _)) in enumerate(zip(before, seen), 1) if not evaluable]
        if blocked:
            reasons.append(f"gesperrt in Sitzung {', '.join(map(str, blocked))}")
        return result(NA, "; ".join(reasons))
    shows = [bool(purposes) and (bool(vendors) or not matte_variant) for _, purposes, vendors in seen]
    fewest = min(len(purposes) for _, purposes, _ in seen)
    # "all purposes" as Matte's row "5 purposes": 1-11 for policy version >= 4, otherwise 1-10
    complete = all(purposes >= all_purposes(strings_of(phase, channels)[0])
                   for phase, (_, purposes, _) in zip(before, seen))
    return result(YES if all(shows) else NO, None if all(shows) else "mindestens eine Sitzung ohne Zustimmung",
                  purposes_min=fewest, all_purposes=all(shows) and complete)


# --- V2 no way to reject

def v2(label, handling="exclude"):
    """level: "1. Ebene", "nur 2. Ebene" or "gar nicht". A cookiewall without a free way to
    reject (w) is excluded or counted as "gar nicht", depending on the handling."""
    if label is None:
        return result(NA, "kein Label")
    outcome = label["outcome"]
    if outcome == "rejected":
        return result(NO, level="1. Ebene" if label["reject_level"] == 1 else "nur 2. Ebene")
    if outcome == "n":
        return result(YES, level="gar nicht")
    if outcome == "w":
        if handling == "count_as_v2":
            return result(YES, "Cookiewall ohne kostenloses Ablehnen", level="gar nicht (Cookiewall)")
        return result(NA, "Cookiewall ohne kostenloses Ablehnen, ausgeschlossen")
    return result(NA, {"b": "kein Banner", "x": "Banner kaputt"}[outcome])


# --- V3 pre-selected options

def v3(label, what="purposes", matte_denominator=False):
    """what: "purposes", "vendors" or "either" (Matte: purpose or vendor options pre-ticked).
    Denominator: sites with a way to reject (r) and a 2nd layer; "?" = not checked, outside the
    denominator. matte_denominator: all sites with a way to reject (Matte, 508), no 2nd layer
    counts as not pre-selected."""
    if label is None or label["outcome"] != "rejected":
        return result(NA, "keine kostenlose Ablehnmöglichkeit" if label else "kein Label")
    if label["settings_layer_available"] != 1:
        if matte_denominator:
            return result(NO, "keine 2. Ebene")
        return result(NA, "keine 2. Ebene" if label["settings_layer_available"] == 0 else "2. Ebene nicht geprüft")
    values = {"purposes": [label["purposes_preselected"]], "vendors": [label["vendors_preselected"]],
              "either": [label["purposes_preselected"], label["vendors_preselected"]]}[what]
    if 1 in values:
        return result(YES)
    if None in values:
        return result(NA, "nicht geprüft")
    return result(NO)


def v3_cookiewall(label):
    """Extra line, not part of V3: pre-selection on the 2nd layer of cookiewalls (code w).
    value "ja" if purposes or vendors are pre-selected; purposes and vendors separately."""
    if label is None or label["outcome"] != "w":
        return result(NA, "keine Cookiewall (w)")
    if label["settings_layer_available"] != 1:
        return result(NA, "keine 2. Ebene")
    as_text = {1: YES, 0: NO, None: NA}
    purposes, vendors = as_text[label["purposes_preselected"]], as_text[label["vendors_preselected"]]
    return result(YES if YES in (purposes, vendors) else NO if (purposes, vendors) == (NO, NO) else NA,
                  purposes=purposes, vendors=vendors)


# --- V4 choice not respected

def v4_phases(semi, moment="reload"):
    """(after reject, after accept) of the examination; moment "reload" or "action"."""
    suffix = "_reload" if moment == "reload" else ""
    reject, accept = session_of(semi, "reject"), session_of(semi, "accept")
    return (reject["phases"].get(f"after_reject{suffix}") if reject else None,
            accept["phases"].get(f"after_accept{suffix}") if accept else None)


def v4(semi, variant="strict", channels=MAIN_CHANNELS, moment="reload"):
    """variant: strict (after rejecting all purposes set that are set after accepting; only if
    that set is not empty), matte (strict and >= 1 vendor consent), lax (>= 1 purpose after
    rejecting), all10 / all11 (all purposes 1-10 / 1-11 after rejecting, extra figures)."""
    if semi is None or semi["label"] is None or semi["label"]["outcome"] != "rejected":
        return result(NA, "nicht abgelehnt (Code nicht r)")
    after_reject, after_accept = v4_phases(semi, moment)
    evaluable, rejected, vendors = consent(after_reject, channels)
    if not evaluable:
        return result(NA, "nach Ablehnen: " + why_not_evaluable(after_reject, channels))
    details = {"purposes_after_reject": sorted(rejected), "vendors_after_reject": len(vendors)}
    if variant == "lax":
        return result(YES if rejected else NO, **details)
    details["all_purposes"] = rejected >= all_purposes(strings_of(after_reject, channels)[0])
    if variant in ("all10", "all11"):
        return result(YES if rejected >= (PURPOSES_V2_1 if variant == "all10" else PURPOSES_V2_2) else NO, **details)
    accept_evaluable, accepted, _ = consent(after_accept, channels)
    if not accept_evaluable:
        return result(NA, "nach Akzeptieren: " + why_not_evaluable(after_accept, channels), **details)
    if not accepted:
        return result(NA, "Zweckmenge nach Akzeptieren leer", **details)
    details["purposes_after_accept"] = sorted(accepted)
    respected = not accepted <= rejected or (variant == "matte" and not vendors)
    return result(NO if respected else YES, **details)


def v4_action_differs(semi, channels=MAIN_CHANNELS):
    """Does the snapshot right after the action show other purposes or vendors than the one
    after the reload? Per session (reject, accept); None if one of the two is missing."""
    differs = {}
    for kind in ("reject", "accept"):
        session = session_of(semi, kind) if semi else None
        if session is None:
            continue
        action = consent(session["phases"].get(f"after_{kind}"), channels)
        reload = consent(session["phases"].get(f"after_{kind}_reload"), channels)
        differs[kind] = None if not (action[0] and reload[0]) else action[1:] != reload[1:]
    return differs


# Milder classification per violation for the crosscheck (site_data.effective_examination),
# from mild to severe. The Matte variant is strict plus >= 1 vendor consent, so it is the most
# severe level of V4.
V2_ORDER = ("1. Ebene", "nur 2. Ebene", "gar nicht")
V4_ORDER = ("kein Verstoß", "nur locker", "streng ohne Vendor-Consent", "Matte-Variante")


def v2_rank(semi):
    """Index in V2_ORDER; w counts as "gar nicht" (no free way to reject); None for b and x."""
    level = v2(semi["label"], "count_as_v2").get("level")
    if level is None:
        return None
    return V2_ORDER.index("gar nicht" if level.startswith("gar nicht") else level)


def v4_rank(semi):
    """Index in V4_ORDER; None if V4 cannot be evaluated (no reject session, no string)."""
    if v4(semi, "lax")["value"] == NA:
        return None
    if v4(semi, "matte")["value"] == YES:
        return V4_ORDER.index("Matte-Variante")
    if v4(semi, "strict")["value"] == YES:
        return V4_ORDER.index("streng ohne Vendor-Consent")
    if v4(semi, "lax")["value"] == YES:
        return V4_ORDER.index("nur locker")
    return V4_ORDER.index("kein Verstoß")


RANKS = {"V2": v2_rank, "V4": v4_rank}


# --- legitimate interest after rejecting

def special_purpose_only_vendors(gvl):
    """Vendors of the GVL that declare only special purposes (no purpose with consent or LI)."""
    return {int(vendor_id) for vendor_id, vendor in gvl["vendors"].items()
            if not vendor.get("purposes") and not vendor.get("legIntPurposes") and vendor.get("specialPurposes")}


def li_after_reject(semi, gvl_for, channels=MAIN_CHANNELS, moment="reload"):
    """Legitimate interest after rejecting, not counted as V4: purposes with LI (purposes 3-6
    separately), vendors with LI, and among them vendors that only have special purposes in the
    GVL of the string. gvl_for(vendor_list_version, policy_version) returns the GVL or None."""
    if semi is None or semi["label"] is None or semi["label"]["outcome"] != "rejected":
        return result(NA, "nicht abgelehnt (Code nicht r)")
    after_reject, _ = v4_phases(semi, moment)
    strings = strings_of(after_reject, channels)
    if not strings:
        return result(NA, "nach Ablehnen: " + why_not_evaluable(after_reject, channels))
    purpose_li = set().union(*(s["purpose_li"] for s in strings))
    vendor_li = set().union(*(s["vendor_li"] for s in strings))
    sp_only, gvl_missing = set(), False
    for s in strings:
        gvl = gvl_for(s["vendor_list_version"], s["policy_version"])
        if gvl is None:
            gvl_missing = True
        else:
            sp_only |= s["vendor_li"] & special_purpose_only_vendors(gvl)
    return result(YES if purpose_li or vendor_li else NO, purpose_li=sorted(purpose_li),
                  purpose_li_3_6=sorted(purpose_li & LI_NOT_ALLOWED), vendor_li=len(vendor_li),
                  vendor_li_special_purpose_only=None if gvl_missing else len(sp_only),
                  vendor_li_other=None if gvl_missing else len(vendor_li - sp_only))


# --- transfer to third parties (Matte VIII-A)

def third_party_consent_requests(phases):
    """Requests to third parties carrying a TC string with >= 1 purpose consent."""
    return [r for phase in phases if phase for r in phase["requests"]
            if r["third_party"] and r["tc_string"] and r["tc_string"]["decoded"] and r["tc_string"]["purposes"]]


def transfer_before(automatic):
    """(a) before any action: only from the automatic mode, with the rule of V1 (both sessions)."""
    if automatic is None:
        return result(NA, "kein automatischer Modus")
    before = [s["phases"].get("before") for s in automatic["sessions"]]
    if len(before) < 2 or None in before:
        return result(NA, "weniger als zwei Vorher-Snapshots")
    counts = [len(third_party_consent_requests([phase])) for phase in before]
    return result(YES if all(counts) else NO, requests=counts, any_session=any(counts))


def transfer_after_reject(semi):
    """(b) after rejecting: requests of the reject session after the click (until the snapshot
    after the action and until the one after the reload)."""
    if semi is None or semi["label"] is None or semi["label"]["outcome"] != "rejected":
        return result(NA, "nicht abgelehnt (Code nicht r)")
    session = session_of(semi, "reject")
    phases = [session["phases"].get("after_reject"), session["phases"].get("after_reject_reload")]
    if None in phases:
        return result(NA, "Snapshot nach Ablehnen fehlt")
    found = third_party_consent_requests(phases)
    return result(YES if found else NO, requests=len(found), domains=sorted({r["domain"] for r in found}))


# --- E5 consent outside disclosedVendors

def undisclosed_consent(phase, channels=MAIN_CHANNELS):
    """Vendor consents outside disclosedVendors (only strings with that segment)."""
    strings = [s for s in strings_of(phase, channels) if s["disclosed_present"]]
    if not strings:
        return result(NA, "kein String mit disclosedVendors")
    undisclosed = set().union(*(s["vendors"] - s["disclosed"] for s in strings))
    return result(YES if undisclosed else NO, vendors=len(undisclosed))


def unknown_vendor_consent(phase, channels=MAIN_CHANNELS):
    """Vendor consents for IDs that are not in the GVL of the string (Matte, Appendix F,
    "consent to nonexistent vendors"); not evaluable without that GVL."""
    strings = [s for s in strings_of(phase, channels) if s.get("gvl_available")]
    if not strings:
        return result(NA, "GVL des Strings nicht verfügbar oder kein String")
    unknown = set().union(*(s["unknown_vendors"] for s in strings))
    return result(YES if unknown else NO, vendors=len(unknown))


# --- channel 2

def channel_2_status(phase):
    if phase is None:
        return None
    return next((o["status"] for o in phase["observations"] if o["channel"] == "third_party_frame"), None)
