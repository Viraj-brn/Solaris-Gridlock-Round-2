"""
Theme 1: Parking-Induced Congestion
Module 2: Feature Engineering

Takes the cleaned DataFrame from data_loader and produces ML-ready features.
Inspired by global strategies: Vietnam, Indonesia, Taipei, Bangkok, SFpark, Barcelona, Rwanda.

Usage:
    python feature_engineer.py
"""

import pandas as pd
import numpy as np
import math
from config import (
    PCU_MAP, PCU_DEFAULT,
    TWO_WHEELER_TYPES, THREE_WHEELER_TYPES, HEAVY_VEHICLE_TYPES,
    ZONE_ARCHETYPES, ZONE_ARCHETYPE_DEFAULT,
    CBD_LAT, CBD_LON,
    SPILLOVER_RADIUS_KM,
    PERSISTENCE_THRESHOLD, WEEKEND_SURGE_THRESHOLD,
)


# TEMPORAL FEATURES

def add_temporal_features(df):
    """
    Extract temporal features from ist_datetime.
    Includes cyclical encoding (sin/cos) for hour and day_of_week
    to capture the circular nature of time.
    """
    print("Adding temporal features...")

    df['hour'] = df['ist_datetime'].dt.hour
    df['day_of_week'] = df['ist_datetime'].dt.dayofweek   # 0=Mon, 6=Sun
    df['month'] = df['ist_datetime'].dt.month
    df['is_weekend'] = df['day_of_week'].isin([5, 6]).astype('int8')

    # Cyclical encoding - Your Round 1 secret weapon
    df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
    df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
    df['day_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
    df['day_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)

    # Calendar Features (Mocked for 2023/2024 dates commonly seen in Bangalore data)
    # Festivals (e.g., Deepavali, Dasara, Ganesh Chaturthi, Ugadi)
    FESTIVAL_DATES = [
        '2023-03-22', '2023-09-18', '2023-10-23', '2023-10-24', '2023-11-12', '2023-11-13',
        '2024-04-09', '2024-09-07', '2024-10-12', '2024-10-31', '2024-11-01'
    ]
    df['is_festival'] = df['ist_datetime'].dt.strftime('%Y-%m-%d').isin(FESTIVAL_DATES).astype('int8')

    # Second Saturday (Bank/Post-office holiday in India)
    # A day is a second Saturday if it is a Saturday (day_of_week==5) and the day of the month is between 8 and 14.
    df['is_second_saturday'] = ((df['day_of_week'] == 5) & (df['ist_datetime'].dt.day >= 8) & (df['ist_datetime'].dt.day <= 14)).astype('int8')

    print(f"  Temporal features added: hour, day_of_week, month, is_weekend, cyclical sin/cos, is_festival, is_second_saturday")
    return df


# PCU ENGINEERING 

def add_pcu_weights(df):
    """
    Map vehicle types to PCU (Passenger Car Unit) weights from Indian HCM.
    A bus (3.5) blocks 7x more road than a scooter (0.5).
    """
    print("Adding PCU weights...")

    # Convert category to string for mapping
    vtype_col = df['vehicle_type'].astype(str)
    df['pcu_weight'] = vtype_col.map(PCU_MAP).fillna(PCU_DEFAULT)

    # Report unmapped types
    unmapped = set(vtype_col.unique()) - set(PCU_MAP.keys())
    unmapped.discard('nan')
    unmapped.discard('UNKNOWN')
    if unmapped:
        print(f"  WARNING: Unmapped vehicle types (using default PCU={PCU_DEFAULT}): {unmapped}")

    # Vehicle category flags for ratio computation
    df['is_two_wheeler'] = vtype_col.isin(TWO_WHEELER_TYPES).astype('int8')
    df['is_three_wheeler'] = vtype_col.isin(THREE_WHEELER_TYPES).astype('int8')
    df['is_heavy_vehicle'] = vtype_col.isin(HEAVY_VEHICLE_TYPES).astype('int8')

    print(f"  PCU weight stats: mean={df['pcu_weight'].mean():.3f}, "
          f"median={df['pcu_weight'].median():.3f}, "
          f"max={df['pcu_weight'].max():.1f}")
    return df


# SPATIAL FEATURES

def haversine_km(lat1, lon1, lat2, lon2):
    """Haversine distance in kilometers between two points."""
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def haversine_km_vectorized(lat1, lon1, lat2, lon2):
    """Vectorized haversine for numpy arrays / pandas Series."""
    R = 6371
    lat1_r, lat2_r = np.radians(lat1), np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = (np.sin(dlat / 2) ** 2 +
         np.cos(lat1_r) * np.cos(lat2_r) *
         np.sin(dlon / 2) ** 2)
    return R * 2 * np.arcsin(np.sqrt(a))


def add_spatial_features(df):
    """
    Add spatial features:
    - distance_to_cbd: Haversine distance to Majestic (CBD reference)
    - is_junction: whether the violation is at a named junction
    """
    print("Adding spatial features...")

    # Distance to CBD 
    df['distance_to_cbd'] = haversine_km_vectorized(
        df['latitude'], df['longitude'], CBD_LAT, CBD_LON
    )

    # Junction flag
    df['is_junction'] = (df['junction_name'].astype(str) != 'No Junction').astype('int8')

    print(f"  Distance to CBD: mean={df['distance_to_cbd'].mean():.2f}km, "
          f"max={df['distance_to_cbd'].max():.2f}km")
    print(f"  Junction violations: {df['is_junction'].sum():,} / {len(df):,} "
          f"({100*df['is_junction'].mean():.1f}%)")
    return df


# ZONE-LEVEL AGGREGATION

def aggregate_zone_hourly(df):
    """
    Aggregate violations by (police_station, day_of_week, hour).
    Produces the PCU-weighted Congestion Impact Score (our target variable)
    plus vehicle-type composition ratios for strategy selection.
    """
    print("Aggregating zone-hourly statistics...")

    group_cols = ['police_station', 'day_of_week', 'hour']

    # Compute zone-level centroids from raw data (for spatial features later)
    zone_centroids = df.groupby('police_station').agg(
        lat_mean=('latitude', 'mean'),
        lon_mean=('longitude', 'mean')
    ).reset_index()

    agg = df.groupby(group_cols).agg(
        # Target variable: PCU-weighted congestion impact
        total_pcu_impact=('pcu_weight', 'sum'),

        # Raw violation count
        raw_violation_count=('pcu_weight', 'count'),

        # Vehicle type counts for ratio computation
        two_wheeler_count=('is_two_wheeler', 'sum'),
        three_wheeler_count=('is_three_wheeler', 'sum'),
        heavy_vehicle_count=('is_heavy_vehicle', 'sum'),

        # Validation ratio (enforcement quality signal)
        validation_approved_count=('validation_status',
                                   lambda x: (x == 'approved').sum()),

        # Junction violations
        junction_violation_count=('is_junction', 'sum'),

        # Violation severity
        avg_offence_count=('offence_count', 'mean'),
        avg_violation_count=('violation_count', 'mean'),

        # Temporal context (keep for features)
        is_weekend=('is_weekend', 'first'),
        month=('month', 'median'),
        is_festival=('is_festival', 'first'),
        is_second_saturday=('is_second_saturday', 'first'),

        # Spatial (mean coordinates for centroid)
        lat_mean=('latitude', 'mean'),
        lon_mean=('longitude', 'mean'),
    ).reset_index()

    # Compute ratios
    agg['two_wheeler_ratio'] = agg['two_wheeler_count'] / agg['raw_violation_count']
    agg['three_wheeler_ratio'] = agg['three_wheeler_count'] / agg['raw_violation_count']
    agg['heavy_vehicle_ratio'] = agg['heavy_vehicle_count'] / agg['raw_violation_count']
    agg['validation_ratio'] = agg['validation_approved_count'] / agg['raw_violation_count']
    agg['junction_ratio'] = agg['junction_violation_count'] / agg['raw_violation_count']

    # Distance to CBD from zone centroid
    agg['distance_to_cbd'] = haversine_km_vectorized(
        agg['lat_mean'], agg['lon_mean'], CBD_LAT, CBD_LON
    )

    # Cyclical encoding
    agg['hour_sin'] = np.sin(2 * np.pi * agg['hour'] / 24)
    agg['hour_cos'] = np.cos(2 * np.pi * agg['hour'] / 24)
    agg['day_sin'] = np.sin(2 * np.pi * agg['day_of_week'] / 7)
    agg['day_cos'] = np.cos(2 * np.pi * agg['day_of_week'] / 7)

    print(f"  Aggregated shape: {agg.shape}")
    print(f"  Target (total_pcu_impact) stats:")
    print(f"    mean={agg['total_pcu_impact'].mean():.2f}, "
          f"median={agg['total_pcu_impact'].median():.2f}, "
          f"max={agg['total_pcu_impact'].max():.2f}, "
          f"std={agg['total_pcu_impact'].std():.2f}")

    return agg, zone_centroids


# ZONE ARCHETYPE 

def classify_zone_archetype(df):
    """
    Assign each police station zone a "personality" archetype.
    The decision engine selects different strategies for different archetypes.
    """
    print("Classifying zone archetypes...")

    df['zone_archetype'] = (
        df['police_station']
        .astype(str)
        .map(ZONE_ARCHETYPES)
        .fillna(ZONE_ARCHETYPE_DEFAULT)
    )

    # Encode as numeric for ML
    archetype_codes = {v: i for i, v in enumerate(
        sorted(set(ZONE_ARCHETYPES.values()) | {ZONE_ARCHETYPE_DEFAULT})
    )}
    df['zone_archetype_code'] = df['zone_archetype'].map(archetype_codes)

    print(f"  Archetype distribution:")
    for arch, count in df['zone_archetype'].value_counts().items():
        print(f"    {arch}: {count}")

    return df


# WEEKEND SURGE 

def add_weekend_surge_ratio(df):
    """
    For each zone, compute weekend_violations / weekday_violations.
    Zones with ratio > 1.2 are candidates for temporary weekend superblocks.
    """
    print("Computing weekend surge ratios...")

    # Compute per-zone weekend and weekday totals
    zone_weekend = df[df['is_weekend'] == 1].groupby('police_station')['raw_violation_count'].sum()
    zone_weekday = df[df['is_weekend'] == 0].groupby('police_station')['raw_violation_count'].sum()

    # Weekend has 2 days, weekday has 5 -- normalize per-day
    surge = (zone_weekend / 2) / (zone_weekday / 5)
    surge = surge.fillna(0).rename('weekend_surge_ratio')

    df = df.merge(surge.reset_index(), on='police_station', how='left')
    df['weekend_surge_ratio'] = df['weekend_surge_ratio'].fillna(0)

    superblock_candidates = surge[surge > WEEKEND_SURGE_THRESHOLD].index.tolist()
    print(f"  Superblock candidates (surge > {WEEKEND_SURGE_THRESHOLD}): {superblock_candidates[:10]}")

    return df


# PERSISTENCE SCORE 

def add_persistence_score(df):
    """
    For each zone, what fraction of all possible (day_of_week x hour) slots
    have violations? Score > 0.8 = "persistent informal parking zone" --
    candidate for formalization rather than enforcement.
    """
    print("Computing persistence scores...")

    total_possible_slots = 7 * 24  # 168 slots per zone

    slots_with_violations = (
        df.groupby('police_station')
        .apply(lambda x: len(x))  # Each row IS a unique (zone, day, hour) combo
        .rename('occupied_slots')
    )

    persistence = (slots_with_violations / total_possible_slots).rename('persistence_score')
    persistence = persistence.clip(upper=1.0)  # Cap at 1.0

    df = df.merge(persistence.reset_index(), on='police_station', how='left')

    persistent_zones = persistence[persistence > PERSISTENCE_THRESHOLD].index.tolist()
    print(f"  Persistent zones (score > {PERSISTENCE_THRESHOLD}): {persistent_zones[:10]}")

    return df


# HISTORICAL ZONE STATS 

def add_historical_zone_stats(df, raw_df):
    """
    Add historical total violations per zone (for Model Ward threshold check).
    Uses the raw (non-aggregated) DataFrame for accurate counts.
    """
    print("Adding historical zone statistics...")

    zone_totals = (
        raw_df.groupby('police_station')
        .size()
        .rename('historical_violations')
        .reset_index()
    )
    zone_totals.columns = ['police_station', 'historical_violations']

    df = df.merge(zone_totals, on='police_station', how='left')
    df['historical_violations'] = df['historical_violations'].fillna(0).astype(int)

    print(f"  Top 5 zones by historical violations:")
    top5 = zone_totals.nlargest(5, 'historical_violations')
    for _, row in top5.iterrows():
        print(f"    {row['police_station']}: {row['historical_violations']:,}")

    return df


# SPATIAL SPILLOVER / BALLOON EFFECT 

def build_adjacency_map(zone_centroids, radius_km=SPILLOVER_RADIUS_KM):
    """
    Build a map of adjacent zones based on centroid distance.
    Zones whose centroids are within radius_km are considered neighbors.
    """
    print(f"Building zone adjacency map (radius={radius_km}km)...")

    adjacency = {}
    zones = zone_centroids['police_station'].tolist()
    lats = zone_centroids['lat_mean'].tolist()
    lons = zone_centroids['lon_mean'].tolist()

    for i, z1 in enumerate(zones):
        neighbors = []
        for j, z2 in enumerate(zones):
            if i != j:
                dist = haversine_km(lats[i], lons[i], lats[j], lons[j])
                if dist <= radius_km:
                    neighbors.append(z2)
        adjacency[z1] = neighbors

    # Report stats
    neighbor_counts = [len(v) for v in adjacency.values()]
    print(f"  {len(zones)} zones, avg {np.mean(neighbor_counts):.1f} neighbors per zone")
    print(f"  Zones with 0 neighbors: {sum(1 for c in neighbor_counts if c == 0)}")

    return adjacency


def add_spatial_lag_pcu(df, adjacency_map):
    """
    For each (zone, day, hour), compute the average PCU impact
    of geographically adjacent zones at the same (day, hour).
    This captures the "balloon effect" -- enforcement displacement.
    """
    print("Computing spatial lag PCU (balloon effect)...")

    # Create a lookup: (zone, day, hour) -> total_pcu_impact
    lookup = df.set_index(['police_station', 'day_of_week', 'hour'])['total_pcu_impact'].to_dict()

    spatial_lag = []
    for _, row in df.iterrows():
        zone = row['police_station']
        day = row['day_of_week']
        hour = row['hour']

        neighbors = adjacency_map.get(zone, [])
        if not neighbors:
            spatial_lag.append(0.0)
            continue

        neighbor_pcus = []
        for n in neighbors:
            key = (n, day, hour)
            if key in lookup:
                neighbor_pcus.append(lookup[key])

        if neighbor_pcus:
            spatial_lag.append(np.mean(neighbor_pcus))
        else:
            spatial_lag.append(0.0)

    df['spatial_lag_pcu'] = spatial_lag

    # Delta: how does neighbor pressure compare to own pressure?
    df['spatial_lag_delta'] = df['spatial_lag_pcu'] - df['total_pcu_impact']

    print(f"  Spatial lag PCU: mean={df['spatial_lag_pcu'].mean():.2f}, "
          f"std={df['spatial_lag_pcu'].std():.2f}")
    print(f"  Spatial lag delta: mean={df['spatial_lag_delta'].mean():.2f}")

    return df


# MASTER FUNCTION: Run all feature engineering

def engineer_all_features(df):
    """
    Run the full feature engineering pipeline on the cleaned DataFrame.
    Returns (aggregated_df, zone_centroids, adjacency_map).
    """
    print("\n" + "=" * 70)
    print("FEATURE ENGINEERING PIPELINE")
    print("=" * 70)

    # Row-level features
    df = add_temporal_features(df)
    df = add_pcu_weights(df)
    df = add_spatial_features(df)

    # Aggregate to zone-hourly level
    aggregated, zone_centroids = aggregate_zone_hourly(df)

    # Zone-level features
    aggregated = classify_zone_archetype(aggregated)
    aggregated = add_weekend_surge_ratio(aggregated)
    aggregated = add_persistence_score(aggregated)
    aggregated = add_historical_zone_stats(aggregated, df)

    # Spatial spillover (balloon effect)
    adjacency_map = build_adjacency_map(zone_centroids)
    aggregated = add_spatial_lag_pcu(aggregated, adjacency_map)

    print("\n" + "=" * 70)
    print("FEATURE ENGINEERING COMPLETE")
    print("=" * 70)
    print(f"Final aggregated shape: {aggregated.shape}")
    print(f"Columns: {list(aggregated.columns)}")
    print(f"\nTarget (total_pcu_impact) distribution:")
    print(aggregated['total_pcu_impact'].describe())

    return aggregated, zone_centroids, adjacency_map


# STANDALONE TEST
if __name__ == '__main__':
    from src.data_processing.data_loader import load_parking_data, clean_parking_data, convert_utc_to_ist

    # Load and clean
    df = load_parking_data()
    df = clean_parking_data(df)
    df = convert_utc_to_ist(df)

    # Engineer features
    aggregated, centroids, adj_map = engineer_all_features(df)

    # Save
    output_path = 'data/processed/aggregated_zone_hourly.csv'
    print(f"\nSaving aggregated data to {output_path}...")
    aggregated.to_csv(output_path, index=False)

    centroids_path = 'data/processed/zone_centroids.csv'
    centroids.to_csv(centroids_path, index=False)
    print(f"Saved zone centroids to {centroids_path}")

    # Show sample for top zone
    print("\nSample: Upparpet zone, Sunday, top 5 hours:")
    sample = aggregated[
        (aggregated['police_station'] == 'Upparpet') &
        (aggregated['day_of_week'] == 6)
    ].nlargest(5, 'total_pcu_impact')
    print(sample[['police_station', 'day_of_week', 'hour',
                   'total_pcu_impact', 'raw_violation_count',
                   'two_wheeler_ratio', 'three_wheeler_ratio',
                   'zone_archetype', 'spatial_lag_pcu']].to_string())
    print("\nDone!")
