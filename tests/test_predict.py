# Simple script to test predictions from the predictive engine.
import pandas as pd
from src.modeling.predictive_engine import generate_prediction
import json

if __name__ == '__main__':
    print("Loading data...")
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, '..', 'data', 'processed', 'cleaned_parking_data.csv')
    df = pd.read_csv(csv_path)
    df['ist_date'] = pd.to_datetime(df['ist_datetime'], format='mixed').dt.strftime('%Y-%m-%d')
    print("Generating prediction...")
    res = generate_prediction(df)
    print(f"Status: {res['status']}")
    print(f"Message: {res['message']}")
    print(f"Number of ranked zones: {len(res['ranked_zones'])}")
    if res['ranked_zones']:
        print("Top zone:")
        print(json.dumps(res['ranked_zones'][0], indent=2))
