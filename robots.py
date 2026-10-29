"""robots.txt: may the start page of a site be crawled? Respected in every mode, there is no way
to bypass it.

The decision comes from Protego (RFC 9309). For the comparison with Matte et al. (2020), two more
decisions are stored for the same response:
- urllib: what Python's urllib.robotparser decides (Matte et al. used it)
- cookinspect: what the original Cookinspect code decided; its own read() treats every status
  >= 400 as "everything allowed" (cookinspect.py:96-98 at 948a85f), also 5xx, and an unknown
  fetch error as allowed as well
"""
import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urljoin

from protego import Protego

import config


def fetch_robots(robots_url):
    """Returns (status, content); status is None if robots.txt could not be fetched at all."""
    request = urllib.request.Request(robots_url, headers={"User-Agent": config.HTTP_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=config.HTTP_TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:   # the server answered, but with an error status
        return error.code, None
    except Exception:                         # no answer: DNS, TLS, timeout, connection refused
        return None, None


def protego_decision(status, content, page_url):
    """RFC 9309: a 4xx robots.txt allows everything, a 5xx or unreachable one disallows everything."""
    if status is None or status >= 500:
        return False
    if status >= 400:
        return True
    return Protego.parse(content).can_fetch(page_url, config.ROBOTS_USER_AGENT)


def urllib_decision(status, content, page_url):
    """What Python's urllib.robotparser decides for the same response, following
    RobotFileParser.read(): 401/403 disallow everything, other 4xx allow everything, 5xx or
    no response disallow. Its parser has no wildcards, uses the first instead of the longest
    match, and turns "Disallow: /?" into "Disallow: /"."""
    if status is None or status >= 500 or status in (401, 403):
        return False
    if status >= 400:
        return True
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(content.splitlines())
    return parser.can_fetch(config.ROBOTS_USER_AGENT, page_url)


def cookinspect_decision(status, content, page_url):
    """What the original Cookinspect decided: 401/403 disallow everything, every other status
    >= 400 (also 5xx) allows everything, no response counts as allowed ("Let's assume access is
    not refused"). Cookinspect first retried over HTTP and without www; those retries belong to
    the reachability check of the prefilter."""
    if status in (401, 403):
        return False
    if status is None or status >= 400:
        return True
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(content.splitlines())
    return parser.can_fetch(config.ROBOTS_USER_AGENT, page_url)


def check_robots(page_url):
    robots_url = urljoin(page_url, "/robots.txt")
    status, content = fetch_robots(robots_url)
    return {
        "robots_url": robots_url,
        "robots_status": status,
        "robots_allowed": protego_decision(status, content, page_url),
        "robots_allowed_urllib": urllib_decision(status, content, page_url),
        "robots_allowed_cookinspect": cookinspect_decision(status, content, page_url),
    }
