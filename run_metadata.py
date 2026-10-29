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

IP_COUNTRY_URL = "https://ipinfo.io/country"
DECODER_PACKAGE = "@iabtechlabtcf/core"


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


def decoder_version():
    """Installed version of the TC string decoder (pinned in decode/package.json)."""
    package_json = config.DECODE_DIR / "node_modules" / DECODER_PACKAGE / "package.json"
    if not package_json.exists():
        return None
    return json.loads(package_json.read_text())["version"]


def node_version():
    try:
        return subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        return None


def settings_from_config():
    return {name: (value if isinstance(value, (int, float, bool, type(None))) else str(value))
            for name, value in vars(config).items() if name.isupper()}


def check_environment():
    """Safe environment: refuses to run under another user than config.CRAWL_USER (if set)."""
    user = getpass.getuser()
    if config.CRAWL_USER is not None and user != config.CRAWL_USER:
        raise SystemExit(f"Run this under the macOS user '{config.CRAWL_USER}', not '{user}' (config.CRAWL_USER).")
    if config.CRAWL_USER is None:
        print("Warning: config.CRAWL_USER is not set, so the own crawl user is not checked.")
    return {"os_user": user, "crawl_user_checked": config.CRAWL_USER is not None}


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


def new_metadata(mode, **extra):
    return {
        "mode": mode,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ip_country": ip_country(),
        "environment": check_environment(),
        "git": git_commit(),
        "browser": browser_metadata(),
        "python_version": platform.python_version(),
        "packages": {name: package_version(name) for name in ("selenium", "protego", "tldextract")},
        "node_version": node_version(),
        "decoder": {"package": DECODER_PACKAGE, "version": decoder_version()},
        "platform": platform.platform(),
        "machine": platform.machine(),
        "config": settings_from_config(),
        **extra,
    }


def write_metadata(metadata, output_dir):
    path = output_dir / "run_metadata.json"
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))
    return path


if __name__ == "__main__":
    print(json.dumps(new_metadata("setup-check"), indent=2, ensure_ascii=False))
