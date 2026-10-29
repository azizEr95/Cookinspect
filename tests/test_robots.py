"""robots.txt decisions (offline): Protego (RFC 9309), urllib.robotparser and the original Cookinspect."""
from robots import cookinspect_decision, protego_decision, urllib_decision

PAGE = "https://www.example.de/"


def decisions(status, content=None):
    return (protego_decision(status, content, PAGE), urllib_decision(status, content, PAGE),
            cookinspect_decision(status, content, PAGE))


def test_allow_everything():
    assert decisions(200, "User-agent: *\nDisallow:\n") == (True, True, True)


def test_disallow_everything():
    assert decisions(200, "User-agent: *\nDisallow: /\n") == (False, False, False)


def test_404_allows_everything():
    assert decisions(404) == (True, True, True)


def test_403_disallows_everything_except_in_rfc_9309():
    # RFC 9309: every 4xx means "no robots.txt", so everything is allowed
    assert decisions(403) == (True, False, False)


def test_5xx_disallows_except_in_original_cookinspect():
    assert decisions(503) == (False, False, True)


def test_unreachable_disallows_except_in_original_cookinspect():
    assert decisions(None) == (False, False, True)


def test_longest_match_wins_only_in_protego():
    # Allow: /$ is the longer (more specific) rule for the start page; urllib takes the first match
    # and knows no "$"
    content = "User-agent: *\nDisallow: /\nAllow: /$\n"
    assert decisions(200, content) == (True, False, False)


def test_disallow_query_is_not_disallow_all():
    # urllib.robotparser turns "Disallow: /?" into "Disallow: /"
    content = "User-agent: *\nDisallow: /?\n"
    assert decisions(200, content) == (True, False, False)


def test_rules_for_other_agents_do_not_apply():
    content = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    assert decisions(200, content) == (True, True, True)


def test_google_de_disallow_query_blocks_start_page_only_in_urllib():
    # Excerpt of https://www.google.de/robots.txt (fetched 2026-10-29): "Disallow: /?" becomes
    # "Disallow: /" in urllib.robotparser and is the first rule matching the start page
    content = ("User-agent: *\nUser-agent: Yandex\nDisallow: /search\nAllow: /search/about\n"
               "Disallow: /index.html?\nDisallow: /?\nDisallow: /goto?\nAllow: /?hl=\n")
    assert decisions(200, content) == (True, False, False)


# Reachability with the fallbacks of Matte et al. (2020), p. 5

import socket
import ssl
import urllib.error

import robots


def fake_fetch(answers):
    """fetch_robots replacement: answers maps a robots.txt URL to (status, content, error)."""
    calls = []

    def fetch(url):
        calls.append(url)
        return answers.get(url, (None, None, "other"))
    return fetch, calls


def test_https_www_answers(monkeypatch):
    fetch, calls = fake_fetch({"https://www.example.de/robots.txt": (200, "", None)})
    monkeypatch.setattr(robots, "fetch_robots", fetch)
    assert robots.find_robots("example.de")[:2] == ("https://www.example.de", 200)
    assert calls == ["https://www.example.de/robots.txt"]


def test_network_error_moves_to_http(monkeypatch):
    fetch, calls = fake_fetch({"https://www.example.de/robots.txt": (None, None, "network"),
                               "http://www.example.de/robots.txt": (200, "", None)})
    monkeypatch.setattr(robots, "fetch_robots", fetch)
    assert robots.find_robots("example.de")[:2] == ("http://www.example.de", 200)


def test_dns_error_removes_www(monkeypatch):
    fetch, calls = fake_fetch({"https://www.example.de/robots.txt": (None, None, "dns"),
                               "https://example.de/robots.txt": (404, None, None)})
    monkeypatch.setattr(robots, "fetch_robots", fetch)
    assert robots.find_robots("example.de")[:2] == ("https://example.de", 404)


def test_dns_then_network_error_tries_all_three(monkeypatch):
    fetch, calls = fake_fetch({"https://www.example.de/robots.txt": (None, None, "dns"),
                               "https://example.de/robots.txt": (None, None, "network"),
                               "http://example.de/robots.txt": (None, None, "network")})
    monkeypatch.setattr(robots, "fetch_robots", fetch)
    main_page_url, status, content, error, attempts = robots.find_robots("example.de")
    assert (main_page_url, status, error) == ("http://example.de", None, "network")
    assert len(attempts) == 3


def test_other_error_is_not_retried(monkeypatch):
    fetch, calls = fake_fetch({})
    monkeypatch.setattr(robots, "fetch_robots", fetch)
    assert robots.find_robots("example.de")[3] == "other"
    assert len(calls) == 1


def test_error_kinds():
    assert robots.error_kind(urllib.error.URLError(socket.gaierror(8, "nodename nor servname"))) == "dns"
    assert robots.error_kind(urllib.error.URLError(TimeoutError("timed out"))) == "network"
    assert robots.error_kind(urllib.error.URLError(ssl.SSLCertVerificationError("expired"))) == "network"
    assert robots.error_kind(urllib.error.URLError(ConnectionRefusedError(61, "refused"))) == "network"
    assert robots.error_kind(ConnectionResetError()) == "network"
    assert robots.error_kind(ValueError("odd redirect")) == "other"
