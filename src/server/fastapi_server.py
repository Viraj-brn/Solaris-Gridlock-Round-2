import json
import pandas as pd
import subprocess
from datetime import datetime
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
import os

app = FastAPI(title="Bangalore Congestion Intelligence Engine", version="1.0")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount frontend directory for static files
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

# In-memory storage and state
aggregated = None
raw_df = None
zone_feedback = {}

TAG_GROUPS = {
    "Parking Violations": [
        'viol_double_parking', 'viol_no_parking', 'viol_parking_in_a_main_road',
        'viol_parking_near_bustop_school_hospital_etc', 'viol_parking_near_road_crossing',
        'viol_parking_near_traffic_light_or_zebra_cross', 'viol_parking_on_footpath',
        'viol_parking_opposite_to_another_parked_vehicle', 'viol_parking_other_than_bus_stop',
        'viol_wrong_parking'
    ],
    "Safety & Equipment": [
        'viol_2w_3w_-_using_mobile_phone', 'viol_defective_number_plate', 'viol_fail_to_use_safety_belts',
        'viol_other_-_using_mobile_phone', 'viol_rider_not_wearing_helmet', 'viol_using_black_film_other_materials',
        'viol_without_side_mirror'
    ],
    "Commercial & Cargo": [
        'viol_carrying_lenghty_material', 'viol_demanding_excess_fare', 'viol_h_t_v_prohibited',
        'viol_refuse_to_go_for_hire'
    ]
}

def load_data():
    global aggregated, raw_df
    print("Loading aggregated data into memory...")
    try:
        aggregated = pd.read_csv('data/processed/aggregated_zone_hourly.csv')
        print("Aggregated data loaded successfully.")
    except FileNotFoundError:
        print("Warning: aggregated_zone_hourly.csv not found.")

    print("Loading raw data for dynamic heatmaps and charts...")
    try:
        raw_df = pd.read_csv('data/processed/cleaned_parking_data.csv')
        raw_df['ist_datetime'] = pd.to_datetime(raw_df['ist_datetime'], format='mixed', utc=True)
        raw_df['hour'] = raw_df['ist_datetime'].dt.hour
        raw_df['day_of_week'] = raw_df['ist_datetime'].dt.dayofweek
        print("Raw data loaded successfully.")
    except FileNotFoundError:
        print("Warning: cleaned_parking_data.csv not found.")

def run_data_pipeline():
    print("[Pipeline] Running scheduled data preparation pipeline...")
    # Execute the data loader and feature engineer pipeline
    # Equivalent to `python run.py --prepare`
    try:
        subprocess.run(["python", "run.py", "--prepare"], check=True)
        print("[Pipeline] Data preparation completed. Reloading data into memory...")
        load_data()
    except subprocess.CalledProcessError as e:
        print(f"[Pipeline] Failed to execute data pipeline: {e}")
    except Exception as e:
        print(f"[Pipeline] Error during pipeline execution: {e}")

@app.on_event("startup")
async def startup_event():
    # Load the data on startup
    load_data()
    
    # Initialize background scheduler for data pipeline
    scheduler = BackgroundScheduler()
    # Run daily at 2:00 AM
    scheduler.add_job(run_data_pipeline, 'cron', hour=2, minute=0)
    scheduler.start()
    print("Background scheduler started.")

@app.get("/")
async def serve_index():
    return FileResponse('frontend/dashboard.html')

@app.get("/zone_markers.json")
async def serve_zone_markers():
    return FileResponse('frontend/data/zone_markers.json')

@app.get("/api/filters")
async def get_filters():
    if raw_df is None:
        raise HTTPException(status_code=500, detail="Raw data not loaded")
    
    tags = list(TAG_GROUPS.keys())
    vehicles = sorted([str(x) for x in raw_df['vehicle_type'].dropna().unique()])
    min_date = raw_df['ist_date'].min() if not raw_df['ist_date'].empty else None
    max_date = raw_df['ist_date'].max() if not raw_df['ist_date'].empty else None
    
    return {
        'tags': tags, 
        'vehicles': vehicles,
        'min_date': min_date,
        'max_date': max_date
    }

@app.get("/api/police_stations")
async def get_police_stations():
    try:
        centroids = pd.read_csv('data/processed/zone_centroids.csv')
        stations = []
        for _, row in centroids.iterrows():
            lat = float(row['lat_mean']) if 'lat_mean' in row else float(row['lat'])
            lng = float(row['lon_mean']) if 'lon_mean' in row else float(row['lng'])
            stations.append({'name': row['police_station'], 'lat': lat, 'lng': lng})
        return {'stations': stations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/scenario")
async def get_scenario(
    tag: str = Query("ALL"),
    vehicle: str = Query("ALL"),
    day_of_week: str = Query("ALL"),
    min_hour: int = Query(0),
    max_hour: int = Query(23)
):
    global zone_feedback
    if raw_df is None:
        raise HTTPException(status_code=500, detail="Raw data not loaded")

    try:
        unique_dates = sorted(raw_df['ist_date'].dropna().unique())
        visible_dates = unique_dates[-7:]
        visible_days_count = len(visible_dates)
        filtered = raw_df[raw_df['ist_date'].isin(visible_dates)].copy()
        
        # Apply time filter
        filtered = filtered[(filtered['hour'] >= min_hour) & (filtered['hour'] <= max_hour)]
        
        # Apply day of week filter
        if day_of_week != 'ALL':
            days_map = {'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3, 'Friday': 4, 'Saturday': 5, 'Sunday': 6}
            if day_of_week in days_map:
                filtered = filtered[filtered['day_of_week'] == days_map[day_of_week]]
        
        # Apply tag filter
        if tag != 'ALL' and tag in TAG_GROUPS:
            valid_cols = [c for c in TAG_GROUPS[tag] if c in filtered.columns]
            if valid_cols:
                filtered = filtered[filtered[valid_cols].sum(axis=1) > 0]
            
        # Apply vehicle filter
        if vehicle != 'ALL':
            filtered = filtered[filtered['vehicle_type'] == vehicle]
        
        zone_counts = filtered['police_station'].value_counts()
        top_zones = zone_counts[zone_counts > 0].head(100).to_dict()
        
        sample_size = int(len(filtered) * 0.3)
        sample_size = min(sample_size, 10000)
        if sample_size < len(filtered) and sample_size > 0:
            sampled = filtered.sample(n=sample_size, random_state=42)
        else:
            sampled = filtered
            
        heatmap = [{'lat': row['latitude'], 'lng': row['longitude'], 'weight': 1.0} for _, row in sampled.iterrows()]
        
        try:
            centroids = pd.read_csv('data/processed/zone_centroids.csv')
        except:
            centroids = pd.DataFrame(columns=['police_station', 'lat', 'lng'])
            
        zone_markers = []
        ranked_zones = []
        
        for z, count in top_zones.items():
            c_row = centroids[centroids['police_station'] == z]
            lat, lng = 12.9716, 77.5946
            if not c_row.empty:
                if 'lat_mean' in c_row:
                    lat = float(c_row['lat_mean'].values[0])
                    lng = float(c_row['lon_mean'].values[0])
                else:
                    lat = float(c_row['lat'].values[0])
                    lng = float(c_row['lng'].values[0])
            
            zone_data = filtered[filtered['police_station'] == z]
            
            if not zone_data.empty:
                hour_counts = zone_data['hour'].value_counts()
                peak_hour = hour_counts.idxmax() if not hour_counts.empty else 12
                
                peak_ratio = hour_counts.max() / count
                classification = "CHRONIC" if peak_ratio < 0.2 else "PEAK-DRIVEN"
                
                top_veh = zone_data['vehicle_type'].mode()[0] if not zone_data['vehicle_type'].mode().empty else "Unknown"
                veh_comp = {str(k): int(v) for k, v in zone_data['vehicle_type'].value_counts().items()}
                
                try:
                    day_srs = pd.to_datetime(zone_data['ist_date']).dt.day_name()
                    peak_day = day_srs.mode()[0] if not day_srs.empty else "Unknown"
                except:
                    peak_day = "Unknown"
                    
                viol_cols = [c for c in zone_data.columns if c.startswith('viol_')]
                top_tag = zone_data[viol_cols].sum().idxmax() if len(viol_cols) > 0 else 'Unknown'
                cause = f"Driven by {top_veh} ({top_tag})"
                
                wardens = max(1, min(5, int(count / 100)))
                workforce = f"{wardens} Wardens, 1 Tow Truck"
                
                start_h = max(0, peak_hour - 1)
                end_h = min(23, peak_hour + 2)
                patrol_window = f"{start_h:02d}:00 - {end_h:02d}:00"
            else:
                classification = "SPORADIC"
                cause = "Unknown"
                workforce = "1 Warden"
                patrol_window = "Flexible"
                veh_comp = {}
                peak_day = "Unknown"

            zone_markers.append({'zone': z, 'count': int(count), 'lat': float(lat), 'lng': float(lng)})
            ranked_zones.append({
                'zone': z,
                'count': int(count),
                'classification': classification,
                'cause': cause,
                'workforce': workforce,
                'patrol_window': patrol_window,
                'vehicular_composition': veh_comp,
                'peak_day': peak_day
            })
        
        for rz in ranked_zones:
            if rz['zone'] in zone_feedback:
                rz['count'] = int(rz['count'] * 0.5)
                rz['classification'] += " (MITIGATED)"
                
        ranked_zones = sorted(ranked_zones, key=lambda x: x['count'], reverse=True)

        response_data = {
            'heatmap': heatmap,
            'zone_markers': zone_markers,
            'ranked_zones': ranked_zones,
            'time_patterns': {int(k): int(v) for k, v in filtered.groupby('hour').size().items()},
            'vehicle_breakdown': {str(k): int(v) for k, v in filtered['vehicle_type'].value_counts().items()},
            'violation_breakdown': {k.replace('viol_', '').replace('_', ' ').title(): int(v) for k, v in filtered[[c for c in filtered.columns if c.startswith('viol_')]].sum().items() if v > 0},
            'total_violations': int(len(filtered)),
            'window_days': visible_days_count,
            'window_start': visible_dates[0] if visible_dates else None,
            'window_end': visible_dates[-1] if visible_dates else None,
        }
        
        return JSONResponse(content=response_data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/feedback")
async def register_feedback(zone: str = Query("")):
    global zone_feedback
    if zone:
        zone_feedback[zone] = True
    return {'status': 'ok', 'message': f'Feedback registered for {zone}. Severity temporarily reduced.'}

def filter_prediction_payload(payload, tag, vehicle, day_of_week, min_hour, max_hour):
    """Apply dashboard filters to forecast output without touching live data."""
    prediction_day = pd.to_datetime(payload['prediction_date']).day_name()
    zones = payload.get('ranked_zones', [])
    if day_of_week != 'ALL' and day_of_week != prediction_day:
        zones = []
    if vehicle != 'ALL':
        zones = [z for z in zones if z['profile_vehicle'] == vehicle]
    if tag != 'ALL' and tag in TAG_GROUPS:
        valid_columns = set(TAG_GROUPS[tag])
        zones = [z for z in zones if z.get('profile_violation_col') in valid_columns]
    zones = [
        z for z in zones if min_hour <= z['profile_peak_hour'] <= max_hour
    ]

    valid_zones = {z['zone'] for z in zones}
    payload['ranked_zones'] = zones
    payload['zone_markers'] = [
        marker for marker in payload.get('zone_markers', [])
        if marker['zone'] in valid_zones
    ]
    payload['heatmap'] = [
        point for point in payload.get('heatmap', [])
        if point.get('zone') in valid_zones
    ]

    time_patterns = {}
    vehicle_breakdown = {}
    violation_breakdown = {}
    for zone in zones:
        count = int(zone['count'])
        hour = str(zone['profile_peak_hour'])
        time_patterns[hour] = time_patterns.get(hour, 0) + count
        vehicle_name = str(zone['profile_vehicle'])
        vehicle_breakdown[vehicle_name] = vehicle_breakdown.get(vehicle_name, 0) + count
        violation_name = zone['profile_violation']
        violation_breakdown[violation_name] = violation_breakdown.get(violation_name, 0) + count

    payload['time_patterns'] = time_patterns
    payload['vehicle_breakdown'] = vehicle_breakdown
    payload['violation_breakdown'] = violation_breakdown
    payload['total_violations'] = sum(int(zone['count']) for zone in zones)
    payload['prediction_day_name'] = prediction_day
    return payload

@app.get("/api/predict_tomorrow")
async def predict_tomorrow(
    tag: str = Query("ALL"),
    vehicle: str = Query("ALL"),
    day_of_week: str = Query("ALL"),
    min_hour: int = Query(0),
    max_hour: int = Query(23)
):
    try:
        import src.modeling.predictive_engine as predictive_engine
        
        prediction_payload = predictive_engine.generate_prediction(raw_df)
        if prediction_payload.get('status') == 'ok':
            prediction_payload = filter_prediction_payload(
                prediction_payload, tag, vehicle, day_of_week, min_hour, max_hour
            )
        
        return JSONResponse(content=prediction_payload)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("fastapi_server:app", host="0.0.0.0", port=8000, reload=True)
