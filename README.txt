Clean_Raw_Hub.py
================

Cleans four raw Hub exports in one run:
  - HubDailyContentData_yyyy-mm-dd.csv  -> HubDailyContent_<month_tag>_cleaned.csv
  - HubDailyEventData_yyyy-mm-dd.csv    -> HubDailyEvents_<month_tag>_cleaned.csv
  - HubDailyUsers_yyyy-mm-dd.csv        -> HubDailyUsers_<month_tag>_cleaned.csv
  - HubMonthlyUsers_yyyy-mm-dd.csv      -> HubMonthlyUsers_<month_tag>_cleaned.csv

Requirements
------------
Python 3.14 and the packages listed in requirements.txt (pandas, plus
nbformat/nbclient for re-running notebooks). Install them into the virtual
environment described below rather than system-wide.

Virtual environment
-------------------
One-time setup, from this folder:

  python -m venv .venv
  .venv\Scripts\Activate.ps1        (PowerShell; use .venv\Scripts\activate.bat for cmd.exe)
  pip install -r requirements.txt

Every new terminal session, activate it again before running anything:

  .venv\Scripts\Activate.ps1

The prompt shows a "(.venv)" prefix when it's active.

Folder layout
-------------
Run the script from (or place it in) a folder that has an "input" subfolder:

  input/     the four raw CSVs above (exactly one of each)
  output/    cleaned CSVs are written here (created automatically)
  reports/   a summary .txt report per dataset is written here (created automatically)

Usage
-----
With the virtual environment activated (see above):

  python Clean_Raw_Hub.py

Each of the four input files must be the only file in input/ matching its
pattern -- if none or more than one is found, the script stops with an error
naming the problem file(s) instead of guessing.

What "month_tag" means
-----------------------
month_tag is always the month BEFORE the date in the input filename, e.g.
HubDailyUsers_2026-08-02.csv produces HubDailyUsers_202607_cleaned.csv.
It comes from the filename only.

Output
------
For each dataset the script prints the cleaned row count and the paths of
the CSV and report it wrote, then a final summary of all four. Each report
in reports/ lists the raw/cleaned row counts, duplicate counts, and rows
dropped, followed by df.describe() over the cleaned numeric columns -- a
quick way to sanity-check a run without opening the CSVs.

Notes
-----
- Cleaning logic is not configurable via command-line flags; each dataset's
  rules (columns, renames, date handling, etc.) are the ones specified for
  that dataset and are not meant to be changed per run.
- Re-running is safe: files in output/ and reports/ are overwritten, not
  appended to.
