"""INTEGRIDAD-01 case A7: absent DTS amounts stay absent.

An unreported, stale, or other-date amount is not published as zero, as the
prior close, or as a day rebuilt from MTD, and it does not enter the z window.
"""
import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_dts_nowcast as dts


class IntegridadA7NowcastAbsentTests(unittest.TestCase):
    def test_absent_amounts_stay_absent_and_leave_the_z_window(self):
        # Stored zero is not a report. Only a field marked present is real, including zero.
        self.assertIsNone(dts.present_amount({"today": 0.0, "present": set()}, "today"))
        self.assertEqual(dts.present_amount({"today": 0.0, "present": {"today"}}, "today"), 0.0)

        # Today is not rebuilt from MTD, inside a month or on a month boundary.
        rebuilt, refused = dts.today_amount(None, 40.0, 25.0, True)
        self.assertIsNone(rebuilt)
        self.assertTrue(refused)
        self.assertEqual(dts.today_amount(None, 40.0, None, False), (None, True))
        self.assertEqual(dts.today_amount(0.0, 40.0, 25.0, True), (0.0, False))
        self.assertEqual(dts.today_amount(None, 40.0, None, True), (None, False))

        # Opening balance is not yesterday's close.
        self.assertEqual(dts.opening_balance(None, 999.0), (None, True))
        self.assertEqual(dts.opening_balance(0.0, 999.0), (0.0, False))
        self.assertEqual(dts.opening_balance(None, None), (None, False))

        # A reported zero total is kept. No Table II day is not published as zero.
        self.assertEqual(dts.operating_total(0.0, 50.0, True), 0.0)
        self.assertEqual(dts.operating_total(None, 50.0, True), 50.0)
        self.assertEqual(dts.operating_total(None, 0.0, True), 0.0)
        self.assertIsNone(dts.operating_total(None, 0.0, False))

        # A null security line poisons that total. A reported zero does not.
        poisoned = {"bills_iss_total": 0.0}
        dts.add_into(poisoned, "bills_iss_total", None)
        self.assertIsNone(poisoned["bills_iss_total"])
        kept = {"bills_iss_total": 0.0}
        dts.add_into(kept, "bills_iss_total", 0.0)
        self.assertEqual(kept["bills_iss_total"], 0.0)

        # A calendar day that was not built is absent, not zero.
        self.assertIsNone(dts.calendar_value({}, "2026-11-12"))
        self.assertEqual(dts.calendar_value({"2026-11-12": 0.0}, "2026-11-12"), 0.0)

        def observed_day(**overrides):
            args = dict(
                tga_close=100.0, tga_open=100.0, previous_close=999.0,
                D_raw=0.0, W_raw=0.0, I_raw=0.0, R_raw=0.0,
                i_calc=0.0, r_calc=0.0, op_dep_t2=0.0, op_wd_t2=0.0,
                ntf_scheduled=0.0, ntf_expected=0.0, is_warmup=False,
            )
            args.update(overrides)
            return dts.accounting_derivatives(**args)

        complete = observed_day()
        self.assertEqual(complete["D"], 0.0)
        self.assertEqual(complete["ntf_total"], 0.0)
        self.assertEqual(complete["dtga"], 0.0)
        self.assertEqual(complete["z_realized"], 0.0)
        self.assertTrue(complete["inputs_complete"])
        self.assertFalse(complete["refused_open"])

        flows = dict(tga_close=110.0, tga_open=100.0, D_raw=30.0, W_raw=20.0, I_raw=15.0, R_raw=10.0,
                     i_calc=15.0, r_calc=10.0, op_dep_t2=15.0, op_wd_t2=10.0, ntf_scheduled=4.0, ntf_expected=2.0)
        matched = observed_day(**flows)
        self.assertEqual(matched["ntf_total"], (20.0 - 10.0) - (30.0 - 15.0))
        self.assertEqual(matched["dtga"], 10.0)
        self.assertEqual(matched["recon_diff"], 0.0)
        self.assertEqual(matched["z_realized"], matched["ntf_total"] - 4.0)
        self.assertEqual(matched["z_ex_ante"], matched["ntf_total"] - 2.0)

        missing_deposit = observed_day(**{**flows, "D_raw": None})
        self.assertIsNone(missing_deposit["D"])
        self.assertIsNone(missing_deposit["ntf_total"])
        self.assertIsNone(missing_deposit["op_dep"])
        self.assertIsNone(missing_deposit["z_realized"])
        self.assertIsNone(missing_deposit["z_ex_ante"])
        self.assertFalse(missing_deposit["inputs_complete"])

        borrowed_open = observed_day(**{**flows, "tga_open": None, "previous_close": 999.0})
        self.assertIsNone(borrowed_open["tga_open"])
        self.assertNotEqual(borrowed_open["tga_open"], 999.0)
        self.assertIsNone(borrowed_open["dtga"])
        self.assertTrue(borrowed_open["refused_open"])
        self.assertIsNone(borrowed_open["z_realized"])
        self.assertEqual(
            dts.history_row_quality(True, [borrowed_open["tga_close"], borrowed_open["tga_open"]]),
            "STALE",
        )
        self.assertEqual(dts.history_row_quality(False, [1.0, None]), "ABSENT")
        self.assertEqual(dts.history_row_quality(False, [1.0, 0.0]), "OK")

        # A missing calendar component is not published as a partial or zero schedule.
        def missing_customs(side, cid, d, field="today"):
            return None if cid == "CUSTOMS_DUTIES" else 3.0

        self.assertIsNone(dts.build_asymmetric_calendar_schedule(["2026-11-12"], missing_customs)[1]["2026-11-12"])

        def reported_zeros(side, cid, d, field="today"):
            return 0.0

        self.assertEqual(dts.build_asymmetric_calendar_schedule(["2026-11-12"], reported_zeros)[1]["2026-11-12"], 0.0)

        # Absent corp/SECA does not vote as a zero non-shock. A real zero still can.
        self.assertTrue(dts.shock_day(False, None, 0.0))
        self.assertFalse(dts.shock_day(False, 0.0, 0.0))
        self.assertTrue(dts.shock_day(False, 15000.0, 5000.1))
        self.assertFalse(dts.shock_day(False, 15000.0, 5000.0))

        # The filled zero would move the robust z; the absent day is left out of the window.
        base = [10.0] * 10 + [30.0] * 10
        absent = base + [None, 20.0]
        filled = base + [0.0, 20.0]
        flags = [False] * len(absent)
        z_absent = dts.robust_zscore_out_of_sample(absent, flags, len(absent) - 1, window=60, mad_floor=1)[0]
        z_filled = dts.robust_zscore_out_of_sample(filled, flags, len(filled) - 1, window=60, mad_floor=1)[0]
        omitted = base + [20.0]
        z_omitted = dts.robust_zscore_out_of_sample(omitted, [False] * len(omitted), len(omitted) - 1, window=60, mad_floor=1)[0]
        self.assertEqual(z_absent, z_omitted)
        self.assertNotEqual(z_absent, z_filled)

    def test_ui_renders_no_data_and_keeps_a_real_zero(self):
        script = textwrap.dedent(
            """
            import {treasuryHTML} from './assets/treasury.mjs';
            const p={open:null,D:0,W:10,net:null,recon:null,ok:false,I:null,R:2,op_D:null,op_W:8};
            const book={generated_at:'2026-11-14T12:00:00Z',valid_until_utc:'2026-11-16T21:45:00Z',
              schema:'treasury-book-1.0',asof:'2026-11-12',components:[],
              rows:[{d:'2026-11-12',fy:2027,tga:110,ntf:null,z:null,
                periods:{today:{...p},mtd:{...p},fytd:{...p}},components:{},
                debt:{headroom:null,public:null,total:null}}]};
            const html=treasuryHTML(book,{asof:book.asof,dq:{block:true,stale:false}},{lang:'en'});
            if(!html.includes('Opening balance for period: NO DATA')) throw new Error('null open was not labelled NO DATA');
            if(!html.includes('cash-value">0</div>')) throw new Error('real zero deposit was not rendered as 0');
            if(html.includes('999')) throw new Error('carried previous close into the UI');
            console.log('ok');
            """
        )
        root = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=root, capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ok", proc.stdout)


if __name__ == "__main__":
    unittest.main()
