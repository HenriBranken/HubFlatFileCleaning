"""Copy each dataset's month-tagged cleaned CSV in output/ to a fixed filename
(no month tag) in output/to_upload/, for downstream tools that expect a stable
filename.

Run after Clean_Raw_Hub.py (or the per-dataset notebooks) have produced this
month's output/<Prefix>_<ccyymm>_cleaned.csv files. ccyymm is not passed in --
it's inferred per dataset from whichever single file in output/ matches
<Prefix>_<ccyymm>_cleaned.csv.
"""
import re
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "output"
UPLOAD_DIR = OUTPUT_DIR / "to_upload"

# Source prefix (as written by Clean_Raw_Hub.py/notebooks) -> fixed destination filename.
RENAME_MAP = {
    "HubAssessmentResults": "HubAssessmentResults.csv",
    "HubDailyContent": "HubContent.csv",
    "HubDailyEvents": "HubEvents.csv",
    "HubDailyUsers": "HubUsers.csv",
    "HubMonthlyUsers": "HubMonthlyUsers.csv",
}


def find_cleaned_file(prefix: str) -> Path:
    filename_re = re.compile(rf"^{re.escape(prefix)}_(\d{{6}})_cleaned\.csv$")
    matches = sorted(p for p in OUTPUT_DIR.glob(f"{prefix}_*_cleaned.csv") if filename_re.match(p.name))
    if not matches:
        raise FileNotFoundError(f"No {prefix}_ccyymm_cleaned.csv file found in {OUTPUT_DIR}")
    if len(matches) > 1:
        raise ValueError(
            f"Multiple candidate cleaned files found for {prefix} in {OUTPUT_DIR}: "
            f"{[m.name for m in matches]}. Remove the stale one(s) before renaming."
        )
    return matches[0]


def main():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for prefix, dest_name in RENAME_MAP.items():
        source_path = find_cleaned_file(prefix)
        dest_path = UPLOAD_DIR / dest_name
        shutil.copyfile(source_path, dest_path)
        print(f"{source_path.name} -> {dest_path.relative_to(OUTPUT_DIR)}")


if __name__ == "__main__":
    main()
