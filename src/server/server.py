import http.server
import socketserver
import urllib.parse
import json
import pandas as pd
import threading
import subprocess
import random
from datetime import datetime
from src.data_processing.generate_map_data import generate_zone_markers

PORT = 8080

# Load aggregated data once into memory on startup
print("Loading aggregated data into memory...")
try:
    aggregated = pd.read_csv('data/processed/aggregated_zone_hourly.csv')
    print("Aggregated data loaded successfully.")
except FileNotFoundError:
    print("Error: aggregated_zone_hourly.csv not found. Run 'python run.py --prepare' first.")
    exit(1)

print("Loading raw data for dynamic heatmaps and charts...")
try:
    raw_df = pd.read_csv('data/processed/cleaned_parking_data.csv')
    raw_df['ist_datetime'] = pd.to_datetime(raw_df['ist_datetime'], format='mixed', utc=True)
    raw_df['hour'] = raw_df['ist_datetime'].dt.hour
    raw_df['day_of_week'] = raw_df['ist_datetime'].dt.dayofweek
    print("Raw data loaded successfully.")
except FileNotFoundError:
    print("Error: cleaned_parking_data.csv not found. Continuing without dynamic heatmap.")
    raw_df = None

def rebuild_pipeline():
    global aggregated, raw_df
    print("[Ingest] Simulating live data append...")
    # Append some synthetic high-volume data to violations.csv for a specific zone
    try:
        with open('data/raw/violations.csv', 'a', encoding='utf-8') as f:
            now_str = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
            # Add 200 synthetic violations at Madiwala to trigger a spike
            for _ in range(200):
                f.write(f"1,No Parking,12.9226,77.6174,{now_str},2,Madiwala,rejected\n")
    except Exception as e:
        print("Failed to append synthetic data:", e)

    print("[Ingest] Re-running ETL pipeline in background...")
    subprocess.run(["python", "run.py", "--prepare"], shell=True)
    subprocess.run(["python", "time_clustering.py"], shell=True)
    
    print("[Ingest] Hot-reloading aggregated dataframe...")
    try:
        new_agg = pd.read_csv('data/processed/aggregated_zone_hourly.csv')
        aggregated = new_agg
        print("[Ingest] Pipeline reload complete! System is updated.")
    except Exception as e:
        print("[Ingest] Reload failed:", e)

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


def filter_prediction_payload(payload, query):
    """Apply dashboard filters to forecast output without touching live data."""
    tag = query.get('tag', ['ALL'])[0]
    vehicle = query.get('vehicle', ['ALL'])[0]
    day_of_week = query.get('day_of_week', ['ALL'])[0]
    min_hour = int(query.get('min_hour', [0])[0])
    max_hour = int(query.get('max_hour', [23])[0])

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

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        global zone_feedback
        parsed_path = urllib.parse.urlparse(self.path)
        
        if parsed_path.path == '/':
            self.path = '/frontend/dashboard.html'
        elif parsed_path.path in ['/dashboard.html', '/script.js', '/style.css']:
            self.path = '/frontend' + parsed_path.path
        elif parsed_path.path == '/zone_markers.json':
            self.path = '/frontend/data/zone_markers.json'

        # Endpoint to get filter options
        if parsed_path.path == '/api/filters':
            try:
                if raw_df is not None:
                    tags = list(TAG_GROUPS.keys())
                    vehicles = sorted([str(x) for x in raw_df['vehicle_type'].dropna().unique()])
                    min_date = raw_df['ist_date'].min() if not raw_df['ist_date'].empty else None
                    max_date = raw_df['ist_date'].max() if not raw_df['ist_date'].empty else None
                    
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'tags': tags, 
                        'vehicles': vehicles,
                        'min_date': min_date,
                        'max_date': max_date
                    }).encode('utf-8'))
                else:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b"raw_df not loaded")
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))
            return

        if parsed_path.path == '/api/police_stations':
            try:
                import pandas as pd
                try:
                    centroids = pd.read_csv('data/processed/zone_centroids.csv')
                    stations = []
                    for _, row in centroids.iterrows():
                        lat = float(row['lat_mean']) if 'lat_mean' in row else float(row['lat'])
                        lng = float(row['lon_mean']) if 'lon_mean' in row else float(row['lng'])
                        stations.append({'name': row['police_station'], 'lat': lat, 'lng': lng})
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'stations': stations}).encode('utf-8'))
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode('utf-8'))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))
            return

        # Intercept the API call to update the scenario
        if parsed_path.path == '/api/scenario':
            query = urllib.parse.parse_qs(parsed_path.query)
            try:
                tag = query.get('tag', ['ALL'])[0]
                vehicle = query.get('vehicle', ['ALL'])[0]
                day_of_week = query.get('day_of_week', ['ALL'])[0]
                min_hour = int(query.get('min_hour', [0])[0])
                max_hour = int(query.get('max_hour', [23])[0])
                
                if raw_df is not None:
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
                    
                    import pandas as pd
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
                                
                            viol_cols = [c for c in zone_data.columns if c.startswith('viol_')]; top_tag = zone_data[viol_cols].sum().idxmax() if len(viol_cols) > 0 else 'Unknown'
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
                    
                    if 'zone_feedback' not in globals():
                        zone_feedback = {}
                        
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
                    
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(response_data).encode('utf-8'))
                else:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b"raw_df not loaded")
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))
            return
            
        if parsed_path.path == '/api/feedback':
            query = urllib.parse.parse_qs(parsed_path.query)
            zone = query.get('zone', [''])[0]
            if zone:
                if 'zone_feedback' not in globals():
                    zone_feedback = {}
                zone_feedback[zone] = True
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok', 'message': f'Feedback registered for {zone}. Severity temporarily reduced.'}).encode('utf-8'))
            return
            
        if parsed_path.path == '/api/predict_tomorrow':
            try:
                import predictive_engine
                
                prediction_payload = predictive_engine.generate_prediction(raw_df)
                if prediction_payload.get('status') == 'ok':
                    prediction_payload = filter_prediction_payload(
                        prediction_payload,
                        urllib.parse.parse_qs(parsed_path.query),
                    )
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(prediction_payload).encode('utf-8'))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
            
        return super().do_GET()

if __name__ == '__main__':
    PORT = 8000
    with socketserver.TCPServer(("", PORT), CustomHandler) as httpd:
        print("serving at port", PORT)
        httpd.serve_forever()

