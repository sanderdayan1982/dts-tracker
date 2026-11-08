import datetime as dt, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_macro_radar as m

FEED = {"generated_at": "2026-11-09T18:00:00.000Z", "calendar": [
    {"currency": "USD", "title": "CPI m/m", "event_at": "2026-11-10T13:30:00.000Z", "forecast": "0.3%"},
    {"currency": "USD", "title": "Core CPI m/m", "event_at": "2026-11-10T13:30:00.000Z", "forecast": "0.3%"},
    {"currency": "CAD", "title": "CPI m/m", "event_at": "2026-11-10T13:30:00.000Z", "forecast": "9.9%"},
    {"currency": "USD", "title": "Non-Farm Employment Change", "event_at": "2026-11-06T13:30:00.000Z", "forecast": "65K"},
    {"currency": "USD", "title": "Housing Starts", "event_at": "2026-11-18T13:30:00.000Z", "forecast": "1.32M"}]}
NOW = dt.datetime(2026, 11, 9, 20, tzinfo=dt.timezone.utc)

class ConsensusFeedTests(unittest.TestCase):
    def test_units(self):
        self.assertEqual(m.parse_ff_value("65K", "thousand_jobs"), 65)
        self.assertAlmostEqual(m.parse_ff_value("1.32M", "thousand_homes_saar"), 1320)
        self.assertAlmostEqual(m.parse_ff_value("-107.9B", "usd_billions"), -107.9)
        self.assertEqual(m.parse_ff_value("0.3%", "percent_mom"), .3)
        self.assertIsNone(m.parse_ff_value("0.3%", "thousand_jobs"))     # unit mismatch is rejected
        self.assertIsNone(m.parse_ff_value(None, "percent"))
    def test_same_release_only(self):
        cards = [{"id": "cpi", "release_date": "2026-11-10", "reference_period": "2026-10", "unit": "percent_mom"},
                 {"id": "nfp", "release_date": "2026-12-04", "reference_period": "2026-11", "unit": "thousand_jobs"},
                 {"id": "housing", "release_date": "2026-11-18", "reference_period": "2026-10", "unit": "thousand_homes_saar"}]
        out = m.radar_news_consensus(cards, NOW, FEED)
        self.assertEqual(out["cpi"]["value"], .3)                # USD, not CAD
        self.assertNotIn("nfp", out)                              # Nov-6 event is a different release
        self.assertAlmostEqual(out["housing"]["value"], 1320)
        self.assertIsNotNone(m.verified_consensus(out, "cpi", "2026-10", "percent_mom", NOW))
        after = dt.datetime(2026, 11, 10, 14, tzinfo=dt.timezone.utc)
        self.assertIsNone(m.verified_consensus(out, "cpi", "2026-10", "percent_mom", after))   # never after the release
    def test_future_or_missing_capture_rejected(self):
        self.assertEqual(m.radar_news_consensus([], NOW, {"generated_at": "2027-01-01T00:00:00Z", "calendar": []}), {})
        self.assertEqual(m.radar_news_consensus([], NOW, {"calendar": []}), {})

if __name__ == "__main__": unittest.main()
