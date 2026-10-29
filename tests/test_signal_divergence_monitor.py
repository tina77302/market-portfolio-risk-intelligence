import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from market_engine.signal_divergence.monitor import (
    ROOT, SIGNALS, PCTS, CORR, SOURCES, checked, classify, export, integrate, past_percentile,
)


def inputs(pattern=(1, 0, 1, 0, 0)):
    dates = pd.to_datetime(['2024-01-04', '2024-01-05', '2024-01-08', '2024-01-09', '2024-01-10'])
    v1 = pd.DataFrame({'Date': dates, 'Prob_XGBoost': .1})
    msi = pd.DataFrame({'Date': dates, 'Korea_MSI': .2, 'Stress_Threshold': 1.1})
    breadth = pd.DataFrame({'Date': dates})
    for i, (s, p) in enumerate(zip(SIGNALS, PCTS)):
        breadth[s] = .3
        breadth[p] = [.90 if v and i < 2 else .2 for v in pattern]
    corr = pd.DataFrame({'Date': dates, **{c: .5 for c in CORR}})
    return [v1, msi, breadth, corr]


class MonitorTests(unittest.TestCase):
    def test_two_of_three_trading_observations(self):
        out = integrate(*inputs())
        self.assertTrue(pd.isna(out.persistent.iloc[1]))
        self.assertEqual(out.persistent.iloc[2:].tolist(), [1, 0, 0])
        self.assertEqual(out.state.iloc[2], 'SIGNAL DIVERGENCE')
        self.assertEqual(out.Date.iloc[2], pd.Timestamp('2024-01-08'))

    def test_state_precedence_and_boundaries(self):
        cases = [(.49, .2, 1.1, 1, 'SIGNAL DIVERGENCE'),
                 (.5, .2, 1.1, 1, 'ALIGNED RISK'),
                 (.5, .2, 1.1, 0, 'MODEL-LED WARNING'),
                 (.49, 1.1, 1.1, 1, 'OBSERVED MSI STRESS'),
                 (.49, 1.2, 1.1, 0, 'OBSERVED MSI STRESS'),
                 (.5, 1.1, 1.1, 0, 'ALIGNED RISK'),
                 (.49, .2, 1.1, 0, 'NORMAL')]
        for *values, state in cases:
            self.assertEqual(classify(*values)[0], state)
        a = inputs()
        a[2].loc[2, PCTS[:2]] = .899999
        self.assertEqual(integrate(*a).extreme_count.iloc[2], 0)

    def test_missing_never_normal(self):
        for pos in range(4):
            values = [.1, .2, 1.1, 0]
            values[pos] = np.nan
            self.assertTrue(classify(*values)[0].startswith('UNKNOWN'))
        a = inputs()
        a[2].loc[1, PCTS[0]] = np.nan
        out = integrate(*a)
        self.assertTrue(pd.isna(out.extreme_count.iloc[1]))
        self.assertTrue(out.state.iloc[2].startswith('UNKNOWN'))
        a = inputs()
        a[3].loc[2, CORR] = np.nan
        out = integrate(*a)
        self.assertTrue(pd.isna(out.correlation_count.iloc[2]))
        self.assertEqual(out.state.iloc[2], 'SIGNAL DIVERGENCE')

    def test_alignment_no_forward_fill_and_missing_observation(self):
        a = inputs()
        a[2] = a[2].drop(index=1).iloc[::-1]
        a[0] = a[0].drop(index=3)
        out = integrate(*a)
        self.assertTrue(out.Date.is_monotonic_increasing)
        self.assertTrue(pd.isna(out.raw_breadth.iloc[1]))
        self.assertTrue(pd.isna(out.persistent.iloc[2]))
        self.assertTrue(pd.isna(out.Prob_XGBoost.iloc[3]))

    def test_reject_duplicate_dates_and_percentage_units(self):
        a = inputs()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            checked(pd.concat([a[0], a[0]]), ['Prob_XGBoost'], 'v1')
        a[0]['Prob_XGBoost'] = 25
        with self.assertRaisesRegex(ValueError, '0–1'):
            integrate(*a)

    def test_future_mutation_cannot_change_past(self):
        a = inputs()
        before = integrate(*a).iloc[:3].copy()
        a[2].loc[3:, PCTS] = 1
        pd.testing.assert_frame_equal(before, integrate(*a).iloc[:3])
        x = pd.Series([.1, .2, .3, .4, .5])
        original = past_percentile(x, minimum=2)
        x.iloc[4] = 999
        pd.testing.assert_series_equal(original.iloc[:4], past_percentile(x, minimum=2).iloc[:4])
        self.assertEqual(original.iloc[2], 1)

    def test_stored_percentiles_match_past_only_research(self):
        breadth = pd.read_csv(ROOT / SOURCES['breadth'])
        # Reproduce the frozen empirical-CDF convention at sample dates, including holdout.
        for key in SIGNALS:
            x = breadth[key]
            for date in ['2016-09-13', '2026-10-12', '2026-10-13']:
                i = breadth.index[breadth.Date == date][0]
                expected = (x.iloc[:i].dropna() <= x.iloc[i]).mean()
                self.assertAlmostEqual(breadth.loc[i, key + '_pct'], expected)

    def test_export_real_holdout_and_preserved_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            out = export(output=Path(directory) / 'monitor.json')
            json.loads((Path(directory) / 'monitor.json').read_text())
        rows = {r['Date']: r for r in out['holdout']}
        self.assertEqual(rows['2026-10-12']['persistent'], 0)
        self.assertEqual(rows['2026-10-13']['persistent'], 1)
        self.assertEqual(rows['2026-10-12']['reported_v1_percent'], 15.6)
        self.assertIsNone(rows['2026-10-13']['Prob_XGBoost'])
        self.assertIsNone(rows['2026-10-13']['Stress_Threshold'])
        self.assertTrue(rows['2026-10-13']['state'].startswith('UNKNOWN'))
        self.assertEqual(out['evidence']['eligible'], 18)
        self.assertEqual(out['evidence']['detected'], 6)
        self.assertEqual(out['last_complete']['Date'], '2026-09-16')

    def test_missing_required_source_preserves_observations_as_unknown(self):
        a = inputs()
        a[1] = pd.DataFrame(columns=["Date", "Korea_MSI", "Stress_Threshold"])
        out = integrate(*a)
        self.assertEqual(len(out), 5)
        self.assertTrue(out.state.str.startswith("UNKNOWN").all())

    def test_absent_sources_produce_clean_unavailable_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = export(root=root)
            self.assertEqual(len(out['issues']), 4)
            self.assertIsNone(out['latest'])
            self.assertIsNone(out['last_complete'])
            self.assertEqual(out['history'], [])


if __name__ == '__main__':
    unittest.main()
