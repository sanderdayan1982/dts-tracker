"""A published debt limit of 0 during the 2024 suspension is not headroom."""
import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_dts_nowcast as dts
from treasury_book import build_book


DAY = "2024-09-05"


def debt_row(catg, close, desc="null"):
    return {
        "record_date": DAY,
        "debt_catg": catg,
        "debt_catg_desc": desc,
        "close_today_bal": close,
        "open_today_bal": close,
    }


class DebtLimitSuspensionTests(unittest.TestCase):
    def test_suspended_limit_is_null_and_the_page_says_suspendido(self):
        organized = dts.organize_debt_limit([
            debt_row("Debt Held by the Public", "28258351"),
            debt_row("Intragovernmental Holdings", "7087221"),
            debt_row("Debt Not Subject to Limit", "117091", "Unamortized Discount (-)"),
            debt_row("Other Debt Subject to Limit", "0", "Guaranteed Debt of Government Agencies"),
            debt_row("Statutory Debt Limit", "0"),
        ])[DAY]
        self.assertEqual(organized["stat_debt_limit"], 0.0)
        source = dict(
            tga_close=120, tga_open=100, tga_open_mtd=90, tga_open_fytd=80,
            tga_dep_t1=30, tga_wd_t1=10, tga_dep_mtd_t1=70, tga_wd_mtd_t1=40,
            tga_dep_fytd_t1=100, tga_wd_fytd_t1=60,
        )
        book = build_book({DAY: source}, {}, {}, {}, {"asof": DAY}, {DAY: organized})
        debt = book["rows"][0]["debt"]
        self.assertIsNone(debt["headroom"])
        self.assertEqual(debt["status"], "SUSPENDED")
        self.assertNotEqual(debt["headroom"], 0)

        script = textwrap.dedent(
            """
            import {readFileSync} from 'node:fs';
            import {cashDeskHTML} from './assets/cash-desk.mjs';
            import {selectCashRows} from './assets/treasury.mjs';
            const book = JSON.parse(readFileSync(0, 'utf8'));
            const html = cashDeskHTML(book, selectCashRows(book), 'today', 'es');
            const start = html.indexOf('Margen frente al límite de deuda');
            const panel = html.slice(start, html.indexOf('</article>', start));
            if (!panel.includes('<div class="cash-value">SUSPENDIDO</div>')) {
              console.error('suspended headroom was not labelled SUSPENDIDO');
              process.exit(1);
            }
            if (/cash-value">-?[0-9]/.test(panel)) {
              console.error('suspended headroom was rendered as a number');
              process.exit(1);
            }
            console.log('ok');
            """
        )
        root = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=root, input=json.dumps(book), capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ok", proc.stdout)


if __name__ == "__main__":
    unittest.main()
