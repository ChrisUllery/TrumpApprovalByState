"""Prepare a local, Git-ignored dashboard data copy from validated scraper output.

Run from the repository root:
    python scripts/prepare_preview.py

Copies the validated public snapshot into docs/data for GitHub Pages.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "processed" / "state_approval_with_2024_votes.json"
DESTINATION = ROOT / "docs" / "data" / "state_approval.json"
GITIGNORE = ROOT / ".gitignore"
GITIGNORE_LINES = ["data/processed/"]


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(
            f"Cannot find {SOURCE}\n"
            "Run the 50-state Civiqs extraction script first."
        )

    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) != 50:
        raise SystemExit(f"Expected 50 records in {SOURCE}, found {len(data) if isinstance(data, list) else 'invalid format'}")
    names = [item.get("state") for item in data]
    if len(set(names)) != 50:
        raise SystemExit("Dataset contains duplicated or missing state names.")
    required = ("republican_approve", "republican_disapprove", "democratic_approve", "democratic_disapprove", "republican_approve_display", "democratic_approve_display")
    for row in data:
        for field in required:
            if field not in row:
                raise SystemExit(f"Missing {field} for {row.get('state', 'unknown')}")
    for row in data:
        for key in ("trump_2024_votes", "total_2024_presidential_votes", "trump_2024_vote_share_pct", "fec_2024_source_url"):
            if key not in row:
                raise SystemExit(f"Missing {key} for {row.get('state', 'unknown')}")
    if len({r.get("report_date") for r in data}) != 1:
        raise SystemExit("Reporting dates differ between states.")

    current = GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.exists() else ""
    existing_lines = {line.strip() for line in current.splitlines()}
    missing_lines = [line for line in GITIGNORE_LINES if line not in existing_lines]
    if missing_lines:
        prefix = "" if not current else "\n" if not current.endswith("\n") else ""
        GITIGNORE.write_text(current + prefix + "\n".join(missing_lines) + "\n", encoding="utf-8")
        print("Updated .gitignore with private data exclusions.")

    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, DESTINATION)
    print(f"Validated {len(data)} states")
    print(f"GitHub Pages JSON created: {DESTINATION}")
    print("To preview: python -m http.server 8000 --directory docs")
    print("Open http://localhost:8000")


if __name__ == "__main__":
    main()
