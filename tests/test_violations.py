"""Violations (violations.py), the rules which examination counts (site_data.py) and the
selection for the crosscheck (crosscheck.py) and the tables (evaluate.py), on small hand-made
sites without a database."""
import random

import crosscheck
import evaluate
import site_data
import violations as v

ALL = set(range(1, 12))


def tc(purposes=(), vendors=(), purpose_li=(), vendor_li=(), disclosed=None, policy=5):
    return {"decoded": True, "tc_version": 2, "policy_version": policy, "vendor_list_version": 150, "cmp_id": 6,
            "disclosed_present": disclosed is not None, "purposes": set(purposes), "purpose_li": set(purpose_li),
            "vendors": set(vendors), "vendor_li": set(vendor_li), "disclosed": set(disclosed or ())}


def phase(channel_1=None, status="measured", cookie=None, requests=()):
    """A snapshot: channel 1 with a string (or a status without), optionally a cookie."""
    observations = [{"channel": "tcfapi", "status": status if channel_1 is None else "measured", "tc_string": channel_1},
                    {"channel": "third_party_frame", "status": "not_measurable", "tc_string": None}]
    if cookie is not None:
        observations.append({"channel": "cookie", "status": "measured", "tc_string": cookie})
    return {"observations": observations,
            "requests": [{"third_party": True, "domain": d, "tc_string": s} for d, s in requests]}


def automatic(before_1, before_2, blocked=False):
    return {"sessions": [{"number": n, "blocked": blocked, "phases": {"before": p}}
                         for n, p in ((1, before_1), (2, before_2))]}


def label(outcome="rejected", reject_level=1, settings=1, purposes_pre=0, vendors_pre=0, cookiewall_seen=0):
    return {"outcome": outcome, "reject_level": reject_level if outcome == "rejected" else None,
            "settings_layer_available": settings, "purposes_preselected": purposes_pre,
            "vendors_preselected": vendors_pre, "cookiewall_seen": cookiewall_seen}


def semi(after_reject=None, after_accept=None, action_reject=None, action_accept=None, **label_fields):
    sessions = []
    if after_reject is not None:
        sessions.append({"kind": "reject", "phases": {"after_reject": action_reject or after_reject,
                                                      "after_reject_reload": after_reject}})
    if after_accept is not None:
        sessions.append({"kind": "accept", "phases": {"after_accept": action_accept or after_accept,
                                                      "after_accept_reload": after_accept}})
    return {"label": label(**label_fields), "sessions": sessions}


# --- V1

def test_v1_only_if_both_sessions_show_consent():
    assert v.v1(automatic(phase(tc({1, 2}, {10})), phase(tc({1}, {10}))))["value"] == v.YES
    assert v.v1(automatic(phase(tc({1, 2}, {10})), phase(tc())))["value"] == v.NO


def test_v1_all_purposes_as_matte_row_5_purposes():
    result = v.v1(automatic(phase(tc(ALL, {10})), phase(tc(ALL, {10}))))
    assert result["all_purposes"] is True
    assert v.v1(automatic(phase(tc(ALL)), phase(tc({1, 2}))))["all_purposes"] is False


def test_v1_matte_variant_needs_a_vendor_consent():
    site = automatic(phase(tc({1})), phase(tc({1})))
    assert v.v1(site)["value"] == v.YES
    assert v.v1(site, matte_variant=True)["value"] == v.NO


def test_v1_tcf_api_without_string_is_not_evaluable_e7():
    # amazon.de: channel 1 answers with empty tcData, also if only one session has no string
    result = v.v1(automatic(phase(status="empty_tc_data"), phase(tc({1}))))
    assert result["value"] == v.NA and "empty_tc_data" in result["reason"]
    assert v.v1(None)["value"] == v.NA


def test_v1_matte_channels_any_channel_shows_it():
    # channel 1 without consent, the cookie with consent: only the variant "Matte-Kanäle" counts it
    site = automatic(phase(tc(), cookie=tc({1})), phase(tc(), cookie=tc({1})))
    assert v.v1(site)["value"] == v.NO
    assert v.v1(site, channels=site_data.MATTE_CHANNELS)["value"] == v.YES


# --- V2, V3

def test_v2_by_layer_and_cookiewall_handling():
    assert v.v2(label(reject_level=1))["level"] == "1. Ebene"
    assert v.v2(label(reject_level=2))["level"] == "nur 2. Ebene"
    assert v.v2(label("n")) == {"value": v.YES, "reason": None, "level": "gar nicht"}
    assert v.v2(label("w"), "exclude")["value"] == v.NA
    assert v.v2(label("w"), "count_as_v2")["value"] == v.YES
    assert v.v2(label("b"))["value"] == v.NA and v.v2(label("x"))["value"] == v.NA


def test_v3_denominator_second_layer_and_not_checked():
    assert v.v3(label(purposes_pre=1), "purposes")["value"] == v.YES
    assert v.v3(label(purposes_pre=0, vendors_pre=1), "purposes")["value"] == v.NO
    assert v.v3(label(purposes_pre=0, vendors_pre=1), "vendors")["value"] == v.YES
    assert v.v3(label(purposes_pre=None), "purposes") == {"value": v.NA, "reason": "nicht geprüft"}
    assert v.v3(label(settings=0), "purposes")["value"] == v.NA
    assert v.v3(label(settings=None), "purposes")["reason"] == "2. Ebene nicht geprüft"
    assert v.v3(label("n"), "purposes")["value"] == v.NA


def test_v3_either_with_matte_denominator():
    assert v.v3(label(purposes_pre=0, vendors_pre=1), "either", matte_denominator=True)["value"] == v.YES
    assert v.v3(label(settings=0), "either", matte_denominator=True)["value"] == v.NO


# --- V4

def test_v4_strict_matte_lax():
    # after rejecting the same purposes as after accepting: strict; with a vendor also Matte
    examination = semi(phase(tc({1, 2}, {10})), phase(tc({1, 2}, {10, 11})))
    assert [v.v4(examination, k)["value"] for k in ("strict", "matte", "lax")] == [v.YES, v.YES, v.YES]
    without_vendor = semi(phase(tc({1, 2})), phase(tc({1, 2}, {10})))
    assert [v.v4(without_vendor, k)["value"] for k in ("strict", "matte")] == [v.YES, v.NO]
    partly = semi(phase(tc({1}, {10})), phase(tc({1, 2}, {10})))
    assert [v.v4(partly, k)["value"] for k in ("strict", "lax")] == [v.NO, v.YES]
    respected = semi(phase(tc()), phase(tc({1, 2}, {10})))
    assert [v.v4(respected, k)["value"] for k in ("strict", "lax")] == [v.NO, v.NO]


def test_v4_empty_set_after_accepting_is_not_evaluable():
    result = v.v4(semi(phase(tc()), phase(tc())), "strict")
    assert result == {**result, "value": v.NA, "reason": "Zweckmenge nach Akzeptieren leer"}
    assert v.v4(semi(phase(tc()), phase(tc())), "lax")["value"] == v.NO


def test_v4_extra_figures_all_purposes():
    examination = semi(phase(tc(range(1, 11), {1})), phase(tc(ALL, {1})))
    assert v.v4(examination, "all10")["value"] == v.YES
    assert v.v4(examination, "all11")["value"] == v.NO


def test_v4_on_the_snapshot_after_reload_amazon_case():
    # amazon.de: right after the action only empty tcData, after the reload a string
    examination = semi(phase(tc()), phase(tc({1, 2, 4, 7, 9, 10}, {5})),
                       action_reject=phase(status="empty_tc_data"), action_accept=phase(status="empty_tc_data"))
    assert v.v4(examination, "strict")["value"] == v.NO
    assert v.v4(examination, "strict", moment="action")["value"] == v.NA
    assert v.v4_action_differs(examination) == {"reject": None, "accept": None}


def test_v4_action_and_reload_differ():
    examination = semi(phase(tc()), phase(tc({1}, {5})), action_reject=phase(tc({1}, {5})))
    assert v.v4(examination, "lax", moment="action")["value"] == v.YES
    assert v.v4(examination, "lax")["value"] == v.NO
    assert v.v4_action_differs(examination) == {"reject": True, "accept": False}


def test_v4_only_for_code_r():
    assert v.v4(semi(after_accept=phase(tc(ALL)), outcome="w"), "strict")["value"] == v.NA
    assert v.v4(semi(phase(status="empty_tc_data"), phase(tc({1}))), "strict")["reason"].startswith("nach Ablehnen")


# --- LI, transfer, E5

def test_li_after_reject_purposes_3_6_and_special_purpose_only_vendors():
    gvl = {"vendors": {"10": {"purposes": [], "legIntPurposes": [], "specialPurposes": [1, 2]},
                       "11": {"purposes": [1], "legIntPurposes": [2, 7], "specialPurposes": [1]}}}
    examination = semi(phase(tc(purpose_li={2, 3, 7}, vendor_li={10, 11})), phase(tc({1}, {10})))
    result = v.li_after_reject(examination, lambda version, policy: gvl)
    assert (result["purpose_li_3_6"], result["vendor_li"]) == ([3], 2)
    assert (result["vendor_li_special_purpose_only"], result["vendor_li_other"]) == (1, 1)
    assert v.li_after_reject(examination, lambda version, policy: None)["vendor_li_special_purpose_only"] is None


def test_transfer_before_and_after_reject():
    with_consent, without = tc({1}), tc()
    site = automatic(phase(tc(), requests=[("ads.example", with_consent)]),
                     phase(tc(), requests=[("ads.example", without)]))
    result = v.transfer_before(site)
    assert (result["value"], result["any_session"], result["requests"]) == (v.NO, True, [1, 0])
    examination = semi(phase(tc(), requests=[("ads.example", with_consent)]), phase(tc({1})))
    assert v.transfer_after_reject(examination)["value"] == v.YES


def test_e5_consent_outside_disclosed_vendors():
    assert v.undisclosed_consent(phase(tc({1}, {10, 99}, disclosed={10})))["vendors"] == 1
    assert v.undisclosed_consent(phase(tc({1}, {10}, disclosed={10})))["value"] == v.NO
    assert v.undisclosed_consent(phase(tc({1}, {10})))["value"] == v.NA   # v2.2 string without the segment


# --- which examination counts (site_data.effective_examination)

def examination(id, role, started_at, operator="ae", crosscheck_of=None, correction_of=None, outcome="rejected"):
    return {"id": id, "role": role, "operator": operator, "started_at": started_at, "crosscheck_of": crosscheck_of,
            "correction_of": correction_of, "label": {"outcome": outcome}}


def by_outcome(e):
    """Stand-in for violations.severity: code n = one violation (V2)."""
    return (e["label"]["outcome"] == "n",)


def test_correction_replaces_the_examination_it_refers_to():
    first = examination("p", "primary", "1", outcome="n")
    corrected = examination("c", "correction", "2", correction_of="p", outcome="rejected")
    effective, info = site_data.effective_examination([first, corrected], by_outcome)
    assert (effective["id"], effective["role"], effective["corrects"]) == ("c", "primary", "p")


def test_latest_correction_counts():
    exams = [examination("p", "primary", "1"), examination("c1", "correction", "2", correction_of="p", outcome="n"),
             examination("c2", "correction", "3", correction_of="p", outcome="x")]
    assert site_data.effective_examination(exams, by_outcome)[0]["id"] == "c2"


def test_recheck_replaces_all_earlier_examinations():
    exams = [examination("p", "primary", "1"), examination("k", "crosscheck", "2", "xy", crosscheck_of="p"),
             examination("r", "recheck", "3", "xy", outcome="n")]
    effective, info = site_data.effective_examination(exams, by_outcome)
    assert (effective["id"], info["source"]) == ("r", "recheck")


def test_milder_result_counts_not_the_later_one():
    # the crosscheck (later) finds a way to reject: milder, it counts
    exams = [examination("p", "primary", "1", outcome="n"),
             examination("k", "crosscheck", "2", "xy", crosscheck_of="p", outcome="rejected")]
    effective, info = site_data.effective_examination(exams, by_outcome)
    assert (effective["id"], info["crosscheck"]["differs"]) == ("k", True)
    # the crosscheck (later) finds no way to reject: the first one is milder and counts
    exams = [examination("p", "primary", "1", outcome="rejected"),
             examination("k", "crosscheck", "2", "xy", crosscheck_of="p", outcome="n")]
    effective, info = site_data.effective_examination(exams, by_outcome)
    assert (effective["id"], info["source"], info["crosscheck"]["differs"]) == ("p", "primary", True)


def test_same_result_keeps_the_first_examination():
    exams = [examination("p", "primary", "1"), examination("k", "crosscheck", "2", "xy", crosscheck_of="p")]
    effective, info = site_data.effective_examination(exams, by_outcome)
    assert (effective["id"], info["crosscheck"]["differs"]) == ("p", False)


def test_several_first_examinations_latest_with_warning():
    exams = [examination("p1", "primary", "1"), examination("p2", "primary", "2")]
    effective, info = site_data.effective_examination(exams, by_outcome)
    assert effective["id"] == "p2" and "2 fertige erste Prüfungen" in info["warnings"][0]


def test_examination_without_label_is_ignored():
    unlabeled = {**examination("p2", "primary", "2"), "label": None}
    assert site_data.effective_examination([examination("p1", "primary", "1"), unlabeled], by_outcome)[0]["id"] == "p1"


# --- crosscheck selection (Matte V-C)

def site(domain, cmp_id, examination_fields, operator="ae"):
    semi_examination = {**semi(**examination_fields), "id": f"e-{domain}", "operator": operator,
                        "url": f"https://www.{domain}"}
    return {"domain": domain, "cmp_id": cmp_id, "semi": semi_examination, "source": "primary", "crosscheck": None}


def test_selection_per_kind_and_cmp():
    violating = {"after_reject": phase(tc({1, 2}, {10})), "after_accept": phase(tc({1, 2}, {10}))}
    clean = {"after_reject": phase(tc()), "after_accept": phase(tc({1, 2}, {10}))}
    sites = {s["domain"]: s for s in [
        site("a.de", 6, violating), site("b.de", 6, violating), site("c.de", 6, clean),
        site("d.de", 345, {"outcome": "n"}), site("e.de", 345, clean), site("f.de", 35, clean)]}
    chosen = crosscheck.select(sites, random.Random(1))
    summary = sorted((kind, selected_as, s["cmp_id"]) for s, kind, selected_as in chosen)
    # V4: CMP 6 has a violation -> one violating site and one clean site of CMP 6
    # V2: CMP 345 has a violation -> d.de and one clean site of CMP 345
    assert summary == [("V2", "Verstoß", 345), ("V2", "unauffällig", 345), ("V4", "Verstoß", 6), ("V4", "unauffällig", 6)]
    assert [s["domain"] for s, kind, selected_as in chosen if kind == "V4" and selected_as == "unauffällig"] == ["c.de"]


def test_selection_takes_clean_sites_of_other_cmps_if_needed():
    violating = {"after_reject": phase(tc({1}, {10})), "after_accept": phase(tc({1}, {10}))}
    clean = {"after_reject": phase(tc()), "after_accept": phase(tc({1}, {10}))}
    sites = {s["domain"]: s for s in [site("a.de", 6, violating), site("f.de", 35, clean)]}
    chosen = crosscheck.select(sites, random.Random(1))
    assert [(s["domain"], selected_as) for s, kind, selected_as in chosen if kind == "V4"] == [
        ("a.de", "Verstoß"), ("f.de", "unauffällig")]


def test_crosscheck_by_the_other_person():
    assert crosscheck.other_operator("ae", ["ae", "xy"]) == "xy"


# --- tables (evaluate.py)

def test_tables_with_matte_mapping(monkeypatch):
    monkeypatch.setattr(evaluate, "gvl_for", lambda version, policy: None)
    ignored = {"after_reject": phase(tc(ALL, {10})), "after_accept": phase(tc(ALL, {10}))}
    respected = {"after_reject": phase(tc()), "after_accept": phase(tc(ALL, {10}))}
    sites = {}
    for domain, fields, before in (("a.de", ignored, tc(ALL, {10})), ("b.de", respected, tc()),
                                   ("c.de", {"outcome": "w", "after_accept": phase(tc(ALL))}, tc())):
        s = site(domain, 6, fields)
        s.update(rank=1, warnings=[], automatic={**automatic(phase(before), phase(before)),
                                                 "cookiewall_suspected": domain == "c.de", "cookiewall_reason": None})
        sites[domain] = s
    results = {d: evaluate.evaluate_site(s) for d, s in sites.items()}
    figures, text = evaluate.tab_iii(results, results)
    assert figures["v1"]["text"] == "33,3 % (1/3)" and figures["v1_all"]["hits"] == 1
    assert figures["v4"]["text"] == "50,0 % (1/2)"
    assert [figures["v2"][h]["text"] for h in v.COOKIEWALL_HANDLINGS] == ["0,0 % (0/2)", "33,3 % (1/3)"]
    assert figures["any"]["text"] == "33,3 % (1/3)"
    assert "[Matte 5,3 % (27/508)]" in text
    assert "V4 Matte-Variante ↔ „5 purposes“" in evaluate.TAB_III_MAPPING
    assert "Heuristik gegen Code w" in evaluate.details(results, results, sites)


def test_e5_consent_for_vendors_missing_in_the_gvl():
    known = {**tc({1}, {10, 99}), "gvl_available": True, "unknown_vendors": {99}}
    assert v.unknown_vendor_consent(phase(known))["vendors"] == 1
    assert v.unknown_vendor_consent(phase({**known, "gvl_available": False}))["value"] == v.NA
