"""Compare calendar-feature weights using training-pool zone-level PCU impact."""

import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.feature_selection import mutual_info_regression
from sklearn.linear_model import LinearRegression

from src.modeling.evaluate_model import TRAIN_DAYS
from src.modeling.knn_core import (
    CALENDAR_FEATURE_NAMES,
    aggregate_daily_pcu,
    generate_calendar_features,
)

warnings.filterwarnings('ignore')


def normalize(values):
    values = np.nan_to_num(np.asarray(values, dtype=float), nan=0.0)
    low, high = values.min(), values.max()
    if high == low:
        return np.ones_like(values) * 3.0
    return 1.0 + 4.0 * ((values - low) / (high - low))


def build_training_matrix(path='data/processed/cleaned_parking_data.csv'):
    raw = pd.read_csv(
        path, usecols=['police_station', 'ist_date', 'vehicle_type']
    )
    daily_impacts = aggregate_daily_pcu(raw)
    dates = sorted(daily_impacts['ist_date'].unique())
    train_dates = dates[:TRAIN_DAYS]
    training = daily_impacts[daily_impacts['ist_date'].isin(train_dates)].copy()
    features = np.vstack([
        generate_calendar_features(date) for date in training['ist_date']
    ])
    return features, training['impact'].to_numpy(), train_dates


def derive_weight_table(path='data/processed/cleaned_parking_data.csv'):
    features, target, train_dates = build_training_matrix(path)

    random_forest = RandomForestRegressor(n_estimators=100, random_state=42)
    random_forest.fit(features, target)

    linear_regression = LinearRegression()
    linear_regression.fit(features, target)

    mutual_information = mutual_info_regression(
        features, target, random_state=42
    )
    frame = pd.DataFrame(features, columns=CALENDAR_FEATURE_NAMES)
    frame['target'] = target
    correlations = frame.corr(numeric_only=True)['target'].drop('target').abs()

    table = pd.DataFrame({
        'feature': CALENDAR_FEATURE_NAMES,
        'random_forest': normalize(random_forest.feature_importances_),
        'linear_regression': normalize(np.abs(linear_regression.coef_)),
        'mutual_information': normalize(mutual_information),
        'correlation': normalize(correlations.reindex(CALENDAR_FEATURE_NAMES).to_numpy()),
    })
    return table, train_dates, len(target)


def main():
    print('Loading training-pool zone-level PCU impacts...')
    table, train_dates, sample_count = derive_weight_table()
    print(
        f'Using {len(train_dates)} training dates '
        f'({train_dates[0]} through {train_dates[-1]}) and {sample_count} zone-days.'
    )
    print('\n--- FEATURE WEIGHTS COMPARISON (Scaled 1.0 to 5.0) ---')
    print(
        f"{'Feature':<22} | {'Rand. Forest':<12} | {'Linear Reg':<12} | "
        f"{'Mutual Info':<12} | {'Correlation':<12}"
    )
    print('-' * 83)
    for row in table.itertuples(index=False):
        print(
            f'{row.feature:<22} | {row.random_forest:<12.3f} | '
            f'{row.linear_regression:<12.3f} | {row.mutual_information:<12.3f} | '
            f'{row.correlation:<12.3f}'
        )
    table.to_csv('data/processed/calendar_feature_weights.csv', index=False)
    print('\nSaved corrected table to calendar_feature_weights.csv')


if __name__ == '__main__':
    main()
