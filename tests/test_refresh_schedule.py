"""orden Sander t383u: calendario guiado por los datos (pasadas +15m/+45m/+2h/+4h, aviso a +2h).

Tests nuevos: dato publicado a su hora, fuente con retraso, fuente caída, festivo de EE. UU.,
valid_until_utc vencido y workflow de GitHub solo manual. No modifica ningún test existente."""
import copy
import datetime as dt
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import refresh_schedule as R  # noqa: E402
from build_dts_nowcast import expected_latest_bd_and_validity  # noqa: E402

UTC = dt.timezone.utc


def at(text):
    return dt.datetime.fromisoformat(text).replace(tzinfo=UTC)


def radar(observed="2026-09-01", release="2026-11-25", ref="2026-10", valid="2026-12-31T00:00:00Z"):
    return {"valid_until_utc": valid, "cards": [
        {"id": "pce", "series_id": "PCEPI", "release_date": release, "observed_period": observed,
         "reference_period": ref}]}


def published(observed="2026-10-01"):
    # After the release the generator rolls the card to the next publication.
    return radar(observed=observed, release="2026-12-23", ref="2026-11")


DTS = {"asof": "2026-11-24", "valid_until_utc": "2026-11-25T21:45:00Z"}   # already entered: not in play for PCE tests


class OnTime(unittest.TestCase):
    def test_published_on_time_one_pass_then_quiet(self):
        state, before = {}, radar()
        self.assertEqual(R.plan(state, before, DTS, at("2026-11-25T13:44:00"))[0], False)
        due, why = R.plan(state, before, DTS, at("2026-11-25T13:45:00"))
        self.assertTrue(due)
        self.assertIn("pce:2026-11-25+15m", why)
        R.mark_pass(state, at("2026-11-25T13:45:00"), before)
        after = published()
        R.register(state, after, DTS, at("2026-11-25T13:46:00"))
        self.assertTrue(state["targets"]["pce:2026-11-25"]["entered"])
        for t in ("2026-11-25T14:15:00", "2026-11-25T15:30:00", "2026-11-25T17:30:00"):
            self.assertEqual(R.plan(state, after, DTS, at(t)), (False, []))
            self.assertEqual(R.alerts(state, after, DTS, at(t)), [])

    def test_release_time_from_consensus_and_g17_clock(self):
        card = {"id": "x", "series_id": "PCEPI", "release_date": "2026-11-25", "reference_period": "2026-10",
                "consensus": {"release_at": "2026-11-25T15:00:00Z"}}
        self.assertEqual(R._release_at(card), at("2026-11-25T15:00:00"))
        ip = {"id": "production", "series_id": "INDPRO", "release_date": "2026-12-16", "reference_period": "2026-11"}
        self.assertEqual(R._release_at(ip), at("2026-12-16T14:15:00"))


class Delayed(unittest.TestCase):
    def test_source_delayed_passes_alert_at_2h_and_final_at_4h(self):
        state, r = {}, radar()
        runs = []
        for t in ("2026-11-25T13:45:00", "2026-11-25T14:15:00", "2026-11-25T15:30:00", "2026-11-25T17:30:00"):
            due, _ = R.plan(state, r, DTS, at(t))
            self.assertTrue(due, t)
            R.mark_pass(state, at(t), r)
            runs.append(R.alerts(state, r, DTS, at(t), sources={"PCEPI": {"status": "OK"}}))
        self.assertEqual(runs[0], [])
        self.assertEqual(runs[1], [])
        self.assertEqual(len(runs[2]), 1)
        self.assertIn("pce sin dato a release_at+2h", runs[2][0])
        self.assertIn("25-Nov 14:30 WAT", runs[2][0])
        self.assertIn(R.CAUSE_DELAYED, runs[2][0])
        self.assertEqual(len(runs[3]), 1)
        self.assertIn("+4h", runs[3][0])
        # No more passes and no repeated alert.
        self.assertEqual(R.plan(state, r, DTS, at("2026-11-25T20:00:00"))[0], False)
        self.assertEqual(R.alerts(state, r, DTS, at("2026-11-25T20:00:00")), [])

    def test_late_runner_collapses_missed_slots_into_one_pass(self):
        state, r = {}, radar()
        due, why = R.plan(state, r, DTS, at("2026-11-25T16:00:00"))
        self.assertTrue(due)
        self.assertEqual([w for w in why if w.startswith("pce")], ["pce:2026-11-25+120m"])
        R.mark_pass(state, at("2026-11-25T16:00:00"), r)
        self.assertEqual(R.plan(state, r, DTS, at("2026-11-25T16:05:00"))[0], False)


class SourceDown(unittest.TestCase):
    def test_source_down_cause(self):
        state, r = {}, radar()
        R.plan(state, r, DTS, at("2026-11-25T15:30:00"))
        R.mark_pass(state, at("2026-11-25T15:30:00"), r)
        msgs = R.alerts(state, r, DTS, at("2026-11-25T15:30:00"),
                        sources={"PCEPI": {"status": "FETCH_FAIL", "error": "URLError: official feed unavailable"}})
        self.assertEqual(len(msgs), 1)
        self.assertIn(R.CAUSE_DOWN, msgs[0])

    def test_job_error_cause_wins(self):
        state, r = {}, radar()
        R.plan(state, r, DTS, at("2026-11-25T15:30:00"))
        msgs = R.alerts(state, r, DTS, at("2026-11-25T15:30:00"), sources={"PCEPI": {"status": "OK"}},
                        job_error="RuntimeError")
        self.assertIn(R.CAUSE_ERROR, msgs[0])


class UsHoliday(unittest.TestCase):
    def test_thanksgiving_has_no_dts_target(self):
        # DTS validity computed by the production rule right after the Wednesday 25-nov publication.
        _exp, valid = expected_latest_bd_and_validity(at("2026-11-25T22:30:00"))
        self.assertTrue(valid.startswith("2026-11-27"))   # Thursday 26-nov (Thanksgiving) skipped
        dts = {"asof": "2026-11-24", "valid_until_utc": valid}
        r = published()
        state = {}
        for t in ("2026-11-26T22:00:00", "2026-11-27T00:30:00"):
            self.assertEqual(R.plan(state, r, dts, at(t)), (False, []), t)
            self.assertEqual(R.alerts(state, r, dts, at(t)), [])
        release, expected = R.dts_target(dts)
        self.assertEqual(release, at("2026-11-27T21:45:00"))
        self.assertEqual(expected, "2026-11-25")
        self.assertTrue(R.plan(state, r, dts, at("2026-11-27T22:00:00"))[0])

    def test_validity_on_holiday_is_not_a_target(self):
        self.assertIsNone(R.dts_target({"valid_until_utc": "2026-11-26T21:45:00Z"}))

    def test_dts_entered_by_asof(self):
        state = {}
        dts = {"asof": "2026-11-24", "valid_until_utc": "2026-11-27T21:45:00Z"}
        R.plan(state, published(), dts, at("2026-11-27T22:00:00"))
        R.mark_pass(state, at("2026-11-27T22:00:00"), published())
        after = {"asof": "2026-11-25", "valid_until_utc": "2026-11-30T21:45:00Z"}
        self.assertEqual(R.plan(state, published(), after, at("2026-11-27T22:30:00")), (False, []))
        self.assertEqual(R.alerts(state, published(), after, at("2026-11-28T00:00:00")), [])


class Validity(unittest.TestCase):
    def test_expired_validity_forces_one_pass_then_alerts_once(self):
        state, r = {}, published()
        r["valid_until_utc"] = "2026-11-25T13:30:00Z"
        due, why = R.plan(state, r, DTS, at("2026-11-25T13:31:00"))
        self.assertTrue(due)
        self.assertTrue(any("valid_until_utc vencido" in w for w in why))
        self.assertEqual(R.alerts(state, r, DTS, at("2026-11-25T13:31:00")), [])   # no alert before the pass
        R.mark_pass(state, at("2026-11-25T13:31:00"), r)
        msgs = R.alerts(state, r, DTS, at("2026-11-25T13:33:00"))
        self.assertEqual(len(msgs), 1)
        self.assertIn("valid_until_utc vencido", msgs[0])
        self.assertEqual(R.plan(state, r, DTS, at("2026-11-25T13:40:00")), (False, []))
        self.assertEqual(R.alerts(state, r, DTS, at("2026-11-25T13:40:00")), [])

    def test_renewed_validity_no_alert(self):
        state, r = {}, published()
        r["valid_until_utc"] = "2026-11-25T13:30:00Z"
        R.plan(state, r, DTS, at("2026-11-25T13:31:00"))
        R.mark_pass(state, at("2026-11-25T13:31:00"), r)
        renewed = copy.deepcopy(r)
        renewed["valid_until_utc"] = "2026-11-27T13:31:00Z"
        self.assertEqual(R.alerts(state, renewed, DTS, at("2026-11-25T13:33:00")), [])

    def test_validity_renewal_margin(self):
        self.assertTrue(R.validity_needs_renewal({"valid_until_utc": "2026-11-25T20:00:00Z"}, at("2026-11-25T13:00:00")))
        self.assertFalse(R.validity_needs_renewal({"valid_until_utc": "2026-11-27T20:00:00Z"}, at("2026-11-25T13:00:00")))
        self.assertTrue(R.validity_needs_renewal({}, at("2026-11-25T13:00:00")))


class Dedup(unittest.TestCase):
    def test_timestamps_alone_are_not_a_publication(self):
        old = '{"generated_at":"2026-11-25T12:00:00Z","valid_until_utc":"x","cards":[{"id":"pce","last":0.3,"source_retrieved_at":"a"}]}'
        same = '{"generated_at":"2026-11-25T18:00:00Z","valid_until_utc":"y","cards":[{"id":"pce","last":0.3,"source_retrieved_at":"b"}]}'
        moved = '{"generated_at":"2026-11-25T18:00:00Z","valid_until_utc":"y","cards":[{"id":"pce","last":0.32,"source_retrieved_at":"b"}]}'
        self.assertFalse(R.substantive_change(old, same))
        self.assertTrue(R.substantive_change(old, moved))

    def test_float_noise_is_not_a_publication(self):
        old = '{"mae":0.12301613783834447,"range80":[182.65090631961974,202.6]}'
        noise = '{"mae":0.12301613783834453,"range80":[182.6509063196197,202.6]}'
        real = '{"mae":0.1230162,"range80":[182.65090631961974,202.6]}'
        self.assertFalse(R.substantive_change(old, noise))
        self.assertTrue(R.substantive_change(old, real))


class WorkflowManualOnly(unittest.TestCase):
    def test_refresh_workflow_is_manual_only(self):
        text = (ROOT / ".github" / "workflows" / "dts_nowcast_daily.yml").read_text(encoding="utf-8")
        triggers = text.split("\non:", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("workflow_dispatch", triggers)
        self.assertNotIn("schedule", triggers)
        self.assertNotIn("cron", triggers)
        self.assertIsNone(re.search(r"^\s+push:", triggers, re.M))

    def test_ci_workflow_cannot_publish(self):
        text = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
        self.assertIn("contents: read", text)
        self.assertNotIn("git push", text)
        self.assertNotIn("schedule", text)


if __name__ == "__main__":
    unittest.main()
