"""Phase 1 spike, criterion K1 again: the CDP performance log misses requests from cross-site
iframes (own renderer process). This script tests the two ways out on the local test site:

    venv/bin/python spikes/cdp/spike_k1.py bidi         # WebDriver BiDi network.beforeRequestSent
    venv/bin/python spikes/cdp/spike_k1.py no-isolation # performance log with site isolation off

Expected ground truth (see server output): 4 consent requests from localhost:8001 (top) and
4 from 127.0.0.1:8002 (iframe): GET, POST form, POST JSON, sendBeacon.
"""
import json
import sys
import threading
import time

from selenium import webdriver

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
import config  # noqa: E402
from spike import LISTENER_JS, consent_requests, read_events  # noqa: E402


def cdp_performance_log_requests(driver):
    """Network.requestWillBeSent from the CDP performance log (the first approach of spike.py)."""
    requests = []
    for entry in driver.get_log("performance"):
        message = json.loads(entry["message"])["message"]
        if message["method"] != "Network.requestWillBeSent":
            continue
        params = message["params"]
        request = params["request"]
        body = request.get("postData")
        if body is None and request.get("hasPostData"):
            try:
                body = driver.execute_cdp_cmd("Network.getRequestPostData",
                                              {"requestId": params["requestId"]})["postData"]
            except Exception as error:  # noqa: BLE001
                body = f"<getRequestPostData failed: {type(error).__name__}>"
        requests.append({"url": request["url"], "method": request["method"], "type": params.get("type"),
                         "frameId": params.get("frameId"), "body": body})
    return requests


def base_options():
    options = webdriver.ChromeOptions()
    options.browser_version = config.CHROME_VERSION
    return options


def print_requests(requests):
    found = consent_requests(requests)
    print(f"{len(requests)} requests, {len(found)} with consent signal")
    for r in found:
        print(f"  {r['method']:4} {r['type'] or '':9} context={str(r['frameId'])[:8]}"
              f" {r['url'][:70]}  body={(r['body'] or '')[:70]!r}")
    return found


def run_bidi():
    options = base_options()
    options.enable_bidi = True
    driver = webdriver.Chrome(options=options)
    events, lock = [], threading.Lock()

    def on_request(params):
        with lock:
            events.append(params)

    try:
        driver.network.add_data_collector(data_types=["request"], max_encoded_data_size=200_000)
        driver.network.add_event_handler("before_request_sent", on_request)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": LISTENER_JS})
        driver.get("http://localhost:8001/top.html")
        time.sleep(config.SLEEP_TIME_CMP_WAIT)

        with lock:
            snapshot = list(events)
        if snapshot:
            print("first event type/keys:", type(snapshot[0]).__name__, sorted(vars(snapshot[0]) if hasattr(snapshot[0], "__dict__") else snapshot[0])[:12])
        requests = []
        for params in snapshot:
            p = params if isinstance(params, dict) else vars(params)
            request = p["request"]
            request = request if isinstance(request, dict) else vars(request)
            body = None
            if request.get("bodySize"):
                try:
                    data = driver.network.get_data(data_type="request", request=request["request"])
                    body = data.get("bytes", {}).get("value") if isinstance(data, dict) else str(data)
                except Exception as error:  # noqa: BLE001
                    body = f"<get_data failed: {type(error).__name__}: {error}>"[:120]
            requests.append({"url": request["url"], "method": request["method"], "type": None,
                             "frameId": p.get("context"), "body": body})
        print_requests(requests)
        print("listener (CDP script next to BiDi):", json.dumps(read_events(driver))[:300])
    finally:
        driver.quit()


def run_no_isolation():
    options = base_options()
    options.add_argument("--disable-site-isolation-trials")
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = webdriver.Chrome(options=options)
    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.get("http://localhost:8001/top.html")
        time.sleep(config.SLEEP_TIME_CMP_WAIT)
        print_requests(cdp_performance_log_requests(driver))
    finally:
        driver.quit()


if __name__ == "__main__":
    {"bidi": run_bidi, "no-isolation": run_no_isolation}[sys.argv[1]]()
