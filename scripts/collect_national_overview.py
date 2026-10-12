"""Collect national Civiqs estimates and combine with the FEC's official 2024 national totals.

Run from TrumpApprovalByState project root:
    python scripts/collect_national_overview.py

Requires selenium (already used by the project's Civiqs scraper) and Chrome.
Reads: data/raw/2024presgeresults.xlsx
Writes: data/processed/national_approval_current.json
        docs/data/national_approval.json

Uses the filtered *Subgroups Total* table row on each of three Civiqs pages.
Does not average states or infer national polling from statewide estimates.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from merge_fec_2024_votes import read_fec_xlsx, percent_two_decimals

ROOT = Path(__file__).resolve().parents[1]
CIVIQS = "https://civiqs.com/results/approve_president_trump_2025"
FEC_SOURCE = "https://www.fec.gov/documents/5645/2024presgeresults.xlsx"
FEC = ROOT / "data" / "raw" / "2024presgeresults.xlsx"
PROCESSED = ROOT / "data" / "processed" / "national_approval_current.json"
PUBLIC = ROOT / "docs" / "data" / "national_approval.json"
STATES_JSON = ROOT / "docs" / "data" / "state_approval.json"
GROUPS = (("net", None), ("republican", "Republican"), ("democratic", "Democrat"))
ROW_SELECTOR = '//div[contains(@class,"leading-10") and div/div[@data-testid="desktop-percent"]]'


def extract_total(driver):
    """Read the single Subgroups 'Total' row, not the graph's All Respondents figure."""
    matches = []
    for row in driver.find_elements(By.XPATH, ROW_SELECTOR):
        # Match the Civiqs TOTAL row case-insensitively.
        # Read its label as in the earlier working scraper.
        label_texts = [
            element.text.strip().casefold()
            for element in row.find_elements(
                By.XPATH, './/a | .//div[contains(@class,"w-52")]'
            )
        ]
        lines = row.text.strip().splitlines()
        first_line = lines[0].strip().casefold() if lines else ""
        if "total" not in label_texts and first_line != "total":
            continue
        labels = [e.text.strip() for e in row.find_elements(By.CSS_SELECTOR, '[data-testid="desktop-percent"]')]
        if len(labels) != 3:
            raise ValueError(f"Civiqs Total row has {len(labels)} percentages: {labels}")
        matches.append(labels)
    if not matches:
        return None
    if len(matches) > 2:
        raise ValueError(f"Found {len(matches)} national Total rows: Civiqs page structure changed")
    # Some page layouts show an All Respondents total followed by a
    # Subgroups Total row. The last is the filtered subgroup population.
    subgroup_total = matches[-1]
    fields = {}
    for key, label in zip(("approve", "disapprove", "neither"), subgroup_total):
        if not re.fullmatch(r"(?:<1|\d{1,3})%", label):
            raise ValueError(f"Unexpected Civiqs {key} percentage {label!r}")
        fields[key] = 0.5 if label == "<1%" else float(label.removesuffix("%"))
        fields[f"{key}_display"] = label
    total = sum(fields[k] for k in ("approve", "disapprove", "neither"))
    if not 98 <= total <= 102:
        raise ValueError(f"Civiqs national row totals {total}% (outside 98–102%)")
    return fields


def extract_date(driver):
    for element in driver.find_elements(By.CSS_SELECTOR, '[data-testid="timeseries-label-container"] span'):
        label = element.text.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", label):
            return label
    return None


def main():
    # Check FEC workbook first; only run the live scraper when local inputs are valid.
    fec = read_fec_xlsx(FEC)
    trump = sum(r["trump"] for r in fec)
    total = sum(r["total"] for r in fec)
    if (trump, total) != (77_302_580, 155_238_302):
        raise ValueError(f"Unexpected FEC 2024 national totals: {trump:,} / {total:,}")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    driver = webdriver.Chrome(options=options)
    collected = {}
    try:
        for key, party in GROUPS:
            params = {"uncertainty": "true", "zoomIn": "true", "annotations": "true"}
            if party:
                params["party"] = party
            url = CIVIQS + "?" + urlencode(params)
            print(f"Fetching Civiqs national {key} results ...", flush=True)
            driver.get(url)
            WebDriverWait(driver, 50).until(lambda b: extract_total(b) is not None)
            if party:
                expected = rf"Refined by:\s*party:\s*{re.escape(party)}\b"
                WebDriverWait(driver, 25).until(lambda b: bool(re.search(expected, b.find_element(By.TAG_NAME, "body").text, re.I)))
            values = extract_total(driver)
            date = WebDriverWait(driver, 25).until(lambda b: extract_date(b))
            collected[key] = {**values, "source_url": driver.current_url, "report_date": date}
            print(f"  {date}: approve {values['approve_display']}, disapprove {values['disapprove_display']}, neither {values['neither_display']}")
    finally:
        driver.quit()

    dates = {g["report_date"] for g in collected.values()}
    if len(dates) != 1:
        raise ValueError(f"National reporting dates don't match across groups: {dates}")
    national_date = dates.pop()

    if not STATES_JSON.is_file():
        raise FileNotFoundError(f"State dashboard data missing: {STATES_JSON}")
    states = json.loads(STATES_JSON.read_text(encoding="utf-8"))
    if not isinstance(states, list) or len(states) != 50:
        raise ValueError("Expected exactly 50 published state records")
    state_dates = {row.get("report_date") for row in states}
    if len(state_dates) != 1:
        raise ValueError("The published state snapshot contains inconsistent reporting dates")
    state_date = state_dates.pop()
    if national_date != state_date:
        print(f"NOTE: National Civiqs date is {national_date}; state snapshot date is {state_date}.")
        print("The sidebar will label its national date explicitly. No state numbers were changed.")

    output = {
        "report_date": national_date,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "groups": {key: {k:v for k,v in collected[key].items() if k != "report_date"} for key,_ in GROUPS},
        "election_2024": {
            "trump_votes": trump,
            "total_presidential_votes": total,
            "trump_vote_share_pct": percent_two_decimals(trump, total),
            "source_url": FEC_SOURCE,
        },
    }
    encoded = json.dumps(output, indent=2, ensure_ascii=False) + "\n"
    PROCESSED.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED.write_text(encoded, encoding="utf-8")
    PUBLIC.write_text(encoded, encoding="utf-8")
    print(f"FEC national share: {trump:,} / {total:,} = {output['election_2024']['trump_vote_share_pct']:.2f}%")
    print(f"Saved {PROCESSED}")
    print(f"Saved {PUBLIC}")
    print("SUCCESS: National Civiqs estimates and official FEC nationwide vote share saved.")


if __name__ == "__main__":
    main()
