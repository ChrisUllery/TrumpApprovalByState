
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ============================================================
# CONFIG
# ============================================================

URL = "https://civiqs.com/results/approve_president_trump_2025"

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "processed"

STATES = dict(
    line.split("|")
    for line in """
Alabama|AL
Alaska|AK
Arizona|AZ
Arkansas|AR
California|CA
Colorado|CO
Connecticut|CT
Delaware|DE
Florida|FL
Georgia|GA
Hawaii|HI
Idaho|ID
Illinois|IL
Indiana|IN
Iowa|IA
Kansas|KS
Kentucky|KY
Louisiana|LA
Maine|ME
Maryland|MD
Massachusetts|MA
Michigan|MI
Minnesota|MN
Mississippi|MS
Missouri|MO
Montana|MT
Nebraska|NE
Nevada|NV
New Hampshire|NH
New Jersey|NJ
New Mexico|NM
New York|NY
North Carolina|NC
North Dakota|ND
Ohio|OH
Oklahoma|OK
Oregon|OR
Pennsylvania|PA
Rhode Island|RI
South Carolina|SC
South Dakota|SD
Tennessee|TN
Texas|TX
Utah|UT
Vermont|VT
Virginia|VA
Washington|WA
West Virginia|WV
Wisconsin|WI
Wyoming|WY
""".strip().splitlines()
)


# ============================================================
# EXTRACTION
# ============================================================

def parse_percentage(text):
    value = text.strip().replace("%", "")
    return float(value)


def extract_state_rows(driver):
    rows = driver.find_elements(
        By.XPATH,
        '//div[contains(@class,"leading-10") '
        'and div/div[@data-testid="desktop-percent"]]'
    )

    records = {}

    for row in rows:
        lines = row.text.splitlines()

        if not lines:
            continue

        label = lines[0].strip()

        if label not in STATES:
            continue

        percentages = [
            element.text.strip()
            for element in row.find_elements(
                By.CSS_SELECTOR,
                '[data-testid="desktop-percent"]'
            )
        ]

        if len(percentages) != 3:
            raise ValueError(
                f"{label}: expected 3 percentages, got {percentages}"
            )

        approve, disapprove, neither = [
            parse_percentage(value)
            for value in percentages
        ]

        total = approve + disapprove + neither

        if not 98 <= total <= 102:
            raise ValueError(
                f"{label}: percentages total {total}%"
            )

        if label in records:
            raise ValueError(f"Duplicate state: {label}")

        records[label] = {
            "state": label,
            "state_abbr": STATES[label],
            "approve": approve,
            "disapprove": disapprove,
            "neither": neither,
            "net_from_rounded": approve - disapprove,
        }

    return records


def extract_report_date(driver):
    elements = driver.find_elements(
        By.CSS_SELECTOR,
        '[data-testid="timeseries-label-container"] span'
    )

    for element in elements:
        text = element.text.strip()

        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return text

    raise ValueError("Could not identify the Civiqs report date")


# ============================================================
# MAIN
# ============================================================

options = Options()
options.add_argument("--headless=new")
options.add_argument("--window-size=1920,1080")

driver = webdriver.Chrome(options=options)

try:
    print("Opening Civiqs...")
    driver.get(URL)

    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, '[data-testid="desktop-percent"]')
        )
    )

    print("Waiting for all state rows...")

    WebDriverWait(driver, 45).until(
        lambda browser: len(extract_state_rows(browser)) == 50
    )

    state_data = extract_state_rows(driver)
    report_date = extract_report_date(driver)
    retrieved_at = datetime.now(timezone.utc).isoformat()

    if set(state_data) != set(STATES):
        missing = sorted(set(STATES) - set(state_data))
        raise ValueError(f"Missing states: {missing}")

    records = []

    for state in STATES:
        record = {
            **state_data[state],
            "report_date": report_date,
            "source_url": driver.current_url,
            "retrieved_at_utc": retrieved_at,
        }
        records.append(record)

finally:
    driver.quit()


# ============================================================
# SAVE
# ============================================================

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

csv_path = OUTPUT_DIR / "state_approval_all_50.csv"
json_path = OUTPUT_DIR / "state_approval_all_50.json"

with open(csv_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=list(records[0].keys())
    )
    writer.writeheader()
    writer.writerows(records)

with open(json_path, "w", encoding="utf-8") as f:
    json.dump(records, f, indent=2, ensure_ascii=False)

print(f"\nReport date: {report_date}")
print(f"States collected: {len(records)}")

for record in records:
    print(
        f"{record['state']:<20} "
        f"Approve: {record['approve']:>5.0f}% | "
        f"Disapprove: {record['disapprove']:>5.0f}%"
    )

print("\nSaved:")
print(csv_path)
print(json_path)
print("\nSUCCESS: All 50 states validated.")
