"""Live check of capture.py on the local test site (tests/site), against the requests that really
reached the server. Covers the open limits of Phase 1: nested iframes, service workers and the
timing of the preload script. Not part of pytest (needs a browser).

    venv/bin/python tests/check_capture.py

This test script clicks "accept" on the test site itself, in place of the human. The clicking
stays here; capture.py never clicks (CLAUDE.md, Ablauf).
"""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from browser import start_chrome  # noqa: E402
from capture import Capture  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402

TOP_URL = "http://localhost:8001/top.html?reload_after_choice=1"


def path_of(url):
    parsed = urlparse(url)
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def main():
    results = {}
    with tempfile.TemporaryDirectory() as log_dir:
        server = subprocess.Popen([sys.executable, str(Path(__file__).parent / "site_server.py"), log_dir],
                                  stdout=subprocess.PIPE)
        server.stdout.readline()   # "serving on ..."
        driver = start_chrome()
        try:
            session = Capture(driver, TOP_URL)
            driver.get(TOP_URL)
            time.sleep(config.SLEEP_TIME_CMP_WAIT)
            results["before"] = session.snapshot("before")
            timing = driver.execute_script("return window.__firstPageScriptAt")
            injected = [m for m in session.tcf_messages if m["kind"] == "injected"][0]["t"]

            mark = session.mark()
            driver.find_element(By.ID, "accept").click()   # test only: stands in for the human
            event = session.wait_for_event("useractioncomplete", config.USERACTIONCOMPLETE_TIMEOUT, after=mark)
            time.sleep(1)   # the test CMP reloads the page 200 ms after the choice
            results["after_accept"] = session.snapshot("after_accept")
            time.sleep(config.SLEEP_TIME_REFRESH)
            session.collect_requests()
            driver.refresh()
            time.sleep(config.SLEEP_TIME_CMP_WAIT)
            results["after_reload"] = session.snapshot("after_reload")
            listeners_before_remove = driver.execute_script("return window.__pruefstandListenerCount()")
            closing = session.close()
            listeners_after_remove = driver.execute_script("return window.__pruefstandListenerCount()")
        finally:
            driver.quit()
            server.terminate()
        received = [json.loads(line) for line in open(Path(log_dir) / "received.jsonl")]

    captured_paths = {(urlparse(r["url"]).port, path_of(r["url"])) for r in session.requests}
    missing = [r for r in received if (r["port"], r["path"]) not in captured_paths]
    signals = [(r["until_snapshot"], r["source"], r["method"], s["location"], s["key"],
                s["kind"], s.get("tc_version")) for r in session.requests for s in r["signals"]]

    print("Preload script before the first page script:", injected <= timing,
          f"(preload at {injected} ms, first page script at {round(timing)} ms)")
    print("useractioncomplete received despite the reload by the CMP:", event is not None,
          "| tcString:", (event or {}).get("tcString", "")[:24])
    print("removeEventListener:", closing["remove_listener"],
          f"| listeners of the CMP before/after: {listeners_before_remove}/{listeners_after_remove}")
    for label, snapshot in results.items():
        latest = snapshot["channel_1"]["latest_event"] or {}
        print(f"\n[{label}] channel 1: {latest.get('eventStatus')} {str(latest.get('tcString'))[:24]}"
              f" | channel 2: {snapshot['channel_2']['status']}"
              f" {str((snapshot['channel_2'].get('event') or {}).get('tcString'))[:24]}"
              f" | cookies: {[c['name'] for c in snapshot['storage']['cookies']]}"
              f" | localStorage: {[e['key'] for e in snapshot['storage']['local_storage']]}"
              f" | requests: {snapshot['requests']['count']} ({len(snapshot['requests']['with_signals'])} with signals)")
    print(f"\nRequests at the server: {len(received)}, of them not seen by capture.py: {len(missing)}")
    for r in missing:
        print("  missing:", r["port"], r["method"], r["path"])
    print("\nSignals found (snapshot, frame, method, location, key, kind, version):")
    for signal in signals:
        print("  ", signal)


if __name__ == "__main__":
    main()
