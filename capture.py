"""Capture of the consent signals during a visit (Phase 3), without browser extensions.

Channels (CLAUDE.md, Ablauf):
  1  __tcfapi addEventListener in the top frame. A WebDriver BiDi preload script registers the
     listener at document start of every page and sends every event at once to Python through
     a BiDi channel (script.message), so that no event is lost when the CMP reloads the page
     (docs/entscheidungen.md, E1 and E2). removeEventListener is called at the end.
  2  from a third-party position: inside an existing third-party iframe, __tcfapiCall through
     postMessage to the __tcfapiLocator frame. Without such an iframe: "not measurable".
  storage: the first-party cookie euconsent-v2 (and other consent cookies) and localStorage.
  requests: every request of the tab, also from iframes, GET and POST (BiDi network events and
     the data collector for bodies): gdpr_consent, gdpr (also gdpr=0), addtl_consent in the URL,
     in form data and in JSON bodies (OpenRTB/Prebid, e.g. user.ext.consent).

The tool never clicks: it only reads. Decoding the TC strings follows in Phase 4, storing in
Phase 5; here every TC string is kept raw, with its version taken from the string itself.

    session = Capture(driver, "https://www.example.de")   # right after start_chrome()
    driver.get(...)
    snapshot = session.snapshot("before")
    mark = session.mark()                                  # before the human acts
    event = session.wait_for_event("useractioncomplete", config.USERACTIONCOMPLETE_TIMEOUT, after=mark)
    session.close()                                        # removeEventListener
"""
import base64
import json
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlparse

import tldextract
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

import config

TCF_CHANNEL = "ci_tcf"

# Preload script, runs at document start in every page and frame of the tab; only the top frame
# registers. __tcfapi usually does not exist yet at document start, so it waits for it (polling
# every 50 ms, at most MAX_WAIT_MS). Every message is a JSON string, which keeps the BiDi
# serialization simple. BiDi only passes channels as arguments of a preload script, so the
# waiting time is put into the source (listener_function).
LISTENER_FUNCTION = r"""
(send) => {
  const maxWaitMs = MAX_WAIT_MS;
  if (window !== window.top) return;
  const message = (kind, fields) => send(JSON.stringify(Object.assign({
    kind: kind, url: location.href, t: Math.round(performance.now()),
    at: new Date().toISOString() }, fields)));
  message("injected", {});
  const started = performance.now();
  const register = () => {
    if (typeof window.__tcfapi !== "function") {
      if (performance.now() - started < maxWaitMs) setTimeout(register, 50);
      else message("no_tcfapi", {});
      return;
    }
    message("registering", {});
    window.__tcfapi("addEventListener", 2, (tcData, success) => {
      // some CMPs call back with an empty object (seen on amazon.de, CMP 376): kept and marked
      const emptyTcData = !tcData || Object.keys(tcData).length === 0;
      tcData = tcData || {};
      if (tcData.listenerId !== undefined) window.__ciListenerId = tcData.listenerId;
      message("event", {
        success: success, emptyTcData: emptyTcData, eventStatus: tcData.eventStatus, listenerId: tcData.listenerId,
        cmpId: tcData.cmpId, cmpVersion: tcData.cmpVersion, cmpStatus: tcData.cmpStatus,
        gdprApplies: tcData.gdprApplies, tcfPolicyVersion: tcData.tcfPolicyVersion,
        isServiceSpecific: tcData.isServiceSpecific, useNonStandardTexts: tcData.useNonStandardTexts,
        tcString: tcData.tcString, addtlConsent: tcData.addtlConsent,
      });
    });
  };
  register();
}
"""

def listener_function():
    return LISTENER_FUNCTION.replace("MAX_WAIT_MS", str(int(config.TCF_LISTENER_WAIT * 1000)))


# Removes our listener (runs in the top frame). The callback of removeEventListener reports
# whether the CMP accepted it.
REMOVE_LISTENER_SCRIPT = """
const done = arguments[arguments.length - 1];
if (typeof window.__tcfapi !== "function" || window.__ciListenerId === undefined) {
  done({removed: null, reason: "no listener registered in this document"}); return;
}
const timer = setTimeout(() => done({removed: null, reason: "no answer"}), 2000);
try {
  window.__tcfapi("removeEventListener", 2, (success) => {
    clearTimeout(timer); done({removed: success, listenerId: window.__ciListenerId});
  }, window.__ciListenerId);
} catch (error) { clearTimeout(timer); done({removed: null, reason: String(error)}); }
"""

# Channel 2, runs inside a third-party iframe (after switch_to.frame). Looks for the
# __tcfapiLocator frame among the ancestors and asks ping and addEventListener through
# postMessage, as a vendor script would; then removes the listener again.
CHANNEL_2_SCRIPT = r"""
const done = arguments[arguments.length - 1];
const waitMs = arguments[0];
let f = window, locator = null;
while (true) {
  try { if (f.frames["__tcfapiLocator"]) { locator = f; break; } } catch (e) {}
  if (f === window.top) break;
  f = f.parent;
}
if (!locator) { done({status: "no_locator"}); return; }
const answers = {};
const onMessage = (e) => {
  let d = e.data;
  if (typeof d === "string") { try { d = JSON.parse(d); } catch (x) { return; } }
  const r = d && d.__tcfapiReturn;
  if (!r || !String(r.callId).startsWith("ci_")) return;
  answers[r.callId] = {success: r.success, returnValue: r.returnValue};
  if (r.callId === "ci_addEventListener" && r.returnValue && r.returnValue.listenerId !== undefined)
    locator.postMessage({__tcfapiCall: {command: "removeEventListener", version: 2,
      callId: "ci_removeEventListener", parameter: r.returnValue.listenerId}}, "*");
};
window.addEventListener("message", onMessage);
for (const command of ["ping", "addEventListener"])
  locator.postMessage({__tcfapiCall: {command: command, version: 2, callId: "ci_" + command}}, "*");
setTimeout(() => {
  window.removeEventListener("message", onMessage);
  const pick = (a) => a && a.returnValue ? {
    success: a.success, eventStatus: a.returnValue.eventStatus, tcString: a.returnValue.tcString,
    cmpId: a.returnValue.cmpId, cmpLoaded: a.returnValue.cmpLoaded,
    gdprApplies: a.returnValue.gdprApplies, listenerId: a.returnValue.listenerId} : (a || null);
  done({status: Object.keys(answers).length ? "answered" : "no_answer",
        ping: pick(answers.ci_ping), event: pick(answers.ci_addEventListener),
        removed: answers.ci_removeEventListener ? answers.ci_removeEventListener.success : null});
}, waitMs);
"""

# Signals in request URLs and bodies
CONSENT_PARAMS = ("gdpr_consent", "gdpr", "addtl_consent")
# Keys in JSON bodies (OpenRTB 2.5 user.ext.consent / regs.ext.gdpr, OpenRTB 2.6 user.consent /
# regs.gdpr, Prebid gdprConsent.consentString / gdprApplies, Google addtl_consent)
CONSENT_JSON_KEYS = ("consent", "consentstring", "consent_string", "gdpr_consent", "gdpr",
                     "gdprapplies", "addtl_consent", "addtlconsent")
CONSENT_STORAGE_PATTERN = re.compile(r"consent|tcf|euconsent|cmp|_sp_", re.IGNORECASE)
# TC strings: base64url segments separated by dots. v1 strings start with "B", v2 with "C"
# (the first 6 bits are the version). Candidates are checked with tc_string_header; the decoder
# (Phase 4) reads them completely.
TC_STRING_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])[BC][A-Za-z0-9_-]{20,}(?:\.[A-Za-z0-9_-]+)*")
BASE64URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
# Plausible creation dates of a TC string: TCF v1 came out in 2018 (the examples of the v1
# specification are from November 2017)
TC_CREATED_EARLIEST = datetime(2017, 1, 1, tzinfo=timezone.utc)
MACRO_PATTERN = re.compile(r"\$\{|%24%7B|\{\{|\[GDPR|__GDPR", re.IGNORECASE)

# Registrable domains from the public suffix list bundled with tldextract (no download, so that
# the result does not change between runs; the tldextract version is in the metadata).
_registrable = tldextract.TLDExtract(suffix_list_urls=())


def registrable_domain(url_or_host):
    host = urlparse(url_or_host).hostname if "://" in url_or_host else url_or_host
    return _registrable(host or "").top_domain_under_public_suffix or (host or "")


def tc_string_header(value):
    """The header fields that v1 and v2 share (version 6 bits, Created 36, LastUpdated 36,
    CmpId 12, CmpVersion 12, ConsentScreen 6, ConsentLanguage 12), or None if value is no
    plausible TC string: version 1 or 2, creation date between 2017 and next year, language two
    letters. This tells a TC string from other base64 tokens; it does not decode the rest."""
    if not isinstance(value, str) or len(value) < 20:
        return None
    core = value.split(".")[0]
    if any(c not in BASE64URL for c in core):
        return None
    bits = "".join(format(BASE64URL.index(c), "06b") for c in core[:20])   # 120 bits

    def number(start, length):
        return int(bits[start:start + length], 2)

    version = number(0, 6)
    if version not in (1, 2):
        return None
    created = datetime.fromtimestamp(number(6, 36) / 10, tz=timezone.utc)
    if not TC_CREATED_EARLIEST <= created <= datetime.now(timezone.utc).replace(year=datetime.now().year + 1):
        return None
    letters = (number(108, 6), number(114, 6))
    if any(letter > 25 for letter in letters):
        return None
    return {"tc_version": version, "created": created.isoformat(), "cmp_id": number(78, 12),
            "consent_language": "".join(chr(ord("a") + letter) for letter in letters)}


def tc_string_version(value):
    """Version taken from the string itself (1 or 2), None if it is no TC string."""
    header = tc_string_header(value)
    return header["tc_version"] if header else None


def classify(key, value):
    """Kind of a consent value: tc_string (with version), gdpr flag, addtl_consent, macro, empty."""
    value = "" if value is None else str(value)
    key = key.lower()
    if value == "":
        return {"kind": "empty"}
    if MACRO_PATTERN.search(value):
        return {"kind": "macro"}   # placeholder that was never filled in, e.g. ${GDPR_CONSENT_755}
    if key in ("gdpr", "gdprapplies"):
        return {"kind": "gdpr_flag"}
    if key in ("addtl_consent", "addtlconsent") or value.startswith("1~"):
        return {"kind": "addtl_consent"}
    version = tc_string_version(value)
    if version:
        return {"kind": "tc_string", "tc_version": version}
    return {"kind": "other"}


def body_text(data):
    """Body bytes from BiDi network.getData: {"type": "string"|"base64", "value": ...}."""
    if not data:
        return None
    if data.get("type") == "base64":
        return base64.b64decode(data["value"]).decode("utf-8", errors="replace")
    return data.get("value")


def json_signals(value, path=""):
    """Consent fields anywhere in a JSON body, with their path (e.g. user.ext.consent)."""
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key.lower() in CONSENT_JSON_KEYS and not isinstance(child, (dict, list)):
                found.append({"location": "body_json", "key": child_path, "value": child,
                              **classify(key, child)})
            else:
                found.extend(json_signals(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(json_signals(child, f"{path}[{index}]"))
    return found


def consent_signals(url, body):
    """All consent signals of one request: query parameters, form data, JSON fields."""
    found = []
    for key, value in parse_qsl(urlparse(url).query, keep_blank_values=True):
        if key.lower() in CONSENT_PARAMS:
            found.append({"location": "query", "key": key, "value": value, **classify(key, value)})
    if body:
        stripped = body.strip()
        parsed = None
        if stripped[:1] in "{[":
            try:
                parsed = json.loads(stripped)
            except ValueError:
                parsed = None
        if parsed is not None:
            found.extend(json_signals(parsed))
        else:   # form data (application/x-www-form-urlencoded, also sent as text/plain)
            for key, value in parse_qsl(stripped, keep_blank_values=True):
                if key.lower() in CONSENT_PARAMS:
                    found.append({"location": "body_form", "key": key, "value": value, **classify(key, value)})
    return found


def tc_strings_in(text):
    """TC strings inside a stored value (e.g. a JSON object in localStorage)."""
    return [{"value": match, "tc_version": tc_string_version(match)}
            for match in TC_STRING_PATTERN.findall(text or "") if tc_string_version(match)]


def bidi_string(data):
    """The string that the preload script sent (a BiDi remote value)."""
    if isinstance(data, dict):
        return data.get("value")
    return getattr(data, "value", data)


class Capture:
    """All channels of one browser session (one fresh browser per session)."""

    def __init__(self, driver, site_url):
        self.driver = driver
        self.site_url = site_url
        self.site_domain = registrable_domain(site_url)
        self.top_context = driver.current_window_handle
        self.lock = threading.Lock()
        self.tcf_messages = []       # all messages of the preload script, in order
        self.new_requests = []       # network events not yet processed
        self.requests = []           # processed requests, all of the session
        self.closed = None
        self.snapshots_taken = 0

        driver.network.add_data_collector(data_types=["request"], max_encoded_data_size=config.MAX_BODY_SIZE)
        driver.network.add_event_handler("before_request_sent", self._on_request)
        driver.script.add_event_handler("message", self._on_message)
        driver.script.add_preload_script(
            function_declaration=listener_function(),
            arguments=[{"type": "channel", "value": {"channel": TCF_CHANNEL}}])

    # --- callbacks (run on Selenium's websocket thread: only store, no WebDriver calls here)

    def _on_message(self, params):
        if params.channel != TCF_CHANNEL:
            return
        try:
            message = json.loads(bidi_string(params.data))
        except (TypeError, ValueError):
            return
        message["received_at"] = datetime.now(timezone.utc).isoformat()
        with self.lock:
            self.tcf_messages.append(message)

    def _on_request(self, params):
        params = params if isinstance(params, dict) else vars(params)
        request = params["request"]
        request = request if isinstance(request, dict) else vars(request)
        with self.lock:
            self.new_requests.append({
                "id": request.get("request"), "url": request.get("url"), "method": request.get("method"),
                "body_size": request.get("bodySize") or request.get("body_size"),
                "context": params.get("context"), "navigation": params.get("navigation"),
                "time": datetime.now(timezone.utc).isoformat(),
            })

    # --- channel 1

    def events(self, status=None):
        with self.lock:
            events = [m for m in self.tcf_messages if m["kind"] == "event"]
        return [e for e in events if status is None or e.get("eventStatus") == status]

    def mark(self):
        """Position in the message log. Taken before the human acts, so that an event that
        arrives before wait_for_event is called is not missed."""
        with self.lock:
            return len(self.tcf_messages)

    def wait_for_event(self, status, timeout, after):
        """First event with this eventStatus after the mark `after` (from mark()). Returns it, or
        None after timeout seconds (then "no useractioncomplete" is stored, CLAUDE.md, Ablauf 4)."""
        deadline = time.monotonic() + timeout
        while True:
            with self.lock:
                later = self.tcf_messages[after:]
            for message in later:
                if message["kind"] == "event" and message.get("eventStatus") == status:
                    return message
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.2)

    def remove_listener(self):
        """removeEventListener for our listener in the current document."""
        try:
            self.driver.switch_to.default_content()
            self.driver.set_script_timeout(5)
            return self.driver.execute_async_script(REMOVE_LISTENER_SCRIPT)
        except WebDriverException as error:
            return {"removed": None, "reason": f"{type(error).__name__}: {error.msg}"}

    # --- requests

    def collect_requests(self):
        """Processes the network events since the last call: reads the bodies and the consent
        signals. Called by snapshot() and before every navigation, while the bodies still exist."""
        with self.lock:
            new, self.new_requests = self.new_requests, []
        for request in new:
            body, body_status = None, None
            if request["body_size"]:
                if request["body_size"] > config.MAX_BODY_SIZE:
                    body_status = "too_large"
                else:
                    try:
                        data = self.driver.network.get_data(data_type="request", request=request["id"])
                        body = body_text(data.get("bytes") if isinstance(data, dict) else getattr(data, "bytes", None))
                        body_status = "read"
                    except WebDriverException as error:
                        body_status = f"not_available: {error.msg}"[:200]
            request["body_status"] = body_status
            # top frame, an iframe, or a worker (requests of service workers have no browsing context)
            request["source"] = ("worker" if request["context"] is None
                                 else "top" if request["context"] == self.top_context else "iframe")
            request["third_party"] = registrable_domain(request["url"] or "") != self.site_domain
            request["signals"] = consent_signals(request["url"] or "", body)
            request["body"] = body if request["signals"] else None   # keep bodies only where needed
            self.requests.append(request)
        return new

    # --- storage

    def storage(self):
        """Consent cookies (all domains of the session) and localStorage of the top frame."""
        cookies = []
        for cookie in self.driver.storage.get_cookies().cookies:
            value = bidi_string(cookie.value) or ""
            if cookie.name == "euconsent-v2" or CONSENT_STORAGE_PATTERN.search(cookie.name) or tc_strings_in(value):
                cookies.append({"name": cookie.name, "domain": cookie.domain, "value": value,
                                "first_party": registrable_domain(cookie.domain.lstrip(".")) == self.site_domain,
                                "tc_strings": tc_strings_in(value)})
        self.driver.switch_to.default_content()
        local = self.driver.execute_script(
            "const out = {}; for (let i = 0; i < localStorage.length; i++) {"
            " const k = localStorage.key(i); out[k] = String(localStorage.getItem(k)); } return out;")
        local_storage = [{"key": key, "value": value, "tc_strings": tc_strings_in(value)}
                         for key, value in local.items()
                         if CONSENT_STORAGE_PATTERN.search(key) or tc_strings_in(value)]
        return {"cookies": cookies, "local_storage": local_storage}

    # --- channel 2

    def third_party_iframes(self):
        """iframe elements of the top document from another registrable domain."""
        self.driver.switch_to.default_content()
        frames = []
        for element in self.driver.find_elements(By.TAG_NAME, "iframe"):
            src = element.get_attribute("src") or ""
            if src.startswith("http") and registrable_domain(src) != self.site_domain \
                    and element.get_attribute("name") != "__tcfapiLocator":
                frames.append((element, src))
        return frames

    def channel_2(self):
        """Asks the CMP from the first third-party iframe that reaches the locator frame. Never
        falls back to the main frame: without a third-party iframe it is "not_measurable"."""
        frames = self.third_party_iframes()
        if not frames:
            return {"status": "not_measurable", "reason": "no third-party iframe"}
        tried = []
        for element, src in frames[:config.CHANNEL_2_MAX_FRAMES]:
            try:
                self.driver.switch_to.default_content()
                self.driver.switch_to.frame(element)
                self.driver.set_script_timeout(config.CHANNEL_2_WAIT + 3)
                result = self.driver.execute_async_script(CHANNEL_2_SCRIPT, config.CHANNEL_2_WAIT * 1000)
            except WebDriverException as error:
                result = {"status": "error", "reason": f"{type(error).__name__}: {error.msg}"[:200]}
            result["frame_src"] = src[:300]
            if result["status"] == "answered":
                self.driver.switch_to.default_content()
                return {**result, "tried_frames": len(tried) + 1}
            tried.append(result)
        self.driver.switch_to.default_content()
        return {"status": "not_measurable", "reason": "no third-party iframe reached the CMP",
                "tried": tried}

    # --- snapshot of all channels

    def snapshot(self, label, channel_2=True):
        """State of all channels now. The requests are those since the previous snapshot."""
        new_requests = self.collect_requests()
        for request in new_requests:
            request["until_snapshot"] = label   # sent after the previous snapshot, before this one
        events = self.events()
        latest = events[-1] if events else None
        snapshot = {
            "label": label,
            "taken_at": datetime.now(timezone.utc).isoformat(),
            "page_url": self.driver.current_url,
            "channel_1": {
                "latest_event": latest,
                "events_in_session": len(events),
                "tcfapi_seen": any(m["kind"] == "registering" for m in self.tcf_messages),
            },
            "channel_2": self.channel_2() if channel_2 else {"status": "skipped"},
            "storage": self.storage(),
            "requests": {
                "count": len(new_requests),
                "third_party": sum(1 for r in new_requests if r["third_party"]),
                "with_signals": [r for r in new_requests if r["signals"]],
            },
        }
        self.snapshots_taken += 1
        return snapshot

    def close(self):
        """removeEventListener and the full message log of channel 1."""
        self.collect_requests()
        self.closed = self.remove_listener()
        with self.lock:
            messages = list(self.tcf_messages)
        return {"remove_listener": self.closed, "tcf_messages": messages}
