import pandas as pd
import src.modeling.predictive_engine

# Load raw data
raw_df = pd.read_csv('c:/Users/ASUS/Code files/Solaris/cleaned_parking_data.csv')
raw_df['ist_datetime'] = pd.to_datetime(raw_df['ist_datetime'], format='mixed', utc=True)
raw_df['hour'] = raw_df['ist_datetime'].dt.hour
raw_df['day_of_week'] = raw_df['ist_datetime'].dt.dayofweek

# Call prediction
prediction_payload = predictive_engine.generate_prediction(raw_df)

# Output results as markdown
print(prediction_payload['message'])
print("| Zone | Predicted Impact | Weighted Neighbor Agreement | Profile Vehicle | Profile Peak Hour | Duration Class | Burst Class |")
print("|------|----------------------|---------------------------|-----------------|-------------------|----------------|-------------|")
for z in prediction_payload['ranked_zones'][:10]: # Top 10 zones
    print(f"| {z['zone']} | {z['count']} | {z['neighbor_agreement_pct']}% | {z['profile_vehicle']} | {z['profile_peak_hour']}:00 | {z['duration_class']} | {z['burst_class']} |")
