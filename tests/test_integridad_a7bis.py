"""INTEGRIDAD-01 case A7-bis: the three remaining zero-fills stay null.

Table V today/FYTD, Table IIIC balances, and debt-limit headroom. A missing
amount is published as null and rendered as NO DATA. A reported zero stays
zero and does not get treated as missing. A missing amount never enters a sum
or a derived headroom.
"""
import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_dts_nowcast as dts
import test_fiscal_pulse as pulse_fix
from argos_dts import refund_total
from fiscal_pulse import INDICATORS, build_pulse
from treasury_book import build_book


DAY = "2026-11-12"
ZERO_DAY = "2026-11-13"


def refund_row(day, kind, today, fytd):
    return {
        "record_date": day,
        "tax_refund_type": kind,
        "tax_refund_today_amt": today,
        "tax_refund_fytd_amt": fytd,
    }


def debt_row(day, catg, close, desc="null", open_bal=None):
    return {
        "record_date": day,
        "debt_catg": catg,
        "debt_catg_desc": desc,
        "close_today_bal": close,
        "open_today_bal": open_bal,
    }


def cash_source():
    return dict(
        tga_close=120, tga_open=100, tga_open_mtd=90, tga_open_fytd=80,
        tga_dep_t1=30, tga_wd_t1=10, tga_dep_mtd_t1=70, tga_wd_mtd_t1=40,
        tga_dep_fytd_t1=100, tga_wd_fytd_t1=60,
    )


class IntegridadA7BisTests(unittest.TestCase):
    def test_table_v_gap_is_null_and_reported_zero_stays_zero(self):
        gap = dts.organize_tax_refunds([
            refund_row(DAY, "Taxes - Business Tax Refunds (Checks)", None, "0"),
            refund_row(DAY, "Taxes - Business Tax Refunds (EFT)", "5", "null"),
            refund_row(DAY, "Taxes - Individual Tax Refunds (Checks)", "0", "0"),
            refund_row(DAY, "Taxes - Individual Tax Refunds (EFT)", "", None),
        ])[DAY]
        # A missing channel is null, not a substituted zero, and stays out of the total.
        self.assertIsNone(gap["biz_checks_today"])
        self.assertNotIn("biz_checks_today", gap["present"])
        self.assertEqual(gap["biz_eft_today"], 5.0)
        self.assertIsNone(dts.published_refund(gap, "biz", "today"))
        self.assertNotEqual(dts.published_refund(gap, "biz", "today"), 5)
        self.assertEqual(gap["biz_checks_fytd"], 0.0)
        self.assertIn("biz_checks_fytd", gap["present"])
        self.assertIsNone(gap["biz_eft_fytd"])
        self.assertIsNone(dts.published_refund(gap, "biz", "fytd"))
        self.assertEqual(gap["indiv_checks_today"], 0.0)
        self.assertEqual(gap["indiv_checks_fytd"], 0.0)
        self.assertIsNone(gap["indiv_eft_today"])
        self.assertIsNone(gap["indiv_eft_fytd"])
        self.assertIsNone(dts.published_refund(gap, "indiv", "today"))
        self.assertIsNone(dts.published_refund(gap, "indiv", "fytd"))
        # The reported zero channel is not swallowed by the missing sibling.
        self.assertEqual(refund_total(gap, "indiv", "fytd"), None)

        zero = dts.organize_tax_refunds([
            refund_row(ZERO_DAY, "Taxes - Business Tax Refunds (Checks)", "0", "0"),
            refund_row(ZERO_DAY, "Taxes - Business Tax Refunds (EFT)", "0", "0"),
            refund_row(ZERO_DAY, "Taxes - Individual Tax Refunds (Checks)", "0", "0"),
            refund_row(ZERO_DAY, "Taxes - Individual Tax Refunds (EFT)", "0", "0"),
        ])[ZERO_DAY]
        self.assertEqual(dts.published_refund(zero, "biz", "today"), 0)
        self.assertEqual(dts.published_refund(zero, "biz", "fytd"), 0)
        self.assertEqual(dts.published_refund(zero, "indiv", "today"), 0)
        self.assertEqual(dts.published_refund(zero, "indiv", "fytd"), 0)
        self.assertEqual(zero["biz_checks_today"], 0.0)
        self.assertIn("indiv_eft_fytd", zero["present"])

    def test_table_iiic_gap_is_null_and_reported_zero_stays_zero(self):
        # Public Treasury figures for 2026-11-12, plus one blank component.
        complete = dts.organize_debt_limit([
            debt_row(DAY, "Debt Held by the Public", "32824386"),
            debt_row(DAY, "Intragovernmental Holdings", "7784121"),
            debt_row(DAY, "Debt Not Subject to Limit", "474", "Other Debt (-)"),
            debt_row(DAY, "Debt Not Subject to Limit", "194581", "Unamortized Discount (-)"),
            debt_row(DAY, "Debt Not Subject to Limit", "3591", "Federal Financing Bank (-)"),
            debt_row(DAY, "Other Debt Subject to Limit", "0", "Guaranteed Debt of Government Agencies"),
            debt_row(DAY, "Statutory Debt Limit", "41103996"),
        ])[DAY]
        self.assertEqual(complete["debt_public"], 32824386.0)
        self.assertEqual(complete["other_subj_limit"], 0.0)
        self.assertEqual(complete["not_subj_limit"], 474 + 194581 + 3591)
        self.assertEqual(complete["debt_total"], 32824386 + 7784121)
        self.assertEqual(complete["debt_subj_limit"], 40608507 - 198646)
        self.assertEqual(dts.debt_headroom_musd(complete), 694135)
        book = build_book({DAY: cash_source()}, {}, {}, {}, {"asof": DAY}, {DAY: complete})
        self.assertEqual(book["rows"][0]["debt"]["headroom"], 694135)
        self.assertEqual(book["rows"][0]["debt"]["public"], 32824386)

        gap = dts.organize_debt_limit([
            debt_row(DAY, "Debt Held by the Public", "null"),
            debt_row(DAY, "Intragovernmental Holdings", "7784121"),
            debt_row(DAY, "Debt Not Subject to Limit", "474", "Other Debt (-)"),
            debt_row(DAY, "Debt Not Subject to Limit", None, "Unamortized Discount (-)"),
            debt_row(DAY, "Debt Not Subject to Limit", "3591", "Federal Financing Bank (-)"),
            debt_row(DAY, "Other Debt Subject to Limit", "0", "Guaranteed Debt of Government Agencies"),
            debt_row(DAY, "Statutory Debt Limit", "null", open_bal="null"),
        ])[DAY]
        self.assertIsNone(gap["debt_public"])
        self.assertEqual(gap["debt_intra"], 7784121.0)
        self.assertIsNone(gap["debt_total"])
        self.assertNotEqual(gap["debt_total"], 7784121)
        self.assertIsNone(gap["not_subj_limit"])
        self.assertNotEqual(gap["not_subj_limit"], 474 + 3591)
        self.assertEqual(gap["other_subj_limit"], 0.0)
        self.assertIsNone(gap["stat_debt_limit"])
        self.assertIsNone(gap["debt_subj_limit"])
        self.assertIsNone(dts.debt_headroom_musd(gap))
        gap_book = build_book({DAY: cash_source()}, {}, {}, {}, {"asof": DAY}, {DAY: gap})
        self.assertIsNone(gap_book["rows"][0]["debt"]["public"])
        self.assertIsNone(gap_book["rows"][0]["debt"]["total"])
        self.assertIsNone(gap_book["rows"][0]["debt"]["headroom"])

        # An explicit blank subject line is not rebuilt from the other lines.
        blank_subject = dts.organize_debt_limit([
            debt_row(DAY, "Total Public Debt Outstanding", "1000"),
            debt_row(DAY, "Total Public Debt Subject to Limit", None),
            debt_row(DAY, "Statutory Debt Limit", "1000"),
        ])[DAY]
        self.assertEqual(blank_subject["debt_total"], 1000.0)
        self.assertIsNone(blank_subject["debt_subj_limit"])
        self.assertIsNone(dts.debt_headroom_musd(blank_subject))

        zero = dts.organize_debt_limit([
            debt_row(ZERO_DAY, "Debt Held by the Public", "0"),
            debt_row(ZERO_DAY, "Intragovernmental Holdings", "0"),
            debt_row(ZERO_DAY, "Debt Not Subject to Limit", "0", "Other Debt (-)"),
            debt_row(ZERO_DAY, "Other Debt Subject to Limit", "0", "Guaranteed Debt of Government Agencies"),
            debt_row(ZERO_DAY, "Statutory Debt Limit", "0"),
        ])[ZERO_DAY]
        self.assertEqual(zero["debt_public"], 0.0)
        self.assertEqual(zero["debt_total"], 0.0)
        self.assertEqual(zero["not_subj_limit"], 0.0)
        self.assertEqual(zero["other_subj_limit"], 0.0)
        self.assertEqual(zero["debt_subj_limit"], 0.0)
        self.assertEqual(zero["stat_debt_limit"], 0.0)
        self.assertEqual(dts.debt_headroom_musd(zero), 0)
        zero_book = build_book(
            {ZERO_DAY: cash_source()}, {}, {}, {}, {"asof": ZERO_DAY}, {ZERO_DAY: zero}
        )
        self.assertEqual(zero_book["rows"][0]["debt"]["public"], 0)
        self.assertEqual(zero_book["rows"][0]["debt"]["total"], 0)
        self.assertEqual(zero_book["rows"][0]["debt"]["headroom"], 0)

    def test_debt_headroom_does_not_subtract_a_substituted_zero(self):
        self.assertIsNone(dts.debt_headroom_musd({"stat_debt_limit": None, "debt_subj_limit": 400.0}))
        self.assertIsNone(dts.debt_headroom_musd({"stat_debt_limit": 1000.0, "debt_subj_limit": None}))
        self.assertIsNone(dts.debt_headroom_musd({}))
        self.assertEqual(dts.debt_headroom_musd({"stat_debt_limit": 0.0, "debt_subj_limit": 0.0}), 0)
        self.assertEqual(dts.debt_headroom_musd({"stat_debt_limit": 1000.0, "debt_subj_limit": 0.0}), 1000)
        self.assertEqual(dts.debt_headroom_musd({"stat_debt_limit": 1000.0, "debt_subj_limit": 400.0}), 600)

    def test_ui_renders_no_data_for_gaps_and_keeps_zero(self):
        gap_refunds = dts.organize_tax_refunds([
            refund_row(DAY, "Taxes - Individual Tax Refunds (Checks)", "0", None),
            refund_row(DAY, "Taxes - Individual Tax Refunds (EFT)", None, "null"),
            refund_row(DAY, "Taxes - Business Tax Refunds (Checks)", None, "0"),
            refund_row(DAY, "Taxes - Business Tax Refunds (EFT)", "2", None),
        ])[DAY]
        zero_refunds = dts.organize_tax_refunds([
            refund_row(ZERO_DAY, "Taxes - Individual Tax Refunds (Checks)", "0", "0"),
            refund_row(ZERO_DAY, "Taxes - Individual Tax Refunds (EFT)", "0", "0"),
            refund_row(ZERO_DAY, "Taxes - Business Tax Refunds (Checks)", "0", "0"),
            refund_row(ZERO_DAY, "Taxes - Business Tax Refunds (EFT)", "0", "0"),
        ])[ZERO_DAY]
        gap_debt = dts.organize_debt_limit([
            debt_row(DAY, "Debt Held by the Public", None),
            debt_row(DAY, "Intragovernmental Holdings", "10"),
            debt_row(DAY, "Statutory Debt Limit", None),
        ])[DAY]
        zero_debt = dts.organize_debt_limit([
            debt_row(ZERO_DAY, "Debt Held by the Public", "0"),
            debt_row(ZERO_DAY, "Intragovernmental Holdings", "0"),
            debt_row(ZERO_DAY, "Statutory Debt Limit", "0"),
            debt_row(ZERO_DAY, "Total Public Debt Subject to Limit", "0"),
        ])[ZERO_DAY]
        spec = {
            "gapRefundToday": dts.published_refund(gap_refunds, "indiv", "today"),
            "gapRefundFytd": dts.published_refund(gap_refunds, "indiv", "fytd"),
            "gapBizToday": dts.published_refund(gap_refunds, "biz", "today"),
            "zeroRefundFytd": dts.published_refund(zero_refunds, "indiv", "fytd"),
            "zeroBizToday": dts.published_refund(zero_refunds, "biz", "today"),
            "gapHeadroom": dts.debt_headroom_musd(gap_debt),
            "zeroHeadroom": dts.debt_headroom_musd(zero_debt),
            "gapBook": build_book({DAY: cash_source()}, {}, {}, {}, {"asof": DAY}, {DAY: gap_debt}),
            "zeroBook": build_book(
                {ZERO_DAY: cash_source()}, {}, {}, {}, {"asof": ZERO_DAY}, {ZERO_DAY: zero_debt}
            ),
        }
        self.assertIsNone(spec["gapRefundToday"])
        self.assertIsNone(spec["gapRefundFytd"])
        self.assertIsNone(spec["gapBizToday"])
        self.assertEqual(spec["zeroRefundFytd"], 0)
        self.assertEqual(spec["zeroBizToday"], 0)
        self.assertIsNone(spec["gapHeadroom"])
        self.assertEqual(spec["zeroHeadroom"], 0)
        self.assertIsNone(spec["gapBook"]["rows"][0]["debt"]["public"])
        self.assertIsNone(spec["gapBook"]["rows"][0]["debt"]["headroom"])
        self.assertEqual(spec["zeroBook"]["rows"][0]["debt"]["public"], 0)
        self.assertEqual(spec["zeroBook"]["rows"][0]["debt"]["headroom"], 0)

        script = textwrap.dedent(
            """
            import {readFileSync} from 'node:fs';
            import {formatAmount} from './assets/app.mjs';
            import {cashDeskHTML} from './assets/cash-desk.mjs';
            import {selectCashRows} from './assets/treasury.mjs';
            const spec = JSON.parse(readFileSync(0, 'utf8'));
            const fiscal = (value) => `<div class="big">${formatAmount(value, 'en', 0)}</div><td class="numeric">${formatAmount(value, 'en', 0)}</td>`;
            const desk = (book) => cashDeskHTML(book, selectCashRows(book), 'today', 'en');
            const gapRefund = fiscal(spec.gapRefundFytd);
            const zeroRefund = fiscal(spec.zeroRefundFytd);
            const gapHead = fiscal(spec.gapHeadroom);
            const zeroHead = fiscal(spec.zeroHeadroom);
            const gapDesk = desk(spec.gapBook);
            const zeroDesk = desk(spec.zeroBook);
            const problems = [];
            const check = (ok, message) => { if (!ok) problems.push(message); };
            check(gapRefund.includes('<div class="big">NO DATA</div>'), 'null Table V FYTD was not rendered NO DATA');
            check(gapRefund.includes('<td class="numeric">NO DATA</td>'), 'null Table V FYTD cell was not rendered NO DATA');
            check(fiscal(spec.gapRefundToday).includes('NO DATA'), 'null Table V today was not rendered NO DATA');
            check(fiscal(spec.gapBizToday).includes('NO DATA'), 'null business refund today was not rendered NO DATA');
            check(zeroRefund.includes('<div class="big">0</div>'), 'reported zero FYTD refund was not rendered as 0');
            check(!zeroRefund.includes('NO DATA'), 'reported zero FYTD refund was rendered as NO DATA');
            check(fiscal(spec.zeroBizToday).includes('<div class="big">0</div>'), 'reported zero business refund was not rendered as 0');
            check(gapHead.includes('<td class="numeric">NO DATA</td>'), 'null headroom was not rendered NO DATA');
            check(zeroHead.includes('<td class="numeric">0</td>'), 'zero headroom was not rendered as 0');
            check(!zeroHead.includes('NO DATA'), 'zero headroom was rendered as NO DATA');
            check(gapDesk.includes('<div class="cash-value">NO DATA</div>'), 'cash desk hid a null headroom');
            check(gapDesk.includes('Total public debt: NO DATA'), 'null Table IIIC total was not NO DATA');
            check(gapDesk.includes('Debt held by the public: NO DATA'), 'null Table IIIC public debt was not NO DATA');
            check(zeroDesk.includes('<div class="cash-value">0</div>'), 'cash desk hid a zero headroom');
            check(zeroDesk.includes('Total public debt: 0 · Debt held by the public: 0'), 'reported zero Table IIIC debt was not kept');
            if (problems.length) {
              console.error(problems.join('\\n'));
              process.exit(1);
            }
            console.log('ok');
            """
        )
        root = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=root, input=json.dumps(spec), capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ok", proc.stdout)

    def test_table_ii_duplicate_line_is_not_an_empty_accumulator(self):
        # One row, nothing reported: the cell stays null. It is not initialized to zero.
        self.assertEqual(dts.merge_table_ii_line(None, None, None, None), [None, None, None])
        # A reported zero is a real zero, on its own and inside a sum.
        self.assertEqual(dts.merge_table_ii_line(None, 0.0, 0.0, 0.0), [0.0, 0.0, 0.0])
        self.assertEqual(dts.merge_table_ii_line([0.0, 0.0, 0.0], 5.0, 0.0, 7.0), [5.0, 0.0, 7.0])
        self.assertEqual(dts.merge_table_ii_line([3.0, 1.0, 4.0], 4.0, 2.0, 0.0), [7.0, 3.0, 4.0])
        # A missing vintage on either duplicate poisons that vintage. It does not become zero
        # and it does not enter the sum, in either row order.
        self.assertEqual(dts.merge_table_ii_line([None, 8.0, None], 4.0, None, 2.0), [None, None, None])
        self.assertEqual(dts.merge_table_ii_line([4.0, 0.0, None], None, 3.0, None), [None, 3.0, None])
        self.assertNotEqual(dts.merge_table_ii_line([None, 8.0, None], 4.0, None, 2.0), [4.0, 8.0, 2.0])

    def test_missing_pulse_basis_is_no_data_and_zero_keeps_its_reading(self):
        spec = {item["id"]: item for item in INDICATORS}
        missing = build_pulse(pulse_fix.book(), pulse_fix.CPI, pulse_fix.NOW)
        salaries = next(item for item in missing["indicators"] if item["id"] == "fed_salaries")
        self.assertIsNone(salaries["fytd"]["change"])
        self.assertEqual(salaries["reading_es"], "NO DATA")
        self.assertEqual(salaries["reading_en"], "NO DATA")
        self.assertNotIn(spec["fed_salaries"]["down_es"], salaries["reading_es"])
        self.assertNotIn(spec["fed_salaries"]["down_en"], salaries["reading_en"])
        self.assertNotIn("Sin cambio relevante", salaries["reading_es"])

        zero = build_pulse(pulse_fix.book(1.0), pulse_fix.CPI, pulse_fix.NOW)
        withheld = next(item for item in zero["indicators"] if item["id"] == "withheld")
        self.assertEqual(withheld["fytd"]["change"], 0.0)
        self.assertEqual(withheld["reading_es"], spec["withheld"]["down_es"])
        self.assertEqual(withheld["reading_en"], spec["withheld"]["down_en"])
        self.assertNotEqual(withheld["reading_es"], "NO DATA")

        script = textwrap.dedent(
            """
            import {readFileSync} from 'node:fs';
            import {pulseHTML} from './assets/pulse.mjs';
            const spec = JSON.parse(readFileSync(0, 'utf8'));
            const now = Date.parse('2026-11-08T12:00:00Z');
            const gap = pulseHTML(spec.missing, [], 'es', now);
            const kept = pulseHTML(spec.zero, [], 'en', now);
            const article = (html, id) => {
              const start = html.indexOf('data-pulse-item="' + id + '"');
              const next = html.indexOf('data-pulse-item=', start + 1);
              return html.slice(start, next === -1 ? undefined : next);
            };
            const gapArticle = article(gap, 'fed_salaries');
            const zeroArticle = article(kept, 'withheld');
            const problems = [];
            const check = (ok, message) => { if (!ok) problems.push(message); };
            check(gapArticle.includes('<p class="pulse-reading">NO DATA</p>'), 'missing basis direction was not rendered NO DATA');
            check(!gapArticle.includes('Menos nómina'), 'missing basis rendered the down reading');
            check(zeroArticle.includes(spec.downEn), 'reported zero basis lost its current down reading');
            check(!zeroArticle.includes('<p class="pulse-reading">NO DATA</p>'), 'reported zero basis was rendered NO DATA');
            check(zeroArticle.includes('0.0'), 'reported zero change was not rendered as zero');
            if (problems.length) {
              console.error(problems.join('\\n'));
              process.exit(1);
            }
            console.log('ok');
            """
        )
        root = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=root,
            input=json.dumps({
                "missing": missing,
                "zero": zero,
                "downEn": spec["withheld"]["down_en"],
            }),
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ok", proc.stdout)


if __name__ == "__main__":
    unittest.main()
