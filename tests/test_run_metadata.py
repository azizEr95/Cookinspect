"""A real crawl is refused without CRAWL_USER or with uncommitted changes; a test run is not."""
import getpass

import pytest

import config
import run_metadata


def clean(monkeypatch, dirty=False):
    monkeypatch.setattr(run_metadata, "git_commit", lambda: {"commit": "x", "branch": "b", "dirty": dirty})


def test_real_crawl_refused_without_crawl_user(monkeypatch):
    clean(monkeypatch)
    monkeypatch.setattr(config, "CRAWL_USER", None)
    with pytest.raises(SystemExit, match="CRAWL_USER"):
        run_metadata.check_environment(test_run=False)


def test_real_crawl_refused_when_dirty(monkeypatch):
    clean(monkeypatch, dirty=True)
    monkeypatch.setattr(config, "CRAWL_USER", getpass.getuser())
    with pytest.raises(SystemExit, match="uncommitted"):
        run_metadata.check_environment(test_run=False)


def test_real_crawl_allowed_when_clean_and_right_user(monkeypatch):
    clean(monkeypatch)
    monkeypatch.setattr(config, "CRAWL_USER", getpass.getuser())
    assert run_metadata.check_environment(test_run=False)["run_as_crawl_user"] is True


def test_real_crawl_refused_under_other_user(monkeypatch):
    clean(monkeypatch)
    monkeypatch.setattr(config, "CRAWL_USER", "someone-else")
    with pytest.raises(SystemExit, match="someone-else"):
        run_metadata.check_environment(test_run=False)


def test_test_run_under_other_user_only_warns(monkeypatch):
    clean(monkeypatch)
    monkeypatch.setattr(config, "CRAWL_USER", "someone-else")
    assert run_metadata.check_environment(test_run=True)["run_as_crawl_user"] is False


def test_test_run_allowed_without_crawl_user_and_dirty(monkeypatch):
    clean(monkeypatch, dirty=True)
    monkeypatch.setattr(config, "CRAWL_USER", None)
    assert run_metadata.check_environment(test_run=True)["run_as_crawl_user"] is False
