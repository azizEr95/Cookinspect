"""Cookiewall detection (pay or OK) in the automatic mode. A HEURISTIC: it marks suspected
cookiewalls, it does not decide. Phase 8 compares it with the manual code w of the semi-automatic
mode and reports how well they agree (CLAUDE.md, Cookiewalls).

It only reads, it never clicks: the visible text of consent dialogs in the top document (also in
open shadow roots) and of CMP iframes, plus the domains the page requested.

A site counts as suspected cookiewall if the dialog text offers both consent (e.g. "Akzeptieren")
and paying (e.g. "Pur-Abo", "werbefrei", a price in euros), or if the page loads a known
pay-or-OK provider (contentpass).
"""
import re

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

CONSENT_MARKERS = ("akzeptieren", "zustimmen", "einverstanden", "alle annehmen", "accept")
PAY_MARKERS = ("pur-abo", "pur abo", "pur-abonnement", "pur abonnement", "werbefrei", "ohne werbung",
               "ohne werbetracking", "ohne tracking", "abonnieren", "abo abschließen", "zum abo",
               "contentpass", "jetzt abonnieren", "monatlich kündbar")
PRICE_PATTERN = re.compile(r"\d+[,.]\d{2}\s?€|€\s?\d+[,.]\d{2}|\d+[,.]\d{2}\s?euro", re.IGNORECASE)
PAY_OR_OK_PROVIDERS = ("contentpass.net", "contentpass.de")

# iframes of CMPs (by id, title or src): Sourcepoint, Usercentrics, OneTrust, Didomi, consentmanager ...
CMP_IFRAME_PATTERN = re.compile(r"sp_message|privacy-mgmt|consent|cmp|cookie|didomi|usercentrics|onetrust|"
                                r"contentpass", re.IGNORECASE)

# Visible text of elements that look like consent dialogs, also inside open shadow roots.
DIALOG_TEXT_SCRIPT = r"""
const selector = '[role="dialog"], [aria-modal="true"], [id*="consent" i], [class*="consent" i], ' +
  '[id*="cookie" i], [class*="cookie" i], [id*="cmp" i], [class*="cmp" i], [id*="gdpr" i], [id^="sp_message"]';
const texts = [];
const visible = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
const collect = (root) => {
  for (const e of root.querySelectorAll(selector)) if (visible(e)) texts.push(e.innerText || "");
  for (const e of root.querySelectorAll("*")) if (e.shadowRoot) {
    texts.push(e.shadowRoot.textContent || "");
    collect(e.shadowRoot);
  }
};
collect(document);
return texts.join("\n").slice(0, 50000);
"""


def dialog_texts(driver):
    """Texts of consent dialogs: top document and CMP iframes (one level)."""
    driver.switch_to.default_content()
    texts = [driver.execute_script(DIALOG_TEXT_SCRIPT) or ""]
    for frame in driver.find_elements(By.TAG_NAME, "iframe"):
        try:
            description = " ".join(filter(None, (frame.get_attribute(a) for a in ("id", "title", "src", "name"))))
            if not CMP_IFRAME_PATTERN.search(description) or not frame.is_displayed():
                continue
            driver.switch_to.frame(frame)
            texts.append(driver.execute_script("return document.body ? document.body.innerText : ''") or "")
        except WebDriverException:
            pass
        finally:
            driver.switch_to.default_content()
    return texts


def detect_cookiewall(texts, request_domains):
    """(suspected, reason). texts: from dialog_texts; request_domains: registrable domains requested."""
    providers = sorted(d for d in set(request_domains) if d in PAY_OR_OK_PROVIDERS)
    if providers:
        return True, f"pay-or-OK provider: {', '.join(providers)}"
    text = "\n".join(texts).lower()
    consent = [m for m in CONSENT_MARKERS if m in text]
    pay = [m for m in PAY_MARKERS if m in text] + (["price in euros"] if PRICE_PATTERN.search(text) else [])
    if consent and pay:
        return True, f"dialog offers consent ({', '.join(consent[:3])}) and paying ({', '.join(pay[:3])})"
    return False, None
