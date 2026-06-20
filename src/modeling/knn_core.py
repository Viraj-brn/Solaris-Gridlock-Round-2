# Core KNN logic and primitives for predicting parking violation hotspots.
"""Shared calendar-KNN primitives used by prediction and evaluation."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    KNN_CONFIDENCE_THRESHOLD,
    KNN_FEATURE_WEIGHTS,
    KNN_K,
    PCU_DEFAULT,
    PCU_MAP,
)
from src.data_processing.karnataka_calendar import (
    KARNATAKA_FESTIVALS_SORTED,
    KARNATAKA_HOLIDAYS_SORTED,
)


CALENDAR_FEATURE_NAMES = (
    'is_festival',
    'is_holiday',
    'is_monday',
    'is_tues_to_fri',
    'is_sat_sun',
    'is_second_saturday',
)

MODEL_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / 'models' / 'knn_model_config.json'


def load_model_config():
    fallback = {
        'k': KNN_K,
        'feature_weights': list(KNN_FEATURE_WEIGHTS),
        'confidence_threshold': KNN_CONFIDENCE_THRESHOLD,
        'selection_objective': 'f1',
    }
    if not MODEL_CONFIG_PATH.exists():
        return fallback
    with MODEL_CONFIG_PATH.open('r', encoding='utf-8') as handle:
        loaded = json.load(handle)
    if len(loaded.get('feature_weights', [])) != len(CALENDAR_FEATURE_NAMES):
        raise ValueError('knn_model_config.json has an invalid feature vector.')
    return loaded


MODEL_CONFIG = load_model_config()
MODEL_K = int(MODEL_CONFIG['k'])
MODEL_FEATURE_WEIGHTS = np.asarray(MODEL_CONFIG['feature_weights'], dtype=float)
MODEL_CONFIDENCE_THRESHOLD = float(MODEL_CONFIG['confidence_threshold'])
DEFAULT_FEATURE_WEIGHTS = MODEL_FEATURE_WEIGHTS


def is_second_saturday(dt):
    return int(dt.weekday() == 5 and 8 <= dt.day <= 14)


def generate_calendar_features(date_value):
    dt = pd.to_datetime(date_value)
    date_str = dt.strftime('%Y-%m-%d')
    dow = dt.dayofweek
    return np.array([
        int(date_str in KARNATAKA_FESTIVALS_SORTED),
        int(date_str in KARNATAKA_HOLIDAYS_SORTED),
        int(dow == 0),
        int(1 <= dow <= 4),
        int(dow in (5, 6)),
        is_second_saturday(dt),
    ], dtype=float)


def calendar_distance(vec1, vec2, feature_weights=DEFAULT_FEATURE_WEIGHTS):
    weights = np.asarray(feature_weights, dtype=float)
    if weights.shape != (len(CALENDAR_FEATURE_NAMES),):
        raise ValueError(
            f'Expected {len(CALENDAR_FEATURE_NAMES)} feature weights in order '
            f'{CALENDAR_FEATURE_NAMES}, got shape {weights.shape}'
        )
    return float(np.sqrt(np.sum(weights * (vec1 - vec2) ** 2)))


def aggregate_daily_pcu(df):
    """Return one observed PCU-impact row per zone and date."""
    data = df.copy()
    data['pcu_weight'] = (
        data['vehicle_type'].astype(str).map(PCU_MAP).fillna(PCU_DEFAULT)
    )
    return (
        data.groupby(['police_station', 'ist_date'], observed=True)['pcu_weight']
        .sum()
        .reset_index(name='impact')
    )


def select_neighbor_dates(target_date, candidate_dates, feature_weights,
                          k=MODEL_K):
    """Select calendar-similar prior dates with the production recency rule."""
    target_vec = generate_calendar_features(target_date)
    target_dt = pd.to_datetime(target_date)
    distances = []

    for candidate_date in candidate_dates:
        candidate_vec = generate_calendar_features(candidate_date)
        distance = calendar_distance(target_vec, candidate_vec, feature_weights)
        days_ago = (target_dt - pd.to_datetime(candidate_date)).days
        recency_bonus = max(0.0, (30 - days_ago) * 0.05)
        distances.append((candidate_date, distance - recency_bonus))

    distances.sort(key=lambda item: item[1])
    return distances[:min(k, len(distances))]


def zone_medians(daily_impacts, candidate_dates):
    """Expanding medians over observed zone-days in the candidate pool."""
    pool = daily_impacts[daily_impacts['ist_date'].isin(candidate_dates)]
    return pool.groupby('police_station', observed=True)['impact'].median().to_dict()


def is_hotspot(impact, historical_median):
    """Canonical zone-day hotspot definition."""
    return historical_median > 0 and impact >= historical_median


def distance_weights(neighbors):
    adjusted_distances = np.array([max(0.0, distance) for _, distance in neighbors])
    return 1.0 / (adjusted_distances + 1e-5)


def predict_zone_day_records(daily_impacts, target_date, candidate_dates,
                             feature_weights=DEFAULT_FEATURE_WEIGHTS, k=MODEL_K,
                             min_history_days=None):
    """Generate zone-level scores and labels for one walk-forward date."""
    candidate_dates = list(candidate_dates)
    min_history_days = k if min_history_days is None else min_history_days
    if len(candidate_dates) < min_history_days:
        raise ValueError(
            f'Insufficient history: need at least {min_history_days} candidate '
            f'days, found {len(candidate_dates)}.'
        )

    neighbors = select_neighbor_dates(
        target_date, candidate_dates, feature_weights, k=k
    )
    neighbor_dates = [date for date, _ in neighbors]
    actual_k = len(neighbor_dates)
    neighbor_weights = distance_weights(neighbors)
    medians = zone_medians(daily_impacts, candidate_dates)

    pool = daily_impacts[daily_impacts['ist_date'].isin(candidate_dates)]
    impact_lookup = {
        (row.police_station, row.ist_date): row.impact
        for row in daily_impacts.itertuples(index=False)
    }

    records = []
    for zone in pool['police_station'].dropna().unique():
        median = medians.get(zone, 0)
        if median <= 0:
            continue
        # Missing zone-days are deliberately treated as zero observed impact.
        # Evaluation reports coverage so this accepted simplification is visible.
        neighbor_impacts = [
            impact_lookup.get((zone, date), 0.0) for date in neighbor_dates
        ]
        agreements = np.array([
            is_hotspot(value, median) for value in neighbor_impacts
        ], dtype=float)
        confidence = float(np.average(agreements, weights=neighbor_weights))
        actual_impact = impact_lookup.get((zone, target_date), 0.0)
        records.append({
            'date': target_date,
            'zone': zone,
            'confidence': confidence,
            'actual_hotspot': is_hotspot(actual_impact, median),
            'actual_impact': actual_impact,
            'historical_median': median,
            'neighbor_count': actual_k,
            'neighbor_impacts': neighbor_impacts,
            'neighbors': neighbors,
        })
    return records
