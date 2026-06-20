# Script to analyze and summarize the parking violations dataset.
import pandas as pd
import sys

print("=" * 80)
print("PROBLEM 1: PARKING VIOLATIONS DATASET (Jan-May)")
print("=" * 80)
df1 = pd.read_csv(r"dataset round2/jan to may police violation_anonymized791b166.csv", low_memory=False)
print(f"Shape: {df1.shape}")
print(f"\nColumns: {list(df1.columns)}")
print(f"\nDtypes:\n{df1.dtypes}")
print(f"\nNull counts:\n{df1.isnull().sum()}")
print(f"\nViolation types (value_counts top 20):\n{df1['violation_type'].value_counts().head(20)}")
print(f"\nVehicle types:\n{df1['vehicle_type'].value_counts().head(15)}")
print(f"\nPolice stations:\n{df1['police_station'].value_counts().head(20)}")
print(f"\nValidation status:\n{df1['validation_status'].value_counts()}")
print(f"\nDate range: {df1['created_datetime'].min()} to {df1['created_datetime'].max()}")
print(f"\nSample locations:\n{df1['location'].dropna().head(5).tolist()}")
print(f"\nJunction names:\n{df1['junction_name'].value_counts().head(15)}")
print(f"\nCenter codes:\n{df1['center_code'].value_counts().head(15)}")
print(f"\nLat range: {df1['latitude'].min()} to {df1['latitude'].max()}")
print(f"Lon range: {df1['longitude'].min()} to {df1['longitude'].max()}")
