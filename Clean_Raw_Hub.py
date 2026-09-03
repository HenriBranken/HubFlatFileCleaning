"""Clean the five raw Hub exports (HubDailyContent, HubDailyEvents, HubDailyUsers,
HubMonthlyUsers, HubAssessmentResults) in one run.

Reads from input/, writes cleaned CSVs to output/, summary reports to reports/, and
every dropped/duplicate-collapsed row (tagged with a DropReason column) to
dropped_and_dupes/ (all siblings of this script).
"""
import csv
import html
import io
import re
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
INPUT_DIR = SCRIPT_DIR / "input"
OUTPUT_DIR = SCRIPT_DIR / "output"
REPORTS_DIR = SCRIPT_DIR / "reports"
DROPPED_DIR = SCRIPT_DIR / "dropped_and_dupes"


def find_default_input(directory: Path, prefix: str, filename_re: re.Pattern, ext: str = "csv") -> Path:
    matches = sorted(p for p in directory.glob(f"{prefix}_*.{ext}") if filename_re.match(p.name))
    if not matches:
        raise FileNotFoundError(f"No {prefix}_yyyy-mm-dd.{ext} file found in {directory}")
    if len(matches) > 1:
        raise ValueError(
            f"Multiple candidate input files found in {directory}: "
            f"{[m.name for m in matches]}. Pass one explicitly."
        )
    return matches[0]


def month_tag_from_filename(path: Path, prefix: str, filename_re: re.Pattern, ext: str = "csv") -> str:
    match = filename_re.match(path.name)
    if not match:
        raise ValueError(f"Filename '{path.name}' does not match expected pattern {prefix}_yyyy-mm-dd.{ext}")
    year, month = (int(g) for g in match.groups())
    # month_tag refers to the prior month's data, not the export date's month.
    year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return f"{year}{month:02d}"


def write_report(
    reports_dir: Path,
    prefix: str,
    month_tag: str,
    input_path: Path,
    df_raw: pd.DataFrame,
    df_before_dedup: pd.DataFrame,
    df_cleaned: pd.DataFrame,
    output_path: Path,
) -> tuple[Path, str]:
    report_lines = [
        f"Input file: {input_path.name}",
        f"Raw row count: {len(df_raw)}",
        f"Raw duplicate rows: {int(df_raw.duplicated().sum())}",
        "=======================================================================",
        f"Month tag: {month_tag}",
        f"Blank/missing-key rows dropped: {len(df_raw) - len(df_before_dedup)}",
        f"Duplicate rows collapsed: {len(df_before_dedup) - len(df_cleaned)}",
        "=======================================================================",
        f"Cleaned row count: {len(df_cleaned)}",
        f"Cleaned duplicate rows: {int(df_cleaned.duplicated().sum())}",
        f"Output file: {output_path.name}",
    ]
    report_text = "\n".join(report_lines) + "\n"
    report_text += "\n\n\n" + df_cleaned.describe().to_string() + "\n"

    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{prefix}_{month_tag}_report.txt"
    report_path.write_text(report_text, encoding="utf-8")

    return report_path, report_text


def write_dropped_and_dupes(
    dropped_dir: Path,
    prefix: str,
    month_tag: str,
    dropped_blank: pd.DataFrame,
    duplicate_rows: pd.DataFrame,
) -> Path:
    """Write every row dropped for blank/missing-key data, plus every row belonging to a
    collapsed duplicate group (all N rows per group, not the N-1 that get summed away),
    tagged with a DropReason column so the two causes stay distinguishable.
    """
    dropped_blank = dropped_blank.copy()
    dropped_blank.insert(0, "DropReason", "dropped blank")

    duplicate_rows = duplicate_rows.copy()
    duplicate_rows.insert(0, "DropReason", "duplicate collapsed")

    combined = pd.concat([dropped_blank, duplicate_rows], ignore_index=True, sort=False)

    dropped_dir.mkdir(parents=True, exist_ok=True)
    out_path = dropped_dir / f"{prefix}_{month_tag}_dropped_and_dupes.csv"
    combined.to_csv(out_path, index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)

    return out_path


HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(value: str) -> str:
    text = HTML_TAG_RE.sub("", value)
    text = html.unescape(text)
    return text.replace("\xa0", " ").strip()


def blank_out_null_text(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize literal "null"/"Null"/"NULL" text entries (a Hub export quirk, distinct
    from a genuinely empty cell) to blank, so downstream blank/missing-key checks and the
    cleaned output treat them the same as an empty cell.
    """
    df = df.copy()
    for col in df.columns:
        is_null_text = df[col].str.strip().str.lower() == "null"
        df.loc[is_null_text, col] = ""
    return df


def read_semicolon_csv_protecting_backslashes(path: Path) -> pd.DataFrame:
    with open(path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    # Protect literal backslashes that aren't a genuine CSV \" escape (e.g. the real
    # company name "TBWA\RAAD") by doubling them, so escapechar below only ever
    # consumes actual \" sequences and every other backslash survives intact.
    protected_text = re.sub(r'\\(?!")', r"\\\\", raw_text)

    return pd.read_csv(
        io.StringIO(protected_text), sep=";", engine="python", escapechar="\\",
        dtype=str, keep_default_na=False, encoding="utf-8",
    )


# ============================================================
# 1. HubDailyContent
# ============================================================

LS_COLS_DC = [
    "Date", "CompanyCode", "CompanyName", "Country", "HomeCountry", "HomeCountryCode", "Operation",
    "AppInterest", "CategoryName", "ContentTitleLocalLanguage", "ContentTitle", "ContentLanguage",
    "ContentType", "DeviceCategory", "UserType", "Users", "TotalEvents", "UniqueEvents",
    "Stack", "Route", "Topic",
]
LS_STRING_COLS_DC = [
    "CompanyCode", "CompanyName", "Country", "HomeCountry", "HomeCountryCode", "Operation",
    "AppInterest", "CategoryName", "ContentTitleLocalLanguage", "ContentTitle", "ContentLanguage",
    "ContentType", "DeviceCategory", "UserType", "Users", "TotalEvents", "UniqueEvents",
    "Stack", "Route", "Topic",
]
LS_INT_COLS_DC = ["Users", "TotalEvents", "UniqueEvents"]
HTML_COLS_DC = ["ContentTitleLocalLanguage", "ContentTitle", "Stack"]

# Duplicate rows are collapsed by grouping on every LS_COLS_DC field except the
# summed measures (Users/TotalEvents/UniqueEvents) and summing those.
GROUP_COLS_DC = [c for c in LS_COLS_DC if c not in LS_INT_COLS_DC]
SUM_COLS_DC = LS_INT_COLS_DC

RENAME_MAP_DC = {"ContentTitle": "ContentTitleLocalLanguage", "ContentTitleEN": "ContentTitle"}

INPUT_PREFIX_DC = "HubDailyContentData"
PREFIX_DC = "HubDailyContent"
FILENAME_RE_DC = re.compile(r"^HubDailyContentData_(\d{4})-(\d{2})-\d{2}\.csv$")


def clean_dc(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = blank_out_null_text(df)
    df = df.rename(columns=RENAME_MAP_DC)

    present_ls_cols = [c for c in LS_COLS_DC if c in df.columns]
    is_blank = df[present_ls_cols].apply(lambda col: col.str.strip() == "").all(axis=1)
    dropped_blank = df.loc[is_blank].copy()
    df = df.loc[~is_blank].copy()

    missing_key = df["Date"].str.strip() == ""
    dropped_missing_key = df.loc[missing_key].copy()
    df = df.loc[~missing_key].copy()

    dropped = pd.concat([dropped_blank, dropped_missing_key])

    # %f always zero-pads to 6-digit microseconds; slicing off the last 3 leaves milliseconds.
    df["Date"] = pd.to_datetime(df["Date"], format="%Y-%m-%d").dt.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3]

    df = df[[c for c in LS_COLS_DC if c in df.columns]]

    for col in LS_STRING_COLS_DC:
        df[col] = df[col].str.strip().str.replace(r"\s+", " ", regex=True)

    for col in LS_INT_COLS_DC:
        df[col] = df[col].astype(int)

    for col in HTML_COLS_DC:
        df[col] = df[col].apply(strip_html)

    return df, dropped


def collapse_duplicates_dc(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    duplicate_rows = df.loc[df.duplicated(subset=GROUP_COLS_DC, keep=False)].copy()

    for col in SUM_COLS_DC:
        df[col] = df[col].astype(int)
    df = df.groupby(GROUP_COLS_DC, as_index=False)[SUM_COLS_DC].sum()
    return df[LS_COLS_DC], duplicate_rows


def process_dc() -> tuple[Path, Path, Path]:
    input_path = find_default_input(INPUT_DIR, INPUT_PREFIX_DC, FILENAME_RE_DC)
    month_tag = month_tag_from_filename(input_path, INPUT_PREFIX_DC, FILENAME_RE_DC)

    df_raw = read_semicolon_csv_protecting_backslashes(input_path)
    df_before_dedup, dropped_blank_dc = clean_dc(df_raw)
    df_cleaned, duplicate_rows_dc = collapse_duplicates_dc(df_before_dedup)

    output_path = OUTPUT_DIR / f"{PREFIX_DC}_{month_tag}_cleaned.csv"
    df_cleaned.to_csv(output_path, sep=";", index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)
    print(f"Cleaned {len(df_cleaned)} rows -> {output_path}")

    dropped_path = write_dropped_and_dupes(DROPPED_DIR, PREFIX_DC, month_tag, dropped_blank_dc, duplicate_rows_dc)
    print(f"Dropped/duplicate rows written -> {dropped_path}")

    report_path, _ = write_report(
        REPORTS_DIR, PREFIX_DC, month_tag, input_path, df_raw, df_before_dedup, df_cleaned, output_path
    )
    print(f"Report written -> {report_path}")

    return output_path, report_path, dropped_path


# ============================================================
# 2. HubDailyEvents
# ============================================================

LS_COLS_DE = [
    "Date", "CompanyCode", "CompanyName", "Country", "HomeCountry", "HomeCountryCode",
    "Operation", "Feature", "EventAction", "EventCategory", "EventLabel", "EventSection",
    "EventQuestion", "UserType", "Users", "TotalEvents", "UniqueEvents",
    "SessionsWithEvent", "Events/SessionwithEvent",
]
LS_STRING_COLS_DE = [
    "CompanyCode", "CompanyName", "Country", "HomeCountry", "HomeCountryCode", "Operation",
    "EventAction", "EventCategory", "EventLabel", "EventSection", "EventQuestion", "UserType",
]
LS_INT_COLS_DE = ["TotalEvents", "UniqueEvents", "SessionsWithEvent", "Events/SessionwithEvent"]
HTML_COLS_DE = ["EventSection"]

# Duplicate rows are collapsed by grouping on every LS_COLS_DE field except the summed
# measures and summing those. Users isn't in LS_INT_COLS_DE (clean_de never casts it),
# so collapse_duplicates_de casts it defensively before summing.
SUM_COLS_DE = ["Users"] + LS_INT_COLS_DE
GROUP_COLS_DE = [c for c in LS_COLS_DE if c not in SUM_COLS_DE]

RENAME_MAP_DE = {
    "eventAction": "EventAction",
    "eventCategory": "EventCategory",
    "eventLabel": "EventLabel",
    "eventSection": "EventSection",
    "eventQuestion": "EventQuestion",
    "EventsPerSessionWithEvent": "Events/SessionwithEvent",
}

SORT_COLS_DE = ["Date", "CompanyCode", "CompanyName", "Country", "HomeCountry", "HomeCountryCode"]

INPUT_PREFIX_DE = "HubDailyEventData"
PREFIX_DE = "HubDailyEvents"
FILENAME_RE_DE = re.compile(r"^HubDailyEventData_(\d{4})-(\d{2})-\d{2}\.csv$")


def clean_de(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = blank_out_null_text(df)
    df = df.rename(columns=RENAME_MAP_DE)

    present_ls_cols = [c for c in LS_COLS_DE if c in df.columns]
    is_blank = df[present_ls_cols].apply(lambda col: col.str.strip() == "").all(axis=1)
    dropped_blank = df.loc[is_blank].copy()
    df = df.loc[~is_blank].copy()

    missing_key = df["Date"].str.strip() == ""
    dropped_missing_key = df.loc[missing_key].copy()
    df = df.loc[~missing_key].copy()

    dropped = pd.concat([dropped_blank, dropped_missing_key])

    # %f always zero-pads to 6-digit microseconds; slicing off the last 3 leaves milliseconds.
    df["Date"] = pd.to_datetime(df["Date"], format="%Y-%m-%d").dt.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3]

    # Strip HTML before the whitespace pass below, so any double spaces left behind by
    # removing tags get collapsed along with genuine source whitespace.
    for col in HTML_COLS_DE:
        df[col] = df[col].apply(strip_html)

    # Feature has no source column in the raw data; LS_COLS_DE already positions it
    # between Operation and EventAction via the reindex below.
    df["Feature"] = ""

    df = df[LS_COLS_DE]

    for col in LS_STRING_COLS_DE:
        df[col] = df[col].str.strip().str.replace(r"\s+", " ", regex=True)

    for col in LS_INT_COLS_DE:
        df[col] = df[col].astype(int)

    df = df.sort_values(by=SORT_COLS_DE, ascending=True).reset_index(drop=True)

    return df, dropped


def collapse_duplicates_de(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    duplicate_rows = df.loc[df.duplicated(subset=GROUP_COLS_DE, keep=False)].copy()

    for col in SUM_COLS_DE:
        df[col] = df[col].astype(int)
    df = df.groupby(GROUP_COLS_DE, as_index=False)[SUM_COLS_DE].sum()
    return df[LS_COLS_DE], duplicate_rows


def process_de() -> tuple[Path, Path, Path]:
    input_path = find_default_input(INPUT_DIR, INPUT_PREFIX_DE, FILENAME_RE_DE)
    month_tag = month_tag_from_filename(input_path, INPUT_PREFIX_DE, FILENAME_RE_DE)

    df_raw = read_semicolon_csv_protecting_backslashes(input_path)
    df_before_dedup, dropped_blank_de = clean_de(df_raw)
    df_cleaned, duplicate_rows_de = collapse_duplicates_de(df_before_dedup)

    output_path = OUTPUT_DIR / f"{PREFIX_DE}_{month_tag}_cleaned.csv"
    df_cleaned.to_csv(output_path, sep=";", index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)
    print(f"Cleaned {len(df_cleaned)} rows -> {output_path}")

    dropped_path = write_dropped_and_dupes(DROPPED_DIR, PREFIX_DE, month_tag, dropped_blank_de, duplicate_rows_de)
    print(f"Dropped/duplicate rows written -> {dropped_path}")

    report_path, _ = write_report(
        REPORTS_DIR, PREFIX_DE, month_tag, input_path, df_raw, df_before_dedup, df_cleaned, output_path
    )
    print(f"Report written -> {report_path}")

    return output_path, report_path, dropped_path


# ============================================================
# 3. HubDailyUsers
# ============================================================

LS_COLS_DU = [
    "Date", "CompanyCode", "CompanyName", "Country", "HomeCountry", "HomeCountryCode",
    "Operation", "DeviceCategory", "UserType", "Users", "Sessions", "SessionDuration",
]
LS_STRING_COLS_DU = [
    "CompanyCode", "CompanyName", "Country", "HomeCountry", "HomeCountryCode",
    "Operation", "DeviceCategory", "UserType",
]
LS_INT_COLS_DU = ["Sessions", "Users"]
SORT_COLS_DU = ["Date", "CompanyCode", "CompanyName", "Country", "HomeCountry", "HomeCountryCode"]

# Duplicate rows are collapsed by grouping on every LS_COLS_DU field except the summed
# measures and summing those. SessionDuration is a hh:mm:ss string, not numeric -- see
# _hms_to_seconds/_seconds_to_hms below.
SUM_COLS_DU = ["Users", "Sessions", "SessionDuration"]
GROUP_COLS_DU = [c for c in LS_COLS_DU if c not in SUM_COLS_DU]

PREFIX_DU = "HubDailyUsers"
FILENAME_RE_DU = re.compile(r"^HubDailyUsers_(\d{4})-(\d{2})-\d{2}\.csv$")


def clean_du(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = blank_out_null_text(df)

    # Raw SessionDurationInSeconds actually holds hh:mm:ss strings despite its name;
    # kept as-is, not converted.
    df = df.drop(columns=["SessionDuration"]).rename(columns={"SessionDurationInSeconds": "SessionDuration"})

    present_ls_cols = [c for c in LS_COLS_DU if c in df.columns]
    is_blank = df[present_ls_cols].apply(lambda col: col.str.strip() == "").all(axis=1)
    dropped_blank = df.loc[is_blank].copy()
    df = df.loc[~is_blank].copy()

    missing_key = df["Date"].str.strip() == ""
    dropped_missing_key = df.loc[missing_key].copy()
    df = df.loc[~missing_key].copy()

    dropped = pd.concat([dropped_blank, dropped_missing_key])

    # %f always zero-pads to 6-digit microseconds; slicing off the last 3 leaves milliseconds.
    df["Date"] = pd.to_datetime(df["Date"], format="%Y-%m-%d").dt.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3]

    df = df[[c for c in LS_COLS_DU if c in df.columns]]

    for col in LS_STRING_COLS_DU:
        df[col] = df[col].str.strip().str.replace(r"\s+", " ", regex=True)

    for col in LS_INT_COLS_DU:
        df[col] = df[col].astype(int)

    df = df.sort_values(by=SORT_COLS_DU, ascending=True).reset_index(drop=True)

    return df, dropped


def _hms_to_seconds(value: str) -> int:
    h, m, s = value.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def _seconds_to_hms(total_seconds: int) -> str:
    h, remainder = divmod(total_seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def collapse_duplicates_du(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    duplicate_rows = df.loc[df.duplicated(subset=GROUP_COLS_DU, keep=False)].copy()

    df["Users"] = df["Users"].astype(int)
    df["Sessions"] = df["Sessions"].astype(int)
    df = df.groupby(GROUP_COLS_DU, as_index=False).agg({
        "Users": "sum",
        "Sessions": "sum",
        "SessionDuration": lambda s: _seconds_to_hms(sum(_hms_to_seconds(v) for v in s)),
    })
    return df[LS_COLS_DU], duplicate_rows


def process_du() -> tuple[Path, Path, Path]:
    input_path = find_default_input(INPUT_DIR, PREFIX_DU, FILENAME_RE_DU)
    month_tag = month_tag_from_filename(input_path, PREFIX_DU, FILENAME_RE_DU)

    # Plain read, no engine/escapechar -- this file has no HTML content needing escaped
    # quotes, and those options only corrupt the real company name "TBWA\RAAD".
    df_raw = pd.read_csv(input_path, sep=";", dtype=str, keep_default_na=False, encoding="utf-8")
    df_before_dedup, dropped_blank_du = clean_du(df_raw)
    df_cleaned, duplicate_rows_du = collapse_duplicates_du(df_before_dedup)

    output_path = OUTPUT_DIR / f"{PREFIX_DU}_{month_tag}_cleaned.csv"
    df_cleaned.to_csv(output_path, sep=";", index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)
    print(f"Cleaned {len(df_cleaned)} rows -> {output_path}")

    dropped_path = write_dropped_and_dupes(DROPPED_DIR, PREFIX_DU, month_tag, dropped_blank_du, duplicate_rows_du)
    print(f"Dropped/duplicate rows written -> {dropped_path}")

    report_path, _ = write_report(
        REPORTS_DIR, PREFIX_DU, month_tag, input_path, df_raw, df_before_dedup, df_cleaned, output_path
    )
    print(f"Report written -> {report_path}")

    return output_path, report_path, dropped_path


# ============================================================
# 4. HubMonthlyUsers
# ============================================================

LS_COLS_MU = [
    "MonthDate", "Month", "CompanyCode", "CompanyName", "Country",
    "HomeCountry", "HomeCountryCode", "Operation",
    "NewUsers", "Users", "Sessions", "Hits",
]
LS_STRING_COLS_MU = [
    "CompanyCode", "CompanyName", "Country", "HomeCountry", "HomeCountryCode", "Operation",
]
LS_INT_COLS_MU = ["NewUsers", "Users", "Sessions", "Hits"]

# Duplicate rows are collapsed by grouping on every LS_COLS_MU field except the summed
# measures and summing those.
GROUP_COLS_MU = [c for c in LS_COLS_MU if c not in LS_INT_COLS_MU]
SUM_COLS_MU = LS_INT_COLS_MU

PREFIX_MU = "HubMonthlyUsers"
FILENAME_RE_MU = re.compile(r"^HubMonthlyUsers_(\d{4})-(\d{2})-\d{2}\.csv$")


def clean_mu(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = blank_out_null_text(df)
    df = df.rename(columns={"Date": "MonthDate"})

    present_ls_cols = [c for c in LS_COLS_MU if c in df.columns]
    is_blank = df[present_ls_cols].apply(lambda col: col.str.strip() == "").all(axis=1)
    dropped_blank = df.loc[is_blank].copy()
    df = df.loc[~is_blank].copy()

    missing_key = df["MonthDate"].str.strip() == ""
    dropped_missing_key = df.loc[missing_key].copy()
    df = df.loc[~missing_key].copy()

    dropped = pd.concat([dropped_blank, dropped_missing_key])

    # %f always zero-pads to 6-digit microseconds; slicing off the last 3 leaves milliseconds.
    df["MonthDate"] = pd.to_datetime(df["MonthDate"], format="%Y-%m-%d").dt.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3]
    df["Month"] = pd.to_datetime(df["Month"], format="%Y-%m").dt.strftime("%Y %m")

    df = df[[c for c in LS_COLS_MU if c in df.columns]]

    for col in LS_STRING_COLS_MU:
        df[col] = df[col].str.strip().str.replace(r"\s+", " ", regex=True)

    for col in LS_INT_COLS_MU:
        df[col] = df[col].astype(int)

    return df, dropped


def collapse_duplicates_mu(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    duplicate_rows = df.loc[df.duplicated(subset=GROUP_COLS_MU, keep=False)].copy()

    for col in SUM_COLS_MU:
        df[col] = df[col].astype(int)
    df = df.groupby(GROUP_COLS_MU, as_index=False)[SUM_COLS_MU].sum()
    return df[LS_COLS_MU], duplicate_rows


def process_mu() -> tuple[Path, Path, Path]:
    input_path = find_default_input(INPUT_DIR, PREFIX_MU, FILENAME_RE_MU)
    month_tag = month_tag_from_filename(input_path, PREFIX_MU, FILENAME_RE_MU)

    # Plain read, no engine/escapechar -- same reasoning as HubDailyUsers.
    df_raw = pd.read_csv(input_path, sep=";", dtype=str, keep_default_na=False, encoding="utf-8")
    df_before_dedup, dropped_blank_mu = clean_mu(df_raw)
    df_cleaned, duplicate_rows_mu = collapse_duplicates_mu(df_before_dedup)

    output_path = OUTPUT_DIR / f"{PREFIX_MU}_{month_tag}_cleaned.csv"
    df_cleaned.to_csv(output_path, sep=";", index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)
    print(f"Cleaned {len(df_cleaned)} rows -> {output_path}")

    dropped_path = write_dropped_and_dupes(DROPPED_DIR, PREFIX_MU, month_tag, dropped_blank_mu, duplicate_rows_mu)
    print(f"Dropped/duplicate rows written -> {dropped_path}")

    report_path, _ = write_report(
        REPORTS_DIR, PREFIX_MU, month_tag, input_path, df_raw, df_before_dedup, df_cleaned, output_path
    )
    print(f"Report written -> {report_path}")

    return output_path, report_path, dropped_path


# ============================================================
# 5. HubAssessmentResults
# ============================================================

LS_COLS_AR = [
    "Date", "CompanyCode", "CompanyName", "CurrentCountry", "HomeCountry",
    "Operation", "AssessmentType", "SectionName", "Result",
]
LS_STRING_COLS_AR = [
    "CompanyCode", "CompanyName", "CurrentCountry", "HomeCountry",
    "Operation", "AssessmentType", "SectionName", "Result",
]
LS_INT_COLS_AR = []
HTML_COLS_AR = ["SectionName"]
SORT_COLS_AR = ["Date", "CompanyCode", "CompanyName", "CurrentCountry", "HomeCountry", "Operation"]

PREFIX_AR = "HubAssessmentResults"
FILENAME_RE_AR = re.compile(r"^HubAssessmentResults_(\d{4})-(\d{2})-\d{2}\.xlsx$")


def clean_ar(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = blank_out_null_text(df)

    present_ls_cols = [c for c in LS_COLS_AR if c in df.columns]
    is_blank = df[present_ls_cols].apply(lambda col: col.str.strip() == "").all(axis=1)
    dropped_blank = df.loc[is_blank].copy()
    df = df.loc[~is_blank].copy()

    missing_key = df["Date"].str.strip() == ""
    dropped_missing_key = df.loc[missing_key].copy()
    df = df.loc[~missing_key].copy()

    dropped = pd.concat([dropped_blank, dropped_missing_key])

    # The raw timestamp carries 7-digit fractional seconds and a UTC offset (always
    # "+00:00"); %f zero-pads/truncates to 6-digit microseconds, and slicing off the
    # last 3 leaves milliseconds. Dropping the offset from the output format loses no
    # information since every row is already UTC.
    df["Date"] = (
        pd.to_datetime(df["Date"], format="%Y-%m-%d %H:%M:%S.%f %z")
        .dt.strftime("%Y-%m-%d %H:%M:%S.%f")
        .str[:-3]
    )

    for col in HTML_COLS_AR:
        df[col] = df[col].apply(strip_html)

    df["Result"] = df["Result"].str.lower()

    df = df[[c for c in LS_COLS_AR if c in df.columns]]

    for col in LS_STRING_COLS_AR:
        df[col] = df[col].str.strip().str.replace(r"\s+", " ", regex=True)

    for col in LS_INT_COLS_AR:
        df[col] = df[col].astype(int)

    df = df.sort_values(by=SORT_COLS_AR, ascending=True).reset_index(drop=True)

    return df, dropped


def process_ar() -> tuple[Path, Path, Path]:
    input_path = find_default_input(INPUT_DIR, PREFIX_AR, FILENAME_RE_AR, ext="xlsx")
    month_tag = month_tag_from_filename(input_path, PREFIX_AR, FILENAME_RE_AR, ext="xlsx")

    # pd.read_excel reads cell values directly rather than tokenizing a delimited text
    # stream, so there's no escapechar/backslash-protection concept to apply here.
    df_raw = pd.read_excel(input_path, sheet_name="Sheet1", dtype=str, keep_default_na=False)
    df_cleaned, dropped_blank_ar = clean_ar(df_raw)

    output_path = OUTPUT_DIR / f"{PREFIX_AR}_{month_tag}_cleaned.csv"
    df_cleaned.to_csv(output_path, sep=";", index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)
    print(f"Cleaned {len(df_cleaned)} rows -> {output_path}")

    # No dedup step for this dataset (per the notes), so there are no duplicate-collapsed
    # rows to report -- pass an empty frame through.
    dropped_path = write_dropped_and_dupes(DROPPED_DIR, PREFIX_AR, month_tag, dropped_blank_ar, pd.DataFrame())
    print(f"Dropped/duplicate rows written -> {dropped_path}")

    # No dedup step for this dataset (per the notes) -- df_before_dedup=df_cleaned makes
    # "Duplicate rows collapsed" report as 0 while raw/cleaned duplicate counts still show.
    report_path, _ = write_report(
        REPORTS_DIR, PREFIX_AR, month_tag, input_path, df_raw, df_cleaned, df_cleaned, output_path
    )
    print(f"Report written -> {report_path}")

    return output_path, report_path, dropped_path


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    DROPPED_DIR.mkdir(parents=True, exist_ok=True)

    output_path_dc, report_path_dc, dropped_path_dc = process_dc()
    output_path_de, report_path_de, dropped_path_de = process_de()
    output_path_du, report_path_du, dropped_path_du = process_du()
    output_path_mu, report_path_mu, dropped_path_mu = process_mu()
    output_path_ar, report_path_ar, dropped_path_ar = process_ar()

    print("\nCleaned outputs:")
    for label, out_path, rpt_path, drp_path in [
        ("DailyContent", output_path_dc, report_path_dc, dropped_path_dc),
        ("DailyEvents", output_path_de, report_path_de, dropped_path_de),
        ("DailyUsers", output_path_du, report_path_du, dropped_path_du),
        ("MonthlyUsers", output_path_mu, report_path_mu, dropped_path_mu),
        ("AssessmentResults", output_path_ar, report_path_ar, dropped_path_ar),
    ]:
        print(f"  {label:14s} -> {out_path.name}  (report: {rpt_path.name}, dropped/dupes: {drp_path.name})")


if __name__ == "__main__":
    main()
