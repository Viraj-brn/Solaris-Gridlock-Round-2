# Script to evaluate the calendar KNN hotspot model using walk-forward validation.
"""Canonical walk-forward evaluation for the calendar KNN hotspot model."""

import warnings

import numpy as np
import pandas as pd

from knn_core import (
    DEFAULT_FEATURE_WEIGHTS,
    MODEL_K,
    aggregate_daily_pcu,
    predict_zone_day_records,
)

warnings.filterwarnings('ignore')

TRAIN_DAYS = 120
VALIDATION_DAYS = 15


# Load and aggregate daily impact data from CSV.
def load_daily_impacts(path='cleaned_parking_data.csv'):
    raw_df = pd.read_csv(
        path, usecols=['police_station', 'ist_date', 'vehicle_type']
    )
    return aggregate_daily_pcu(raw_df)


# Split available dates into train, validation, and test sets.
def split_dates(daily_impacts, train_days=TRAIN_DAYS,
                validation_days=VALIDATION_DAYS):
    dates = sorted(daily_impacts['ist_date'].unique())
    if len(dates) <= train_days:
        raise ValueError(
            f'Need more than {train_days} dates for evaluation; found {len(dates)}.'
        )
    train_dates = dates[:train_days]
    validation_dates = dates[train_days:train_days + validation_days]
    test_dates = dates[train_days + validation_days:]
    return dates, train_dates, validation_dates, test_dates


def evaluate_dates(daily_impacts, eval_dates,
                   feature_weights=DEFAULT_FEATURE_WEIGHTS, k=MODEL_K):
    """Evaluate dates walk-forward using every strictly earlier day."""
    all_dates = sorted(daily_impacts['ist_date'].unique())
    records = []
    for target_date in eval_dates:
        candidate_dates = [date for date in all_dates if date < target_date]
        records.extend(predict_zone_day_records(
            daily_impacts,
            target_date,
            candidate_dates,
            feature_weights=feature_weights,
            k=k,
            min_history_days=k,
        ))
    return records


def calculate_metrics(predictions, threshold):
    """Calculate metrics for confidence values expressed as percentages."""
    tp = fp = tn = fn = 0
    for prediction in predictions:
        if isinstance(prediction, dict):
            confidence = prediction['confidence'] * 100.0
            actual = prediction['actual_hotspot']
        else:
            confidence, actual = prediction

        predicted = confidence >= threshold
        if predicted and actual:
            tp += 1
        elif predicted:
            fp += 1
        elif actual:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1, tp, fp, tn, fn


def threshold_grid():
    """Weighted agreement is continuous, so evaluate 5-point increments."""
    return [float(value) for value in range(0, 101, 5)]


# Evaluate predictions across multiple thresholds to find the best configuration.
def sweep_thresholds(predictions, thresholds=None):
    thresholds = threshold_grid() if thresholds is None else thresholds
    rows = []
    best = None
    for threshold in thresholds:
        metrics = calculate_metrics(predictions, threshold)
        row = {
            'threshold': threshold,
            'precision': metrics[0],
            'recall': metrics[1],
            'f1': metrics[2],
            'tp': metrics[3],
            'fp': metrics[4],
            'tn': metrics[5],
            'fn': metrics[6],
        }
        rows.append(row)
        if best is None or (
            row['f1'], row['precision'], row['recall']
        ) > (
            best['f1'], best['precision'], best['recall']
        ):
            best = row
    return rows, best


# Calculate performance metrics on a daily basis.
def per_day_metrics(records, threshold):
    dates = sorted({record['date'] for record in records})
    rows = []
    for date in dates:
        metrics = calculate_metrics(
            [record for record in records if record['date'] == date], threshold
        )
        rows.append({
            'date': date,
            'precision': metrics[0],
            'recall': metrics[1],
            'f1': metrics[2],
            'tp': metrics[3],
            'fp': metrics[4],
            'tn': metrics[5],
            'fn': metrics[6],
        })
    return rows


# Calculate statistical spread (mean, std, min, max) for a given metric.
def metric_spread(daily_rows, metric):
    values = np.array([row[metric] for row in daily_rows], dtype=float)
    return {
        'mean': float(values.mean()),
        'std': float(values.std()),
        'min': float(values.min()),
        'max': float(values.max()),
    }


# Calculate observation coverage percentage per zone.
def zone_coverage(daily_impacts, dates):
    pool = daily_impacts[daily_impacts['ist_date'].isin(dates)]
    counts = pool.groupby('police_station', observed=True)['ist_date'].nunique()
    return pd.DataFrame({
        'police_station': counts.index,
        'observed_days': counts.values,
        'possible_days': len(dates),
        'coverage_pct': counts.values / len(dates) * 100.0,
    }).sort_values('coverage_pct')


# Build the full walk-forward evaluation result set.
def build_evaluation(feature_weights=DEFAULT_FEATURE_WEIGHTS, k=MODEL_K,
                     include_test=True):
    daily_impacts = load_daily_impacts()
    dates, train_dates, validation_dates, test_dates = split_dates(daily_impacts)
    validation_records = evaluate_dates(
        daily_impacts, validation_dates, feature_weights, k
    )
    validation_sweep, best = sweep_thresholds(
        validation_records, threshold_grid()
    )
    result = {
        'dates': dates,
        'train_dates': train_dates,
        'validation_dates': validation_dates,
        'test_dates': test_dates,
        'validation_records': validation_records,
        'validation_sweep': validation_sweep,
        'best': best,
        'feature_weights': np.asarray(feature_weights, dtype=float),
        'k': k,
        'validation_daily': per_day_metrics(validation_records, best['threshold']),
        'coverage': zone_coverage(daily_impacts, dates),
    }
    if include_test:
        test_records = evaluate_dates(daily_impacts, test_dates, feature_weights, k)
        result['test_records'] = test_records
        result['test_metrics'] = calculate_metrics(test_records, best['threshold'])
        result['test_daily'] = per_day_metrics(test_records, best['threshold'])
    return result


# Generate and save a plot comparing metrics across thresholds.
def save_threshold_plot(result, path='threshold_plot.png'):
    import matplotlib.pyplot as plt

    sweep = result['validation_sweep']
    thresholds = [row['threshold'] for row in sweep]
    fig, ax1 = plt.subplots(figsize=(10, 6))
    ax1.plot(thresholds, [row['precision'] for row in sweep], marker='o', label='Precision', color='#673AB7')
    ax1.plot(thresholds, [row['recall'] for row in sweep], marker='o', label='Recall', color='#2979FF')
    ax1.plot(thresholds, [row['f1'] for row in sweep], marker='o', label='F1-Score', color='#FFB300')
    ax1.axvline(result['best']['threshold'], color='red', linestyle='--', label=f"Optimal ({result['best']['threshold']:.1f}%)")
    ax1.set_xlabel('Weighted Neighbor Agreement Threshold (%)')
    ax1.set_ylabel('Score')
    ax1.grid(True, alpha=0.3)

    ax2 = ax1.twinx()
    totals = [row['tp'] + row['fp'] for row in sweep]
    ax2.bar(thresholds, totals, width=3.0, alpha=0.15, color='gray', label='Predicted Hotspots')
    ax2.set_ylabel('Total Predicted Hotspots', color='gray')
    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='center right')
    plt.title('Threshold vs Evaluation Metrics (Walk-Forward Validation)')
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close(fig)


# Execute the full evaluation pipeline and print summary results.
def run_evaluation(save_plot=True):
    print('Loading and evaluating data with walk-forward candidate pools...')
    result = build_evaluation()
    print(f"Train baseline: {len(result['train_dates'])} days")
    print(f"Validation: {len(result['validation_dates'])} days")
    print(f"Test: {len(result['test_dates'])} days\n")
    print(f"{'Threshold':<12} | {'Precision':<10} | {'Recall':<10} | {'F1-Score':<10}")
    print('-' * 55)
    for row in result['validation_sweep']:
        print(
            f"{row['threshold']:>9.1f}%  | {row['precision']:>9.3f}  | "
            f"{row['recall']:>9.3f}  | {row['f1']:>9.3f}"
        )

    best = result['best']
    print(
        f"\n=> Optimal validation threshold: {best['threshold']:.1f}% "
        f"(F1: {best['f1']:.3f})"
    )
    p, r, f1, tp, fp, tn, fn = result['test_metrics']
    print(f"\nTest metrics at {best['threshold']:.1f}%:")
    print(f'Precision: {p:.3f}')
    print(f'Recall:    {r:.3f}')
    print(f'F1-Score:  {f1:.3f}')
    print(f'TP={tp}, FP={fp}, TN={tn}, FN={fn}')

    for split_name in ('validation', 'test'):
        daily_rows = result[f'{split_name}_daily']
        print(f'\n{split_name.title()} per-day spread:')
        for metric in ('precision', 'recall', 'f1'):
            spread = metric_spread(daily_rows, metric)
            print(
                f"  {metric}: mean={spread['mean']:.3f}, "
                f"std={spread['std']:.3f}, min={spread['min']:.3f}, "
                f"max={spread['max']:.3f}"
            )

    result['coverage'].to_csv('zone_data_coverage.csv', index=False)
    print('\nSaved zone coverage to zone_data_coverage.csv')

    if save_plot:
        save_threshold_plot(result)
        print('Saved plot to threshold_plot.png')
    return result


if __name__ == '__main__':
    run_evaluation()
