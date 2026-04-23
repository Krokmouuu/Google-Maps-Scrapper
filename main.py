import logging
from typing import List, Optional
from playwright.sync_api import sync_playwright, Page
from dataclasses import dataclass, asdict
import pandas as pd
import argparse
import platform
import time
import os

@dataclass
class Place:
    name: str = ""
    address: str = ""
    website: str = ""
    phone_number: str = ""
    reviews_count: Optional[int] = None
    reviews_average: Optional[float] = None
    store_shopping: str = "No"
    in_store_pickup: str = "No"
    store_delivery: str = "No"
    place_type: str = ""
    opens_at: str = ""
    introduction: str = ""

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
    )

def extract_text(page: Page, xpath: str) -> str:
    try:
        if page.locator(xpath).count() > 0:
            return page.locator(xpath).inner_text()
    except Exception as e:
        logging.warning(f"Failed to extract text for xpath {xpath}: {e}")
    return ""

def extract_text_first_match(page: Page, xpaths: List[str]) -> str:
    for xp in xpaths:
        text = extract_text(page, xp)
        if text:
            return text
    return ""

def fill_maps_search(page: Page, query: str) -> None:
    """Google Maps DOM changes often; try several selectors (incl. role=search omnibox)."""
    candidates = [
        'input#searchboxinput',
        'div[role="search"] input[type="text"]',
        'xpath=//div[@role="search"]//input[not(@type="hidden")]',
        'xpath=//div[@role="search"]//input[contains(@aria-label, "Maps") or contains(@aria-label, "Cartes") or contains(@aria-label, "Rechercher") or contains(@aria-label, "Search")]',
    ]
    last_err: Optional[Exception] = None
    for sel in candidates:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=8000)
            loc.fill(query)
            return
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"Could not find Google Maps search input; last error: {last_err}")

def handle_consent_if_present(page: Page) -> None:
    """
    Handle Google consent screen if it appears before Maps.
    Supports common FR/EN labels and both accept/reject flows.
    """
    consent_buttons = [
        'button:has-text("Tout accepter")',
        'button:has-text("Tout refuser")',
        'button:has-text("I agree")',
        'button:has-text("Accept all")',
        'button:has-text("Reject all")',
    ]

    # Consent is often served on consent.google.com before redirecting to maps.
    if "consent.google." not in page.url and page.locator(consent_buttons[0]).count() == 0:
        return

    for selector in consent_buttons:
        try:
            btn = page.locator(selector).first
            if btn.count() > 0:
                btn.click(timeout=5000)
                page.wait_for_timeout(1200)
                return
        except Exception:
            continue

def results_links_locator(page: Page):
    # Keep selector broad enough for minor URL format changes.
    return page.locator('//a[contains(@href, "/maps/place")]')

def scroll_results_panel(page: Page) -> None:
    """
    Scroll the results feed (left panel) when available.
    Falling back to mouse wheel can scroll the map instead of results.
    """
    feed_candidates = [
        'div[role="feed"]',
        'xpath=//div[@role="feed"]',
        'xpath=//div[contains(@aria-label, "Results for") or contains(@aria-label, "Résultats pour")]',
    ]
    for selector in feed_candidates:
        try:
            feed = page.locator(selector).first
            if feed.count() > 0:
                feed.hover(timeout=3000)
                feed.evaluate("(el) => { el.scrollBy(0, 1600); }")
                return
        except Exception:
            continue
    page.mouse.wheel(0, 10000)

def extract_place(page: Page) -> Place:
    # XPaths — prefer data-item-id / role; use contains(@class) for hashed UI classes.
    name_xpaths = [
        '//div[contains(@class, "TIHn2")]//h1[contains(@class, "DUwDvf")]',
        '//div[@role="main"]//h1[contains(@class, "DUwDvf")]',
        '//h1[contains(@class, "DUwDvf")]',
    ]
    address_xpath = '//button[@data-item-id="address"]//div[contains(@class, "fontBodyMedium")]'
    website_xpath = '//a[@data-item-id="authority"]//div[contains(@class, "fontBodyMedium")]'
    phone_number_xpath = '//button[contains(@data-item-id, "phone:tel:")]//div[contains(@class, "fontBodyMedium")]'
    reviews_count_xpaths = [
        '//div[contains(@class, "TIHn2")]//div[contains(@class, "fontBodyMedium") and contains(@class, "dmRWX")]//div//span//span//span[@aria-label]',
        '//div[contains(@class, "TIHn2")]//span[@aria-label][contains(@aria-label, "review") or contains(@aria-label, "avis")]',
    ]
    reviews_average_xpaths = [
        '//div[contains(@class, "TIHn2")]//div[contains(@class, "fontBodyMedium") and contains(@class, "dmRWX")]//div//span[@aria-hidden]',
        '//div[contains(@class, "TIHn2")]//span[@aria-hidden="true"][contains(@class, "MW4etd")]',
    ]
    info1 = '//div[contains(@class, "LTs0Rc")][1]'
    info2 = '//div[contains(@class, "LTs0Rc")][2]'
    info3 = '//div[contains(@class, "LTs0Rc")][3]'
    opens_at_xpath = '//button[contains(@data-item-id, "oh")]//div[contains(@class, "fontBodyMedium")]'
    opens_at_xpath2 = '//div[contains(@class, "MkV9")]//span[contains(@class, "ZDu9vd")]//span[2]'
    place_type_xpaths = [
        '//div[contains(@class, "LBgpqf")]//button[contains(@class, "DkEaL")]',
        '//button[contains(@class, "DkEaL")][@jsaction]',
    ]
    intro_xpaths = [
        '//div[contains(@class, "WeS02d") and contains(@class, "fontBodyMedium")]//div[contains(@class, "PYvSYb")]',
        '//div[contains(@class, "PYvSYb")]',
    ]

    place = Place()
    place.name = extract_text_first_match(page, name_xpaths)
    place.address = extract_text(page, address_xpath)
    place.website = extract_text(page, website_xpath)
    place.phone_number = extract_text(page, phone_number_xpath)
    place.place_type = extract_text_first_match(page, place_type_xpaths)
    place.introduction = extract_text_first_match(page, intro_xpaths) or "None Found"

    # Reviews Count
    reviews_count_raw = extract_text_first_match(page, reviews_count_xpaths)
    if reviews_count_raw:
        try:
            temp = reviews_count_raw.replace('\xa0', '').replace('(','').replace(')','').replace(',','')
            place.reviews_count = int(temp)
        except Exception as e:
            logging.warning(f"Failed to parse reviews count: {e}")
    # Reviews Average
    reviews_avg_raw = extract_text_first_match(page, reviews_average_xpaths)
    if reviews_avg_raw:
        try:
            temp = reviews_avg_raw.replace(' ','').replace(',','.')
            place.reviews_average = float(temp)
        except Exception as e:
            logging.warning(f"Failed to parse reviews average: {e}")
    # Store Info
    for idx, info_xpath in enumerate([info1, info2, info3]):
        info_raw = extract_text(page, info_xpath)
        if info_raw:
            temp = info_raw.split('·')
            if len(temp) > 1:
                check = temp[1].replace("\n", "").lower()
                if 'shop' in check:
                    place.store_shopping = "Yes"
                if 'pickup' in check:
                    place.in_store_pickup = "Yes"
                if 'delivery' in check:
                    place.store_delivery = "Yes"
    # Opens At
    opens_at_raw = extract_text(page, opens_at_xpath)
    if opens_at_raw:
        opens = opens_at_raw.split('⋅')
        if len(opens) > 1:
            place.opens_at = opens[1].replace("\u202f","")
        else:
            place.opens_at = opens_at_raw.replace("\u202f","")
    else:
        opens_at2_raw = extract_text(page, opens_at_xpath2)
        if opens_at2_raw:
            opens = opens_at2_raw.split('⋅')
            if len(opens) > 1:
                place.opens_at = opens[1].replace("\u202f","")
            else:
                place.opens_at = opens_at2_raw.replace("\u202f","")
    return place

def scrape_places(search_for: str, total: int) -> List[Place]:
    setup_logging()
    places: List[Place] = []
    with sync_playwright() as p:
        if platform.system() == "Windows":
            browser_path = r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
            browser = p.chromium.launch(executable_path=browser_path, headless=False)
        else:
            browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        try:
            page.goto("https://www.google.com/maps/@32.9817464,70.1930781,3.67z?", timeout=60000)
            page.wait_for_timeout(1000)
            handle_consent_if_present(page)
            fill_maps_search(page, search_for)
            page.keyboard.press("Enter")
            page.wait_for_selector('//a[contains(@href, "/maps/place")]')
            results_links_locator(page).first.hover()
            previously_counted = 0
            stagnation_rounds = 0
            while True:
                scroll_results_panel(page)
                page.wait_for_timeout(1200)
                found = results_links_locator(page).count()
                logging.info(f"Currently Found: {found}")
                if found >= total:
                    break
                if found == previously_counted:
                    stagnation_rounds += 1
                    # Allow several retries before concluding there is no more data.
                    if stagnation_rounds >= 8:
                        logging.info("Arrived at all available")
                        break
                else:
                    stagnation_rounds = 0
                previously_counted = found
            listings = results_links_locator(page).all()[:total]
            listings = [listing.locator("xpath=..") for listing in listings]
            logging.info(f"Total Found: {len(listings)}")
            for idx, listing in enumerate(listings):
                try:
                    listing.click()
                    page.wait_for_selector(
                        '//div[contains(@class, "TIHn2")]//h1[contains(@class, "DUwDvf")] | //h1[contains(@class, "DUwDvf")]',
                        timeout=10000,
                    )
                    time.sleep(1.5)  # Give time for details to load
                    place = extract_place(page)
                    if place.name:
                        places.append(place)
                    else:
                        logging.warning(f"No name found for listing {idx+1}, skipping.")
                except Exception as e:
                    logging.warning(f"Failed to extract listing {idx+1}: {e}")
        finally:
            browser.close()
    return places

def save_places_to_csv(places: List[Place], output_path: str = "result.csv", append: bool = False):
    df = pd.DataFrame([asdict(place) for place in places])
    if not df.empty:
        for column in df.columns:
            if df[column].nunique() == 1:
                df.drop(column, axis=1, inplace=True)
        file_exists = os.path.isfile(output_path)
        mode = "a" if append else "w"
        header = not (append and file_exists)
        df.to_csv(output_path, index=False, mode=mode, header=header)
        logging.info(f"Saved {len(df)} places to {output_path} (append={append})")
    else:
        logging.warning("No data to save. DataFrame is empty.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--search", type=str, help="Search query for Google Maps")
    parser.add_argument("-t", "--total", type=int, help="Total number of results to scrape")
    parser.add_argument("-o", "--output", type=str, default="result.csv", help="Output CSV file path")
    parser.add_argument("--append", action="store_true", help="Append results to the output file instead of overwriting")
    args = parser.parse_args()
    search_for = args.search or "turkish stores in toronto Canada"
    total = args.total or 1
    output_path = args.output
    append = args.append
    places = scrape_places(search_for, total)
    save_places_to_csv(places, output_path, append=append)

if __name__ == "__main__":
    main()
