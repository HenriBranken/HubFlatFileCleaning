import pandas as pd
import io
import re

INPUT_FILE = 'Compare/HubAssessmentResults.csv'
OUTPUT_FILE = 'Compare/dupes/HubAR__dupes.csv'
ENCODING = 'cp1252'  # "cp1252"  /  "utf-8"


# 1. Load the CSV file
filename =  INPUT_FILE  # Replace with your actual file name

with open(filename, "r", encoding="cp1252") as f:
    raw_text = f.read()

# Protect literal backslashes that aren't a genuine CSV \" escape
protected_text = re.sub(r'\\(?!")', r"\\\\", raw_text)

df = pd.read_csv(
    io.StringIO(protected_text), sep=";", engine="python", escapechar="\\",
    dtype=str, keep_default_na=False, encoding="cp1252",
)

# Keep track of original columns to check for exact row matches
original_columns = list(df.columns)


# 2. Check for duplicates (keep='first' ensures we only count the EXTRA copies, not the original)
# This creates a boolean mask where True means the row is a subsequent duplicate
is_duplicate = df.duplicated(subset=original_columns, keep='first')
num_duplicates = is_duplicate.sum()

# Answer the first two questions
print(f"Are there duplicate rows? {'Yes' if num_duplicates > 0 else 'No'}")
print(f"How many duplicate rows? {num_duplicates}\n")

if num_duplicates > 0:
    # 3. Add the 'dupe_id' column 
    # .ngroup() assigns a unique integer to each distinct group of identical rows
    df['dupe_id'] = df.groupby(original_columns).ngroup()
    
    # 4. Extract ONLY the duplicated rows (excluding the original occurrence)
    duplicates_only_df = df[is_duplicate]
    
    # 5. Output the result using ';' as a delimiter
    print("--- Extracted Duplicate Rows ---")
    
    # Generate the CSV string to output to the console
    output_string = duplicates_only_df.to_csv(sep=';', index=False)
    
    # Optional: If you want to save this directly to a new file, uncomment the line below:
    duplicates_only_df.to_csv(OUTPUT_FILE, sep=';', index=False)