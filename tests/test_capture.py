"""Offline parts of capture.py: TC string header, classification of consent values, extraction
from URLs and bodies, storage values, registrable domains."""
import base64

from capture import (body_text, classify, consent_signals, registrable_domain, tc_string_header,
                     tc_string_version, tc_strings_in)

# made with @iabtechlabtcf/core 1.5.22 and a test GVL (tests/site/top.html)
TC_BEFORE = "CQs2X0AQs2X0AEsABAENBkFgAAAAAAAAAAYgAAAAAAAA.IAAA.YAAAAAAAAAAA"
TC_ACCEPTED = "CQs2X0AQs2X0AEsABAENBkFgAP_gAAAAAAYgAAAAAAAA.IAAA.YAAAAAAAAAAA"
TC_V1 = "BOEFEAyOEFEAyAAABAENAI4AAAB9vABAASA"   # example of the TCF v1.1 specification


def test_header_of_v2_string():
    header = tc_string_header(TC_ACCEPTED)
    assert header["tc_version"] == 2
    assert header["cmp_id"] == 300
    assert header["consent_language"] == "en"   # the official decoder reads EN as well
    assert header["created"].startswith("2026-10-29")


def test_version_from_the_string_itself():
    assert tc_string_version(TC_BEFORE) == 2
    assert tc_string_version(TC_V1) == 1
    assert tc_string_header(TC_V1)["consent_language"] == "en"


def test_other_tokens_are_no_tc_strings():
    assert tc_string_version("CustomerSessionTokenAbcdefghijk") is None
    assert tc_string_version("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9") is None   # JWT header
    assert tc_string_version("FRAME_GET_NO_TC_STRING") is None
    assert tc_string_version("C" * 10) is None
    assert tc_string_version(None) is None


def test_classify():
    assert classify("gdpr_consent", TC_BEFORE) == {"kind": "tc_string", "tc_version": 2}
    assert classify("gdpr_consent", TC_V1) == {"kind": "tc_string", "tc_version": 1}
    assert classify("gdpr_consent", "") == {"kind": "empty"}
    assert classify("gdpr_consent", "${GDPR_CONSENT_755}") == {"kind": "macro"}
    assert classify("gdpr_consent", "%24%7BGDPR_CONSENT_755%7D") == {"kind": "macro"}
    assert classify("gdpr", "0") == {"kind": "gdpr_flag"}
    assert classify("addtl_consent", "1~89.2140") == {"kind": "addtl_consent"}
    assert classify("gdpr_consent", "xyz") == {"kind": "other"}


def test_query_parameters_including_gdpr_0():
    signals = consent_signals(f"https://ads.example.com/px?gdpr=0&gdpr_consent={TC_BEFORE}&addtl_consent=1~7&x=1", None)
    assert [(s["location"], s["key"], s["value"], s["kind"]) for s in signals] == [
        ("query", "gdpr", "0", "gdpr_flag"),
        ("query", "gdpr_consent", TC_BEFORE, "tc_string"),
        ("query", "addtl_consent", "1~7", "addtl_consent"),
    ]


def test_form_body():
    signals = consent_signals("https://ads.example.com/collect", f"gdpr=1&gdpr_consent={TC_ACCEPTED}")
    assert [(s["location"], s["key"], s["kind"]) for s in signals] == [
        ("body_form", "gdpr", "gdpr_flag"), ("body_form", "gdpr_consent", "tc_string")]


def test_openrtb_25_and_26_and_prebid():
    body = ('{"imp":[{"id":"1"}],"user":{"ext":{"consent":"%s"}},"regs":{"ext":{"gdpr":1}},'
            '"source":{"ext":{"x":[{"user":{"consent":"%s"}}]}},'
            '"gdprConsent":{"consentString":"%s","gdprApplies":true}}') % (TC_BEFORE, TC_ACCEPTED, TC_ACCEPTED)
    signals = {(s["key"], s["kind"]) for s in consent_signals("https://bid.example.com/openrtb2/auction", body)}
    assert signals == {("user.ext.consent", "tc_string"), ("regs.ext.gdpr", "gdpr_flag"),
                       ("source.ext.x[0].user.consent", "tc_string"),
                       ("gdprConsent.consentString", "tc_string"), ("gdprConsent.gdprApplies", "gdpr_flag")}


def test_no_signals():
    assert consent_signals("https://example.com/a.js?v=1", '{"a": 1}') == []
    assert consent_signals("https://example.com/", "not json, no form") == []


def test_tc_strings_in_stored_json():
    # Sourcepoint keeps the TC string in a JSON object in localStorage (_sp_user_consent_*)
    stored = '{"gdpr":{"euconsent":"%s","grants":{}},"uuid":"8c2e7f0a-1b2c"}' % TC_ACCEPTED
    assert tc_strings_in(stored) == [{"value": TC_ACCEPTED, "tc_version": 2}]
    assert tc_strings_in("CustomerSessionTokenAbcdefghijk") == []


def test_body_text_base64():
    data = {"type": "base64", "value": base64.b64encode(b"gdpr_consent=abc").decode()}
    assert body_text(data) == "gdpr_consent=abc"
    assert body_text({"type": "string", "value": "x"}) == "x"
    assert body_text(None) is None


def test_registrable_domain():
    assert registrable_domain("https://www.bild.de/") == "bild.de"
    assert registrable_domain("https://cdn.privacy-mgmt.com/x") == "privacy-mgmt.com"
    assert registrable_domain("https://news.bbc.co.uk/") == "bbc.co.uk"
    assert registrable_domain("http://localhost:8001/top.html") == "localhost"
    assert registrable_domain("http://127.0.0.1:8002/") == "127.0.0.1"


def test_wait_for_event_sees_event_that_arrived_before_the_call():
    # the event arrives between the human's click and the call (race found in Phase 3)
    from capture import Capture
    import threading
    session = Capture.__new__(Capture)
    session.lock = threading.Lock()
    session.tcf_messages = [{"kind": "event", "eventStatus": "cmpuishown"}]
    mark = session.mark()
    session.tcf_messages.append({"kind": "event", "eventStatus": "useractioncomplete", "tcString": "x"})
    assert session.wait_for_event("useractioncomplete", 0, after=mark)["tcString"] == "x"
    assert session.wait_for_event("useractioncomplete", 0, after=len(session.tcf_messages)) is None
