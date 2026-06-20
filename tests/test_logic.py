# Tests data extraction and breakdown logic on parking data.
import pandas as pd
import os
script_dir = os.path.dirname(os.path.abspath(__file__))
csv_path = os.path.join(script_dir, '..', 'data', 'processed', 'cleaned_parking_data.csv')
raw_df = pd.read_csv(csv_path)
raw_df['ist_datetime'] = pd.to_datetime(raw_df['ist_datetime'], format='mixed', utc=True)
raw_df['hour'] = raw_df['ist_datetime'].dt.hour
filtered = raw_df.head(100)
try:
    time_patterns = {int(k): int(v) for k, v in filtered.groupby('hour').size().items()}
    print("time_patterns OK")
except Exception as e:
    import traceback
    traceback.print_exc()

try:
    vehicle_breakdown = {str(k): int(v) for k, v in filtered['vehicle_type'].value_counts().items()}
    print("vehicle_breakdown OK")
except Exception as e:
    import traceback
    traceback.print_exc()

try:
    viol_cols = [c for c in filtered.columns if c.startswith('viol_')]
    violation_breakdown = {k.replace('viol_', '').replace('_', ' ').title(): int(v) for k, v in filtered[viol_cols].sum().items() if v > 0}
    print("violation_breakdown OK")
except Exception as e:
    import traceback
    traceback.print_exc()
