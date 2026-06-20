# Script for tuning the KNN model parameters and feature weights offline.
"""Offline model selection built entirely on the canonical evaluator.

Prior observed validation/test days may enter later walk-forward pools. The
current target and all future dates are always excluded. Selection uses only
validation F1; the selected configuration is then evaluated once on test.
"""

import json
from pathlib import Path

import numpy as np

from src.utils.compare_weights import derive_weight_table
from src.modeling.evaluate_model import (
    calculate_metrics,
    evaluate_dates,
    load_daily_impacts,
    metric_spread,
    per_day_metrics,
    split_dates,
    sweep_thresholds,
    threshold_grid,
    zone_coverage,
)
from src.modeling.knn_core import CALENDAR_FEATURE_NAMES


K_OPTIONS = (8, 12, 16, 20)
MODEL_CONFIG_PATH = Path(__file__).with_name('knn_model_config.json')
EVALUATION_RESULTS_PATH = Path(__file__).with_name('evaluation_results.json')


def weight_options():
    table, _, _ = derive_weight_table()
    return {
        'training_correlation': table['correlation'].to_numpy(dtype=float),
        'training_random_forest': table['random_forest'].to_numpy(dtype=float),
        'equal': np.ones(len(CALENDAR_FEATURE_NAMES)),
    }


def metrics_dict(metrics):
    return dict(zip(
        ('precision', 'recall', 'f1', 'tp', 'fp', 'tn', 'fn'), metrics
    ))


def run_tuning():
    daily_impacts = load_daily_impacts()
    all_dates, train_dates, validation_dates, test_dates = split_dates(daily_impacts)
    print(f'Training seed: {len(train_dates)} days')
    print(f'Validation: {len(validation_dates)} days')
    print(f'Test: {len(test_dates)} days')
    print('\n--- Walk-Forward Validation Model Selection (objective: F1) ---')

    best_config = None
    for weight_name, weights in weight_options().items():
        for k in K_OPTIONS:
            records = evaluate_dates(daily_impacts, validation_dates, weights, k)
            sweep, best = sweep_thresholds(records, threshold_grid())
            print(
                f'{weight_name:<24} K={k:<2} threshold={best["threshold"]:>5.1f}% '
                f'precision={best["precision"]:.3f} recall={best["recall"]:.3f} '
                f'F1={best["f1"]:.3f}'
            )
            candidate = {
                'weight_name': weight_name,
                'feature_weights': weights,
                'k': k,
                'best': best,
                'sweep': sweep,
                'validation_records': records,
            }
            if best_config is None or (
                best['f1'], best['precision'], best['recall']
            ) > (
                best_config['best']['f1'],
                best_config['best']['precision'],
                best_config['best']['recall'],
            ):
                best_config = candidate

    selected = {
        'k': best_config['k'],
        'feature_names': list(CALENDAR_FEATURE_NAMES),
        'feature_weights': best_config['feature_weights'].tolist(),
        'confidence_threshold': best_config['best']['threshold'],
        'selection_objective': 'f1',
        'objective_reason': (
            'F1 is the neutral baseline because no operational false-alert '
            'versus missed-hotspot cost matrix has been supplied.'
        ),
        'training_days': len(train_dates),
        'validation_days': len(validation_dates),
        'selected_weight_method': best_config['weight_name'],
        'validation_metrics': {
            key: best_config['best'][key]
            for key in ('precision', 'recall', 'f1', 'tp', 'fp', 'tn', 'fn')
        },
    }
    MODEL_CONFIG_PATH.write_text(json.dumps(selected, indent=2), encoding='utf-8')

    # This is the only test evaluation in the selection workflow.
    test_records = evaluate_dates(
        daily_impacts, test_dates, best_config['feature_weights'], best_config['k']
    )
    test_metrics = calculate_metrics(test_records, selected['confidence_threshold'])
    validation_daily = per_day_metrics(
        best_config['validation_records'], selected['confidence_threshold']
    )
    test_daily = per_day_metrics(test_records, selected['confidence_threshold'])
    final_date = test_dates[-1]
    final_day_records = [row for row in test_records if row['date'] == final_date]
    final_day_sweep, _ = sweep_thresholds(final_day_records, threshold_grid())
    coverage = zone_coverage(daily_impacts, all_dates)
    coverage.to_csv('zone_data_coverage.csv', index=False)

    results = {
        'model_config': selected,
        'date_splits': {
            'training': [train_dates[0], train_dates[-1]],
            'validation': [validation_dates[0], validation_dates[-1]],
            'test': [test_dates[0], test_dates[-1]],
        },
        'validation_sweep': best_config['sweep'],
        'validation_daily': validation_daily,
        'validation_spread': {
            metric: metric_spread(validation_daily, metric)
            for metric in ('precision', 'recall', 'f1')
        },
        'test_metrics': metrics_dict(test_metrics),
        'test_daily': test_daily,
        'test_spread': {
            metric: metric_spread(test_daily, metric)
            for metric in ('precision', 'recall', 'f1')
        },
        'final_test_date': final_date,
        'final_test_day_sweep': final_day_sweep,
    }
    EVALUATION_RESULTS_PATH.write_text(
        json.dumps(results, indent=2), encoding='utf-8'
    )

    print(
        f'\nSelected {best_config["weight_name"]}, K={selected["k"]}, '
        f'threshold={selected["confidence_threshold"]:.1f}%.'
    )
    print('\n--- Test Set (one run after selection) ---')
    print(f'Precision: {test_metrics[0]:.3f}')
    print(f'Recall:    {test_metrics[1]:.3f}')
    print(f'F1 Score:  {test_metrics[2]:.3f}')
    for split_name, daily_rows in (
        ('Validation', validation_daily), ('Test', test_daily)
    ):
        spread = metric_spread(daily_rows, 'f1')
        print(
            f'{split_name} daily F1: mean={spread["mean"]:.3f}, '
            f'std={spread["std"]:.3f}, min={spread["min"]:.3f}, '
            f'max={spread["max"]:.3f}'
        )
    print(f'Saved frozen runtime config to {MODEL_CONFIG_PATH.name}')
    print(f'Saved evaluation evidence to {EVALUATION_RESULTS_PATH.name}')
    return selected, results


if __name__ == '__main__':
    run_tuning()
