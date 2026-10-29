"""Live check of capture.py on real sites, before any interaction (nothing is clicked): channel 1
before and after a reload, channel 2, storage, requests with consent signals, removeEventListener.
robots.txt is respected (Protego). Not part of pytest; for the ~10 test sites only.

    venv/bin/python tests/check_capture_real.py t-online.de bild.de ...
"""
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from browser import start_chrome  # noqa: E402
from capture import Capture, tc_string_header  # noqa: E402
from robots import check_robots  # noqa: E402


def describe(snapshot):
    latest = snapshot["channel_1"]["latest_event"] or {}
    header = tc_string_header(latest.get("tcString")) or {}
    storage = snapshot["storage"]
    requests = snapshot["requests"]
    kinds = Counter((r["source"], "3rd" if r["third_party"] else "1st", s["kind"])
                    for r in requests["with_signals"] for s in r["signals"])
    bodies = Counter(r["body_status"] for r in requests["with_signals"] if r["body_status"])
    channel_2 = snapshot["channel_2"]
    return "\n".join([
        f"  channel 1: {latest.get('eventStatus')} | cmpId {latest.get('cmpId')} | gdprApplies {latest.get('gdprApplies')}"
        f" | policy {latest.get('tcfPolicyVersion')} | tcString v{header.get('tc_version')} {str(latest.get('tcString'))[:20]}"
        f" | events in session {snapshot['channel_1']['events_in_session']}",
        f"  channel 2: {channel_2['status']} {channel_2.get('reason', '')}"
        f" {str((channel_2.get('event') or {}).get('tcString'))[:20] if channel_2['status'] == 'answered' else ''}",
        f"  cookies: {[(c['name'], c['first_party'], len(c['tc_strings'])) for c in storage['cookies']]}",
        f"  localStorage: {[(e['key'], len(e['tc_strings'])) for e in storage['local_storage']]}",
        f"  requests: {requests['count']} ({requests['third_party']} third party), with signals: "
        f"{len(requests['with_signals'])}; bodies: {dict(bodies)}",
        f"  signals (source, party, kind): {dict(kinds)}",
    ])


def main(domains):
    for domain in domains:
        url = f"https://www.{domain}"
        robots = check_robots(url)
        print(f"\n===== {domain}  (robots.txt allowed: {robots['robots_allowed']})")
        if not robots["robots_allowed"]:
            continue
        driver = start_chrome()
        try:
            session = Capture(driver, url)
            driver.get(url)
            time.sleep(config.SLEEP_TIME_CMP_WAIT)
            print("[before]\n" + describe(session.snapshot("before")))
            session.collect_requests()
            driver.refresh()
            time.sleep(config.SLEEP_TIME_CMP_WAIT)
            print("[after reload, still no interaction]\n" + describe(session.snapshot("after_reload")))
            messages = session.tcf_messages
            injected = [m["t"] for m in messages if m["kind"] == "injected"]
            registering = [m["t"] for m in messages if m["kind"] == "registering"]
            print(f"  preload: injected at {injected} ms, __tcfapi found at {registering} ms")
            print(f"  removeEventListener: {session.close()['remove_listener']}")
        finally:
            driver.quit()
        time.sleep(config.PAUSE_BETWEEN_DOMAINS)


if __name__ == "__main__":
    main(sys.argv[1:])
