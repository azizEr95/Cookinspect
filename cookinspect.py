#!/usr/bin/env python
# -*- coding: utf-8 -*-

# dependencies:
# python-tldextract
# python-selenium
# python-sqlalchemy
# python-publicsuffix2 (AUR)

import sys
import datetime
import time
import argparse
from urllib.parse import urlparse
import pickle
import os

from selenium.common.exceptions import *

import config
from browser import start_chrome
from robots import check_robots
from utils import *
from iab_data_collection import *
from database import *

########### GLOBAL VARs
db = None
args = None

########### FUNCTIONS

def parse_command_line():
    global args
    parser = argparse.ArgumentParser(description="Perform tests on websites implementing IAB Europe's Transparency and Consent Framework (TCF) to find possible/manifest violations of the GDPR or the TCF itself.")
    parser.add_argument('url', help='Target website')
    group_main = parser.add_argument_group('Main options')
    group_main.add_argument('-a', '--automatic-violations-check', action='store_const', const=True, help='Perform automatic checks of possible violations through multiple tests on target website.')
    group_main.add_argument('-s', '--semi-automatic-violations-check', action='store_const', const=True, help='Perform semi-automatic checks of possible violations through multiple tests on target website.')
    group_main.add_argument('-f', '--full-violations-check', action='store_const', const=True, help='Check all possible violations through multiple tests on target website (perform automatic and semi-automatic tests).')
    group_main.add_argument('-t', '--test-cmp', action='store_const', const=True, help=' [default behaviour] Only test if the target website contains a CMP.')
    group_main.add_argument('-d', '--dump', action='store_const', const=True, help='Display previous results on target domain.')
    group_main.add_argument('-a2', '--automatic-violations-check-full', action='store_const', const=True, help='Version of --automatic-violations-check used for the paper\'s crawl (performs more tests).')

    other = parser.add_argument_group('Other options')
    other.add_argument('--no-fetch', action='store_const', const=True, help='Do not fetch any page: just open the browser (useful for debugging)')
    other.add_argument('--accept-button', help='Class name of the accept button of the banner')
    other.add_argument('--new-only', action='store_const', const=True, help='Ignore website if already present in the database.')
    other.add_argument('--retry', action='store_const', const=True, help='Retry website for which access was not successful (in combination with --new-only).')

    args = parser.parse_args()
    return args

def get_main_page(url):
    parsed_url = urlparse(url)
    main_page_url = "%s://%s" % (parsed_url.scheme, parsed_url.netloc)
    return main_page_url

def robots_txt_allows(website):
    """robots.txt is checked once per run and respected in every mode (robots.py).
    The decisions of urllib.robotparser and of the original Cookinspect are printed for comparison."""
    if getattr(website, "robots_checked_this_run", False):
        return not website.robot_txt_ban
    print("Checking robots.txt...")
    result = check_robots(website.main_page_url)
    website.robots_checked_this_run = True
    website.robot_txt_ban = not result["robots_allowed"]
    print("robots.txt: status %s, allowed: %s (urllib: %s, original Cookinspect: %s)"
          % (result["robots_status"], result["robots_allowed"], result["robots_allowed_urllib"],
             result["robots_allowed_cookinspect"]))
    if website.robot_txt_ban:
        print("Access refused in robots.txt file.")
    return result["robots_allowed"]

def start_browser_and_fetch(website, args):
    # returns None if access is not allowed in robots.txt or the site cannot be loaded
    if not robots_txt_allows(website):
        return None
    browser = start_chrome()   # pinned Chrome for Testing, fresh profile, visible window
    if args.no_fetch:
        time.sleep(3600)
    for i in range(config.MAX_TRIES_TIMEOUT):
        try:
            browser.get(website.main_page_url)
            return browser
        except TimeoutException:
            print("Website timed out.")
        except WebDriverException:
            print("WebDriver Error.")
    quit_properly(browser)
    website.access_successful = False
    return None

def start_new_browser_and_fetch(website, args):
    # Each session gets a new browser with a fresh profile. The browser extensions of the
    # original Cookinspect are gone (Manifest V2); their channels move to WebDriver BiDi in phase 3.
    return start_browser_and_fetch(website, args)

def get_website(domain, db):
    website = db.query(Website).filter_by(domain=domain).scalar()
    if website and website.pickled_consent_strings is not None:
        website.seen_consent_strings = pickle.loads(website.pickled_consent_strings)
    if website and website.pickled_consent_strings_v2 is not None:
        website.seen_consent_strings_v2 = pickle.loads(website.pickled_consent_strings_v2)
    return website

def create_website_or_return_existing_one(url):
    domain = get_domain(url, subdomain=True)
    website = get_website(domain, db)
    new = True
    if website is None:
        website = Website(domain)
        website.main_page_url = get_main_page(args.url)
    else:
        print("Website already existing, loading previous data (domain: %s)..." % website.main_page_url)
        last_visited = datetime.datetime.now()
        website.last_visited = last_visited
        new = False
    return (website, new)

def init_violations_check():
    print("\n--- Crawling %s ---\n" % args.url)
    website, new = create_website_or_return_existing_one(args.url)
    if new:
        db.add(website)
    elif args.new_only:
        if args.retry and website.access_successful == False:
            print("Retrying website present in database, for which access was not successful.")
            website.robot_txt_ban = None
            website.access_successful = None
        else:
            print("Website already present in database. Exiting.")
            sys.exit(0)
    return website

def last_checks(website, semi_automatic=False):
    if not semi_automatic:
        last_checks_consent_strings(website)
    store_consent_strings(website)
    website.pickled_consent_strings = pickle.dumps(website.seen_consent_strings)
    website.pickled_consent_strings_v2 = pickle.dumps(website.seen_consent_strings_v2)
    if semi_automatic and len(website.consent_strings) == 0:
        # still nothing found
        # Test case: ebay.fr
        website.nothing_found_after_manual_validation = True

def last_checks_consent_strings(website):
    # Check that all consent strings are the same
    # Test cases:
    # - Positive: todo
    # - Negative: lepoint.fr
    all_strings = website.seen_consent_strings["postmessage"] | website.seen_consent_strings["GET"] | website.seen_consent_strings["POST"] | website.seen_consent_strings["cookie"]
    all_strings_v2 = website.seen_consent_strings_v2["postmessage"] | website.seen_consent_strings_v2["GET"] | website.seen_consent_strings_v2["POST"] | website.seen_consent_strings_v2["cookie"]
    if len(all_strings) > 1 or len(all_strings_v2) > 1:
        print("Found several consent strings", all_strings)
        website.different_consent_strings = True
    else:
        website.different_consent_strings = False

def store_consent_strings(website):
    for origin in website.seen_consent_strings:
        for consent_string in website.seen_consent_strings[origin]:
            if len(consent_string) > 256:
                print("Issue: consent string longer than 256 characters: %s" % consent_string)
                # Example: virgilio.it
            else:
                website.consent_strings = set(website.consent_strings).union(set([consent_string]))
    # TCFv2
    for origin in website.seen_consent_strings_v2:
        for consent_string in website.seen_consent_strings_v2[origin]:
            website.consent_strings_v2 = set(website.consent_strings_v2).union(set([consent_string]))

def full_violations_check(website):
    ok = automatic_violations_check(website)
    if ok:
        semi_automatic_violations_check(website)

def test_if_website_uses_cmp_only(website):
    browser = start_new_browser_and_fetch(website, args)
    if browser is None:
        return False
    if website.access_successful == False:
        print("Access not successful")
        return False
    print("Checking presence of __cmp()...")
    # Wait for __cmp to be loaded
    time.sleep(SLEEP_TIME_CMP_WAIT)
    uses_cmp = verify___cmp_exists(browser, website)
    print("Checking presence of __tcfapi()...")
    website.tcfv2 = verify___tcfapi_exists(browser, website)
    website.iab_banner = uses_cmp
    if (uses_cmp):
        print("__cmp() found.")
    if (website.tcfv2):
        print("__tcfapi() found.")
    quit_properly(browser)

def automatic_violations_check_full(website):
    # Corresponds to the version of automatic_violations_check() used for the
    # paper's crawl. Includes many tests that are useless for the regular
    # crawls, so this is removed from the default
    browser = start_new_browser_and_fetch(website, args)
    if browser is None:
        return False
    if website.access_successful == False:
        print("Access not successful")
        return False
    print("Checking presence of __cmp()...")
    # Wait for __cmp to be loaded
    time.sleep(SLEEP_TIME_CMP_WAIT)
    uses_cmp = verify___cmp_exists(browser, website)
    website.iab_banner = uses_cmp
    print("Checking presence of the __cmpLocator iframe...")
    cmplocator_found = verify___cmplocator_exists(browser, website)
    if cmplocator_found:
        website.iab_banner_cmplocator = True
    tcfapilocator_found = verify___tcfapilocator_exists(browser, website)
    if tcfapilocator_found:
        website.iab_banner_tcfapilocator = True
    print("Checking presence of __tcfapi()...")
    website.tcfv2 = verify___tcfapi_exists(browser, website)
    if not uses_cmp and not website.tcfv2:
        quit_properly(browser)
        return False
    website.cmp_code = get___cmp_code(browser)
    print("Starting automatic checks...")
    automatic_violations_check_no_extension(browser, website, args) # automatic, without extension
    quit_properly(browser)
    print("Checking shared consent...")
    browser = start_new_browser_and_fetch(website, args)
    if browser is None:
        return False
    if uses_cmp:
        check_violation_shared_consent(browser, website, args)
    if website.tcfv2:
        check_violation_shared_consent(browser, website, args, v2=True)
    quit_properly(browser)
    print("Checking vendors...")
    browser = start_new_browser_and_fetch(website, args)
    if browser is None:
        return False
    # we need to gather domains verifying consent through direct call for checking
    # violations 1 and 3 later
    domains_direct = vendors_violations_check(browser, website, args) # automatic, with override_cmp extension
    quit_properly(browser)
    print("Checking vendors (postMessages, GET and POST data)...")
    browser = start_new_browser_and_fetch(website, args)
    if browser is None:
        return False
    website.current_state = BEFORE_ACTION
    # adds domains checking and not checking consent to domains
    vendors_passive_violations_check(browser, website, domains_direct) # automatic, with monitor_postmessages and watch_requests extension
    quit_properly(browser)
    return True

def automatic_violations_check(website):
    website.current_state = BEFORE_ACTION
    browser = start_new_browser_and_fetch(website, args)
    if browser is None:
        return False
    if website.access_successful == False:
        print("Access not successful")
        return False
    print("Checking presence of __cmp()...")
    # Wait for __cmp to be loaded
    time.sleep(SLEEP_TIME_CMP_WAIT)
    tcfv1 = verify___cmp_exists(browser, website)
    website.iab_banner = tcfv1
    print("Checking presence of the __cmpLocator iframe...")
    cmplocator_found = verify___cmplocator_exists(browser, website)
    if cmplocator_found:
        website.iab_banner_cmplocator = True
    tcfapilocator_found = verify___tcfapilocator_exists(browser, website)
    if tcfapilocator_found:
        website.iab_banner_tcfapilocator = True
    print("Checking presence of __tcfapi()...")
    tcfv2 = verify___tcfapi_exists(browser, website)
    website.tcfv2 = tcfv2
    if not tcfv1 and not tcfv2:
        quit_properly(browser)
        return False
    if tcfv1:
        website.cmp_code = get___cmp_code(browser)
    if tcfv2:
        website.tcfapi_code = get___tcfapi_code(browser)
    print("Starting automatic checks...")
    automatic_violations_check_no_extension(browser, website, args) # automatic, without extension
    # adds domains checking and not checking consent to domains
    if website.tcfv2:
        vendors_passive_violations_check(browser, website, {"direct": set()}, v2=True) # automatic, with monitor_post
    if website.iab_banner: # might bug if tcfv2 was done before because get_through_logs_for_violations() must read logs all at once
        vendors_passive_violations_check(browser, website, {"direct": set()}) # automatic, with monitor_postmessages and watch_requests extension messages and watch_requests extension
    quit_properly(browser)
    return True

def semi_automatic_violations_check(website):
    # robots.txt is checked again in this run when the browser starts (start_browser_and_fetch)
    if not robots_txt_allows(website):
        return
    website.semi_automatic_done = True
    print("Checking other violations. Please refuse all consent on banner in the browser that's going to open, then press enter on this script. If the banner presents no option to refuse consent, accept all, then enter 'n'. If at least one of the purposes are pre-ticked, enter 'p'. If no banner appears, enter 'b'. If banner is broken (e.g. you can't click on the accept button), enter 'x'.")
    browser = start_new_browser_and_fetch(website, args)
    if browser is None:
        return False
    #os.system("mpv ding.mp3 >/dev/null 2>/dev/null &")
    #print("\a")
    headful_violations_check(browser, website, args, refusal=True)
    # reload same website to check post-reload consent
    browser.refresh()
    time.sleep(SLEEP_TIME_REFRESH)
    if not (website.violation_no_option or website.violation_no_banner or website.violation_broken_banner):
        print("Reloading website")
        website.current_state = AFTER_REFUSAL
        # if user can't refuse consent, the "non-respect of decision" violation has no meaning
        # adds domains checking consent to domains
        if website.tcfv2:
            post_reload_violations_check(browser, website, v2=True)
        if website.iab_banner:
            post_reload_violations_check(browser, website)
    quit_properly(browser)
    if website.violation_no_option or website.violation_no_banner or website.violation_broken_banner:
        # nothing left to do
        return
    # consent string was not found: we have to try to get consent string by accepting tracking
    # in case of the "no option" violation, we already made that check
    # Test case: kayak.fr (todo: find a better one: still does not work the second time)
    print("Please validate tracking this time.")
    website.current_state = AFTER_ACCEPTANCE
    browser = start_new_browser_and_fetch(website, args)
    if browser is None:
        return False
    #os.system("mpv msn.mp3 >/dev/null 2>/dev/null &")
    #print("\a")
    headful_violations_check(browser, website, args, refusal=False)
    if website.shared_cookie_set_acceptance and not website.shared_cookie_set_refusal:
        print("*********** VIOLATION: Shared cookie only set upon acceptance! ****************")
    # getting trackers post-refresh
    browser.refresh()
    time.sleep(SLEEP_TIME_REFRESH)
    seen_consent_strings = {"direct": set(), "postmessage": set(), "GET": set(), "POST": set(), "cookie": set()}
    (all_domains, domains_other) = get_through_logs_for_violations(browser, website, seen_consent_strings)
    for origin in seen_consent_strings:
        for consent_string in seen_consent_strings[origin]:
            consent_string_violations(website, consent_string, origin=origin, before_user_action=False, tracking_accepted=True)
    add_trackers(website, all_domains)
    quit_properly(browser)

def x(violation):
    if violation:
        if violation == 2:
            return "x"
        else:
            return "X"
    else:
        return " "

def xa(violation):
    if violation is None:
        return " "
    if len(violation) > 0:
        return "X"
    else:
        return " "

def dump_website(website):
    print("********** Domain: %s **********" % website.domain)
    print("Last visited: %s" % website.last_visited)
    if website.access_successful == False:
        print("Access not successful.")
        return
    if website.robot_txt_ban:
        print("Access refused by robots.txt.")
        if not args.dump:
            return
    if website.iab_banner == False and website.tcfv2 == False:
        print("Website does not use a TCF-related banner.")
        return
    if website.tcfv2:
        print("TCF v2 API found.")
    else:
        print("TCF v2 API not found.")
    mess = ""
    if website.cmpid is None:
        print("Consent string not found.")
    else:
        CMP = import_iab_cmp_list()
        if website.cmpid is not None and website.cmpid in CMP:
            mess = " (%s)" % CMP[website.cmpid]
        else:
            mess = " (incorrect)"
        print("CMP ID: %s%s" % (website.cmpid, mess))
    if website.different_consent_strings:
        print("Different consent strings found.")
    if website.different_cmpids:
        print("Different CMP ids found.")
    if website.shared_cookie_set:
        print("Shared cookie set.")
        if website.shared_cookie_set_refusal:
            print("Shared cookie set upon refusal.")
            if website.shared_cookie_set_acceptance:
                print("Shared cookie set upon acceptance.")
    print("*** Violations:")
    print("+-------------------------------------------+")
    print("| Violation / Behaviour           | DMGPC A |")
    print("|-------------------------------------------|")
    print("| Consent stored before choice    | %s%s%s%s%s   |" % (x(website.violation_consent_set_before_user_action_direct),
                                                             x(website.violation_consent_set_before_user_action_postmessage),
                                                             x(website.violation_consent_set_before_user_action_get),
                                                             x(website.violation_consent_set_before_user_action_post),
                                                             x(website.violation_consent_set_before_user_action_cookie)))
    print("| No way to opt out               |       %s |" % x(website.violation_no_option))
    print("| No banner                       |       %s |" % x(website.violation_no_banner))
    print("| Broken banner                   |       %s |" % x(website.violation_broken_banner))
    print("| Pre-selected choices            |       %s |" % x(website.violation_preticked))
    print("| Non-respect of choice           | %s%s%s%s%s   |" % (x(website.violation_consent_set_active_refusal_direct),
                                                                x(website.violation_consent_set_active_refusal_postmessage),
                                                                x(website.violation_consent_set_active_refusal_get),
                                                                x(website.violation_consent_set_active_refusal_post),
                                                                x(website.violation_consent_set_active_refusal_cookie)))
    print("| Shared Consent                  |       %s |" % x(website.violation_shared_cookie))
    #print("| Consent to non-existent vendors |       %s |" % x(website.violation_unregistered_vendors_in_consent_string))
    print("| Wrong CMP id                    |       %s |" % x(website.violation_incorrect_cmpid))
    #print("| Vendors case 1                  |       %s |" % xa(website.violation_vendor_1))
    #print("| Vendors case 2                  | %s%s%s%s    |" % (xa(website.violation_vendor_2_direct),
    #                                                            xa(website.violation_vendor_2_postmessage),
    #                                                            xa(website.violation_vendor_2_get),
    #                                                            xa(website.violation_vendor_2_post)))
    #print("| Vendors case 3                  |       %s |" % xa(website.violation_vendor_3))
    #print("| Vendors case 4                  | %s%s%s%s    |" % (xa(website.violation_vendor_4_direct),
    #                                                            xa(website.violation_vendor_4_postmessage),
    #                                                            xa(website.violation_vendor_4_get),
    #                                                            xa(website.violation_vendor_4_post)))
    print("+-------------------------------------------+")
    if len(website.consent_strings) > 0 or len(website.consent_strings_v2) > 0:
        print("Consent strings:")
        for origin in website.seen_consent_strings:
            if len(website.seen_consent_strings[origin]) > 0:
                print("%s:" % origin)
                for consent_string in website.seen_consent_strings[origin]:
                    print(consent_string)
        for origin in website.seen_consent_strings_v2:
            if len(website.seen_consent_strings_v2[origin]) > 0:
                print("%s (TCFv2):" % origin)
                for consent_string in website.seen_consent_strings_v2[origin]:
                    print(consent_string)
    elif website.nothing_found_after_manual_validation:
        print("No consent string found, even after manual validation.")
    if website.semi_automatic_done and len(website.seen_consent_strings["direct"]) == 0 and len(website.seen_consent_strings_v2["direct"]) == 0:
        print("Calls to __cmp() never return anything.")

def get_vendor_in_vendorlist(vendorlist, vendor_id):
    for vendor in vendorlist["vendors"]:
        if vendor["id"] == vendor_id:
            return vendor
    return None

def find_legint_ambiguous_cmps_ac():
    # NOT integrated
    # You have to run it on a website having preaction_n3 for each CMP
    # ex: select domain from website where preaction_n3 and cmpid=187;
    domain = get_domain(args.url, subdomain=True)
    website = get_website(domain, db)
    print("-- Trying website: %s" % domain)
    correct = False
    for origin in website.seen_consent_strings:
        if origin == "GET" or origin == "POST":
            continue
        for raw_consent_string in website.seen_consent_strings[origin]:
            consent_string = decode_consent_string(raw_consent_string)
            for vendor_id in consent_string["allowedVendorIds"]:
                vl = get_vendor_list(consent_string["vendorListVersion"])
                for purpose in consent_string["allowedPurposeIds"]:
                    vendor = get_vendor_in_vendorlist(vl, vendor_id)
                    if purpose in vendor["purposeIds"]:
                        print("Uses consent")
                        return
    print("Seems to be using legitimate interests only!")

def main():
    global db
    parse_command_line()

    if args.dump is not None:
        db = start_db()
        domain = get_domain(args.url, subdomain=True)
        website = get_website(domain, db)
        if website is None:
            print("Website not found.")
        else:
            dump_website(website)
        sys.exit(0)

    if args.full_violations_check:
        db = start_db()
        website = init_violations_check()
        full_violations_check(website)
        last_checks(website, semi_automatic=True)
        dump_website(website)
        db.commit()
        sys.exit(0)
    elif args.automatic_violations_check:
        db = start_db()
        website = init_violations_check()
        automatic_violations_check(website)
        last_checks(website)
        dump_website(website)
        db.commit()
        sys.exit(0)
    elif args.automatic_violations_check_full:
        db = start_db()
        website = init_violations_check()
        automatic_violations_check_full(website)
        last_checks(website)
        dump_website(website)
        db.commit()
        sys.exit(0)
    elif args.semi_automatic_violations_check:
        db = start_db()
        website = init_violations_check()
        semi_automatic_violations_check(website)
        last_checks(website, semi_automatic=True)
        dump_website(website)
        db.commit()
        sys.exit(0)
    else: # default
        db = start_db()
        website = init_violations_check()
        test_if_website_uses_cmp_only(website)
        db.commit()
        sys.exit(0)

if __name__ == "__main__":
    main()
