
DATA_FILE = 'data/raw/dataset round2/jan to may police violation_anonymized791b166.csv'

# PCU (Passenger Car Unit) WEIGHTS — Indian Highway Capacity Manual
PCU_MAP = {
    # Two-wheelers (Vietnam/Taipei strategy targets)
    'SCOOTER': 0.5,
    'MOTOR CYCLE': 0.5,
    'MOPED': 0.5,
    # Standard cars
    'CAR': 1.0,
    'JEEP': 1.0,
    # Three-wheelers (Bangkok Win System targets)
    'PASSENGER AUTO': 0.75,
    'GOODS AUTO': 0.75,
    # Light commercial
    'MAXI-CAB': 1.5,
    'LGV': 1.5,
    'VAN': 1.5,
    'TEMPO': 1.5,
    'MINI LORRY': 1.5,
    # Heavy vehicles (highest tow priority — SFpark/Tokyo)
    'PRIVATE BUS': 3.0,
    'BUS (BMTC/KSRTC)': 3.5,
    'LORRY/GOODS VEHICLE': 3.0,
    'HGV': 4.5,
    'TANKER': 3.0,
    'SCHOOL VEHICLE': 3.0,
    'TOURIST BUS': 3.0,
    'FACTORY BUS': 3.0,
    'TRACTOR': 3.0,
    'OTHERS': 1.0,
}
PCU_DEFAULT = 1.0  # Fallback for unmapped vehicle types

# TWO-WHEELER / THREE-WHEELER / HEAVY VEHICLE CATEGORIES
TWO_WHEELER_TYPES = {'SCOOTER', 'MOTOR CYCLE', 'MOPED'}
THREE_WHEELER_TYPES = {'PASSENGER AUTO', 'GOODS AUTO'}
HEAVY_VEHICLE_TYPES = {'BUS (BMTC/KSRTC)', 'PRIVATE BUS', 'HGV', 'LORRY/GOODS VEHICLE', 'LGV'}

# ZONE ARCHETYPES — Maps police stations to their "personality"
ZONE_ARCHETYPES = {
    'Upparpet': 'CBD_RETAIL',
    'Shivajinagar': 'CBD_COMMERCIAL',
    'Malleshwaram': 'RESIDENTIAL_COMMERCIAL',
    'HAL Old Airport': 'IT_CORRIDOR',
    'City Market': 'TRANSIT_HUB',
    'Vijayanagara': 'MIXED_RESIDENTIAL',
    'Rajajinagar': 'MID_COMMERCIAL',
    'Kodigehalli': 'SUBURBAN_TECH',
    'Madiwala': 'TRANSIT_HUB',
    'Bellandur': 'IT_CORRIDOR',
    'HSR Layout': 'IT_CORRIDOR',
    'Indiranagar': 'RESIDENTIAL_COMMERCIAL',
    'Jayanagar': 'RESIDENTIAL_COMMERCIAL',
    'Whitefield': 'SUBURBAN_TECH',
    'Yelahanka': 'SUBURBAN_TECH',
}
ZONE_ARCHETYPE_DEFAULT = 'GENERAL'

# BANGALORE REFERENCE COORDINATES
CBD_LAT = 12.9716   # Majestic / KSR Station
CBD_LON = 77.5946


# THRESHOLDS
HIGH_IMPACT_THRESHOLD = 50.0       # PCU score above which tow trucks deploy
SPILLOVER_RADIUS_KM = 3.0          # Neighbor zone radius for balloon effect
PERSISTENCE_THRESHOLD = 0.8        # Fraction of timeslots with violations
WEEKEND_SURGE_THRESHOLD = 1.2      # Weekend/weekday ratio for superblock trigger
TWO_WHEELER_RATIO_THRESHOLD = 0.50 # Taipei zoning trigger
AUTO_RATIO_THRESHOLD = 0.25        # Bangkok Win System trigger
HEAVY_VEHICLE_RATIO_THRESHOLD = 0.10  # Jakarta time-window trigger
MODEL_WARD_VIOLATION_THRESHOLD = 15000  # Vietnam Model Ward trigger


# RESOURCE CONSTRAINTS
TOTAL_OFFICERS = 20


# CALENDAR KNN
KNN_K = 20
KNN_MIN_HISTORY_DAYS = KNN_K
KNN_FEATURE_WEIGHTS = (
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
)
# Fallbacks used only if knn_model_config.json has not been generated yet.
KNN_CONFIDENCE_THRESHOLD = 40.0
KNN_SELECTION_OBJECTIVE = 'f1'


# COLUMNS TO DROP (noise / PII / irrelevant)

COLUMNS_TO_DROP = [
    'id',
    'vehicle_number',
    'updated_vehicle_number',
    'description',
    'closed_datetime',
    'modified_datetime',
    'device_id',
    'created_by_id',
    'data_sent_to_scita',
    'action_taken_timestamp',
    'data_sent_to_scita_timestamp',
    'updated_vehicle_type',
    'validation_timestamp',
]
