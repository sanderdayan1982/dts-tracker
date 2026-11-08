import datetime as dt, math, random, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import dts_bridge as b
from institutional_core import business_day

class CalendarTests(unittest.TestCase):
    def test_bls_release_rule(self):
        # Third Friday after the week containing the 12th (published BLS dates).
        self.assertEqual(b.nfp_release("2024-09"), dt.date(2024, 10, 4))
        self.assertEqual(b.nfp_release("2026-10"), dt.date(2026, 11, 6))
        self.assertEqual(b.nfp_release("2026-11"), dt.date(2026, 12, 4))
    def test_cutoffs_precede_release(self):
        for per in ("2019-01", "2023-06", "2026-10"):
            cut = b.cutoff_for("nfp", per)
            # DTS dated d is public at 16:00 ET on the next business day; it must be out before 08:30 on release day.
            self.assertLess(b.add_bd(cut, 1), b.nfp_release(per))
        self.assertEqual(b.cutoff_for("claims", "2026-11-07"), dt.date(2026, 11, 10))
        self.assertEqual(b.cutoff_for("retail", "2026-10"), dt.date(2026, 10, 30))

class FeatureTests(unittest.TestCase):
    def daily(self, start="2014-01-01", end="2026-11-05", f=lambda d: 100.0):
        out, d = {}, dt.date.fromisoformat(start)
        while d <= dt.date.fromisoformat(end):
            if business_day(d): out[d.isoformat()] = f(d)
            d += dt.timedelta(days=1)
        return out
    def test_missing_day_is_not_zero(self):
        s = self.daily(); s.pop("2026-11-04")
        self.assertIsNone(b.window_sum(s, dt.date(2026, 11, 5), 5))
    def test_lag364_growth(self):
        s = self.daily(f=lambda d: 110.0 if d.year == 2026 else 100.0)
        self.assertAlmostEqual(b.lag364_growth(s, dt.date(2026, 6, 30), 20), math.log(1.1))
    def test_accumulate_idempotent(self):
        rows = [{"record_date": "2026-11-05", "account_type": "Treasury General Account (TGA)", "transaction_type": "Deposits",
                 "transaction_catg": "Taxes - Withheld Individual/FICA", "transaction_today_amt": "3415"}]
        s = b.accumulate({}, rows); b.accumulate(s, rows)
        self.assertEqual(s["WITHHELD"]["2026-11-05"], 3415)
    def test_totals_are_ignored(self):
        rows = [{"record_date": "2026-11-05", "account_type": "Treasury General Account Total Deposits", "transaction_type": "Deposits",
                 "transaction_catg": "Taxes - Withheld Individual/FICA", "transaction_today_amt": "1"}]
        self.assertEqual(b.accumulate({}, rows), {})

class StatisticsTests(unittest.TestCase):
    def test_ridge_recovers_slope(self):
        random.seed(1); X = [[random.gauss(0, 1)] for _ in range(400)]; y = [2 + 3 * x[0] + random.gauss(0, .1) for x in X]
        m = b.ridge(X, y, lam=0.0)
        self.assertAlmostEqual(m["slopes"][0], 3, places=1); self.assertAlmostEqual(m["intercept"], 2, places=1)
    def test_dm_sign(self):
        good, bad = [0.1] * 50, [1.0] * 50
        bad = [x + (0.01 if i % 2 else -0.01) for i, x in enumerate(bad)]
        stat, p = b.diebold_mariano(good, bad)
        self.assertLess(stat, 0); self.assertLess(p, .01)
    def test_backtest_uses_only_past(self):
        rows = [{"period": f"{2010 + i // 12:04d}-{i % 12 + 1:02d}", "y": float(i), "baseline": 0.0, "x": [float(i)]} for i in range(80)]
        seen = []
        real = b.ridge
        def spy(X, y, lam=1.0):
            seen.append(max(y)); return real(X, y, lam)
        b.ridge = spy
        try: results = b.backtest("nfp", rows)
        finally: b.ridge = real
        for r, top in zip(results, seen):
            self.assertLess(top, rows[[q["period"] for q in rows].index(r["period"])]["y"] - 1)
    def test_covid_excluded(self):
        self.assertTrue(b.in_covid("2020-04")); self.assertFalse(b.in_covid("2022-01")); self.assertFalse(b.in_covid("2020-02-29"))

class EdgeTests(unittest.TestCase):
    def results(self, gain):
        random.seed(7); out = []
        for i in range(72):
            a = random.gauss(0, 1); base = a + random.gauss(0, 1)
            out.append({"period": f"{2019 + i // 12}-{i % 12 + 1:02d}", "actual": a, "baseline": base, "bridge": a + (base - a) * (1 - gain)})
        return out
    def test_edge_requires_dts_added_value(self):
        full = self.results(.4)
        self.assertEqual(b.evaluate(full)["edge"], "DEMONSTRATED")
        self.assertEqual(b.evaluate(full, ablation=full)["edge"], "NONE")   # same errors without DTS -> no DTS value
    def test_no_gain_no_edge(self):
        self.assertEqual(b.evaluate(self.results(0.0))["edge"], "NONE")

if __name__ == "__main__": unittest.main()
