"""A real crawl is refused under a user not in CRAWL_USERS or with uncommitted changes; a test run is not."""
import getpass

import pytest

import config
import run_metadata


def clean(monkeypatch, dirty=False):
    monkeypatch.setattr(run_metadata, "git_commit", lambda: {"commit": "x", "branch": "b", "dirty": dirty})


def test_real_crawl_refused_without_crawl_users(monkeypatch):
    clean(monkeypatch)
    monkeypatch.setattr(config, "CRAWL_USERS", ())
    with pytest.raises(SystemExit, match="CRAWL_USERS"):
        run_metadata.check_environment(test_run=False)


def test_real_crawl_refused_when_dirty(monkeypatch):
    clean(monkeypatch, dirty=True)
    monkeypatch.setattr(config, "CRAWL_USERS", (getpass.getuser(),))
    with pytest.raises(SystemExit, match="uncommitted"):
        run_metadata.check_environment(test_run=False)


def test_real_crawl_allowed_when_clean_and_right_user(monkeypatch):
    clean(monkeypatch)
    monkeypatch.setattr(config, "CRAWL_USERS", ("someone-else", getpass.getuser()))
    assert run_metadata.check_environment(test_run=False)["run_as_crawl_user"] is True


def test_real_crawl_refused_under_other_user(monkeypatch):
    clean(monkeypatch)
    monkeypatch.setattr(config, "CRAWL_USERS", ("someone-else",))
    with pytest.raises(SystemExit, match="someone-else"):
        run_metadata.check_environment(test_run=False)


def test_test_run_under_other_user_only_warns(monkeypatch):
    clean(monkeypatch)
    monkeypatch.setattr(config, "CRAWL_USERS", ("someone-else",))
    assert run_metadata.check_environment(test_run=True)["run_as_crawl_user"] is False


def test_test_run_allowed_without_crawl_users_and_dirty(monkeypatch):
    clean(monkeypatch, dirty=True)
    monkeypatch.setattr(config, "CRAWL_USERS", ())
    assert run_metadata.check_environment(test_run=True)["run_as_crawl_user"] is False


def metadata(test_run, **changes):
    values = {"test_run": test_run, "machine": "arm64", "ip_country": "DE",
              "browser": {"browser_version": config.CHROME_VERSION, "chromedriver_version": config.CHROME_VERSION}}
    values.update(changes)
    return values


def test_setup_as_expected():
    assert run_metadata.check_setup(metadata(False)) is True


@pytest.mark.parametrize("changes, message", [
    ({"machine": "x86_64"}, "machine"),
    ({"ip_country": "FR"}, "ip_country"),
    ({"ip_country": None}, "ip_country"),
    ({"browser": {"browser_version": "157.0.1.1", "chromedriver_version": config.CHROME_VERSION}}, "browser_version"),
])
def test_real_crawl_refused_when_setup_differs(changes, message):
    with pytest.raises(SystemExit, match=message):
        run_metadata.check_setup(metadata(False, **changes))
    assert run_metadata.check_setup(metadata(True, **changes)) is False   # test run: only a warning
