"""Loading a page and looking at what came back, shared by prefilter.py and automatic.py:
load with the retries of Cookinspect, the HTTP status of the main document (BiDi), signs of a
block page (bot detection, not avoided, only detected), and the list of sites to visit."""
import csv

from selenium.common.exceptions import TimeoutException, WebDriverException

import config

# Signs of a block page (bot detection, challenge, access denied). A heuristic: hits are reported,
# not hidden, and can be checked by hand in prefilter.csv. Searched in the title and the beginning
# of the visible text (BLOCK_MARKERS) and in the HTML (BLOCK_HTML_MARKERS: challenge pages of bot
# managers, which often answer with status 200). Only markers that appear on the challenge page
# itself, not on normal pages protected by the same service (e.g. not Cloudflare's
# /cdn-cgi/challenge-platform/ script, which many normal pages load).
BLOCK_STATUS = (401, 403, 429)
BLOCK_HTML_MARKERS = {
    "sec-if-cpt-container": "Akamai Bot Manager",      # e.g. mobile.de, 2026-10-29
    "cf_chl_opt": "Cloudflare challenge",
    "captcha-delivery.com": "DataDome",
    "px-captcha": "PerimeterX/HUMAN",
    "incapsula incident id": "Imperva/Incapsula",
}
BLOCK_MARKERS = (
    "access denied", "zugriff verweigert", "request blocked", "you have been blocked",
    "attention required", "just a moment", "checking your browser", "pardon our interruption",
    "are you a robot", "bist du ein mensch", "sind sie ein mensch", "verify you are human",
    "captcha", "403 forbidden", "error 1020",
)

def read_ranked_domains(path):
    """(rank, domain) pairs from a CSV with rank,domain columns, or a plain list of domains."""
    with open(path, newline="") as f:
        first_line = f.readline()
        f.seek(0)
        if "domain" in first_line.strip().split(","):
            return [(row.get("rank") or str(number), row["domain"].strip())
                    for number, row in enumerate(csv.DictReader(f), start=1) if row["domain"].strip()]
        domains = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        return [(str(number), domain) for number, domain in enumerate(domains, start=1)]


def detect_block(http_status, title, text, html=""):
    """Reason why the page looks like a block page, or None."""
    if http_status in BLOCK_STATUS:
        return f"HTTP {http_status}"
    haystack = f"{title or ''}\n{(text or '')[:2000]}".lower()
    for marker in BLOCK_MARKERS:
        if marker in haystack:
            return f"text: {marker}"
    html = (html or "")[:50000].lower()
    for marker, service in BLOCK_HTML_MARKERS.items():
        if marker in html:
            return f"html: {service}"
    if not (title or "").strip() and not (text or "").strip():
        return "no title and no visible text"
    return None


def watch_main_document(driver):
    """Records the HTTP status of the main document of every navigation in the top frame
    (BiDi network.responseCompleted). Returns the list the statuses are appended to."""
    top_context = driver.current_window_handle
    responses = []

    def field(value, name):   # Selenium passes dataclasses here, but sometimes plain dicts inside
        return value.get(name) if isinstance(value, dict) else getattr(value, name, None)

    def on_response(params):
        if params.context == top_context and params.navigation:
            responses.append({"url": field(params.response, "url"), "status": field(params.response, "status")})

    driver.network.add_event_handler("response_completed", on_response)
    return responses


def load_page(driver, url):
    """Loads url with up to config.MAX_TRIES_TIMEOUT attempts, as Cookinspect did.
    Returns (loaded, attempts, errors)."""
    errors = []
    for attempt in range(1, config.MAX_TRIES_TIMEOUT + 1):
        try:
            driver.get(url)
            return True, attempt, errors
        except TimeoutException:
            errors.append("timeout")
        except WebDriverException as error:
            errors.append(error.msg.splitlines()[0] if error.msg else type(error).__name__)
    return False, config.MAX_TRIES_TIMEOUT, errors
