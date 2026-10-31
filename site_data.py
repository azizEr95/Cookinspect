"""Reads the database into plain dicts per website, for the violation functions (violations.py).
Nothing is computed or stored here except which examination counts for a site.

Per site:
  - automatic: the latest finished examination of the automatic mode, with its two sessions and
    the snapshot "before" of each
  - semi: the semi-automatic examination that counts for V4 (rules below), with all snapshots of
    the reject and the accept session; everything measured in the sessions (V4, LI, transfer
    after rejecting, E5) comes from it
  - semi_label: the examination that counts for V2; the values of the label (V2, V3,
    cookiewall) come from it. Without a differing crosscheck both are the same examination.
  - warnings: e.g. two finished examinations of the same person in the same role

Which semi-automatic examination counts (Matte V-C, CLAUDE.md, Gegenprüfung):
  1. a correction replaces the examination it refers to (the latest correction if there are
     several)
  2. a recheck replaces all earlier examinations of the site (the latest recheck)
  3. otherwise the primary examination and its blind crosscheck, decided separately for V2 and
     for V4 (the crosscheck is done separately for both, Matte V-C): the MILDER classification
     counts (violations.RANKS), not the later one; on a tie the primary one. If only one of the
     two can be evaluated for that violation (e.g. code n has no reject session), that one
     counts. A difference marks the site (all sites of the CMP are rechecked).
     Several primary examinations: the latest, with a warning.

A snapshot ("phase") is {"observations": [...], "requests": [...]}; an observation has the
channel, its status and, if it holds a TC string, the sets of IDs of that string.
"""
import json
from collections import defaultdict

MAIN_CHANNELS = ("tcfapi",)                                                   # main figure: channel 1 only
MATTE_CHANNELS = ("tcfapi", "third_party_frame", "cookie", "local_storage")   # Matte took API and shared cookie together (p. 7)

ID_FIELDS = {"purpose_consent": "purposes", "purpose_li": "purpose_li", "vendor_consent": "vendors",
             "vendor_li": "vendor_li", "vendor_disclosed": "disclosed"}


# --- TC strings

def load_tc_strings(conn):
    """{tc_string_id: {"decoded", "tc_version", "policy_version", "vendor_list_version", "cmp_id",
    "disclosed_present", "gvl_available", "unknown_vendors", "purposes", "purpose_li", "vendors",
    "vendor_li", "disclosed"}}; unknown_vendors: vendor consents not in the GVL of the string
    (decoder.py, consent_lists.gvl_check)."""
    strings = {}
    for row in conn.execute("""SELECT id, decoded, tc_version, policy_version, vendor_list_version, cmp_id,
                                      disclosed_vendors_present, gvl_available, checks_json FROM tc_string"""):
        checks = json.loads(row["checks_json"]) if row["checks_json"] else {}
        strings[row["id"]] = {"decoded": bool(row["decoded"]), "tc_version": row["tc_version"],
                              "policy_version": row["policy_version"], "vendor_list_version": row["vendor_list_version"],
                              "cmp_id": row["cmp_id"], "disclosed_present": bool(row["disclosed_vendors_present"]),
                              "gvl_available": bool(row["gvl_available"]),
                              "unknown_vendors": set(checks.get("unknown_vendor_consents", [])),
                              **{name: set() for name in ID_FIELDS.values()}}
    for row in conn.execute("SELECT tc_string_id, field, value FROM tc_string_entry"):
        if row["field"] in ID_FIELDS:
            strings[row["tc_string_id"]][ID_FIELDS[row["field"]]].add(row["value"])
    return strings


# --- snapshots

def load_phases(conn, tc_strings):
    """{session_id: {phase: {"observations": [...], "requests": [...]}}}"""
    observations = defaultdict(list)
    for row in conn.execute("SELECT snapshot_id, channel, status, detail, tc_string_id, reason FROM observation"):
        observations[row["snapshot_id"]].append({
            "channel": row["channel"], "status": row["status"], "detail": row["detail"], "reason": row["reason"],
            "tc_string": tc_strings.get(row["tc_string_id"]) if row["tc_string_id"] else None})
    requests = defaultdict(list)
    for row in conn.execute("""SELECT r.until_snapshot_id, r.id, r.third_party, r.registrable_domain, rs.tc_string_id
                               FROM request r JOIN request_signal rs ON rs.request_id = r.id
                               WHERE rs.kind = 'tc_string'"""):
        requests[row["until_snapshot_id"]].append({
            "request_id": row["id"], "third_party": bool(row["third_party"]), "domain": row["registrable_domain"],
            "tc_string": tc_strings.get(row["tc_string_id"]) if row["tc_string_id"] else None})
    phases = defaultdict(dict)
    for row in conn.execute("SELECT id, session_id, phase FROM snapshot"):
        phases[row["session_id"]][row["phase"]] = {"observations": observations[row["id"]],
                                                   "requests": requests[row["id"]]}
    return phases


SESSION_FIELDS = ("number", "kind", "loaded", "blocked", "block_reason", "cookiewall_suspected", "cookiewall_reason",
                  "banner_shown", "banner_reloads", "useractioncomplete_received")


def load_examinations(conn, phases):
    """All finished examinations with their sessions (and label), in the order they were started."""
    sessions = defaultdict(list)
    for row in conn.execute(f"SELECT id, examination_id, {', '.join(SESSION_FIELDS)} FROM session ORDER BY number"):
        sessions[row["examination_id"]].append({**{f: row[f] for f in SESSION_FIELDS}, "id": row["id"],
                                                "phases": phases.get(row["id"], {})})
    labels = {row["examination_id"]: dict(row) for row in conn.execute("SELECT * FROM label")}
    examinations = []
    for row in conn.execute("""SELECT e.*, r.purpose FROM examination e JOIN run r ON r.id = e.run_id
                               WHERE e.status = 'done' ORDER BY e.started_at"""):
        examinations.append({**dict(row), "sessions": sessions[row["id"]], "label": labels.get(row["id"])})
    return examinations


def session_of(examination, kind):
    """The reject or the accept session of a semi-automatic examination (None if there is none)."""
    return next((s for s in examination["sessions"] if s["kind"] == kind), None)


# --- which examination counts

def apply_corrections(examinations):
    """Rule 1: each examination that was corrected is replaced by its latest correction (which
    may itself be corrected). The result keeps the role of the corrected examination."""
    corrections = defaultdict(list)
    for e in examinations:
        if e["role"] == "correction":
            corrections[e["correction_of"]].append(e)

    def latest_version(examination):
        if not corrections[examination["id"]]:
            return examination
        newest = max(corrections[examination["id"]], key=lambda c: c["started_at"])
        return {**latest_version(newest), "role": examination["role"], "crosscheck_of": examination["crosscheck_of"],
                "corrects": examination["id"]}

    return [latest_version(e) for e in examinations if e["role"] != "correction"]


def milder(first, second, rank):
    """The examination with the milder classification (lower rank); rank None = not evaluable,
    then the other one counts; on a tie the first one."""
    first_rank, second_rank = rank(first), rank(second)
    if first_rank is None and second_rank is not None:
        return second
    if second_rank is not None and second_rank < first_rank:
        return second
    return first


def effective_examination(examinations, ranks):
    """Rules 1-3 for the semi-automatic examinations of one site (finished, with label).
    ranks: {"V2": function, "V4": function}, each examination -> rank (0 = no violation, higher
    = more severe) or None (not evaluable), see violations.RANKS.
    Returns ({"V2": examination, "V4": examination} or None, info) with info = {"source",
    "crosscheck", "warnings"}."""
    info = {"source": None, "crosscheck": None, "warnings": []}
    examinations = apply_corrections([e for e in examinations if e["label"]])

    def same(examination, source):
        info["source"] = source
        return {kind: examination for kind in ranks}, info

    rechecks = [e for e in examinations if e["role"] == "recheck"]
    if rechecks:
        if len(rechecks) > 1:
            info["warnings"].append(f"{len(rechecks)} Neuprüfungen, die jüngste zählt")
        return same(rechecks[-1], "recheck")
    primaries = [e for e in examinations if e["role"] == "primary"]
    if not primaries:
        if examinations:
            info["warnings"].append("nur Gegenprüfung, keine erste Prüfung")
        return None, info
    if len(primaries) > 1:
        info["warnings"].append(f"{len(primaries)} fertige erste Prüfungen "
                                f"({', '.join(sorted({p['operator'] for p in primaries}))}), die jüngste zählt")
    primary = primaries[-1]
    crosschecks = [e for e in examinations if e["role"] == "crosscheck" and e["crosscheck_of"] == primary["id"]]
    others = [e for e in examinations if e["role"] == "crosscheck" and e["crosscheck_of"] != primary["id"]]
    if others:
        info["warnings"].append(f"{len(others)} Gegenprüfung(en) einer älteren ersten Prüfung, nicht berücksichtigt")
    if not crosschecks:
        return same(primary, "primary")
    crosscheck = crosschecks[-1]
    if len(crosschecks) > 1:
        info["warnings"].append(f"{len(crosschecks)} Gegenprüfungen, die jüngste zählt")
    chosen = {kind: milder(primary, crosscheck, rank) for kind, rank in ranks.items()}
    differs = {kind: rank(primary) != rank(crosscheck) for kind, rank in ranks.items()}
    info["crosscheck"] = {"primary_operator": primary["operator"], "crosscheck_operator": crosscheck["operator"],
                          "ranks": {kind: (rank(primary), rank(crosscheck)) for kind, rank in ranks.items()},
                          "differs_by_kind": differs, "differs": any(differs.values()),
                          "primary": primary, "crosscheck": crosscheck}
    info["source"] = ", ".join(f"{kind}: {'Gegenprüfung (milder)' if e is crosscheck else 'erste Prüfung'}"
                               for kind, e in chosen.items())
    return chosen, info


# --- sites

def cmp_ids_from_prefilter(conn, purpose=None):
    """CMP ID per domain from the latest prefilter run (of the purpose, if given)."""
    query = """SELECT p.domain, p.cmp_id FROM prefilter_result p JOIN run r ON r.id = p.run_id
               WHERE p.tcf = 1 {} ORDER BY r.started_at""".format("AND r.purpose = ?" if purpose else "")
    return {row["domain"]: row["cmp_id"] for row in conn.execute(query, (purpose,) if purpose else ())}


def cmp_id_of(site):
    """From the prefilter, otherwise from the first TC string seen on the site."""
    if site["cmp_id"] is not None:
        return site["cmp_id"]
    for examination in filter(None, [site["semi"], site["semi_label"], site["automatic"]]):
        for session in examination["sessions"]:
            for phase in session["phases"].values():
                for observation in phase["observations"]:
                    if observation["tc_string"] and observation["tc_string"]["cmp_id"] is not None:
                        return observation["tc_string"]["cmp_id"]
    return None


def load_sites(conn, ranks, purpose=None):
    """{domain: site}, for all domains with an automatic or semi-automatic examination.
    ranks: violations.RANKS (milder classification per violation for the crosscheck)."""
    tc_strings = load_tc_strings(conn)
    examinations = load_examinations(conn, load_phases(conn, tc_strings))
    if purpose:
        examinations = [e for e in examinations if e["purpose"] == purpose]
    tranco_ranks = {row["domain"]: row["tranco_rank"] for row in conn.execute("SELECT domain, tranco_rank FROM website")}
    cmp_ids = cmp_ids_from_prefilter(conn, purpose)
    by_domain = defaultdict(list)
    for e in examinations:
        by_domain[e["domain"]].append(e)
    sites = {}
    for domain, own in sorted(by_domain.items(), key=lambda item: (tranco_ranks.get(item[0]) or 10**9, item[0])):
        automatic = [e for e in own if e["role"] == "automatic"]
        semi = [e for e in own if e["role"] != "automatic"]
        chosen, info = effective_examination(semi, ranks)
        if len(automatic) > 1:
            info["warnings"].append(f"{len(automatic)} fertige automatische Prüfungen, die jüngste zählt")
        site = {"domain": domain, "rank": tranco_ranks.get(domain), "cmp_id": cmp_ids.get(domain),
                "automatic": automatic[-1] if automatic else None,
                "semi": chosen["V4"] if chosen else None, "semi_label": chosen["V2"] if chosen else None,
                "semi_examinations": semi, "source": info["source"], "crosscheck": info["crosscheck"],
                "warnings": info["warnings"]}
        site["cmp_id"] = cmp_id_of(site)
        sites[domain] = site
    return sites
