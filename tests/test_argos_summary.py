import sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_macro_radar as m

class ArgosSummaryTests(unittest.TestCase):
    def test_produced_summary_has_no_events(self):
        written = {}
        def capture(path, value, compact=False):
            written[Path(path).name] = value
        with patch.object(m, "atomic_json", capture), patch.object(m.dts_bridge, "build", return_value={"models": {}}):
            m.main(offline=True)
        summary = written["argos_summary.json"]
        self.assertNotIn("events", summary)
        self.assertIn("dts", summary)
        self.assertIn("fiscal_pulse", summary)
        self.assertEqual(summary["v"], 2)
        self.assertEqual(list(summary), ["v", "at", "expires", "dts", "basis", "probabilities", "fiscal_pulse"])
        self.assertEqual(summary["basis"], "research_vs_previous_not_consensus")
        self.assertIsNone(summary["probabilities"])
        self.assertEqual(summary["fiscal_pulse"]["basis"], "dts_vs_same_session_last_year_not_forecast")
        self.assertIn("cards", written["macro_radar.json"])

if __name__ == "__main__":
    unittest.main()
