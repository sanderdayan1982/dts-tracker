import datetime as dt, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fiscal_pulse import build_pulse, classify, monthly_yoy, INDICATORS, pulse_contract
from institutional_core import business_day

def book(factor=1.10, start="2024-09-02", end="2026-11-05"):
    rows, d = [], dt.date.fromisoformat(start)
    cum = {}
    while d <= dt.date.fromisoformat(end):
        if business_day(d):
            fy = d.year + (d.month >= 10)
            k_fy, k_mo = ("fy", fy), ("mo", d.strftime("%Y-%m"))
            today = 100.0 * (factor if fy == 2027 else 1.0)
            for k in (k_fy, k_mo): cum[k] = cum.get(k, 0) + today
            comp = [today, cum[k_mo], cum[k_fy]]
            rows.append({"d": d.isoformat(), "fy": fy, "components": {c: comp for c in ("WITHHELD_FICA", "DOL_UNEMP_BEN", "USDA_SNAP")},
                         "periods": {m: {"I": 10.0, "R": 5.0} for m in ("today", "mtd", "fytd")}})
        d += dt.timedelta(days=1)
    return {"rows": rows, "asof": end, "valid_until_utc": "2026-11-09T21:45:00Z"}

CPI = [{"date": "2025-09-01", "value": 100.0}, {"date": "2026-09-01", "value": 103.0}]
NOW = dt.datetime(2026, 11, 8, tzinfo=dt.timezone.utc)

class PulseTests(unittest.TestCase):
    def test_same_session_and_real_change(self):
        p = build_pulse(book(1.10), CPI, NOW)
        w = next(x for x in p["indicators"] if x["id"] == "withheld")
        self.assertAlmostEqual(w["fytd"]["change"], 10.0, places=1)       # same sessions -> exact 10 %
        self.assertAlmostEqual(w["fytd"]["real_change"], 7.0, places=1)   # minus 3 % CPI
        self.assertEqual(w["state"], "better")
        self.assertEqual(p["sessions_fytd"], 25)
    def test_direction_semantics(self):
        spec = {i["id"]: i for i in INDICATORS}
        self.assertEqual(classify(spec["dol"], 10.0), "worse")          # more benefits = worse labour market
        self.assertEqual(classify(spec["snap"], -10.0), "better")
        self.assertEqual(classify(spec["withheld"], 2.0), "stable")
        self.assertEqual(classify(spec["customs"], 20.0), "pressure_up")
        self.assertEqual(classify(spec["net_issuance"], 10.0), "stable")  # bn threshold
    def test_early_month_mtd_suppressed(self):
        w = next(x for x in build_pulse(book(), CPI, NOW)["indicators"] if x["id"] == "withheld")
        self.assertIsNone(w["mtd"]["change"]); self.assertFalse(w["mtd"]["reliable"])
    def test_missing_is_not_zero(self):
        b = book(); b["rows"][-30]["components"]["USDA_SNAP"] = [None, None, None]
        months = monthly_yoy(b["rows"], ["USDA_SNAP"])
        broken = b["rows"][-30]["d"][:7]
        self.assertIsNone(next(m for m in months if m["month"] == broken)["change"])
    def test_unknown_component_reported_as_unavailable(self):
        sal = next(x for x in build_pulse(book(), CPI, NOW)["indicators"] if x["id"] == "fed_salaries")
        self.assertIsNone(sal["fytd"]["change"]); self.assertEqual(sal["state"], "na")
    def test_expiry_blocks(self):
        p = pulse_contract(build_pulse(book(), CPI, NOW), dt.datetime(2026, 11, 10, tzinfo=dt.timezone.utc))
        self.assertEqual(p["status"], "EXPIRED")
    def test_known_base_event_is_excluded(self):
        b = book(1.30)
        for r in b["rows"]: r["components"]["FED_SALARIES_EFT"] = r["components"]["WITHHELD_FICA"]
        p = build_pulse(b, CPI, NOW)
        sal = next(x for x in p["indicators"] if x["id"] == "fed_salaries")
        self.assertEqual(sal["state"], "distorted"); self.assertTrue(sal["base_effects"])
        self.assertIn("efecto base", p["verdicts"]["labor"]["summary_es"])
    def test_theme_summary(self):
        v = build_pulse(book(1.10), CPI, NOW)["verdicts"]["labor"]
        self.assertIn("summary_es", v); self.assertTrue(v["summary_es"].endswith("."))

if __name__ == "__main__": unittest.main()
