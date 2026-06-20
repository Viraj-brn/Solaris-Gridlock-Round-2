import pandas as pd
import numpy as np
import json
import os

def classify_hotspots():
    print("Classifying hotspots by duration and burstiness...")
    
    if not os.path.exists('aggregated_zone_hourly.csv'):
        print("aggregated_zone_hourly.csv not found.")
        return
        
    df = pd.read_csv('aggregated_zone_hourly.csv')
    
    # Group by police_station and hour to get average violations across all days
    zone_hourly = df.groupby(['police_station', 'hour'])['raw_violation_count'].mean().reset_index()
    
    classifications = {}
    
    for zone, group in zone_hourly.groupby('police_station'):
        hours = group['hour'].values
        counts = group['raw_violation_count'].values
        
        # Reindex to 24 hours
        full_day = np.zeros(24)
        for h, c in zip(hours, counts):
            full_day[h] = c
            
        max_count = np.max(full_day)
        if max_count == 0:
            continue
            
        threshold = 0.2 * max_count # 20% of max is considered "active"
        active_hours = np.where(full_day > threshold)[0]
        
        # Duration Classification
        num_active = len(active_hours)
        if num_active <= 4:
            duration_class = "Short Fixed-Window"
        elif num_active <= 10:
            duration_class = "Medium Window"
        else:
            duration_class = "Long/Spread-out Hours"
            
        # Burstiness Classification
        # Find peaks (simple local maxima over threshold)
        peaks = []
        for i in range(24):
            if full_day[i] > threshold:
                prev_val = full_day[(i-1)%24]
                next_val = full_day[(i+1)%24]
                if full_day[i] >= prev_val and full_day[i] >= next_val:
                    peaks.append(i)
                    
        # Filter peaks that are close to each other
        filtered_peaks = []
        for p in peaks:
            if not filtered_peaks:
                filtered_peaks.append(p)
            else:
                if abs(p - filtered_peaks[-1]) > 2: # Peaks must be separated by > 2 hours
                    filtered_peaks.append(p)
                    
        if len(filtered_peaks) <= 1:
            burst_class = "Single Sharp Peak"
        else:
            burst_class = "Multiple/Sporadic Peaks"
            
        classifications[zone] = {
            'duration_class': duration_class,
            'burst_class': burst_class,
            'active_hours_count': num_active,
            'peak_count': len(filtered_peaks),
            'main_peak_hour': int(filtered_peaks[0]) if filtered_peaks else int(np.argmax(full_day))
        }
        
    with open('hotspot_classifications.json', 'w') as f:
        json.dump(classifications, f, indent=2)
        
    print(f"Classified {len(classifications)} zones.")
    return classifications

if __name__ == '__main__':
    classify_hotspots()
