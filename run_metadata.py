"""Records everything needed to reproduce a run (Demir et al.): date, location, versions,
configuration, website list and Git commit. Written as run_metadata.json into the output
directory of the run. Also checks the safe environment (own macOS user, fresh profile).

    venv/bin/python run_metadata.py     # setup check: prints the metadata of a run started now
"""
import getpass
import importlib.metadata
import json
import platform
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timezone

import config
from browser import browser_versions, start_chrome
from consent_lists import latest_cmp_list, latest_gvl
from decoder import DECODER_PACKAGE, decoder_version

IP_COUNTRY_URL = "https://ipinfo.io/country"


def git_commit():
    """Current commit and whether the working tree has uncommitted changes."""
    def git(*args):
        return subprocess.run(["git", *args], cwd=config.REPO_DIR, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(git("status", "--porcelain"))}


def ip_country():
    """Two-letter country code of the public IP of this machine, or None if the lookup fails."""
    try:
        with urllib.request.urlopen(IP_COUNTRY_URL, timeout=10) as response:
            return response.read().decode().strip() or None
    except Exception:
        return None


def package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def node_version():
    try:
        return subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        return None


def settings_from_config():
    return {name: (value if isinstance(value, (int, float, bool, type(None))) else str(value))
            for name, value in vars(config).items() if name.isupper()}


def check_environment(test_run):
    """Safe environment. A real crawl (not a test run) is refused when config.CRAWL_USER is not set,
    when it runs under another macOS user, or when the working tree has uncommitted changes
    (then the Git commit in the metadata would not describe the code that ran). A test run may
    run under any user, e.g. for development; the metadata record who ran it."""
    user = getpass.getuser()
    right_user = config.CRAWL_USER is not None and user == config.CRAWL_USER
    if not test_run:
        if config.CRAWL_USER is None:
            raise SystemExit("Real crawl refused: config.CRAWL_USER is not set. For a test, add --test.")
        if not right_user:
            raise SystemExit(f"Real crawl refused: run it as the macOS user '{config.CRAWL_USER}', not '{user}'.")
        if git_commit()["dirty"]:
            raise SystemExit("Real crawl refused: uncommitted changes in the repository. Commit first, or add --test.")
    elif not right_user:
        print(f"Warning: test run as '{user}', not as the crawl user ({config.CRAWL_USER}).")
    return {"os_user": user, "crawl_user": config.CRAWL_USER, "run_as_crawl_user": right_user}


def browser_metadata():
    """Starts the browser once to read its versions and checks that the profile is fresh."""
    driver = start_chrome()
    try:
        versions = browser_versions(driver)
    finally:
        driver.quit()
    profile = versions.pop("profile_dir") or ""
    versions["fresh_temporary_profile"] = profile.startswith(tempfile.gettempdir()) or "/T/" in profile
    versions["user_agent_matches_http_user_agent"] = versions["user_agent"] == config.HTTP_USER_AGENT
    return versions


def consent_lists_metadata():
    """Current GVL v3 and the CMP list snapshot of this run (kept under data/). Each TC string is
    evaluated later with the GVL version written in it; those versions are stored per string."""
    lists = {}
    for name, fetch in (("gvl_latest", latest_gvl), ("cmp_list", lambda: latest_cmp_list()[1])):
        try:
            lists[name] = fetch()
        except Exception as error:
            lists[name] = {"error": f"{type(error).__name__}: {error}"}
    return lists


def check_setup(metadata):
    """A real crawl (not a test run) is refused when Chrome, chromedriver, the architecture or
    the IP country do not match config. A test run only prints the differences."""
    expected = {
        "browser.browser_version": (metadata["browser"]["browser_version"], config.CHROME_VERSION),
        "browser.chromedriver_version": (metadata["browser"]["chromedriver_version"], config.CHROME_VERSION),
        "machine": (metadata["machine"], config.EXPECTED_MACHINE),
        "ip_country": (metadata["ip_country"], config.EXPECTED_IP_COUNTRY),
    }
    problems = [f"{name} is {actual!r}, expected {wanted!r}" for name, (actual, wanted) in expected.items()
                if actual != wanted]
    if problems and not metadata["test_run"]:
        raise SystemExit("Real crawl refused: " + "; ".join(problems))
    for problem in problems:
        print(f"Warning (test run): {problem}")
    return not problems


def new_metadata(mode, test_run, **extra):
    """Checks the environment first, so that a refused run starts no browser; then the setup."""
    environment = check_environment(test_run)
    metadata = {
        "mode": mode,
        "test_run": test_run,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ip_country": ip_country(),
        "environment": environment,
        "git": git_commit(),
        "browser": browser_metadata(),
        "python_version": platform.python_version(),
        "packages": {name: package_version(name) for name in ("selenium", "protego", "tldextract")},
        "node_version": node_version(),
        "decoder": {"package": DECODER_PACKAGE, "version": decoder_version()},
        "consent_lists": consent_lists_metadata(),
        "hostname": platform.node(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "config": settings_from_config(),
        **extra,
    }
    metadata["setup_as_expected"] = check_setup(metadata)
    return metadata


def write_metadata(metadata, output_dir):
    path = output_dir / "run_metadata.json"
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))
    return path


if __name__ == "__main__":
    print(json.dumps(new_metadata("setup-check", test_run=True), indent=2, ensure_ascii=False))
