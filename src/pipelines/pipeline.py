"""
Theme 1: Parking-Induced Congestion
Module 5: Pipeline Orchestrator

Chains all modules together for end-to-end execution.

Usage:
    python pipeline.py                  # Full pipeline
    python pipeline.py --skip-training  # Skip ML training, use pre-computed data
"""

import sys
import time
import pandas as pd

from config import DATA_FILE, TOTAL_OFFICERS
from src.data_processing.data_loader import load_parking_data, clean_parking_data, convert_utc_to_ist
from src.data_processing.feature_engineer import engineer_all_features
from src.modeling.model_trainer import run_training_pipeline, predict_ensemble, save_training_results
from src.modeling.decision_engine import run_decision_engine


def run_full_pipeline(skip_training=False):
    """
    Execute the complete Bangalore Congestion Intelligence Engine pipeline.
    """
    total_start = time.time()

    print("\n" + "#" * 70)
    print("#  BANGALORE CONGESTION INTELLIGENCE ENGINE")
    print("#  Theme 1: Parking-Induced Congestion")
    print("#" * 70)

    # STAGE 1: DATA LOADING & CLEANING
    print("\n" + "=" * 70)
    print("STAGE 1: DATA LOADING & CLEANING")
    print("=" * 70)

    stage_start = time.time()
    df = load_parking_data()
    df = clean_parking_data(df)
    df = convert_utc_to_ist(df)
    print(f"  Stage 1 complete in {time.time() - stage_start:.1f}s")

    # STAGE 2: FEATURE ENGINEERING
    print("\n" + "=" * 70)
    print("STAGE 2: FEATURE ENGINEERING")
    print("=" * 70)

    stage_start = time.time()
    aggregated, zone_centroids, adjacency_map = engineer_all_features(df)

    # Save intermediate results
    aggregated.to_csv('data/processed/aggregated_zone_hourly.csv', index=False)
    zone_centroids.to_csv('data/processed/zone_centroids.csv', index=False)
    print(f"  Stage 2 complete in {time.time() - stage_start:.1f}s")

    # STAGE 3: ML MODEL TRAINING
    if not skip_training:
        print("\n" + "=" * 70)
        print("STAGE 3: ML MODEL TRAINING")
        print("=" * 70)

        stage_start = time.time()
        training_results = run_training_pipeline(aggregated)
        save_training_results(training_results)
        print(f"  Stage 3 complete in {time.time() - stage_start:.1f}s")
    else:
        print("\n  Skipping ML training (--skip-training flag)")
        training_results = None

    # STAGE 4: DECISION ENGINE
    print("\n" + "=" * 70)
    print("STAGE 4: DECISION ENGINE")
    print("=" * 70)

    stage_start = time.time()

    # Run for peak scenario: Sunday 10 AM
    print("\n--- Scenario 1: Sunday 10 AM (Peak) ---")
    directives_sun, alloc_sun, profiles_sun, strats_sun = run_decision_engine(
        aggregated, hour=10, day_of_week=6
    )

    # Run for weekday scenario: Monday 9 AM
    print("\n--- Scenario 2: Monday 9 AM (Weekday) ---")
    directives_mon, alloc_mon, profiles_mon, strats_mon = run_decision_engine(
        aggregated, hour=9, day_of_week=0
    )

    # Run for evening scenario: Friday 5 PM (IT corridor rush)
    print("\n--- Scenario 3: Friday 5 PM (Evening Rush) ---")
    directives_fri, alloc_fri, profiles_fri, strats_fri = run_decision_engine(
        aggregated, hour=17, day_of_week=4
    )

    print(f"  Stage 4 complete in {time.time() - stage_start:.1f}s")

    # SUMMARY
    total_time = time.time() - total_start
    print("\n" + "#" * 70)
    print("#  PIPELINE COMPLETE")
    print(f"#  Total time: {total_time:.1f}s")
    print("#" * 70)

    print(f"\n  Generated files:")
    print(f"    - aggregated_zone_hourly.csv  (ML-ready features)")
    print(f"    - zone_centroids.csv          (zone locations)")
    if not skip_training:
        print(f"    - model_lgbm.pkl              (LightGBM model)")
        print(f"    - model_catboost.pkl          (CatBoost model)")
        print(f"    - model_xgboost.pkl           (XGBoost model)")
        print(f"    - model_weights.pkl           (ensemble weights)")
        print(f"    - model_feature_importance.csv")

    return {
        'aggregated': aggregated,
        'zone_centroids': zone_centroids,
        'adjacency_map': adjacency_map,
        'training_results': training_results,
        'scenarios': {
            'sunday_10am': (directives_sun, alloc_sun),
            'monday_9am': (directives_mon, alloc_mon),
            'friday_5pm': (directives_fri, alloc_fri),
        }
    }
# ENTRY POINT
if __name__ == '__main__':
    skip = '--skip-training' in sys.argv
    results = run_full_pipeline(skip_training=skip)
