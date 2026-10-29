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
