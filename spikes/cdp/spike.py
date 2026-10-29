"""Phase 1 spike: can every channel be captured with CDP + Selenium, without browser extensions?

    venv/bin/python spikes/cdp/server.py &                 # local test site (two origins)
    venv/bin/python spikes/cdp/spike.py local              # criteria K1-K5 on the local test site
    venv/bin/python spikes/cdp/spike.py real <domain> ...  # same checks on real sites (robots.txt respected)
    venv/bin/python spikes/cdp/spike.py real-accept <domain> ...  # after clicking accept (spike only)

Criteria (see docs/entscheidungen.md):
  K1 requests from cross-site iframes (own renderer process) appear in the performance log
  K2 POST bodies (JSON, form data, sendBeacon) are readable
  K3 a script added with Page.addScriptToEvaluateOnNewDocument runs before the page scripts,
     registers __tcfapi addEventListener, and is active again after a reload
  K4 channel 2: from inside a cross-site iframe, __tcfapiCall via postMessage to the
     __tcfapiLocator frame returns ping and addEventListener results
  K5 the first-party cookie euconsent-v2 and localStorage are readable

Throwaway code: it decides the approach, the real implementation follows in phase 3.
"""
import json
import sys
import threading
import time
import urllib.request
from urllib.parse import parse_qs, urlparse

from protego import Protego
from selenium import webdriver
from selenium.webdriver.common.by import By

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
import config  # noqa: E402

# Injected at document start of every page and frame of the tab. Only the top frame registers the
# listener. __tcfapi usually does not exist yet at document start, so it waits for it.
LISTENER_JS = r"""
if (window === window.top) {
  window.__ciInjectedAt = performance.now();
  window.__ciEvents = [];
  const register = () => {
    if (typeof window.__tcfapi !== 'function') { setTimeout(register, 50); return; }
    window.__ciRegisteredAt = performance.now();
    window.__tcfapi('addEventListener', 2, (tcData, success) => {
      window.__ciEvents.push({ t: Math.round(performance.now()), success: success,
                               eventStatus: tcData && tcData.eventStatus,
                               listenerId: tcData && tcData.listenerId,
                               tcString: tcData && tcData.tcString });
    });
  };
  register();
}
"""

# Runs inside a third-party iframe (after switch_to.frame). Looks for the __tcfapiLocator frame
# among its ancestors and sends ping + addEventListener through postMessage, as a vendor would.
PROBE_JS = r"""
let f = window, locator = null;
while (true) {
  try { if (f.frames['__tcfapiLocator']) { locator = f; break; } } catch (e) {}
  if (f === window.top) break;
  f = f.parent;
}
if (!locator) return 'no __tcfapiLocator among the ancestors';
window.__ciProbe = [];
window.addEventListener('message', (e) => {
  let d = e.data;
  if (typeof d === 'string') { try { d = JSON.parse(d); } catch (x) { return; } }
  if (d && d.__tcfapiReturn && String(d.__tcfapiReturn.callId).startsWith('ci_'))
    window.__ciProbe.push({ callId: d.__tcfapiReturn.callId, success: d.__tcfapiReturn.success,
      eventStatus: d.__tcfapiReturn.returnValue && d.__tcfapiReturn.returnValue.eventStatus,
      tcString: d.__tcfapiReturn.returnValue && d.__tcfapiReturn.returnValue.tcString,
      cmpLoaded: d.__tcfapiReturn.returnValue && d.__tcfapiReturn.returnValue.cmpLoaded });
});
for (const command of ['ping', 'addEventListener'])
  locator.postMessage({ __tcfapiCall: { command: command, version: 2, callId: 'ci_' + command } }, '*');
return 'sent';
"""

CONSENT_KEYS = ("gdpr_consent", "gdpr", "addtl_consent")


def start_chrome():
    """Chrome for Testing with WebDriver BiDi for the network events (they include requests from
    cross-site iframes, which the CDP performance log misses, see spike_k1.py) and the listener
    script added through CDP."""
    options = webdriver.ChromeOptions()
    options.browser_version = config.CHROME_VERSION
    options.enable_bidi = True
    options.add_argument(f"--lang={config.ACCEPT_LANGUAGES.split(',')[0]}")
    options.add_experimental_option("prefs", {"intl.accept_languages": config.ACCEPT_LANGUAGES})
    driver = webdriver.Chrome(options=options)
    driver.set_window_size(*config.WINDOW_SIZE)
    driver.ci_events = []
    driver.ci_lock = threading.Lock()

    def on_request(params):
        with driver.ci_lock:
            driver.ci_events.append(params)

    driver.network.add_data_collector(data_types=["request"], max_encoded_data_size=1_000_000)
    driver.network.add_event_handler("before_request_sent", on_request)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": LISTENER_JS})
    return driver


def network_requests(driver):
    """All network.beforeRequestSent events since the last call, with browsing context and body."""
    with driver.ci_lock:
        events, driver.ci_events = driver.ci_events, []
    requests = []
    for params in events:
        request = params["request"]
        body = None
        if request.get("bodySize"):
            try:
                body = driver.network.get_data(data_type="request", request=request["request"])["bytes"]["value"]
            except Exception as error:  # noqa: BLE001 - spike: just report it
                body = f"<get_data failed: {type(error).__name__}>"
        requests.append({"url": request["url"], "method": request["method"], "type": None,
                         "frameId": params.get("context"), "body": body})
    return requests


def consent_requests(requests):
    """Requests that carry a consent signal in the URL or in the body (markers or real fields)."""
    found = []
    for r in requests:
        query = parse_qs(urlparse(r["url"]).query)
        in_url = any(k in query for k in CONSENT_KEYS)
        body = r["body"] or ""
        in_body = any(k in body for k in CONSENT_KEYS) or '"consent"' in body
        if in_url or in_body:
            found.append(r)
    return found


def frame_tree(driver):
    tree = driver.execute_cdp_cmd("Page.getFrameTree", {})
    top_id = tree["frameTree"]["frame"]["id"]
    return top_id


def read_events(driver):
    driver.switch_to.default_content()
    return driver.execute_script(
        "return {injectedAt: window.__ciInjectedAt, registeredAt: window.__ciRegisteredAt,"
        " pageSawInjection: window.__pageSawInjection, events: window.__ciEvents || null}")


def third_party_iframes(driver, site_host):
    driver.switch_to.default_content()
    frames = []
    for element in driver.find_elements(By.TAG_NAME, "iframe"):
        src = element.get_attribute("src") or ""
        host = urlparse(src).hostname
        if host and site_host not in host and element.get_attribute("name") != "__tcfapiLocator":
            frames.append((element, src))
    return frames


def probe_channel_2(driver, site_host):
    """K4: run the probe in the first third-party iframe that can reach the locator frame."""
    results = []
    for element, src in third_party_iframes(driver, site_host)[:5]:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(element)
            status = driver.execute_script(PROBE_JS)
            if status != "sent":
                results.append({"src": src, "status": status})
                continue
            time.sleep(1.5)
            answers = driver.execute_script("return window.__ciProbe")
            results.append({"src": src, "status": status, "answers": answers})
            break
        except Exception as error:  # noqa: BLE001
            results.append({"src": src, "status": f"error: {type(error).__name__}: {error}"[:200]})
    driver.switch_to.default_content()
    return results or [{"status": "no third-party iframe -> not measurable"}]


def storage(driver):
    cookies = driver.execute_cdp_cmd("Storage.getCookies", {})["cookies"]
    tc_cookies = [{"name": c["name"], "domain": c["domain"], "value": c["value"][:40] + "..."}
                  for c in cookies if "consent" in c["name"].lower()]
    local = driver.execute_script(
        "const out = {}; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i);"
        " if (/tcf|consent|euconsent|cmp/i.test(k)) out[k] = String(localStorage.getItem(k)).slice(0, 40); }"
        " return out;")
    return {"cookies": tc_cookies, "localStorage": local}


def summarize(label, requests, top_id):
    found = consent_requests(requests)
    print(f"\n--- {label}: {len(requests)} requests, {len(found)} with consent signal")
    for r in found:
        where = "top" if r["frameId"] == top_id else f"frame {r['frameId'][:8]}"
        body = (r["body"] or "")[:90].replace("\n", " ")
        print(f"  {r['method']:4} {r['type'] or '':9} {where:14} {r['url'][:90]}  body={body!r}")
    return found


def run_local():
    driver = start_chrome()
    try:
        driver.get("http://localhost:8001/top.html")
        time.sleep(config.SLEEP_TIME_CMP_WAIT)
        top_id = frame_tree(driver)
        summarize("local, before action", network_requests(driver), top_id)
        print("events before:", json.dumps(read_events(driver)))
        print("channel 2 before:", json.dumps(probe_channel_2(driver, "localhost")))

        driver.find_element(By.ID, "accept").click()   # stands in for the human click
        time.sleep(1)
        print("events after click:", json.dumps(read_events(driver)["events"][-1:]))
        print("channel 2 after click:", json.dumps(probe_channel_2(driver, "localhost")))

        time.sleep(config.SLEEP_TIME_REFRESH)
        driver.refresh()
        time.sleep(config.SLEEP_TIME_CMP_WAIT)
        top_id = frame_tree(driver)
        summarize("local, after reload", network_requests(driver), top_id)
        print("events after reload:", json.dumps(read_events(driver)))
        print("storage:", json.dumps(storage(driver)))
    finally:
        driver.quit()


def robots_allows(domain):
    url = f"https://www.{domain}/robots.txt"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                    timeout=15) as response:
            text = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return 400 <= error.code < 500   # 4xx: everything allowed (RFC 9309)
    except Exception:  # noqa: BLE001
        return False                     # unreachable: nothing allowed
    return Protego.parse(text).can_fetch(f"https://www.{domain}/", "*")


def run_real(domains):
    for domain in domains:
        print(f"\n===== {domain}")
        if not robots_allows(domain):
            print("robots.txt disallows (or unreachable) -> skipped")
            continue
        driver = start_chrome()
        try:
            driver.get(f"https://www.{domain}/")
            time.sleep(config.SLEEP_TIME_CMP_WAIT + 5)
            top_id = frame_tree(driver)
            requests = network_requests(driver)
            found = summarize(f"{domain}, before action", requests, top_id)
            frames = {r["frameId"] for r in requests}
            print(f"frames with requests: {len(frames)} (top + {len(frames - {top_id})} others);"
                  f" consent requests from iframes: {sum(1 for r in found if r['frameId'] != top_id)};"
                  f" POST with body: {sum(1 for r in found if r['method'] == 'POST' and r['body'])}")
            events = read_events(driver)
            print("listener:", json.dumps({k: v for k, v in events.items() if k != "events"}),
                  "statuses:", [e["eventStatus"] for e in (events["events"] or [])])
            print("channel 2:", json.dumps(probe_channel_2(driver, domain))[:600])
            print("storage:", json.dumps(storage(driver)))
            driver.refresh()
            time.sleep(config.SLEEP_TIME_CMP_WAIT + 2)
            events = read_events(driver)
            print("after reload, listener:", json.dumps({k: v for k, v in events.items() if k != "events"}),
                  "statuses:", [e["eventStatus"] for e in (events["events"] or [])])
        finally:
            driver.quit()
        time.sleep(2)




ACCEPT_LABELS = ("alle akzeptieren", "akzeptieren", "zustimmen", "einverstanden", "accept")


def click_accept(driver):
    """Spike only: clicks an accept button in the top document or in a CMP iframe (e.g. Sourcepoint),
    to get a state with a consent signal. The tool itself does not click (semi-automatic mode)."""
    driver.switch_to.default_content()
    contexts = [None] + driver.find_elements(By.CSS_SELECTOR, "iframe[id^='sp_message_iframe'], iframe[title*='onsent' i]")
    for frame in contexts:
        driver.switch_to.default_content()
        if frame is not None:
            driver.switch_to.frame(frame)
        for button in driver.find_elements(By.CSS_SELECTOR, "button, [role='button']"):
            label = " ".join((button.text or button.get_attribute("title") or "").split()).lower()
            if label and any(label.startswith(word) for word in ACCEPT_LABELS):
                button.click()
                driver.switch_to.default_content()
                return label
    driver.switch_to.default_content()
    return None


def run_real_accept(domains):
    for domain in domains:
        print(f"\n===== {domain} (accept)")
        if not robots_allows(domain):
            print("robots.txt disallows (or unreachable) -> skipped")
            continue
        driver = start_chrome()
        try:
            driver.get(f"https://www.{domain}/")
            time.sleep(config.SLEEP_TIME_CMP_WAIT + 5)
            network_requests(driver)                      # drop the requests before the action
            print("clicked:", click_accept(driver))
            time.sleep(8)
            top_id = frame_tree(driver)
            requests = network_requests(driver)
            found = summarize(f"{domain}, after accept", requests, top_id)
            print(f"consent requests from iframes: {sum(1 for r in found if r['frameId'] != top_id)};"
                  f" POST with consent in body: {sum(1 for r in found if r['method'] == 'POST' and r['body'])}")
            events = read_events(driver)["events"] or []
            print("statuses:", [e["eventStatus"] for e in events],
                  "tcString after:", (events[-1]["tcString"] or "")[:30] if events else None)
            print("channel 2:", json.dumps(probe_channel_2(driver, domain))[:400])
            print("storage:", json.dumps(storage(driver))[:400])
            time.sleep(config.SLEEP_TIME_REFRESH)
            driver.refresh()
            time.sleep(config.SLEEP_TIME_CMP_WAIT + 2)
            events = read_events(driver)["events"] or []
            print("after reload, statuses:", [e["eventStatus"] for e in events])
        finally:
            driver.quit()
        time.sleep(2)


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "local":
        run_local()
    elif mode == "real":
        run_real(sys.argv[2:])
    elif mode == "real-accept":
        run_real_accept(sys.argv[2:])
