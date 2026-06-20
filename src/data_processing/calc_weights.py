"""Legacy entry point for the canonical training-only weight derivation."""

import json

from src.utils.compare_weights import derive_weight_table


if __name__ == '__main__':
    table, train_dates, _ = derive_weight_table()
    correlation_weights = {
        row.feature: float(row.correlation)
        for row in table.itertuples(index=False)
    }
    print(
        f'# Derived from {len(train_dates)} training dates '
        f'({train_dates[0]} through {train_dates[-1]})'
    )
    print(json.dumps(correlation_weights, indent=2))
