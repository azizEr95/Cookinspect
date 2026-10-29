"""Phase 1 spike, criterion K3 again: CMPs often reload the page right after the choice, so events
collected in window.__ciEvents are lost (seen on wetteronline.de). This script sends every
__tcfapi event at once to Python through a WebDriver BiDi preload script with a channel
(script.message), which survives reloads.

    venv/bin/python spikes/cdp/spike_k3.py local          # test site, reloads after the click
    venv/bin/python spikes/cdp/spike_k3.py real <domain>  # spike only: clicks accept
"""
import sys
import threading
import time

from selenium import webdriver
from selenium.webdriver.common.by import By

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
import config  # noqa: E402
from spike import click_accept, robots_allows  # noqa: E402

# Preload script: runs at document start in every context; only the top frame registers.
LISTENER_FUNCTION = r"""
(send) => {
  if (window !== window.top) return;
  const register = () => {
    if (typeof window.__tcfapi !== 'function') { setTimeout(register, 50); return; }
    window.__tcfapi('addEventListener', 2, (tcData, success) => {
      send({ url: location.href, t: Math.round(performance.now()), success: success,
             eventStatus: tcData && tcData.eventStatus, listenerId: tcData && tcData.listenerId,
             tcString: tcData && tcData.tcString });
    });
  };
  register();
}
"""


def start_chrome():
    options = webdriver.ChromeOptions()
    options.browser_version = config.CHROME_VERSION
    options.enable_bidi = True
    driver = webdriver.Chrome(options=options)
    driver.ci_events, driver.ci_lock = [], threading.Lock()

    def on_message(params):
        if params.channel == "ci_tcf":
            with driver.ci_lock:
                driver.ci_events.append(params.data)

    driver.script.add_event_handler("message", on_message)
    driver.script.add_preload_script(function_declaration=LISTENER_FUNCTION,
                                     arguments=[{"type": "channel", "value": {"channel": "ci_tcf"}}])
    return driver


def statuses(driver):
    """BiDi serializes the sent object as a remote value; take eventStatus and the page path."""
    out = []
    with driver.ci_lock:
        for data in driver.ci_events:
            data = data if isinstance(data, dict) else vars(data)
            fields = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in data["value"]}
            out.append((fields.get("eventStatus"), (fields.get("tcString") or "")[:16], fields.get("url", "")[-30:]))
    return out


def run(url, click):
    driver = start_chrome()
    try:
        driver.get(url)
        time.sleep(config.SLEEP_TIME_CMP_WAIT + (5 if click is click_accept else 0))
        print("before:", statuses(driver))
        print("clicked:", click(driver))
        time.sleep(config.USERACTIONCOMPLETE_TIMEOUT)
        print("after click (incl. a reload by the page):", statuses(driver))
        driver.refresh()
        time.sleep(config.SLEEP_TIME_CMP_WAIT + 2)
        print("after our reload:", statuses(driver)[-2:])
    finally:
        driver.quit()


if __name__ == "__main__":
    if sys.argv[1] == "local":
        run("http://localhost:8001/top.html?reload_after_choice=1",
            lambda d: d.find_element(By.ID, "accept").click() or "accept")
    elif robots_allows(sys.argv[2]):
        run(f"https://www.{sys.argv[2]}/", click_accept)
