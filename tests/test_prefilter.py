"""Block detection and funnel of the prefilter (offline)."""
from page import detect_block, read_ranked_domains
from prefilter import funnel


def test_block_by_status():
    assert detect_block(403, "Startseite", "") == "HTTP 403"
    assert detect_block(429, "", "") == "HTTP 429"


def test_block_by_text():
    assert detect_block(200, "Just a moment...", "") == "text: just a moment"
    assert detect_block(503, "Fehler", "Zugriff verweigert. Bitte später") == "text: zugriff verweigert"


def test_block_by_html_of_bot_manager():
    # mobile.de on 2026-10-29: status 200, empty title and text, Akamai challenge container
    html = '<html><head></head><body><script src="/cFGNAi1F7/x"></script><div id="sec-if-cpt-container">'
    assert detect_block(200, "", "", html) == "html: Akamai Bot Manager"


def test_empty_page_counts_as_block():
    assert detect_block(200, "", "  ", "<html><body></body></html>") == "no title and no visible text"


def test_cloudflare_script_on_normal_page_is_no_block():
    html = '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
    assert detect_block(200, "Startseite", "Willkommen", html) is None


def test_no_block():
    assert detect_block(200, "Nachrichten aus Berlin", "Politik Sport Kultur") is None
    assert detect_block(None, "Startseite", "Text") is None


def row(domain, protego, urllib, cookinspect, status=200, error=None, loaded=False, tcf=False,
        tcfapi=None, blocked=False):
    return {"domain": domain, "robots_status": status, "robots_error": error, "robots_allowed": protego,
            "robots_allowed_urllib": urllib, "robots_allowed_cookinspect": cookinspect,
            "loaded": loaded, "tcf": tcf, "tcfapi": tcf if tcfapi is None else tcfapi, "blocked": blocked}


def test_funnel_columns():
    rows = [
        row("a.de", True, True, True, loaded=True, tcf=True),
        row("b.de", True, True, True, loaded=True),
        row("google.de", True, False, False, loaded=True),          # urllib: "Disallow: /?"
        row("c.de", False, False, True, status=503),                 # 5xx: only Cookinspect allows
        row("d.de", True, True, True, status=404, loaded=False),     # load failed 3 times
        row("e.de", False, False, True, status=None, error="dns"),   # unreachable
        row("f.de", True, True, True, loaded=True, tcfapi=True),     # __tcfapi without ping answer
        row("g.de", True, True, True, loaded=True, blocked=True),
    ]
    result = funnel(rows)
    assert result["domains"] == 8
    assert result["robots_answered"] == 7
    protego, urllib, cookinspect = (result["columns"][n] for n in ("protego", "urllib", "cookinspect"))
    assert (protego["allowed"], protego["loaded"], protego["tcf"]) == (6, 5, 1)
    assert protego["load_failed"] == 1
    assert protego["blocked"] == 1
    assert protego["tcfapi_without_ping"] == 1
    assert protego["tcf_share_of_loaded"] == 20.0              # 1 of 5 loaded
    assert protego["tcf_share_of_loaded_not_blocked"] == 25.0  # 1 of 4 loaded and not blocked
    assert (urllib["allowed"], urllib["loaded"]) == (5, 4)
    # c.de is allowed by the original code, but not loaded, because Protego forbids it;
    # e.de is unreachable, so it does not count as allowed
    assert (cookinspect["allowed"], cookinspect["allowed_not_loaded_protego_forbids"], cookinspect["loaded"]) == (6, 1, 4)


def test_read_ranked_domains(tmp_path):
    csv_file = tmp_path / "list.csv"
    csv_file.write_text("rank,domain\n4,google.de\n9,amazon.de\n")
    assert read_ranked_domains(csv_file) == [("4", "google.de"), ("9", "amazon.de")]
    plain = tmp_path / "list.txt"
    plain.write_text("google.de\n# comment\namazon.de\n")
    assert read_ranked_domains(plain) == [("1", "google.de"), ("2", "amazon.de")]
