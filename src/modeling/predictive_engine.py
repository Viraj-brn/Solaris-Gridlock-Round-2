import pandas as pd
import numpy as np
import json

from src.modeling.knn_core import (
    MODEL_CONFIDENCE_THRESHOLD,
    MODEL_FEATURE_WEIGHTS,
    MODEL_K,
    aggregate_daily_pcu,
    calendar_distance,
    distance_weights,
    generate_calendar_features,
    is_hotspot,
    select_neighbor_dates,
    zone_medians,
)


def get_similarity(vec1, vec2):
    """Compatibility wrapper around the canonical calendar distance."""
    return calendar_distance(vec1, vec2, MODEL_FEATURE_WEIGHTS)

def generate_prediction(current_df, confidence_threshold=MODEL_CONFIDENCE_THRESHOLD):
    """
    Generates a predictive heatmap and ranked zone list for "Tomorrow"
    using KNN on calendar features and descriptive hotspot profiling.
    """
    if current_df.empty:
        return {
            'heatmap': [],
            'zone_markers': [],
            'ranked_zones': [],
            'status': 'insufficient_history',
            'available_history_days': 0,
            'required_history_days': MODEL_K,
            'message': 'Insufficient history: no candidate days are available.',
        }
        
    if 'hour' not in current_df.columns:
        current_df['hour'] = pd.to_datetime(current_df['ist_datetime'], format='mixed').dt.hour
        
    last_date_str = current_df['ist_date'].max()
    last_date = pd.to_datetime(last_date_str)
    tomorrow_date = last_date + pd.Timedelta(days=1)
    
    # Load hotspot classifications if available
    try:
        with open('frontend/data/time_blocks.json', 'r') as f:
            hotspot_classifications = json.load(f)
    except:
        hotspot_classifications = {}
        
    # Avoid SettingWithCopyWarning if current_df is a slice
    current_df = current_df.copy()

    # Aggregate historical daily data
    daily_counts = aggregate_daily_pcu(current_df).rename(columns={'impact': 'count'})
    
    unique_dates = daily_counts['ist_date'].unique()
    if len(unique_dates) < MODEL_K:
        return {
            'heatmap': [],
            'zone_markers': [],
            'ranked_zones': [],
            'status': 'insufficient_history',
            'available_history_days': int(len(unique_dates)),
            'required_history_days': MODEL_K,
            'message': (
                f'Insufficient history: need at least {MODEL_K} '
                f'days, found {len(unique_dates)}.'
            ),
        }

    neighbor_rows = select_neighbor_dates(
        tomorrow_date, unique_dates, MODEL_FEATURE_WEIGHTS, k=MODEL_K
    )
    knn_dates = [date for date, _ in neighbor_rows]
    actual_k = len(knn_dates)
    knn_weights = distance_weights(neighbor_rows)
    medians = zone_medians(
        daily_counts.rename(columns={'count': 'impact'}), unique_dates
    )
    
    predicted_ranked_zones = []
    predicted_markers = []
    
    # Get centroids
    try:
        centroids = pd.read_csv('data/processed/zone_centroids.csv')
    except:
        centroids = pd.DataFrame(columns=['police_station', 'lat_mean', 'lon_mean'])
        
    all_zones = daily_counts['police_station'].unique()
    
    for z in all_zones:
        z_data = daily_counts[daily_counts['police_station'] == z]
        z_median = medians.get(z, 0)
        
        # Get counts for the KNN days
        knn_counts = []
        for i, kd in enumerate(knn_dates):
            row = z_data[z_data['ist_date'] == kd]
            if not row.empty:
                knn_counts.append(row['count'].values[0])
            else:
                knn_counts.append(0)
            
        # Prediction is distance-weighted mean of KNN days
        pred_count = int(np.sum(np.array(knn_counts) * np.array(knn_weights)) / np.sum(knn_weights))
        if pred_count == 0:
            continue
            
        agreements = np.array([is_hotspot(c, z_median) for c in knn_counts], dtype=float)
        neighbor_agreement = float(np.average(agreements, weights=knn_weights))
        agreement_score = round(neighbor_agreement * 100, 1)
        
        # Profiling (Task D)
        zone_raw_data = current_df[current_df['police_station'] == z]
        top_veh = zone_raw_data['vehicle_type'].mode()[0] if not zone_raw_data['vehicle_type'].mode().empty else "Unknown"
        violation_cols = [c for c in zone_raw_data.columns if c.startswith('viol_')]
        if violation_cols:
            violation_totals = zone_raw_data[violation_cols].sum()
            top_violation_col = violation_totals.idxmax()
            top_violation = top_violation_col.replace('viol_', '').replace('_', ' ').title()
        else:
            top_violation_col = None
            top_violation = 'Unknown'
        
        # Junction/Landmark context
        has_junction = 'junction_name' in zone_raw_data.columns
        if has_junction and not zone_raw_data['junction_name'].mode().empty:
            j_mode = zone_raw_data['junction_name'].mode()[0]
            top_landmark = j_mode if j_mode != 'No Junction' else "Street Segment"
        else:
            top_landmark = "Street Segment"
            
        # Peak time of day
        hour_counts = zone_raw_data['hour'].value_counts()
        peak_hour = hour_counts.idxmax() if not hour_counts.empty else 12
        
        c_row = centroids[centroids['police_station'] == z]
        lat, lng = 12.9716, 77.5946
        if not c_row.empty:
            lat = c_row['lat_mean'].values[0]
            lng = c_row['lon_mean'].values[0]
            
        hc = hotspot_classifications.get(z, {})
        duration_class = hc.get('duration', 'Unknown')
        burst_class = hc.get('burstiness', 'Unknown')
        
        predicted_ranked_zones.append({
            'zone': z,
            'count': pred_count,
            'neighbor_agreement_pct': agreement_score,
            'profile_vehicle': top_veh,
            'profile_violation': top_violation,
            'profile_violation_col': top_violation_col,
            'profile_landmark': top_landmark,
            'profile_peak_hour': int(peak_hour),
            'duration_class': duration_class,
            'burst_class': burst_class
        })
        
        predicted_markers.append({
            'zone': z,
            'count': pred_count,
            'lat': float(lat),
            'lng': float(lng)
        })
        
    # Apply the frozen weighted-neighbor-agreement threshold.
    predicted_ranked_zones = [z for z in predicted_ranked_zones if z['neighbor_agreement_pct'] >= confidence_threshold]
    
    # Sort and apply display cap (e.g., top 100)
    predicted_ranked_zones = sorted(predicted_ranked_zones, key=lambda x: x['count'], reverse=True)[:100]
    
    valid_zones = {z['zone'] for z in predicted_ranked_zones}
    predicted_markers = [m for m in predicted_markers if m['zone'] in valid_zones]
    
    # Generate heatmap
    predicted_heatmap = []
    for z in predicted_ranked_zones:
        zone_data = current_df[current_df['police_station'] == z['zone']]
        if not zone_data.empty:
            sample_size = min(int(z['count']), len(zone_data), 1000)
            if sample_size > 0:
                sampled = zone_data.sample(n=sample_size, replace=True)
                for _, row in sampled.iterrows():
                    lat_jitter = np.random.normal(0, 0.0005)
                    lng_jitter = np.random.normal(0, 0.0005)
                    predicted_heatmap.append({
                        'lat': row['latitude'] + lat_jitter, 
                        'lng': row['longitude'] + lng_jitter, 
                        'weight': 1.0,
                        'zone': z['zone'],
                    })
                    
    return {
        'heatmap': predicted_heatmap,
        'zone_markers': predicted_markers,
        'ranked_zones': predicted_ranked_zones,
        'prediction_date': tomorrow_date.strftime('%Y-%m-%d'),
        'history_start': str(min(unique_dates)),
        'history_end': str(max(unique_dates)),
        'history_days': int(len(unique_dates)),
        'neighbor_count': actual_k,
        'confidence_threshold': confidence_threshold,
        'status': 'ok',
        'message': f'KNN Prediction generated for {tomorrow_date.strftime("%Y-%m-%d")}.'
    }
