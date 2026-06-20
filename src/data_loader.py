"""
Theme 1: Parking-Induced Congestion
Module 1: Data Loading & Cleaning

Usage:
    python data_loader.py
"""

import pandas as pd
import numpy as np
import json
import time
from config import DATA_FILE, COLUMNS_TO_DROP


def load_parking_data(filepath=DATA_FILE):
    """
    Load the parking violations CSV with optimized dtypes.
    Returns the raw DataFrame.
    """
    print(f"Loading {filepath}...")
    start = time.time()

    # Define dtypes upfront to reduce memory & speed up parsing
    dtype_map = {
        'latitude': 'float64',
        'longitude': 'float64',
        'vehicle_type': 'category',
        'violation_type': 'str',
        'offence_code': 'str',
        'police_station': 'category',
        'junction_name': 'category',
        'center_code': 'float32',  # int64 has nulls sometimes, use float
        'validation_status': 'category',
        'location': 'str',
    }

    df = pd.read_csv(
        filepath,
        dtype=dtype_map,
        parse_dates=['created_datetime'],
        low_memory=False
    )

    elapsed = time.time() - start
    print(f"  Loaded {len(df):,} rows x {len(df.columns)} cols in {elapsed:.1f}s")
    return df


def clean_parking_data(df):
    """
    Clean the parking violations DataFrame:
    - Drop irrelevant / PII columns
    - Parse violation_type JSON array into boolean flags
    - Parse offence_code JSON array into severity count
    - Keep ALL rows (unvalidated tickets still represent physical vehicles)
    """
    print("Cleaning data...")
    initial_cols = len(df.columns)

    # 1. Drop noise columns
    cols_to_drop = [c for c in COLUMNS_TO_DROP if c in df.columns]
    df = df.drop(columns=cols_to_drop)
    print(f"  Dropped {len(cols_to_drop)} columns ({initial_cols} -> {len(df.columns)})")

    # 2. Parse violation_type JSON array -> individual boolean flags
    df = _parse_violation_types(df)

    # 3. Parse offence_code JSON array -> count (severity proxy)
    df['offence_count'] = df['offence_code'].apply(_count_json_array)
    df = df.drop(columns=['offence_code'])

    # 4. Handle lat/lon nulls (drop rows with missing coordinates — can't geolocate)
    null_coords = df[['latitude', 'longitude']].isnull().any(axis=1).sum()
    if null_coords > 0:
        print(f"  Dropping {null_coords:,} rows with null coordinates")
        df = df.dropna(subset=['latitude', 'longitude'])

    # 5. Handle vehicle_type nulls — fill with 'UNKNOWN'
    null_vtype = df['vehicle_type'].isnull().sum()
    if null_vtype > 0:
        print(f"  Filling {null_vtype:,} null vehicle_types with 'UNKNOWN'")
        # Category dtype needs the category added first
        if hasattr(df['vehicle_type'], 'cat'):
            df['vehicle_type'] = df['vehicle_type'].cat.add_categories('UNKNOWN')
        df['vehicle_type'] = df['vehicle_type'].fillna('UNKNOWN')

    # 6. Drop location column (free-text, too noisy for ML)
    if 'location' in df.columns:
        df = df.drop(columns=['location'])

    print(f"  Final shape: {df.shape}")
    return df


def convert_utc_to_ist(df, datetime_col='created_datetime'):
    """
    Convert UTC timestamps to IST (UTC + 5:30).
    Adds 'ist_datetime' column and extracts date for time-based splitting.
    """
    print("Converting UTC -> IST...")

    # Ensure datetime
    if not pd.api.types.is_datetime64_any_dtype(df[datetime_col]):
        df[datetime_col] = pd.to_datetime(df[datetime_col], format='mixed', utc=True)

    # Strip timezone info if present, then add 5h30m
    if df[datetime_col].dt.tz is not None:
        df[datetime_col] = df[datetime_col].dt.tz_localize(None)

    df['ist_datetime'] = df[datetime_col] + pd.Timedelta(hours=5, minutes=30)
    df['ist_date'] = df['ist_datetime'].dt.date

    print(f"  IST date range: {df['ist_date'].min()} to {df['ist_date'].max()}")
    return df


def _parse_violation_types(df):
    """
    Parse the violation_type column from JSON array strings like
    '["WRONG PARKING","PARKING NEAR ROAD CROSSING"]'
    into individual boolean flag columns.
    """
    print("  Parsing violation_type JSON arrays...")

    # First, collect all unique violation types across the dataset
    all_types = set()

    def extract_types(val):
        if pd.isna(val):
            return []
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    # Extract all types (sample first for speed, then full)
    type_lists = df['violation_type'].apply(extract_types)
    for tl in type_lists:
        all_types.update(tl)

    print(f"    Found {len(all_types)} unique violation types: {sorted(all_types)}")

    # Create boolean columns for each violation type
    for vtype in sorted(all_types):
        col_name = 'viol_' + vtype.lower().replace(' ', '_').replace('/', '_')
        df[col_name] = type_lists.apply(lambda x: vtype in x).astype('int8')

    # Also keep a count of violation types per row (multi-violation = more severe)
    df['violation_count'] = type_lists.apply(len).astype('int8')

    # Drop the original string column
    df = df.drop(columns=['violation_type'])

    return df


def _count_json_array(val):
    """Count items in a JSON array string like '[112,104]'. Returns 0 on failure."""
    if pd.isna(val):
        return 0
    try:
        parsed = json.loads(val)
        if isinstance(parsed, list):
            return len(parsed)
    except (json.JSONDecodeError, TypeError):
        pass
    return 0


def print_data_summary(df):
    """Print a comprehensive summary of the cleaned DataFrame."""
    print("\n" + "=" * 70)
    print("DATA SUMMARY")
    print("=" * 70)
    print(f"Shape: {df.shape[0]:,} rows × {df.shape[1]} columns")
    print(f"\nColumns: {list(df.columns)}")
    print(f"\nDtypes:\n{df.dtypes}")
    print(f"\nNull counts:\n{df.isnull().sum()}")

    if 'vehicle_type' in df.columns:
        print(f"\nVehicle type distribution:")
        print(df['vehicle_type'].value_counts().head(15))

    if 'police_station' in df.columns:
        print(f"\nTop police stations:")
        print(df['police_station'].value_counts().head(10))

    if 'validation_status' in df.columns:
        print(f"\nValidation status:")
        print(df['validation_status'].value_counts(dropna=False))

    if 'ist_datetime' in df.columns:
        print(f"\nIST hour distribution (peak hours check):")
        hours = df['ist_datetime'].dt.hour.value_counts().sort_index()
        print(hours)

    if 'violation_count' in df.columns:
        print(f"\nViolation count per ticket:")
        print(df['violation_count'].value_counts().sort_index())

    if 'offence_count' in df.columns:
        print(f"\nOffence count per ticket:")
        print(df['offence_count'].value_counts().sort_index())


# =====================================================================
# STANDALONE TEST
# =====================================================================
if __name__ == '__main__':
    df = load_parking_data()
    df = clean_parking_data(df)
    df = convert_utc_to_ist(df)
    print_data_summary(df)

    # Save cleaned data for next module
    output_path = 'data/processed/cleaned_parking_data.csv'
    print(f"\nSaving cleaned data to {output_path}...")
    df.to_csv(output_path, index=False)
    print("Done!")
