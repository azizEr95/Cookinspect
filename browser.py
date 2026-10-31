"""Starts Chrome for Testing in the pinned version, with WebDriver BiDi enabled (see
docs/entscheidungen.md, E1). Every call gets a fresh, temporary profile from chromedriver:
no --user-data-dir is passed, so no cookies, logins or history are carried over.

    venv/bin/python browser.py     # setup check: starts the browser and prints its versions
"""
import json

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.selenium_manager import SeleniumManager

import config


def pinned_paths():
    """Chrome for Testing and chromedriver, both in config.CHROME_VERSION. Without the driver
    version Selenium Manager takes the newest chromedriver of the milestone (e.g. .80 for .73)."""
    paths = SeleniumManager().binary_paths(["--browser", "chrome", "--browser-version", config.CHROME_VERSION,
                                            "--driver-version", config.CHROME_VERSION])
    return paths["browser_path"], paths["driver_path"]


def start_chrome():
    browser_path, driver_path = pinned_paths()
    options = webdriver.ChromeOptions()
    options.binary_location = browser_path
    options.enable_bidi = True
    if config.HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument(f"--lang={config.ACCEPT_LANGUAGES.split(',')[0]}")
    options.add_experimental_option("prefs", {"intl.accept_languages": config.ACCEPT_LANGUAGES})
    driver = webdriver.Chrome(options=options, service=Service(executable_path=driver_path))
    driver.set_window_size(*config.WINDOW_SIZE)
    driver.set_page_load_timeout(config.PAGE_LOAD_TIMEOUT)
    check_versions(driver)
    return driver


def browser_versions(driver):
    capabilities = driver.capabilities
    return {
        "browser_name": capabilities.get("browserName"),
        "browser_version": capabilities.get("browserVersion"),
        "chromedriver_version": capabilities.get("chrome", {}).get("chromedriverVersion", "").split(" ")[0],
        "profile_dir": capabilities.get("chrome", {}).get("userDataDir"),
        "user_agent": driver.execute_script("return navigator.userAgent"),
    }


def check_versions(driver):
    """Stops if the browser is not the pinned Chrome for Testing."""
    version = driver.capabilities.get("browserVersion")
    if version != config.CHROME_VERSION:
        driver.quit()
        raise RuntimeError(f"Chrome {version} started, but config.CHROME_VERSION is {config.CHROME_VERSION}")


if __name__ == "__main__":
    driver = start_chrome()
    try:
        print(json.dumps(browser_versions(driver), indent=2))
    finally:
        driver.quit()
