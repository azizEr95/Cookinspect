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
