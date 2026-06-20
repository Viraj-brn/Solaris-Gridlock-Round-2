import pandas as pd

# Temporal analysis for both datasets
print("=" * 80)
print("TEMPORAL ANALYSIS - PARKING VIOLATIONS")
print("=" * 80)
df1 = pd.read_csv(r"dataset round2/jan to may police violation_anonymized791b166.csv", low_memory=False)
df1['created_datetime'] = pd.to_datetime(df1['created_datetime'], format='mixed', utc=True)
df1['hour'] = df1['created_datetime'].dt.hour
df1['day_of_week'] = df1['created_datetime'].dt.day_name()
df1['month'] = df1['created_datetime'].dt.month
df1['date'] = df1['created_datetime'].dt.date

print("Violations by HOUR:")
print(df1['hour'].value_counts().sort_index())
print("\nViolations by DAY OF WEEK:")
print(df1['day_of_week'].value_counts())
print("\nViolations by MONTH:")
print(df1['month'].value_counts().sort_index())

# Top violation hotspots (lat/lon rounded to 3 decimals as proxy for geohash)
df1['lat_round'] = df1['latitude'].round(3)
df1['lon_round'] = df1['longitude'].round(3)
hotspots = df1.groupby(['lat_round', 'lon_round']).size().sort_values(ascending=False).head(20)
print("\nTop 20 PARKING HOTSPOTS (rounded lat/lon):")
print(hotspots)

# Cross-analysis: top junctions by hour
print("\nTop 5 junctions - violations by peak hours (8-11, 17-20):")
top_junctions = df1[df1['junction_name'] != 'No Junction']['junction_name'].value_counts().head(5).index
for junc in top_junctions:
    junc_data = df1[df1['junction_name'] == junc]
    peak_morning = len(junc_data[(junc_data['hour'] >= 8) & (junc_data['hour'] <= 11)])
    peak_evening = len(junc_data[(junc_data['hour'] >= 17) & (junc_data['hour'] <= 20)])
    off_peak = len(junc_data) - peak_morning - peak_evening
    print(f"  {junc}: Morning={peak_morning}, Evening={peak_evening}, OffPeak={off_peak}")

# Weekend vs weekday
df1['is_weekend'] = df1['day_of_week'].isin(['Saturday', 'Sunday'])
print(f"\nWeekday violations: {len(df1[~df1['is_weekend']])}")
print(f"Weekend violations: {len(df1[df1['is_weekend']])}")
print(f"Weekend/Weekday ratio: {len(df1[df1['is_weekend']]) / len(df1[~df1['is_weekend']]):.2f}")

# Top police stations on weekends
print("\nTop police stations on WEEKENDS:")
print(df1[df1['is_weekend']]['police_station'].value_counts().head(10))

print("\n" + "=" * 80)
print("TEMPORAL ANALYSIS - EVENT DATA")
print("=" * 80)
df2 = pd.read_csv(r"dataset round2/Astram event data_anonymized - Astram event data_anonymizedb40ac87.csv", low_memory=False)
df2['start_datetime'] = pd.to_datetime(df2['start_datetime'], format='mixed')
df2['hour'] = df2['start_datetime'].dt.hour
df2['day_of_week'] = df2['start_datetime'].dt.day_name()
df2['month'] = df2['start_datetime'].dt.month

print("Events by HOUR:")
print(df2['hour'].value_counts().sort_index())
print("\nEvents by DAY OF WEEK:")
print(df2['day_of_week'].value_counts())
print("\nEvents by MONTH:")
print(df2['month'].value_counts().sort_index())

# Event cause by priority
print("\nHIGH priority events by cause:")
high_prio = df2[df2['priority'] == 'High']
print(high_prio['event_cause'].value_counts().head(10))

# Road closure events
print("\nEvents requiring ROAD CLOSURE by cause:")
closures = df2[df2['requires_road_closure'] == True]
print(closures['event_cause'].value_counts())

# Duration analysis (where end_datetime exists)
df2['end_datetime'] = pd.to_datetime(df2['end_datetime'], format='mixed', errors='coerce')
df2['duration_hours'] = (df2['end_datetime'] - df2['start_datetime']).dt.total_seconds() / 3600
valid_dur = df2[df2['duration_hours'].notna() & (df2['duration_hours'] > 0) & (df2['duration_hours'] < 720)]
print(f"\nEvent DURATION stats (hours):")
print(valid_dur['duration_hours'].describe())
print(f"\nAverage duration by event_cause:")
print(valid_dur.groupby('event_cause')['duration_hours'].mean().sort_values(ascending=False).head(10))

# Planned vs unplanned event causes
print("\nPLANNED event causes:")
print(df2[df2['event_type'] == 'planned']['event_cause'].value_counts())
print("\nUNPLANNED event causes (top 10):")
print(df2[df2['event_type'] == 'unplanned']['event_cause'].value_counts().head(10))

# High-impact corridors
print("\nTop corridors for HIGH priority events:")
print(high_prio['corridor'].value_counts().head(15))
