"""
Theme 1: Parking-Induced Congestion
Module 6: Heatmap Visualization Data Generator

Generates JSON data files for the Mappls (MapMyIndia) heatmap visualization.
Outputs:
  - heatmap_points.json    (violation lat/lng for heatmap layer)
  - zone_markers.json      (zone centroids + strategies for marker popups)
  - zone_directives.json   (full directive text for each zone)

Usage:
    python generate_map_data.py
"""

import pandas as pd
import numpy as np
import json
import sys
import os
import math

# Load POIs
try:
    with open('frontend/data/pois.json', 'r') as f:
        POIS = json.load(f)
except Exception:
    POIS = []

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = math.sin(dLat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_nearest_poi(lat, lng):
    if not POIS: return None
    min_dist = float('inf')
    nearest = None
    for p in POIS:
        d = haversine(lat, lng, p['lat'], p['lng'])
        if d < min_dist:
            min_dist = d
            nearest = p
    if min_dist <= 2.0:
        return f"{int(min_dist*1000)}m from {nearest['name']} ({nearest['type']})"
    return None


from config import (
    PCU_MAP, PCU_DEFAULT, ZONE_ARCHETYPES, ZONE_ARCHETYPE_DEFAULT,
    HIGH_IMPACT_THRESHOLD, CBD_LAT, CBD_LON,
)
from src.modeling.decision_engine import (
    build_zone_profile, select_strategies, generate_directive, generate_implementation_playbook,
    STRATEGY_CATALOG, DAY_NAMES,
)


def generate_heatmap_points(raw_df, sample_fraction=0.3):
    """
    Generate heatmap data points from raw violation data.
    Each point is {lat, lng, weight} where weight = PCU value.
    
    sample_fraction: fraction of points to include (0.3 = 30% for performance)
    """
    print("Generating heatmap points...")

    # Sample for browser performance (298K points is too heavy)
    if sample_fraction < 1.0:
        sampled = raw_df.sample(frac=sample_fraction, random_state=42)
        print(f"  Sampled {len(sampled):,} / {len(raw_df):,} points ({sample_fraction:.0%})")
    else:
        sampled = raw_df

    # Build points with PCU weight
    vtype_str = sampled['vehicle_type'].astype(str)
    weights = vtype_str.map(PCU_MAP).fillna(PCU_DEFAULT)

    points = []
    for _, row in sampled.iterrows():
        points.append({
            'lat': round(float(row['latitude']), 6),
            'lng': round(float(row['longitude']), 6),
            'weight': float(weights.loc[row.name]),
        })

    print(f"  Generated {len(points):,} heatmap points")
    return points


def generate_zone_markers(aggregated_df, hours=[10], day_of_week=6):
    """
    Generate zone marker data with strategy information for map popups.
    Each marker has: lat, lng, zone name, PCU score, strategies, colors.
    """
    print(f"Generating zone markers for {DAY_NAMES[day_of_week]} hours={hours} IST...")

    zones = aggregated_df['police_station'].unique()
    markers = []

    for zone in sorted(zones):
        profile = build_zone_profile(aggregated_df, zone, hours, day_of_week)
        if profile is None or profile['avg_pcu_impact'] == 0:
            continue

        strategies = select_strategies(profile)

        # Determine severity color
        pcu = profile['avg_pcu_impact']
        if pcu > HIGH_IMPACT_THRESHOLD:
            severity = 'CRITICAL'
            color = '#FF1744'  # Red
        elif pcu > HIGH_IMPACT_THRESHOLD / 2:
            severity = 'HIGH'
            color = '#FF9100'  # Orange
        elif pcu > HIGH_IMPACT_THRESHOLD / 4:
            severity = 'MODERATE'
            color = '#FFEA00'  # Yellow
        else:
            severity = 'LOW'
            color = '#00E676'  # Green

        # Build strategy summary for popup
        strategy_list = []
        for strategy_key, reason in strategies:
            info = STRATEGY_CATALOG[strategy_key]
            playbook = generate_implementation_playbook(profile, strategy_key)
            strategy_list.append({
                'name': info['name'],
                'source': info['source'],
                'action': info['action'],
                'reason': reason,
                'playbook': playbook
            })

        marker = {
            'lat': round(float(profile['lat']), 6),
            'lng': round(float(profile['lon']), 6),
            'zone': str(zone),
            'archetype': profile['archetype'],
            'pcu_impact': round(pcu, 1),
            'severity': severity,
            'color': color,
            'two_wheeler_pct': round(profile['two_wheeler_ratio'] * 100, 1),
            'auto_pct': round(profile['three_wheeler_ratio'] * 100, 1),
            'heavy_pct': round(profile['heavy_vehicle_ratio'] * 100, 1),
            'spatial_lag_pcu': round(profile['spatial_lag_pcu'], 1),
            'validation_ratio_pct': round(profile['validation_ratio'] * 100, 1),
            'historical_violations': int(profile['historical_violations']),
            'distance_to_cbd_km': round(profile['distance_to_cbd'], 1),
            'strategies': strategy_list,
            'strategy_count': len(strategy_list),
            'poi_context': get_nearest_poi(profile['lat'], profile['lon'])
        }
        markers.append(marker)

    # Sort by PCU impact descending
    markers.sort(key=lambda x: x['pcu_impact'], reverse=True)

    print(f"  Generated {len(markers)} zone markers")
    print(f"  CRITICAL zones: {sum(1 for m in markers if m['severity'] == 'CRITICAL')}")
    print(f"  HIGH zones: {sum(1 for m in markers if m['severity'] == 'HIGH')}")
    print(f"  MODERATE zones: {sum(1 for m in markers if m['severity'] == 'MODERATE')}")
    print(f"  LOW zones: {sum(1 for m in markers if m['severity'] == 'LOW')}")

    return markers


def save_map_data(heatmap_points, zone_markers, output_dir='.'):
    """Save all map data as JSON files."""
    # Heatmap points
    heatmap_path = os.path.join(output_dir, 'frontend/data/heatmap_points.json')
    with open(heatmap_path, 'w') as f:
        json.dump(heatmap_points, f)
    print(f"  Saved {len(heatmap_points):,} heatmap points -> {heatmap_path}")

    # Zone markers
    markers_path = os.path.join(output_dir, 'frontend/data/zone_markers.json')
    with open(markers_path, 'w') as f:
        json.dump(zone_markers, f, indent=2)
    print(f"  Saved {len(zone_markers)} zone markers -> {markers_path}")


# =============================================================================
# STANDALONE TEST
# =============================================================================
if __name__ == '__main__':
    from data_loader import load_parking_data, clean_parking_data, convert_utc_to_ist

    # Load raw data for heatmap points
    print("Loading raw data for heatmap...")
    df = load_parking_data()
    df = clean_parking_data(df)
    df = convert_utc_to_ist(df)

    # Generate heatmap points (30% sample for browser performance)
    heatmap_points = generate_heatmap_points(df, sample_fraction=0.3)

    # Load aggregated data for zone markers
    print("\nLoading aggregated data for zone markers...")
    try:
        aggregated = pd.read_csv('data/processed/aggregated_zone_hourly.csv')
    except FileNotFoundError:
        from feature_engineer import engineer_all_features
        aggregated, _, _ = engineer_all_features(df)

    # Generate markers for Sunday 10 AM
    zone_markers = generate_zone_markers(aggregated, hour=10, day_of_week=6)

    # Save
    save_map_data(heatmap_points, zone_markers)

    print("\nMap data generation complete!")
    print("Open bangalore_heatmap.html in your browser after adding your Mappls API key.")
