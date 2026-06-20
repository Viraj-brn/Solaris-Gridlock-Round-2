"""Plot the final test date using frozen evaluation evidence."""

import json
from pathlib import Path

import matplotlib.pyplot as plt


results = json.loads(
    Path('evaluation_results.json').read_text(encoding='utf-8')
)
sweep = results['final_test_day_sweep']
target_date = results['final_test_date']
chosen_threshold = results['model_config']['confidence_threshold']
thresholds = [row['threshold'] for row in sweep]

fig, ax1 = plt.subplots(figsize=(10, 6))
ax1.plot(thresholds, [row['precision'] for row in sweep], marker='o', label='Precision', color='#673AB7')
ax1.plot(thresholds, [row['recall'] for row in sweep], marker='o', label='Recall', color='#2979FF')
ax1.plot(thresholds, [row['f1'] for row in sweep], marker='o', label='F1-Score', color='#FFB300')
ax1.axvline(chosen_threshold, color='red', linestyle='--', label=f'Validation-selected threshold ({chosen_threshold:.1f}%)')
ax1.set_xlabel('Weighted Neighbor Agreement Threshold (%)')
ax1.set_ylabel('Score')
ax1.grid(True, alpha=0.3)

ax2 = ax1.twinx()
ax2.bar(thresholds, [row['tp'] + row['fp'] for row in sweep], width=3.0, alpha=0.15, color='gray', label='Predicted Hotspots')
ax2.set_ylabel('Predicted Hotspots', color='gray')
lines_1, labels_1 = ax1.get_legend_handles_labels()
lines_2, labels_2 = ax2.get_legend_handles_labels()
ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='center right')
plt.title(f'Threshold Metrics for Final Test Date {target_date}')
plt.tight_layout()
plt.savefig('single_day_plot.png', dpi=300)
plt.close(fig)
print(f'Saved frozen single-day evidence for {target_date}')
