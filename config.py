"""Settings of the Cookinspect reimplementation (TCF v2.2/v2.3). Every value here is written into the
run metadata, so that a run can be reproduced."""
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
DATA_DIR = REPO_DIR / "data"            # crawl results, downloaded GVL and CMP list (not committed)
DECODE_DIR = REPO_DIR / "decode"        # Node project with @iabtechlabtcf/core (version pinned there)
DATABASE_PATH = DATA_DIR / "cookinspect.sqlite"   # one file per person and Mac; merge_databases.py merges them

# Browser: Chrome for Testing, downloaded by Selenium Manager into ~/.cache/selenium.
# Pinned so that every run uses the same browser. The browser must always be started with
# options.browser_version = CHROME_VERSION: without it, Selenium Manager would pick an installed
# Google Chrome or the latest release. Browser and chromedriver versions go into the run metadata.
CHROME_VERSION = "156.0.8078.73"        # Stable channel on 2026-10-28, mac-arm64
HEADLESS = False                        # visible window in all modes (also -a)
ACCEPT_LANGUAGES = "de-DE,de"           # German users
WINDOW_SIZE = (1366, 768)               # as in Cookinspect (most common display in 2019)

# Safe environment: crawls run under their own macOS user, with a fresh browser profile per
# session and no logins. When CRAWL_USER is set, the scripts refuse to run under any other user.
CRAWL_USER = None                       # e.g. "crawler"; None = not checked (a warning is printed)

# HTTP requests outside the browser (robots.txt, reachability) use the user agent of the browser,
# so that both see the same site. The browser's own user agent is not changed (no tricks against
# bot detection); run_metadata.py compares the two and records a mismatch.
HTTP_USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")
HTTP_TIMEOUT = 10                       # seconds, as Cookinspect for robots.txt
ROBOTS_USER_AGENT = "*"                 # robots.txt rules are evaluated for this agent
PAUSE_BETWEEN_DOMAINS = 2               # seconds of pause between two domains (run_list.py and prefilter.py);
                                        # within a domain, requests follow one another as in Cookinspect

# Waiting times and timeouts from Matte et al. (2020), Section IV-A and V
PAGE_LOAD_TIMEOUT = 10                  # seconds per attempt
MAX_TRIES_TIMEOUT = 3                   # attempts before a site counts as unreachable
SLEEP_TIME_CMP_WAIT = 3                 # seconds after the load event before looking for the CMP
TCF_PING_TIMEOUT = 3                    # seconds to wait for the answer to __tcfapi('ping') (prefilter)
SLEEP_TIME_REFRESH = 3                  # seconds between the decision and the reload
USERACTIONCOMPLETE_TIMEOUT = 10         # seconds to wait for eventStatus useractioncomplete;
                                        # afterwards "no useractioncomplete" is stored and the signal read anyway

# Semi-automatic mode
MAX_BANNER_RELOADS = 3                  # reload up to 3 times when no banner appears (Appendix D)
SEMI_AUTOMATIC_LIMIT = None             # optional upper bound of sites for the semi-automatic part, for tests;
                                        # None (default) = all TCF sites of the selected domains, as Matte did

# Capture (capture.py)
MAX_BODY_SIZE = 1_000_000               # bytes per request body kept by the BiDi data collector;
                                        # larger bodies are marked "too_large" (docs/abweichungen.md)
TCF_LISTENER_WAIT = 30                  # seconds the preload script waits for __tcfapi in each document
CHANNEL_2_WAIT = 2                      # seconds to wait for answers of the CMP to __tcfapiCall (channel 2)
CHANNEL_2_MAX_FRAMES = 5                # third-party iframes tried at most for channel 2
