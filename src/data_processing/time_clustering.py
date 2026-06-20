import pandas as pd
import json
import numpy as np

def generate_time_blocks():
    """
    Classify each hotspot by Time Duration and Burstiness.
    
    Duration axes:
    - SHORT_DURATION: Violations are concentrated within <= 4 active hours
    - LONG_DURATION: Violations are spread out over > 4 active hours
    
    Burstiness axes:
    - SINGLE_PEAK: A single distinct peak hour dominates (max hour has > 35% of daily total)
    - MULTIPLE_PEAKS: Multiple or sporadic peaks across active hours
    """
    try:
        agg = pd.read_csv('data/processed/aggregated_zone_hourly.csv')
    except Exception as e:
        print("Could not read aggregated_zone_hourly.csv:", e)
        return

    zones = agg['police_station'].unique()
    time_classifications = {}
    
    for zone in sorted(zones):
        zone_data = agg[agg['police_station'] == zone]
        
        # We will aggregate over all days for a robust profile, 
        # or we could do it per day of week. Let's do a general profile first.
        hourly_vol = zone_data.groupby('hour')['raw_violation_count'].sum().reindex(range(24), fill_value=0)
        total_vol = hourly_vol.sum()
        
        if total_vol == 0:
            time_classifications[zone] = {
                'duration': 'LONG_DURATION',
                'burstiness': 'MULTIPLE_PEAKS',
                'description': 'No Data'
            }
            continue
            
        # Find active hours (e.g., hours with > 10% of the max hour)
        max_vol = hourly_vol.max()
        active_hours = (hourly_vol[hourly_vol > 0.1 * max_vol]).index.tolist()
        num_active = len(active_hours)
        
        duration_class = 'SHORT_DURATION' if num_active <= 4 else 'LONG_DURATION'
        
        # Burstiness: does the max hour account for > 35% of the total?
        burstiness_class = 'SINGLE_PEAK' if (max_vol / total_vol) > 0.35 else 'MULTIPLE_PEAKS'
        
        # Formulate a descriptive text
        if duration_class == 'SHORT_DURATION' and burstiness_class == 'SINGLE_PEAK':
            desc = "Short fixed-window with a sharp peak"
        elif duration_class == 'SHORT_DURATION' and burstiness_class == 'MULTIPLE_PEAKS':
            desc = "Short active window with varying intensity"
        elif duration_class == 'LONG_DURATION' and burstiness_class == 'SINGLE_PEAK':
            desc = "Spread out active hours but dominated by one sharp peak"
        else:
            desc = "Long/spread-out active hours with sporadic peaks"

        time_classifications[zone] = {
            'duration': duration_class,
            'burstiness': burstiness_class,
            'description': desc,
            'active_hours': active_hours,
            'peak_hour': int(hourly_vol.idxmax())
        }

    with open('frontend/data/time_blocks.json', 'w') as f:
        json.dump(time_classifications, f, indent=2)
    print("Time classifications generated in time_blocks.json")

if __name__ == '__main__':
    generate_time_blocks()
