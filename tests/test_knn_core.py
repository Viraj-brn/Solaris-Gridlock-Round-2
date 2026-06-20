# Unit tests for the core KNN zone prediction logic.
import unittest

import pandas as pd

from src.modeling.knn_core import predict_zone_day_records


class KNNCoreTests(unittest.TestCase):
    def setUp(self):
        self.daily = pd.DataFrame({
            'police_station': ['Zone A'] * 4,
            'ist_date': [
                '2024-01-01',
                '2024-01-02',
                '2024-01-03',
                '2024-01-04',
            ],
            'impact': [10.0, 10.0, 10.0, 10.0],
        })

    def test_confidence_uses_actual_neighbor_count(self):
        records = predict_zone_day_records(
            self.daily,
            target_date='2024-01-04',
            candidate_dates=['2024-01-01', '2024-01-02', '2024-01-03'],
            k=12,
            min_history_days=3,
        )
        self.assertEqual(records[0]['neighbor_count'], 3)
        self.assertEqual(records[0]['confidence'], 1.0)

    def test_minimum_history_guard_is_explicit(self):
        with self.assertRaisesRegex(ValueError, 'Insufficient history'):
            predict_zone_day_records(
                self.daily,
                target_date='2024-01-04',
                candidate_dates=['2024-01-01', '2024-01-02'],
                k=12,
                min_history_days=3,
            )


if __name__ == '__main__':
    unittest.main()
