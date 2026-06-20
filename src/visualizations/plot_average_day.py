"""Plot daily validation averages from the frozen evaluation evidence."""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


results = json.loads(
    Path('models/evaluation_results.json').read_text(encoding='utf-8')
)
daily_metrics = results['validation_daily']
threshold = results['model_config']['confidence_threshold']
tp = np.mean([row['tp'] for row in daily_metrics])
fp = np.mean([row['fp'] for row in daily_metrics])
tn = np.mean([row['tn'] for row in daily_metrics])
fn = np.mean([row['fn'] for row in daily_metrics])

labels = [
    'True Positives\n(Correct Alerts)',
    'False Positives\n(False Alarms)',
    'False Negatives\n(Missed Hotspots)',
    'True Negatives\n(Correctly Quiet)',
]
values = [tp, fp, fn, tn]
colors = ['#4CAF50', '#FFC107', '#F44336', '#2196F3']

plt.figure(figsize=(10, 6))
bars = plt.bar(labels, values, color=colors, edgecolor='black', linewidth=1.2)
for bar in bars:
    value = bar.get_height()
    plt.text(
        bar.get_x() + bar.get_width() / 2.0, value + 0.3, f'{value:.1f}',
        ha='center', va='bottom', fontsize=12, fontweight='bold'
    )

plt.title(
    f'Mean Daily Validation Results ({len(daily_metrics)} Days, '
    f'Threshold {threshold:.1f}%)',
    fontsize=14, fontweight='bold', pad=20,
)
plt.ylabel('Mean Number of Police Station Zones per Day', fontsize=12)
plt.grid(axis='y', linestyle='--', alpha=0.7)
plt.ylim(0, max(values) * 1.3)
plt.tight_layout()
plt.savefig('average_day_matrix.png', dpi=300)
plt.close()
print('Saved validation averages from evaluation_results.json')
