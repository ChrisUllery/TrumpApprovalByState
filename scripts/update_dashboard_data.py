"""Refresh the published Civiqs Trump approval snapshots for GitHub Pages.

Run from project root:
    python scripts/update_dashboard_data.py

Reads existing committed public JSON to retain official 2024 FEC election data.
Scrapes overall, Republican and Democratic Civiqs subgroup tables (50 states
and the national Total on each page). Writes public JSON ONLY after every
page and every state passes validation. If the source data and reporting date
have not changed, the public files are left byte-for-byte unchanged.

Uses Selenium 4 + Chrome; works locally or in GitHub Actions on Ubuntu.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
STATES_PATH = ROOT / "docs" / "data" / "state_approval.json"
NATIONAL_PATH = ROOT / "docs" / "data" / "national_approval.json"
CIVIQS = "https://civiqs.com/results/approve_president_trump_2025"
ROW_SELECTOR = '//div[contains(@class,"leading-10") and div/div[@data-testid="desktop-percent"]]'
GROUPS = (("net", None), ("republican", "Republican"), ("democratic", "Democrat"))
PERCENT_KEYS = ("approve", "disapprove", "neither")
FEC_NATIONAL_VOTES = 77_302_580
FEC_NATIONAL_TOTAL = 155_238_302


def read_json(path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"Existing published snapshot is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def checked_percentages(labels: list[str], label: str) -> dict:
    if len(labels) != 3:
        raise ValueError(f"{label}: expected approve/disapprove/neither, got {labels!r}")
    result = {}
    for key, display in zip(PERCENT_KEYS, labels):
        if not re.fullmatch(r"(?:<1|\d{1,3})%", display):
            raise ValueError(f"{label}: unexpected {key} label: {display!r}")
        number = .5 if display == "<1%" else float(display[:-1])
        if not 0 <= number <= 100:
            raise ValueError(f"{label}: {key} out of range: {number}")
        result[key] = number
        result[f"{key}_display"] = display
    total = sum(result[key] for key in PERCENT_KEYS)
    if not 98 <= total <= 102:
        raise ValueError(f"{label}: percentages add to {total}%, outside expected rounding range")
    return result


def extract_rows(browser, state_names: set[str]):
    """One visible subgroup table: 50 state entries and last national Total."""
    states = {}
    totals = []
    for row in browser.find_elements(By.XPATH, ROW_SELECTOR):
        lines = row.text.strip().splitlines()
        if not lines:
            continue
        label = lines[0].strip()
        if label not in state_names and label.casefold() != "total":
            continue
        texts = [item.text.strip() for item in row.find_elements(By.CSS_SELECTOR, '[data-testid="desktop-percent"]')]
        if not all(texts):
            return None  # Civiqs is still rendering its results
        numbers = checked_percentages(texts, label)
        if label in state_names:
            if label in states:
                raise ValueError(f"Duplicate Civiqs state row: {label}")
            states[label] = numbers
        else:
            totals.append(numbers)
    if len(states) != 50 or not totals:
        return None
    if len(totals) > 2:
        raise ValueError(f"Unexpected number of national Total rows: {len(totals)}")
    # The last Total belongs to the Subgroups table (not the graph summary).
    return states, totals[-1]


def extract_date(browser):
    for element in browser.find_elements(By.CSS_SELECTOR, '[data-testid="timeseries-label-container"] span'):
        value = element.text.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return value
    return None


def source_ready(browser, party, state_names):
    try:
        if party:
            # Make sure that Civiqs has applied the requested party filter.
            expected = rf"Refined by:\s*party:\s*{re.escape(party)}\b"
            if not re.search(expected, browser.find_element(By.TAG_NAME, "body").text, re.I):
                return None
        data = extract_rows(browser, state_names)
        date = extract_date(browser)
        if data is None or date is None:
            return None
        return data, date
    except StaleElementReferenceException:
        return None


def without_retrieval_time(item):
    if isinstance(item, list):
        return [without_retrieval_time(x) for x in item]
    if isinstance(item, dict):
        return {k: without_retrieval_time(v) for k, v in item.items() if k != "retrieved_at_utc"}
    return item


def write_when_changed(path: Path, previous, refreshed) -> bool:
    if without_retrieval_time(previous) == without_retrieval_time(refreshed):
        print(f"Unchanged: {path.relative_to(ROOT)}")
        return False
    # Write a complete replacement only after all three pages have been validated.
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(refreshed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    print(f"Updated: {path.relative_to(ROOT)}")
    return True


def validate_current_snapshots(states, national):
    if not isinstance(states, list) or len(states) != 50:
        raise ValueError("Published state JSON must contain exactly 50 records")
    names = [r.get("state") for r in states]
    codes = [r.get("state_abbr") for r in states]
    if len(set(names)) != 50 or len(set(codes)) != 50 or any(not isinstance(n, str) or not n for n in names):
        raise ValueError("Published state records have missing or duplicate names/codes")
    for r in states:
        s = r["state"]
        if not re.fullmatch(r"[A-Z]{2}", r["state_abbr"]):
            raise ValueError(f"{s}: invalid state abbreviation")
        votes = r.get("trump_2024_votes")
        total = r.get("total_2024_presidential_votes")
        share = r.get("trump_2024_vote_share_pct")
        if not isinstance(votes, int) or not isinstance(total, int) or total <= 0 or votes < 0 or votes > total:
            raise ValueError(f"{s}: invalid preserved 2024 vote totals")
        if not isinstance(share, (int, float)) or abs(100 * votes / total - share) > .011:
            raise ValueError(f"{s}: inconsistent preserved 2024 vote share")
        if not r.get("fec_2024_source_url"):
            raise ValueError(f"{s}: missing FEC source URL")
    election = national.get("election_2024", {}) if isinstance(national, dict) else {}
    if (election.get("trump_votes"), election.get("total_presidential_votes")) != (FEC_NATIONAL_VOTES, FEC_NATIONAL_TOTAL):
        raise ValueError("The national JSON does not contain the validated 2024 FEC totals")
    if abs(election.get("trump_vote_share_pct", -1) - 100 * FEC_NATIONAL_VOTES / FEC_NATIONAL_TOTAL) > .011:
        raise ValueError("The national FEC vote share failed validation")
    if not election.get("source_url"):
        raise ValueError("Missing national FEC source URL")
    return set(names)


def main():
    old_states = read_json(STATES_PATH)
    old_national = read_json(NATIONAL_PATH)
    names = validate_current_snapshots(old_states, old_national)

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    browser = webdriver.Chrome(options=options)
    scraped = {}
    try:
        for key, party in GROUPS:
            params = {"uncertainty": "true", "zoomIn": "true", "annotations": "true"}
            if party:
                params["party"] = party
            url = CIVIQS + "?" + urlencode(params)
            print(f"Fetching {key} estimates from Civiqs...", flush=True)
            browser.get(url)
            state_and_national, date = WebDriverWait(browser, 75, poll_frequency=1).until(
                lambda driver: source_ready(driver, party, names)
            )
            state_rows, national_row = state_and_national
            if set(state_rows) != names:
                raise ValueError(f"Civiqs {key}: state list changed unexpectedly")
            scraped[key] = {
                "states": state_rows,
                "national": national_row,
                "date": date,
                "source_url": browser.current_url,
            }
            print(f"  {date} | 50 states | national: approve {national_row['approve_display']}, "
                  f"disapprove {national_row['disapprove_display']}, neither {national_row['neither_display']}", flush=True)
    finally:
        browser.quit()

    report_dates = {item["date"] for item in scraped.values()}
    if len(report_dates) != 1:
        raise ValueError(f"Civiqs returned different dates for the three populations: {report_dates}. No files updated.")
    report_date = report_dates.pop()
    retrieved = datetime.now(timezone.utc).isoformat()

    updated_states = []
    for current in old_states:
        state_name = current["state"]
        overall = scraped["net"]["states"][state_name]
        republican = scraped["republican"]["states"][state_name]
        democratic = scraped["democratic"]["states"][state_name]
        row = dict(current)  # retain verified, fixed FEC fields
        for k in PERCENT_KEYS:
            row[k] = overall[k]
            row[f"{k}_display"] = overall[f"{k}_display"]
            for party_name, p_data in (("republican", republican), ("democratic", democratic)):
                row[f"{party_name}_{k}"] = p_data[k]
                row[f"{party_name}_{k}_display"] = p_data[f"{k}_display"]
        row["net_from_rounded"] = row["approve"] - row["disapprove"]
        row.update({
            "report_date": report_date,
            "retrieved_at_utc": retrieved,
            "source_url": scraped["net"]["source_url"],
            "republican_source_url": scraped["republican"]["source_url"],
            "democratic_source_url": scraped["democratic"]["source_url"],
        })
        updated_states.append(row)

    updated_national = {
        "report_date": report_date,
        "retrieved_at_utc": retrieved,
        "groups": {
            key: {**item["national"], "source_url": item["source_url"]}
            for key, item in scraped.items()
        },
        "election_2024": dict(old_national["election_2024"]),
    }

    # Validate the complete refresh before writing either file.
    if len(updated_states) != 50 or len(updated_national["groups"]) != 3:
        raise ValueError("Incomplete refresh; refusing to publish")
    states_changed = write_when_changed(STATES_PATH, old_states, updated_states)
    national_changed = write_when_changed(NATIONAL_PATH, old_national, updated_national)
    print(f"SUCCESS: 50 states + national Civiqs data validated for {report_date}.")
    print("Election results unchanged. JSON updates: " + ("yes" if states_changed or national_changed else "none"))


if __name__ == "__main__":
    main()
