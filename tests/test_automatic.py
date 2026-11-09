"""Cookiewall heuristic (cookiewall.py) and the site list of the automatic mode (offline). The
texts are shortened from the banners of 2026-10-29 (screenshots checked by hand)."""
from automatic import read_sites
from cookiewall import detect_cookiewall

T_ONLINE = ("Wie wollen Sie t-online nutzen? Kostenfrei mit Werbung ZUSTIMMEN ...oder mit t-online PUR-Abo "
            "Nutzen Sie t-online nahezu werbefrei und ohne Werbetracking für 2,99€/ Monat, monatlich kündbar.")
FOCUS = "AKZEPTIEREN Werbefrei mit Contentpass? WERBEFREI FÜR 3,99€ / MONAT"
BILD = "Alle akzeptieren Einstellungen Ohne Tracking und Cookies nutzen für 3,99 EUR/Monat Jetzt BILD PUR abonnieren"
AMAZON = ("Cookies und Werbeoptionen Wenn du zustimmst, können wir deine personenbezogenen Daten ... "
          "Akzeptieren Ablehnen Personalisieren")


def test_pay_or_ok_banners_are_suspected():
    for text in (T_ONLINE, FOCUS, BILD):
        suspected, reason = detect_cookiewall([text], [])
        assert suspected, text
        assert "consent" in reason and "paying" in reason


def test_banner_with_reject_and_no_payment_is_not_suspected():
    assert detect_cookiewall([AMAZON], []) == (False, None)


def test_pay_or_ok_provider_in_requests():
    assert detect_cookiewall([], ["example.de", "contentpass.net"]) == (True, "pay-or-OK provider: contentpass.net")


def test_payment_without_consent_dialog_is_not_suspected():
    # e.g. a subscription teaser in a dialog without any consent button
    assert detect_cookiewall(["Jetzt abonnieren für 9,99 € im Monat"], []) == (False, None)


def test_read_sites(tmp_path):
    tcf_sites = tmp_path / "tcf_sites.csv"
    tcf_sites.write_text("rank,domain,url,cmp_id\n129,t-online.de,https://www.t-online.de,6\n")
    assert read_sites(tcf_sites) == [{"rank": "129", "domain": "t-online.de", "url": "https://www.t-online.de"}]
    plain = tmp_path / "list.txt"
    plain.write_text("bild.de\n")
    assert read_sites(plain) == [{"rank": None, "domain": "bild.de", "url": "https://www.bild.de"}]


# --- robustness: a broken iframe or an unexpected error ends only one site (skyscanner.de, 2026-11-09)

import pytest  # noqa: E402
from selenium.common.exceptions import StaleElementReferenceException  # noqa: E402
from selenium.webdriver.remote.webelement import WebElement  # noqa: E402

import automatic  # noqa: E402
import database  # noqa: E402
from capture import Capture  # noqa: E402


class FakeFrame(WebElement):
    def __init__(self, attributes=None, stale=False):
        super().__init__(parent=None, id_="frame")
        self.attributes, self.stale = attributes or {}, stale

    def get_attribute(self, name):
        if self.stale:
            raise StaleElementReferenceException("gone")
        return self.attributes.get(name)


class FakeDriver:
    def __init__(self, elements):
        self.elements = elements
        self.switch_to = type("SwitchTo", (), {"default_content": lambda self: None})()

    def find_elements(self, by, value):
        return self.elements


def test_iframes_that_are_no_elements_or_gone_are_skipped():
    ad = FakeFrame({"src": "https://ads.example.com/frame"})
    capture = Capture.__new__(Capture)   # without browser
    capture.site_domain = "skyscanner.de"
    capture.driver = FakeDriver([{}, FakeFrame(stale=True), FakeFrame({"src": "https://www.skyscanner.de/x"}), ad])
    assert capture.third_party_iframes() == [(ad, "https://ads.example.com/frame")]


@pytest.fixture
def conn():
    connection = database.connect(":memory:")
    run_id = database.insert_run(connection, {
        "mode": "automatic", "test_run": True, "started_at": database.now(), "git": {"commit": "x", "dirty": False},
        "browser": {"browser_version": "156"}, "decoder": {"version": "1"}})
    return connection, run_id


def test_unexpected_error_aborts_only_the_site(conn, monkeypatch):
    connection, run_id = conn
    monkeypatch.setattr(automatic, "check_robots", lambda url: {"robots_allowed": True})

    def broken_session(*args):
        raise AttributeError("'dict' object has no attribute 'get_attribute'")

    monkeypatch.setattr(automatic, "run_session", broken_session)
    site = {"rank": "92", "domain": "skyscanner.de", "url": "https://www.skyscanner.de"}
    examination_id = automatic.examine_site(connection, run_id, site, {}, None)
    status, note = connection.execute("SELECT status, note FROM examination WHERE id = ?", (examination_id,)).fetchone()
    assert status == "aborted" and "AttributeError" in note


def test_ctrl_c_still_stops_the_run(conn, monkeypatch):
    connection, run_id = conn
    monkeypatch.setattr(automatic, "check_robots", lambda url: {"robots_allowed": True})

    def interrupted_session(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(automatic, "run_session", interrupted_session)
    with pytest.raises(KeyboardInterrupt):
        automatic.examine_site(connection, run_id, {"rank": "1", "domain": "a.de", "url": "https://www.a.de"}, {}, None)


def test_cookiewall_texts_skip_iframes_that_are_no_elements():
    from cookiewall import dialog_texts
    driver = FakeDriver([{}])
    driver.execute_script = lambda script: "Akzeptieren"
    assert dialog_texts(driver) == ["Akzeptieren"]
