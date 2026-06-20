"""
Theme 1: Parking-Induced Congestion

Strategies sourced from:
  - Vietnam Model Ward (concentrated enforcement)
  - Indonesia Push-Pull (progressive fees + Park-and-Ride)
  - Taipei 5-Pillar Zoning (designated scooter zones)
  - Bangkok Win System (auto-rickshaw stands)
  - SFpark Zone Scoring (tow priority)
  - Barcelona Superblocks (weekend commercial zones)
  - Rwanda Formalize the Informal (convert persistent violations to designated zones)
  - Tokyo TSP (patrol routing through hotspots)
  - Jakarta Time-Window (loading vehicle restrictions)

Usage:
    python decision_engine.py
"""

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from config import (
    HIGH_IMPACT_THRESHOLD,
    TWO_WHEELER_RATIO_THRESHOLD,
    AUTO_RATIO_THRESHOLD,
    HEAVY_VEHICLE_RATIO_THRESHOLD,
    MODEL_WARD_VIOLATION_THRESHOLD,
    WEEKEND_SURGE_THRESHOLD,
    PERSISTENCE_THRESHOLD,
    TOTAL_OFFICERS,
    ZONE_ARCHETYPES,
)


# STRATEGY DEFINITIONS

STRATEGY_CATALOG = {
    'ACTIVATE_MODEL_WARD': {
        'name': 'Activate Model Ward',
        'source': 'Vietnam (Hanoi)',
        'description': 'Deploy concentrated enforcement for 2-week intensive crackdown',
        'action': 'Zero-tolerance enforcement with full resource allocation',
        'effectiveness_multiplier': 1.5,  # Highest ROI per officer
        'min_officers': 3,
    },
    'DESIGNATE_SCOOTER_ZONE': {
        'name': 'Designate Scooter Parking Zone',
        'source': 'Taiwan (Taipei)',
        'description': 'Mark nearest safe zone as temporary 2-wheeler parking',
        'action': 'Install temporary signage + bollards for designated scooter area',
        'effectiveness_multiplier': 1.2,
        'min_officers': 1,
    },
    'CREATE_AUTO_STAND': {
        'name': 'Create Auto-Rickshaw Stand',
        'source': 'Thailand (Bangkok Win System)',
        'description': 'Designate junction as official auto-rickshaw waiting area',
        'action': 'Mark designated auto stand with capacity limits',
        'effectiveness_multiplier': 1.1,
        'min_officers': 1,
    },
    'TEMPORARY_SUPERBLOCK': {
        'name': 'Temporary Weekend Superblock',
        'source': 'Spain (Barcelona)',
        'description': 'Close specific cross-streets to through-traffic on weekends',
        'action': 'Deploy barricades + redirect signage on Sat-Sun peak hours',
        'effectiveness_multiplier': 1.3,
        'min_officers': 2,
    },
    'PARK_AND_RIDE': {
        'name': 'Park-and-Ride Recommendation',
        'source': 'Indonesia (Jakarta Push-Pull)',
        'description': 'Redirect vehicles to Park-and-Ride facilities near transit',
        'action': 'Variable message signs directing to P&R + increased metro feeder buses',
        'effectiveness_multiplier': 1.0,
        'min_officers': 1,
    },
    'TIME_WINDOW_ENFORCEMENT': {
        'name': 'Time-Window Loading Restriction',
        'source': 'Indonesia/UK (Jakarta + London)',
        'description': 'Restrict commercial loading/unloading to off-peak hours only',
        'action': 'Commercial vehicles allowed loading 6-8 AM only; enforce during peak',
        'effectiveness_multiplier': 1.1,
        'min_officers': 1,
    },
    'DEPLOY_TOW_TRUCK': {
        'name': 'Deploy Tow Truck (PCU Priority)',
        'source': 'USA/Japan (SFpark + Tokyo)',
        'description': 'Tow vehicles starting with highest PCU impact',
        'action': 'Prioritize: HGV (4.5) > Bus (3.5) > Maxi-Cab (1.5) > Car (1.0)',
        'effectiveness_multiplier': 1.4,
        'min_officers': 2,
    },
    'FORMALIZE_AS_DESIGNATED_ZONE': {
        'name': 'Formalize as Designated Parking Zone',
        'source': 'Rwanda (Kigali)',
        'description': 'Convert persistent violation cluster into official parking zone',
        'action': 'Survey, mark, and legitimize the area as paid parking',
        'effectiveness_multiplier': 0.8,  # Lower immediate impact but long-term fix
        'min_officers': 0,
    },
    'GEOFENCED_IDLE_PROHIBITION': {
        'name': 'Geofenced No-Idle Zone',
        'source': 'Bangalore-specific (IT corridor)',
        'description': 'Prohibit cab/auto idling near tech parks',
        'action': 'Digital signage + enforcement at designated pickup zones',
        'effectiveness_multiplier': 1.2,
        'min_officers': 2,
    },
}



# ZONE PROFILE BUILDER
import json

def build_zone_profile(aggregated_df, zone_name, hours=None, day_of_week=None, classifications=None):
    """
    Build a complete profile for a zone including vehicle composition,
    archetype, strategy trigger values, and time classifications.
    """
    zone_data = aggregated_df[aggregated_df['police_station'] == zone_name]

    if len(zone_data) == 0:
        return None

    # Filter by specific time if provided
    if hours is not None:
        if isinstance(hours, list):
            zone_data = zone_data[zone_data['hour'].isin(hours)]
        else:
            zone_data = zone_data[zone_data['hour'] == hours]
    if day_of_week is not None:
        zone_data = zone_data[zone_data['day_of_week'] == day_of_week]

    if len(zone_data) == 0:
        return None

    # Aggregate across matching rows
    profile = {
        'zone': zone_name,
        'hours': hours,
        'day_of_week': day_of_week,

        # PCU impact
        'predicted_pcu_impact': zone_data['total_pcu_impact'].sum(),
        'avg_pcu_impact': zone_data['total_pcu_impact'].mean(),

        # Vehicle composition
        'two_wheeler_ratio': zone_data['two_wheeler_ratio'].mean(),
        'three_wheeler_ratio': zone_data['three_wheeler_ratio'].mean(),
        'heavy_vehicle_ratio': zone_data['heavy_vehicle_ratio'].mean(),

        # Zone metadata
        'archetype': zone_data['zone_archetype'].iloc[0],
        'historical_violations': zone_data['historical_violations'].iloc[0],
        'persistence_score': zone_data['persistence_score'].iloc[0],
        'weekend_surge_ratio': zone_data['weekend_surge_ratio'].iloc[0],
        'is_weekend': int(zone_data['is_weekend'].iloc[0]) if pd.notna(zone_data['is_weekend'].iloc[0]) else 0,

        # Spatial spillover
        'spatial_lag_pcu': zone_data['spatial_lag_pcu'].mean(),
        'spatial_lag_delta': zone_data['spatial_lag_delta'].mean(),

        # Enforcement quality
        'validation_ratio': zone_data['validation_ratio'].mean(),

        # Location
        'lat': zone_data['lat_mean'].mean(),
        'lon': zone_data['lon_mean'].mean(),
        'distance_to_cbd': zone_data['distance_to_cbd'].mean(),
        
        # Time Classifications
        'duration_class': classifications.get(zone_name, {}).get('duration', 'Unknown') if classifications else 'Unknown',
        'burst_class': classifications.get(zone_name, {}).get('burstiness', 'Unknown') if classifications else 'Unknown',
    }

    return profile



# STRATEGY SELECTION (Rule-Based)

def select_strategies(profile):
    """
    Select applicable strategies for a zone based on its profile.
    Returns list of (strategy_key, reason) tuples.
    """
    if profile is None:
        return []

    strategies = []

    # 1. Vietnam Model Ward - concentrated enforcement for worst zones
    if profile['historical_violations'] > MODEL_WARD_VIOLATION_THRESHOLD:
        strategies.append((
            'ACTIVATE_MODEL_WARD',
            f"Historical violations ({profile['historical_violations']:,}) > "
            f"threshold ({MODEL_WARD_VIOLATION_THRESHOLD:,})"
        ))

    # 2. Taipei Zoning - designated 2-wheeler zones
    if profile['two_wheeler_ratio'] > TWO_WHEELER_RATIO_THRESHOLD:
        strategies.append((
            'DESIGNATE_SCOOTER_ZONE',
            f"Two-wheeler ratio ({profile['two_wheeler_ratio']:.1%}) > "
            f"threshold ({TWO_WHEELER_RATIO_THRESHOLD:.0%})"
        ))

    # 3. Bangkok Win System - auto-rickshaw stands
    if profile['three_wheeler_ratio'] > AUTO_RATIO_THRESHOLD:
        strategies.append((
            'CREATE_AUTO_STAND',
            f"Auto/3-wheeler ratio ({profile['three_wheeler_ratio']:.1%}) > "
            f"threshold ({AUTO_RATIO_THRESHOLD:.0%})"
        ))

    # 4. Barcelona Superblock - weekend commercial zones
    if (profile['is_weekend'] and
            profile['weekend_surge_ratio'] > WEEKEND_SURGE_THRESHOLD):
        strategies.append((
            'TEMPORARY_SUPERBLOCK',
            f"Weekend + surge ratio ({profile['weekend_surge_ratio']:.2f}) > "
            f"threshold ({WEEKEND_SURGE_THRESHOLD})"
        ))

    # 5. Indonesia Push-Pull - Park-and-Ride near transit/IT
    if profile['archetype'] in ('IT_CORRIDOR', 'SUBURBAN_TECH'):
        strategies.append((
            'PARK_AND_RIDE',
            f"Zone archetype is {profile['archetype']} (near transit/IT)"
        ))

    # 6. Jakarta Time-Window - heavy vehicle loading restrictions
    if profile['heavy_vehicle_ratio'] > HEAVY_VEHICLE_RATIO_THRESHOLD:
        strategies.append((
            'TIME_WINDOW_ENFORCEMENT',
            f"Heavy vehicle ratio ({profile['heavy_vehicle_ratio']:.1%}) > "
            f"threshold ({HEAVY_VEHICLE_RATIO_THRESHOLD:.0%})"
        ))

    # 7. SFpark Tow Priority - when impact exceeds threshold
    if profile['avg_pcu_impact'] > HIGH_IMPACT_THRESHOLD:
        strategies.append((
            'DEPLOY_TOW_TRUCK',
            f"PCU impact ({profile['avg_pcu_impact']:.1f}) > "
            f"threshold ({HIGH_IMPACT_THRESHOLD})"
        ))

    # 8. Rwanda Formalize - persistent clusters become official zones
    if profile['persistence_score'] > PERSISTENCE_THRESHOLD:
        strategies.append((
            'FORMALIZE_AS_DESIGNATED_ZONE',
            f"Persistence score ({profile['persistence_score']:.2f}) > "
            f"threshold ({PERSISTENCE_THRESHOLD})"
        ))

    # 9. Geofenced idle prohibition - IT corridor + high auto ratio
    if (profile['archetype'] in ('IT_CORRIDOR', 'SUBURBAN_TECH') and
            profile['three_wheeler_ratio'] > 0.15):
        strategies.append((
            'GEOFENCED_IDLE_PROHIBITION',
            f"IT corridor with auto ratio ({profile['three_wheeler_ratio']:.1%})"
        ))

    return strategies



# IMPLEMENTATION PLAYBOOK GENERATOR

def generate_implementation_playbook(profile, strategy_key):
    """
    Generate context-aware implementation details for a specific strategy
    based on the zone's unique profile data.
    """
    playbook = {
        'location': '',
        'scale': '',
        'timing': '',
        'personnel': '',
        'materials': '',
        'coordination': ''
    }
    
    # --- Contextual Logic ---
    
    # 1. Location Context based on Archetype
    arch = profile.get('archetype', 'GENERAL')
    if arch in ['CBD_RETAIL', 'CBD_COMMERCIAL']:
        playbook['location'] = "Deploy on service roads or designated off-street pockets to avoid choking narrow main carriageways."
    elif arch in ['IT_CORRIDOR', 'SUBURBAN_TECH']:
        playbook['location'] = "Utilize wide shoulder strips near tech park boundaries or transit feeder points."
    elif arch in ['TRANSIT_HUB']:
        playbook['location'] = "Focus within 200m radius of transit station entrances/exits."
    else:
        playbook['location'] = "Deploy near primary commercial nodes or major junctions within the zone."
        
    # 2. Scale/Capacity based on PCU and Ratios
    if strategy_key == 'DESIGNATE_SCOOTER_ZONE':
        ratio = profile.get('two_wheeler_ratio', 0)
        pcu = profile.get('avg_pcu_impact', 0)
        if pcu > 50 and ratio > 0.5:
            playbook['scale'] = "High demand (~150+ slots needed). Create 3 rows of diagonal parking."
        elif pcu > 25:
            playbook['scale'] = "Moderate demand (~50-80 slots). Create parallel or single-row diagonal parking."
        else:
            playbook['scale'] = "Standard demand (~30 slots). Single row parallel parking."
            
    elif strategy_key == 'CREATE_AUTO_STAND':
        ratio = profile.get('three_wheeler_ratio', 0)
        pcu = profile.get('avg_pcu_impact', 0)
        if pcu > 50 and ratio > 0.2:
            playbook['scale'] = "Major stand (15-20 autos capacity). Implement queue management."
        else:
            playbook['scale'] = "Standard stand (5-10 autos capacity)."
            
    elif strategy_key == 'DEPLOY_TOW_TRUCK':
        pcu = profile.get('avg_pcu_impact', 0)
        if pcu > 75:
            playbook['scale'] = "Deploy 2 heavy-duty tow trucks; focus entirely on buses/HGVs first."
        else:
            playbook['scale'] = "Deploy 1 tow truck; target highest PCU vehicles."
    else:
        playbook['scale'] = "Scale intervention relative to observed peak volume."

    # 3. Timing based on Hour/Day
    hour = profile.get('hours') or profile.get('hour')
    day = profile.get('day_of_week')
    if hour is not None:
        start_hr = max(0, hour - 1)
        end_hr = min(23, hour + 2)
        day_str = DAY_NAMES[day] if day is not None else "peak days"
        playbook['timing'] = f"Enforce strictly between {start_hr}:00 and {end_hr}:00 on {day_str}s."
    else:
        playbook['timing'] = "Continuous enforcement required based on historical patterns."
        
    # 4. Personnel based on Validation Ratio
    val_ratio = profile.get('validation_ratio', 1.0)
    if pd.isna(val_ratio):
        val_ratio = 1.0
    if val_ratio < 0.4:
        playbook['personnel'] = "Historical follow-through is low. Assign a senior officer (Inspector level) to supervise."
    else:
        playbook['personnel'] = "Standard deployment. Zone has good historical compliance record."
        
    # 5. Materials based on Persistence Score
    persistence = profile.get('persistence_score', 0)
    if persistence > 0.8:
        playbook['materials'] = "Chronic issue. Use permanent infrastructure (painted lines, concrete bollards, mounted signs)."
    else:
        playbook['materials'] = "Spike issue. Use temporary infrastructure (traffic cones, barricades, portable signs)."
        
    # 6. Coordination based on Spatial Lag
    delta = profile.get('spatial_lag_delta', 0)
    if delta > 10:
        playbook['coordination'] = "Neighboring zones have higher pressure. Expect spillover; alert adjacent traffic stations."
    elif delta < -10:
        playbook['coordination'] = "This zone is the core pressure point. Interventions here will relieve neighbor zones."
    else:
        playbook['coordination'] = "Spatial pressure is balanced. Standalone intervention is sufficient."

    return playbook



# DIRECTIVE GENERATOR

DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
             'Friday', 'Saturday', 'Sunday']


def generate_directive(profile, strategies):
    """
    Generate a human-readable enforcement directive for a zone.
    """
    zone = profile['zone']
    hour = profile.get('hours') or profile.get('hour')
    day = profile['day_of_week']

    day_name = DAY_NAMES[day] if day is not None else 'All days'
    hour_str = f"{hour}:00" if hour is not None else 'All hours'

    lines = []
    lines.append(f"\n{'='*65}")
    lines.append(f"  ENFORCEMENT DIRECTIVE: {zone}")
    lines.append(f"  Time: {day_name} {hour_str} IST")
    lines.append(f"  Zone Type: {profile['archetype']}")
    lines.append(f"{'='*65}")
    lines.append(f"  PCU Impact Score: {profile['avg_pcu_impact']:.1f} "
                 f"({'HIGH' if profile['avg_pcu_impact'] > HIGH_IMPACT_THRESHOLD else 'MODERATE' if profile['avg_pcu_impact'] > HIGH_IMPACT_THRESHOLD/2 else 'LOW'})")
    lines.append(f"  Time Classification: Duration={profile['duration_class']}, Burstiness={profile['burst_class']}")
    lines.append(f"  Vehicle Composition:")
    lines.append(f"    Two-wheelers: {profile['two_wheeler_ratio']:.1%}")
    lines.append(f"    Auto/3-wheelers: {profile['three_wheeler_ratio']:.1%}")
    lines.append(f"    Heavy vehicles: {profile['heavy_vehicle_ratio']:.1%}")
    lines.append(f"  Spatial Pressure: neighbor PCU={profile['spatial_lag_pcu']:.1f}, "
                 f"delta={profile['spatial_lag_delta']:.1f}")
    lines.append(f"  Enforcement Quality: validation ratio={profile['validation_ratio']:.1%}")
    lines.append(f"  Location: ({profile['lat']:.4f}, {profile['lon']:.4f}), "
                 f"{profile['distance_to_cbd']:.1f}km from CBD")

    if strategies:
        lines.append(f"\n  RECOMMENDED ACTIONS ({len(strategies)}):")
        lines.append(f"  {'-'*50}")
        for i, (strategy_key, reason) in enumerate(strategies, 1):
            info = STRATEGY_CATALOG[strategy_key]
            playbook = generate_implementation_playbook(profile, strategy_key)
            lines.append(f"  {i}. {info['name']} [{info['source']}]")
            lines.append(f"     Action: {info['action']}")
            lines.append(f"     Reason: {reason}")
            lines.append(f"     Min officers: {info['min_officers']}")
            lines.append(f"     --- Playbook ---")
            lines.append(f"     Location: {playbook['location']}")
            lines.append(f"     Scale: {playbook['scale']}")
            lines.append(f"     Timing: {playbook['timing']}")
            lines.append(f"     Personnel: {playbook['personnel']}")
            lines.append(f"     Materials: {playbook['materials']}")
            lines.append(f"     Coordination: {playbook['coordination']}")
    else:
        lines.append(f"\n  STATUS: LOW PRIORITY - No specific intervention needed")

    return '\n'.join(lines)



# CONSTRAINED RESOURCE ALLOCATION (Linear Programming)

def allocate_resources(zone_profiles, strategies_per_zone, total_officers=TOTAL_OFFICERS):
    """
    Solve the constrained officer allocation problem via Linear Programming.

    Objective: max sum_i (predicted_pcu_i * strategy_multiplier_i * x_i)
    Subject to:
      - sum(x_i) <= total_officers
      - x_i >= min_officers for zones above PCU threshold
      - x_i >= 0, integer

    Returns dict of {zone: officers_assigned}
    """
    print(f"\n{'='*65}")
    print(f"  RESOURCE ALLOCATION (LP Optimization)")
    print(f"  Total officers available: {total_officers}")
    print(f"{'='*65}")

    zones = list(zone_profiles.keys())
    n_zones = len(zones)

    if n_zones == 0:
        print("  No zones to allocate.")
        return {}

    # Compute effectiveness coefficient for each zone
    coefficients = []
    min_bounds = []

    for zone in zones:
        profile = zone_profiles[zone]
        strategies = strategies_per_zone.get(zone, [])

        # Max effectiveness multiplier from selected strategies
        if strategies:
            max_mult = max(
                STRATEGY_CATALOG[s[0]]['effectiveness_multiplier']
                for s in strategies
            )
            # Min officers needed for the most demanding strategy
            min_off = max(
                STRATEGY_CATALOG[s[0]]['min_officers']
                for s in strategies
            )
        else:
            max_mult = 0.5  # Low priority zones still get something if available
            min_off = 0

        coeff = profile['avg_pcu_impact'] * max_mult
        coefficients.append(coeff)

        # Only enforce minimum if zone is above threshold
        if profile['avg_pcu_impact'] > HIGH_IMPACT_THRESHOLD / 2:
            min_bounds.append(min(min_off, total_officers))
        else:
            min_bounds.append(0)

    # Check if minimum bounds exceed total
    total_min = sum(min_bounds)
    if total_min > total_officers:
        print(f"  WARNING: Minimum officer requirements ({total_min}) exceed "
              f"available ({total_officers}). Relaxing constraints.")
        # Scale down minimums proportionally
        scale = total_officers / total_min * 0.8  # Leave 20% slack
        min_bounds = [max(0, int(m * scale)) for m in min_bounds]

    # Solve LP (linprog minimizes, so negate for maximization)
    c = [-coeff for coeff in coefficients]  # Negate for minimization

    # Constraint: sum(x_i) <= total_officers
    A_ub = [[1] * n_zones]
    b_ub = [total_officers]

    # Bounds: min_officers <= x_i <= total_officers
    bounds = [(min_bounds[i], total_officers) for i in range(n_zones)]

    result = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds,
                     method='highs', options={'presolve': True})

    if result.success:
        allocation = {}
        for i, zone in enumerate(zones):
            officers = max(0, round(result.x[i]))
            allocation[zone] = officers

        # Ensure total doesn't exceed budget (rounding can cause overflow)
        total_assigned = sum(allocation.values())
        while total_assigned > total_officers:
            # Reduce from least impactful zone
            min_zone = min(
                (z for z in allocation if allocation[z] > min_bounds[zones.index(z)]),
                key=lambda z: coefficients[zones.index(z)]
            )
            allocation[min_zone] -= 1
            total_assigned -= 1

        # Print allocation
        sorted_zones = sorted(allocation.items(), key=lambda x: x[1], reverse=True)
        print(f"\n  Officer Allocation:")
        print(f"  {'Zone':<25s} {'Officers':>8s} {'PCU Impact':>12s} {'Strategy':>10s}")
        print(f"  {'-'*55}")
        for zone, officers in sorted_zones:
            if officers > 0:
                pcu = zone_profiles[zone]['avg_pcu_impact']
                n_strats = len(strategies_per_zone.get(zone, []))
                print(f"  {zone:<25s} {officers:>8d} {pcu:>12.1f} {n_strats:>10d}")

        total_used = sum(v for v in allocation.values())
        print(f"\n  Total officers assigned: {total_used}/{total_officers}")
        print(f"  Officers in reserve: {total_officers - total_used}")

        return allocation
    else:
        print(f"  LP optimization failed: {result.message}")
        print("  Falling back to proportional allocation...")

        # Proportional fallback
        total_coeff = sum(coefficients) or 1
        allocation = {}
        for i, zone in enumerate(zones):
            prop = coefficients[i] / total_coeff
            allocation[zone] = max(min_bounds[i], round(prop * total_officers))

        return allocation



# FULL DECISION ENGINE RUN

def run_decision_engine(aggregated_df, hour=10, day_of_week=6):
    """
    Run the full decision engine for all zones at a specific time.
    Returns (all_directives, allocation).
    """
    hours = hour
    print(f"\n{'='*65}")
    print(f"  DECISION ENGINE RUN: {DAY_NAMES[day_of_week]} Hours: {hours} IST")
    print(f"{'='*65}")

    zones = aggregated_df['police_station'].unique()
    zone_profiles = {}
    strategies_per_zone = {}
    directives = []
    
    # Load time classifications
    try:
        with open('time_blocks.json', 'r') as f:
            classifications = json.load(f)
    except:
        classifications = {}

    for zone in sorted(zones):
        profile = build_zone_profile(aggregated_df, zone, hours, day_of_week, classifications)
        if profile is None:
            continue

        zone_profiles[zone] = profile
        strategies = select_strategies(profile)
        strategies_per_zone[zone] = strategies

        directive = generate_directive(profile, strategies)
        directives.append(directive)

    # Sort directives by PCU impact (highest first)
    sorted_profiles = sorted(
        zone_profiles.items(),
        key=lambda x: x[1]['avg_pcu_impact'],
        reverse=True
    )

    # Print top 5 directives
    print(f"\n  TOP 5 ZONES BY PCU IMPACT:")
    for zone, profile in sorted_profiles[:5]:
        strategies = strategies_per_zone.get(zone, [])
        directive = generate_directive(profile, strategies)
        print(directive)

    # Resource allocation
    allocation = allocate_resources(zone_profiles, strategies_per_zone)

    return directives, allocation, zone_profiles, strategies_per_zone



# STANDALONE TEST

if __name__ == '__main__':
    print("Loading aggregated data...")

    try:
        # Try loading pre-computed aggregated data
        aggregated = pd.read_csv('aggregated_zone_hourly.csv')
        print(f"  Loaded aggregated data: {aggregated.shape}")
    except FileNotFoundError:
        # Full pipeline
        from data_loader import load_parking_data, clean_parking_data, convert_utc_to_ist
        from feature_engineer import engineer_all_features

        df = load_parking_data()
        df = clean_parking_data(df)
        df = convert_utc_to_ist(df)
        aggregated, _, _ = engineer_all_features(df)

    # Run for Sunday 10 AM (peak violation time)
    directives, allocation, profiles, strategies = run_decision_engine(
        aggregated, hour=10, day_of_week=6  # Sunday
    )

    # Also run for Monday 9 AM (weekday comparison)
    print("\n\n" + "#" * 70)
    print("WEEKDAY COMPARISON: Monday 9 AM")
    print("#" * 70)
    run_decision_engine(aggregated, hour=9, day_of_week=0)

    print("\nDecision Engine test complete!")
