"""Merge official 2024 FEC presidential vote shares with the Civiqs state dataset.

Run from TrumpApprovalByState's root:
    python scripts/merge_fec_2024_votes.py

Reads:
    data/raw/2024presgeresults.xlsx
    data/processed/state_approval_with_parties_test.json

Writes (new files only; does not change the website or original input):
    data/processed/fec_2024_trump_vote_share.csv
    data/processed/state_approval_with_2024_votes.csv
    data/processed/state_approval_with_2024_votes.json

Uses only Python's standard library. The spreadsheet is read as OpenXML (ZIP/XML).
"""

from __future__ import annotations

import csv
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
FEC_XLSX = ROOT / "data" / "raw" / "2024presgeresults.xlsx"
CIVIQS_JSON = ROOT / "data" / "processed" / "state_approval_with_parties_test.json"
OUTPUT_DIR = ROOT / "data" / "processed"
FEC_SOURCE_URL = "https://www.fec.gov/documents/5645/2024presgeresults.xlsx"

# D.C. is present in the FEC file but isn't in our 50-state Civiqs dataset.
STATE_ABBRS = set("""
AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO
MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY
""".split())

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def read_fec_xlsx(path: Path) -> list[dict[str, str]]:
    """Read the FEC's single-sheet workbook without extra Python packages."""
    if not path.is_file():
        raise FileNotFoundError(f"FEC workbook missing: {path}")

    with ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in strings_root.findall(f"{NS}si"):
                shared_strings.append("".join(t.text or "" for t in item.iter(f"{NS}t")))

        sheet_root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        rows = []
        for row in sheet_root.findall(f".//{NS}sheetData/{NS}row"):
            cells = {}
            for cell in row.findall(f"{NS}c"):
                ref = cell.attrib.get("r", "")
                match = re.match(r"[A-Z]+", ref)
                if not match:
                    continue
                col = match.group()
                value_element = cell.find(f"{NS}v")
                value = value_element.text if value_element is not None else None
                if cell.attrib.get("t") == "s" and value is not None:
                    value = shared_strings[int(value)]
                elif cell.attrib.get("t") == "inlineStr":
                    value = "".join(t.text or "" for t in cell.iter(f"{NS}t"))
                if value is not None:
                    cells[col] = value.strip()
            if cells:
                rows.append(cells)

    if not rows:
        raise ValueError("No rows found in the FEC workbook.")

    # The FEC file currently places these in A, Y, AE. Use column headings so
    # rearrangement is detected, not silently misinterpreted.
    header_by_name = {v.upper(): c for c, v in rows[0].items()}
    needed = ("STATE", "TRUMP", "TOTAL VOTES")
    if not all(key in header_by_name for key in needed):
        raise ValueError(f"Missing FEC columns: {set(needed) - set(header_by_name)}")

    records = []
    for cells in rows[1:]:
        code = cells.get(header_by_name["STATE"], "")
        if code not in STATE_ABBRS | {"DC"}:
            continue
        trump = int(Decimal(cells[header_by_name["TRUMP"]]))
        total = int(Decimal(cells[header_by_name["TOTAL VOTES"]]))
        if trump < 0 or total <= 0 or trump > total:
            raise ValueError(f"Invalid vote counts for {code}: {trump} / {total}")
        records.append({"state_abbr": code, "trump": trump, "total": total})

    codes = [row["state_abbr"] for row in records]
    if len(records) != 51 or len(set(codes)) != 51 or set(codes) != STATE_ABBRS | {"DC"}:
        raise ValueError(f"Expected exactly 50 states plus D.C., found {len(records)} rows: {codes}")

    # Independently verify both FEC nationwide totals, including D.C.
    total_row = next((cells for cells in rows if cells.get(header_by_name["STATE"]) == "Total:"), None)
    if total_row is None:
        raise ValueError("Official FEC Total: row not found")
    for key, field in (("TRUMP", "trump"), ("TOTAL VOTES", "total")):
        official = int(Decimal(total_row[header_by_name[key]]))
        calculated = sum(row[field] for row in records)
        if calculated != official:
            raise ValueError(f"FEC {key} checksum mismatch: {calculated:,} vs {official:,}")
    print(f"FEC checksum OK: {sum(r['trump'] for r in records):,} Trump votes; "
          f"{sum(r['total'] for r in records):,} total presidential votes (50 states + D.C.)")
    return records


def percent_two_decimals(trump: int, total: int) -> float:
    pct = (Decimal(trump) * 100 / Decimal(total)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(pct)


def save_csv(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    fec_records = read_fec_xlsx(FEC_XLSX)
    fec_by_abbr = {r["state_abbr"]: r for r in fec_records if r["state_abbr"] != "DC"}

    if not CIVIQS_JSON.is_file():
        raise FileNotFoundError(f"Civiqs 50-state JSON missing: {CIVIQS_JSON}")
    civiqs = json.loads(CIVIQS_JSON.read_text(encoding="utf-8"))
    if not isinstance(civiqs, list) or len(civiqs) != 50:
        raise ValueError("Expected a list of 50 Civiqs state records")

    abbreviations = [item.get("state_abbr") for item in civiqs]
    if len(set(abbreviations)) != 50 or set(abbreviations) != STATE_ABBRS:
        raise ValueError("Civiqs state abbreviations are missing, duplicated, or invalid")

    merged = []
    fec_csv = []
    for item in civiqs:
        abbr = item["state_abbr"]
        votes = fec_by_abbr[abbr]
        pct = percent_two_decimals(votes["trump"], votes["total"])
        fields = {
            "trump_2024_votes": votes["trump"],
            "total_2024_presidential_votes": votes["total"],
            "trump_2024_vote_share_pct": pct,
            "fec_2024_source_url": FEC_SOURCE_URL,
        }
        merged.append({**item, **fields})
        fec_csv.append({
            "state": item["state"], "state_abbr": abbr, **fields
        })

    # Complete verification before writing anything.
    if len(merged) != 50 or len(fec_csv) != 50:
        raise ValueError("State join failed")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = (
        OUTPUT_DIR / "fec_2024_trump_vote_share.csv",
        OUTPUT_DIR / "state_approval_with_2024_votes.csv",
        OUTPUT_DIR / "state_approval_with_2024_votes.json",
    )
    save_csv(outputs[0], fec_csv)
    save_csv(outputs[1], merged)
    outputs[2].write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("SUCCESS: 50 FEC state results matched to 50 Civiqs state records; D.C. excluded.")
    print("All original Civiqs fields preserved; original files unchanged.\n")
    by_code = {r["state_abbr"]: r for r in merged}
    for code in ("PA", "MD", "CA", "TX"):
        r = by_code[code]
        print(f"{r['state']:<15} {r['trump_2024_votes']:>10,} / "
              f"{r['total_2024_presidential_votes']:>10,} = "
              f"{r['trump_2024_vote_share_pct']:.2f}%")
    print("\nSaved:")
    for path in outputs:
        print(f"  {path}")
    print("\nThe local docs/ website has NOT been modified.")


if __name__ == "__main__":
    main()
