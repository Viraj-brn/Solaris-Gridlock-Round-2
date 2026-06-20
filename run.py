"""
Theme 1: Parking-Induced Congestion
Unified Command Line Interface (CLI)

Usage:
  python run.py --all           # Run everything (data -> features -> train -> map)
  python run.py --prepare       # Only run data loading and feature engineering
  python run.py --train         # Only run ML model training
  python run.py --decision      # Run decision engine (add --day and --hour)
  python run.py --map           # Generate map data (add --day and --hour)
"""

import argparse
import sys
import os
import time
import pandas as pd

from src.data_processing.data_loader import load_parking_data, clean_parking_data, convert_utc_to_ist
from src.data_processing.feature_engineer import engineer_all_features
from src.modeling.model_trainer import run_training_pipeline, save_training_results
from src.modeling.decision_engine import run_decision_engine, DAY_NAMES
from src.data_processing.generate_map_data import generate_heatmap_points, generate_zone_markers, save_map_data


def main():
    parser = argparse.ArgumentParser(description="Bangalore Congestion Intelligence Engine (Theme 1)")
    
    # Modes of operation
    parser.add_argument('--all', action='store_true', help='Run the complete end-to-end pipeline')
    parser.add_argument('--prepare', action='store_true', help='Run data loading and feature engineering')
    parser.add_argument('--train', action='store_true', help='Run ML model training')
    parser.add_argument('--decision', action='store_true', help='Run decision engine and resource allocation')
    parser.add_argument('--map', action='store_true', help='Generate MapMyIndia heatmap data')
    
    # Parameters for decision and map
    parser.add_argument('--day', type=int, default=6, help='Day of week (0=Mon, 6=Sun)')
    parser.add_argument('--hour', type=int, default=10, help='Hour of day (0-23, IST)')
    
    args = parser.parse_args()

    # If no arguments provided, show help
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    print("\n" + "="*70)
    print(" BANGALORE CONGESTION INTELLIGENCE ENGINE — LOCAL TEST RUNNER")
    print("="*70)

    # 1. PREPARE DATA (Data Loader + Feature Engineer)
    if args.all or args.prepare:
        print("\n> RUNNING DATA PREPARATION...")
        df = load_parking_data()
        df = clean_parking_data(df)
        df = convert_utc_to_ist(df)
        
        aggregated, zone_centroids, adj_map = engineer_all_features(df)
        
        aggregated.to_csv('data/processed/aggregated_zone_hourly.csv', index=False)
        zone_centroids.to_csv('data/processed/zone_centroids.csv', index=False)
        print("[OK] Data preparation complete. Saved to aggregated_zone_hourly.csv")
    
    # 2. TRAIN ML MODELS
    if args.all or args.train:
        print("\n> RUNNING ML MODEL TRAINING...")
        try:
            aggregated = pd.read_csv('data/processed/aggregated_zone_hourly.csv')
        except FileNotFoundError:
            print("Error: aggregated_zone_hourly.csv not found. Please run with --prepare first.")
            sys.exit(1)
            
        results = run_training_pipeline(aggregated)
        save_training_results(results)
        print("[OK] Model training complete. Models saved to disk.")

    # 3. RUN DECISION ENGINE
    if args.all or args.decision:
        print(f"\n> RUNNING DECISION ENGINE for {DAY_NAMES[args.day]} {args.hour}:00 IST...")
        try:
            aggregated = pd.read_csv('data/processed/aggregated_zone_hourly.csv')
        except FileNotFoundError:
            print("Error: aggregated_zone_hourly.csv not found. Please run with --prepare first.")
            sys.exit(1)
            
        directives, allocation, profiles, strats = run_decision_engine(
            aggregated, hour=args.hour, day_of_week=args.day
        )
        print("[OK] Decision engine execution complete.")

    # 4. GENERATE MAP DATA
    if args.all or args.map:
        print(f"\n> GENERATING MAP DATA for {DAY_NAMES[args.day]} {args.hour}:00 IST...")
        print("Loading raw data for heatmap points (this takes a moment)...")
        df = load_parking_data()
        df = clean_parking_data(df)
        df = convert_utc_to_ist(df)
        
        try:
            aggregated = pd.read_csv('data/processed/aggregated_zone_hourly.csv')
        except FileNotFoundError:
            print("Error: aggregated_zone_hourly.csv not found. Please run with --prepare first.")
            sys.exit(1)

        heatmap_points = generate_heatmap_points(df, sample_fraction=0.3)
        zone_markers = generate_zone_markers(aggregated, hours=[args.hour], day_of_week=args.day)
        save_map_data(heatmap_points, zone_markers)
        print("[OK] Map data generated successfully.")
        print("\nYou can now open 'bangalore_heatmap.html' in your browser!")

    print("\n" + "="*70)
    print(" DONE!")
    print("="*70 + "\n")

if __name__ == '__main__':
    main()
