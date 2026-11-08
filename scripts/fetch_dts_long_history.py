#!/usr/bin/env python3
"""Long DTS history for bridge research (Table II and Table V), stored as compact gzip CSV.

DTS observations are not revised after publication, so each daily amount is the
information a desk had at 16:00 ET on the next business day. Only 'today'
amounts are kept; monthly sums are built from daily rows, never from MTD fields.
"""
from __future__ import annotations
import csv, gzip, io, json, sys, time, urllib.parse, urllib.request, datetime as dt
from pathlib import Path

BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts"
import os
OUT = Path(os.environ.get("DTS_RAW_DIR", "/tmp/dts_raw"))  # raw pages are not committed; dts_bridge.py --rebuild compacts them
START = sys.argv[1] if len(sys.argv) > 1 else "2014-01-01"

def pages(endpoint, fields):
    out, page, total = [], 1, 1
    while page <= total:
        q = urllib.parse.urlencode({"filter": f"record_date:gte:{START}", "sort": "record_date",
                                    "fields": ",".join(fields), "page[size]": "10000", "page[number]": str(page)})
        for attempt in range(4):
            try:
                req = urllib.request.Request(f"{BASE}/{endpoint}?{q}", headers={"User-Agent": "dts-tracker-bridge/7.0 research", "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    body = json.loads(r.read())
                break
            except Exception as exc:
                if attempt == 3: raise
                time.sleep(2 ** attempt)
        total = int(body["meta"]["total-pages"]); count = int(body["meta"]["total-count"])
        out += body["data"]; print(endpoint, page, total, len(out), count, flush=True); page += 1
    if len(out) != count: raise RuntimeError(f"incomplete {endpoint}: {len(out)} != {count}")
    return out

def write(name, rows, cols):
    OUT.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO(); w = csv.writer(buf); w.writerow(cols)
    for r in rows: w.writerow([r.get(c) for c in cols])
    with gzip.open(OUT / name, "wt", encoding="utf-8", compresslevel=9) as fh: fh.write(buf.getvalue())

t2 = pages("deposits_withdrawals_operating_cash", ["record_date", "account_type", "transaction_type", "transaction_catg", "transaction_catg_desc", "transaction_today_amt"])
write("table2.csv.gz", t2, ["record_date", "account_type", "transaction_type", "transaction_catg", "transaction_catg_desc", "transaction_today_amt"])
t5 = pages("income_tax_refunds_issued", ["record_date", "tax_refund_type", "tax_refund_type_desc", "tax_refund_today_amt"])
write("table5.csv.gz", t5, ["record_date", "tax_refund_type", "tax_refund_type_desc", "tax_refund_today_amt"])
# Pre-Feb-2023 statements report withheld taxes only in Table IV (Federal Tax Deposits).
t4 = pages("federal_tax_deposits", ["record_date", "tax_deposit_type", "tax_deposit_type_desc", "tax_deposit_today_amt"])
write("table4_ftd.csv.gz", t4, ["record_date", "tax_deposit_type", "tax_deposit_type_desc", "tax_deposit_today_amt"])
meta = {"retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "start": START,
        "rows": {"table2": len(t2), "table5": len(t5), "table4_ftd": len(t4)}, "source": BASE}
(OUT / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
