#!/usr/bin/env python3
"""DTS cash accounting and calendar diagnostics v6.
Thresholds are monitoring rules, not macro surprise probabilities.
See docs/METHODOLOGY.md for point-in-time and calibration limitations.
"""

import calendar
import datetime
import json
import math
import os
import re
import ssl
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo
from treasury_book import build_book
from institutional_core import (atomic_json, business_day, cash_contract, finite,
                                lag364_stats, settlement)

BASE_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts"
CAL_DAYS = 800          # Complete prior FYTD even near September; not just a 364-day window.
HISTORY_BD_LIMIT = 400  # Keep last 400 business days in dts_history_400d.json
MAD_FLOOR_MUSD = 2500.0 # Engineering noise floor; not a calibrated probability threshold.
MIN_PRIOR_EVENTS = 3    # Minimum prior realizations required before emitting ex-ante expected payment

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
NOWCAST_PATH = DATA_DIR / "dts_nowcast.json"
HISTORY_PATH = DATA_DIR / "dts_history_400d.json"
BENCHMARKS_PATH = DATA_DIR / "macro_benchmarks.json"


def _nth_weekday_of_month(year, month, weekday, n):
    """Return the nth occurrence (1-based, or -1 for last) of `weekday` (0=Mon..6=Sun) in (year, month)."""
    _, last_day = calendar.monthrange(year, month)
    matches = [
        datetime.date(year, month, d)
        for d in range(1, last_day + 1)
        if datetime.date(year, month, d).weekday() == weekday
    ]
    return matches[n - 1] if n > 0 else matches[-1]


def build_fed_k8_holidays(years=(2024, 2025, 2026, 2027, 2028, 2029, 2030)):
    """
    Generate the official Federal Reserve K.8 / Bureau of the Fiscal Service holiday calendar:
      - Fixed-date holidays (Jan 1, Jun 19, Jul 4, Nov 11, Dec 25):
        * If Sunday -> observed on Monday (+1d).
        * If Saturday -> Federal Reserve Banks and DTS remain OPEN on the preceding Friday!
      - Floating Monday/Thursday holidays:
        * MLK Day (3rd Mon Jan), Presidents Day (3rd Mon Feb), Memorial Day (Last Mon May),
          Labor Day (1st Mon Sep), Columbus Day (2nd Mon Oct), Thanksgiving (4th Thu Nov).
    """
    hols = set()
    for y in years:
        fixed = [
            datetime.date(y, 1, 1),
            datetime.date(y, 6, 19),
            datetime.date(y, 7, 4),
            datetime.date(y, 11, 11),
            datetime.date(y, 12, 25),
        ]
        for dt in fixed:
            if dt.weekday() == 6:  # Sunday -> observed Monday
                hols.add((dt + datetime.timedelta(days=1)).isoformat())
            elif dt.weekday() < 5: # Mon-Fri -> observed on the day itself (Saturday is NOT closed on Friday)
                hols.add(dt.isoformat())

        floating = [
            _nth_weekday_of_month(y, 1, 0, 3),  # MLK Day
            _nth_weekday_of_month(y, 2, 0, 3),  # Presidents Day
            _nth_weekday_of_month(y, 5, 0, -1), # Memorial Day
            _nth_weekday_of_month(y, 9, 0, 1),  # Labor Day
            _nth_weekday_of_month(y, 10, 0, 2), # Columbus Day
            _nth_weekday_of_month(y, 11, 3, 4), # Thanksgiving
        ]
        for dt in floating:
            hols.add(dt.isoformat())
    return hols


US_FEDERAL_HOLIDAYS = build_fed_k8_holidays()

# ─────────────────────────────────────────────────────────────────────────────
# 1. VERSIONED CANONICAL ALIAS DICTIONARY (Strictly separated by side)
# ─────────────────────────────────────────────────────────────────────────────
SERIES_SPLICE_META = {
    "CUSTOMS_DUTIES": {
        "old_label": "DHS - Customs and Certain Excise Taxes",
        "new_label": "DHS - Customs Duties, Taxes, and Fees",
        "splice_date": "2025-11-10",
        "clean_20d_yoy_from": "2026-12-09",
        "clean_fytd_yoy_from": "2027-10-01",
        "note": "Old series included Certain Excise Taxes (~3% level shift); FYTD base is mixed until FY2028.",
    }
}

CANONICAL_ALIASES = {
    "Deposits": {
        "CUSTOMS_DUTIES": [
            "DHS - Customs Duties, Taxes, and Fees",
            "DHS - Customs and Certain Excise Taxes",
            "Customs and Certain Excise Taxes",
        ],
        "WITHHELD_FICA": [
            "Taxes - Withheld Individual/FICA",
            "Withheld Individual/FICA",
        ],
        "CORP_INCOME": [
            "Taxes - Corporate Income",
            "Corporate Income",
        ],
        "NON_WITHHELD_SECA": [
            "Taxes - Non Withheld Ind/SECA Electronic",
            "Taxes - Non Withheld Ind/SECA Other",
            "Non Withheld Ind/SECA Electronic",
            "Non Withheld Ind/SECA Other",
        ],
        "NON_WITHHELD_ELEC": [
            "Taxes - Non Withheld Ind/SECA Electronic",
            "Non Withheld Ind/SECA Electronic",
        ],
        "NON_WITHHELD_OTHER": [
            "Taxes - Non Withheld Ind/SECA Other",
            "Non Withheld Ind/SECA Other",
        ],
        "FUTA_TAX": [
            "Taxes - Federal Unemployment (FUTA)",
            "Federal Unemployment (FUTA)",
        ],
        "STATE_UI_DEP": [
            "State Unemployment Insurance Deposits",
        ],
        "MEDICARE_PREMIUMS": [
            "HHS - Medicare Premiums",
            "Medicare Premiums",
        ],
        "TSP_DEP": [
            "Federal Retirement Thrift Savings Plan",
        ],
        "TOTAL_DEPOSITS_EX_DEBT": [
            "Total Deposits",
            "Sub-Total Deposits",
        ],
        "PUBLIC_DEBT_CASH_ISSUES_T2": [
            "Public Debt Cash Issues (Table IIIB)",
        ],
        "TOTAL_TGA_DEPOSITS_T2": [
            "Treasury General Account Total Deposits",
            "Total TGA Deposits (Table II)",
        ],
    },
    "Withdrawals": {
        "DOL_UNEMP_BEN": [
            "DOL - Unemployment Benefits",
            "DOL - Unemployment Insurance Benefits",
            "Unemployment Insurance Benefits",
        ],
        "USDA_SNAP": [
            "USDA - Supp Nutrition Assist Prog (SNAP)",
            "Supp Nutrition Assist Prog (SNAP)",
        ],
        "SSA_BENEFITS": [
            "SSA - Benefits Payments",
            "Benefits Payments",
        ],
        "SSA_SSI": [
            "SSA - Supplemental Security Income",
            "Supplemental Security Income",
        ],
        "TREAS_INTEREST": [
            "Interest on Treasury Securities",
        ],
        "FED_SALARIES_EFT": [
            "Federal Salaries (EFT)",
        ],
        "DOD_ACTIVE_PAY": [
            "DoD - Military Active Duty Pay",
        ],
        "DOD_MIL_RET": [
            "DoD - Military Retirement",
        ],
        "VA_BENEFITS": [
            "VA - Benefits",
        ],
        "DEPT_VA": [
            "Dept of Veterans Affairs (VA)",
        ],
        "OPM_RET": [
            "OPM - Civil Serv Retirement & Disability",
        ],
        "RRB_BENEFITS": [
            "RRB - Benefit Payments",
        ],
        "TSP_WD": [
            "Federal Retirement Thrift Savings Plan",
        ],
        "MEDICARE_PART_A": [
            "HHS - Federal Hospital Insr Trust Fund",
        ],
        "MEDICARE_PART_B": [
            "HHS - Federal Supple Med Insr Trust Fund",
        ],
        "MEDICARE_PART_D": [
            "HHS - Medicare Prescription Drugs",
        ],
        "MEDICAID": [
            "HHS - Grants to States for Medicaid",
        ],
        "DOD_MISC_WD": [
            "Dept of Defense (DoD) - misc",
        ],
        "HHS_MISC_WD": [
            "Dept of Health & Human Serv (HHS) - misc",
        ],
        "ED_WD": [
            "Dept of Education (ED)",
        ],
        "INDIV_REFUNDS_EFT": [
            "Taxes - Individual Tax Refunds (EFT)",
            "Individual Tax Refunds (EFT)",
        ],
        "BIZ_REFUNDS_EFT": [
            "Taxes - Business Tax Refunds (EFT)",
            "Business Tax Refunds (EFT)",
        ],
        "UNCLASSIFIED_WD": [
            "Unclassified",
            "Unclassified - Withdrawals",
        ],
        "TOTAL_WITHDRAWALS_EX_DEBT": [
            "Total Withdrawals",
            "Sub-Total Withdrawals",
        ],
        "PUBLIC_DEBT_CASH_REDEMP_T2": [
            "Public Debt Cash Redemp. (Table IIIB)",
        ],
        "TOTAL_TGA_WITHDRAWALS_T2": [
            "Treasury General Account Total Withdrawals",
            "Total TGA Withdrawals (Table II)",
        ],
    },
}

REVERSAL_SHORT_CODES = {
    "VA - Benefits": "VA_BENEFITS",
    "OPM - Civil Serv Retirement & Disability": "OPM_RET",
    "Taxes - Business Tax Refunds (EFT)": "BIZ_REFUND_EFT",
    "Taxes - Individual Tax Refunds (EFT)": "INDIV_REFUND_EFT",
    "SSA - Benefits Payments": "SSA_BENEFITS",
    "USDA - Supp Nutrition Assist Prog (SNAP)": "USDA_SNAP",
    "DOL - Unemployment Benefits": "DOL_UNEMP_BEN",
}


def parse_num(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return None if math.isnan(val) else float(val)
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "n/a", "-", "--"):
        return None
    if "/" in s:
        s = s.split("/")[-1].strip()
    s = s.replace(",", "").replace("$", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _build_ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    if os.path.exists("/etc/ssl/cert.pem"):
        try:
            return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
        except Exception:
            pass
    return ssl.create_default_context()


SSL_CTX = _build_ssl_context()


def fetch_paginated(endpoint, start_date):
    all_rows = []
    page_num = 1
    total_pages = 1

    while page_num <= total_pages:
        params = {
            "filter": f"record_date:gte:{start_date},record_date:lte:{datetime.date.today().isoformat()}",
            "sort": "-record_date",
            "page[size]": "10000",
            "page[number]": str(page_num),
        }
        qs = urllib.parse.urlencode(params)
        url = f"{BASE_URL}/{endpoint}?{qs}"

        last_err = None
        for attempt in range(1, 4):
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "dts-tracker-g8-nowcaster/5.0 (Institutional Macro Pipeline)",
                        "Accept": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=40, context=SSL_CTX) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                rows = payload.get("data", [])
                meta = payload.get("meta", {})
                total_pages = int(meta.get("total-pages") or 1)
                total_count = int(meta.get("total-count") or len(rows))
                all_rows.extend(rows)
                print(
                    f"  [OK] {endpoint} page {page_num}/{total_pages}: "
                    f"+{len(rows)} rows (acc {len(all_rows)}/{total_count})"
                )
                last_err = None
                break
            except Exception as exc:
                last_err = exc
                wait_s = 2 ** attempt
                print(f"  [WARN] {endpoint} page {page_num} attempt {attempt} failed: {exc} -> retry in {wait_s}s")
                time.sleep(wait_s)

        if last_err is not None:
            raise RuntimeError(f"Failed to fetch {endpoint} page {page_num}: {last_err}")

        page_num += 1

    if len(all_rows) != total_count:
        raise RuntimeError(f"Incomplete pagination for {endpoint}: {len(all_rows)} != {total_count}")
    return all_rows


def mark_fetch_failure_on_existing_json(err_msg):
    """
    If FiscalData API is unreachable, mark the existing dts_nowcast.json as FETCH_FAIL & block=true
    while preserving the original `generated_at` timestamp (Perplexity #4).
    """
    if not NOWCAST_PATH.exists():
        return
    try:
        prev = json.loads(NOWCAST_PATH.read_text(encoding="utf-8"))
        now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        prev["last_fetch_attempt_utc"] = now_utc
        dq = prev.setdefault("dq", {})
        dq["status"] = "FETCH_FAIL"
        dq["stale"] = True
        dq["block"] = True
        dq["fetch_error"] = str(err_msg)[:200]
        if "mmt_liquidity" in prev:
            prev["mmt_liquidity"]["funding_state"] = "BLOCKED"
        for k, card in prev.get("nowcast_cards", {}).items():
            card["state"] = "BLOCKED"
            card["dir"] = None
        atomic_json(NOWCAST_PATH, cash_contract(prev))
        print(f"[DTS NOWCASTER v6.0] Marked existing {NOWCAST_PATH} with status=FETCH_FAIL and block=True")
    except Exception as exc:
        print(f"[WARN] Could not update existing JSON on fetch fail: {exc}")


def normalize_side(raw_type):
    if not raw_type:
        return ""
    t = str(raw_type).strip().lower()
    if t.startswith("deposit"):
        return "Deposits"
    if t.startswith("withdrawal"):
        return "Withdrawals"
    if t.startswith("issue"):
        return "Issues"
    if t.startswith("redemption"):
        return "Redemptions"
    return str(raw_type).strip()


def get_catg_label(row):
    for field in (
        "transaction_catg",
        "classification",
        "classification_desc",
        "tax_refund_type",
        "tax_refund_type_desc",
        "adj_type",
        "adj_type_desc",
        "security_type",
        "security_type_desc",
        "debt_catg",
        "account_type",
    ):
        v = row.get(field)
        if v and str(v).strip().lower() not in ("null", "none", ""):
            return str(v).strip()
    desc = row.get("transaction_catg_desc")
    if desc and str(desc).strip().lower() not in ("null", "none", ""):
        return str(desc).strip()
    return ""


def match_canonical(side, label, desc=""):
    matched = []
    side_map = CANONICAL_ALIASES.get(side, {})
    lbl_clean = label.strip()
    desc_clean = (desc or "").strip()
    for cid, aliases in side_map.items():
        for alias in aliases:
            if lbl_clean == alias or desc_clean == alias:
                matched.append(cid)
                break
    return matched


def _first_present(row, keys):
    for k in keys:
        if k in row and row[k] is not None and str(row[k]).strip().lower() not in ("null", "none", ""):
            return row[k]
    return None


def get_row_amounts(row):
    today = parse_num(
        _first_present(row, ("transaction_today_amt", "today_amt", "tax_refund_today_amt", "adj_today_amt"))
    )
    mtd = parse_num(
        _first_present(row, ("transaction_mtd_amt", "mtd_amt", "tax_refund_mtd_amt", "adj_mtd_amt"))
    )
    fytd = parse_num(
        _first_present(row, ("transaction_fytd_amt", "fytd_amt", "tax_refund_fytd_amt", "adj_fytd_amt"))
    )
    return today, mtd, fytd


def fiscal_year_for_date(d_str):
    y = int(d_str[0:4])
    m = int(d_str[5:7])
    return y + 1 if m >= 10 else y


# ─────────────────────────────────────────────────────────────────────────────
# 2. HOLIDAY- & DST-AWARE TREASURY PUBLICATION CALENDAR (Federal Reserve K.8)
# ─────────────────────────────────────────────────────────────────────────────
def is_us_business_day(dt):
    return business_day(dt, "federal")


def expected_latest_bd_and_validity(now_utc_dt):
    et_tz = ZoneInfo("America/New_York")
    et_now = now_utc_dt.astimezone(et_tz)
    cur_date = et_now.date()

    if is_us_business_day(cur_date) and (et_now.hour > 16 or (et_now.hour == 16 and et_now.minute >= 45)):
        latest_pub_bd = cur_date
    else:
        d = cur_date - datetime.timedelta(days=1)
        while not is_us_business_day(d):
            d -= datetime.timedelta(days=1)
        latest_pub_bd = d

    exp_rec_dt = latest_pub_bd - datetime.timedelta(days=1)
    while not is_us_business_day(exp_rec_dt):
        exp_rec_dt -= datetime.timedelta(days=1)

    next_pub_bd = latest_pub_bd + datetime.timedelta(days=1)
    while not is_us_business_day(next_pub_bd):
        next_pub_bd += datetime.timedelta(days=1)
    next_pub_et = datetime.datetime(
        next_pub_bd.year, next_pub_bd.month, next_pub_bd.day, 16, 45, 0, tzinfo=et_tz
    )
    valid_until_utc = next_pub_et.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return exp_rec_dt.isoformat(), valid_until_utc


# ─────────────────────────────────────────────────────────────────────────────
# 3. ASYMMETRIC SETTLEMENT CALENDAR + WEEKDAY/MONTH-START BASELINE ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def settle_date(nominal_dt, bd_set, min_bd, max_bd, convention="PRECEDING"):
    return settlement(nominal_dt, bd_set, min_bd, max_bd, convention)


def nth_wednesdays(year, month, ns=(2, 3, 4)):
    weds = []
    _, last_day = calendar.monthrange(year, month)
    for day in range(1, last_day + 1):
        dt = datetime.date(year, month, day)
        if dt.weekday() == 2:
            weds.append(dt)
    return [weds[n - 1] for n in ns if n - 1 < len(weds)]


def build_asymmetric_calendar_schedule(all_bd_dates, get_cval):
    bd_set = set(all_bd_dates)
    bd_index = {d: i for i, d in enumerate(all_bd_dates)}
    min_bd, max_bd = all_bd_dates[0], all_bd_dates[-1]

    ym_set = set()
    for d in all_bd_dates:
        y, m = int(d[:4]), int(d[5:7])
        ym_set.add((y, m))
        if m == 12:
            ym_set.add((y + 1, 1))
        else:
            ym_set.add((y, m + 1))
        if m == 1:
            ym_set.add((y - 1, 12))
        else:
            ym_set.add((y, m - 1))

    def _day_offset(nom_dt, conv, offset_bd):
        base_d = settle_date(nom_dt, bd_set, min_bd, max_bd, conv)
        if base_d is None or base_d not in bd_index:
            return None
        idx = bd_index[base_d] + offset_bd
        if 0 <= idx < len(all_bd_dates):
            return all_bd_dates[idx]
        return None

    # Discrete Event Specifications:
    # (event_key, side, canonical_ids, nominal_dates_fn, conv, bd_offset, hist_len, ntf_sign)
    event_specs = [
        (
            "SSA_DAY3",
            "Withdrawals",
            ["SSA_BENEFITS"],
            lambda y, m: [datetime.date(y, m, 3)],
            "PRECEDING",
            0,
            6,
            1.0,
        ),
        (
            "SSA_WED",
            "Withdrawals",
            ["SSA_BENEFITS"],
            lambda y, m: nth_wednesdays(y, m, (2, 3, 4)),
            "PRECEDING",
            0,
            12,
            1.0,
        ),
        (
            "SSI_DAY1",
            "Withdrawals",
            ["SSA_SSI"],
            lambda y, m: [datetime.date(y, m, 1)],
            "PRECEDING",
            0,
            6,
            1.0,
        ),
        (
            "VA_DAY1",
            "Withdrawals",
            ["VA_BENEFITS"],
            lambda y, m: [datetime.date(y, m, 1)],
            "PRECEDING",
            0,
            6,
            1.0,
        ),
        (
            "MIL_ACTIVE_1_15",
            "Withdrawals",
            ["DOD_ACTIVE_PAY"],
            lambda y, m: [datetime.date(y, m, 1), datetime.date(y, m, 15)],
            "PRECEDING",
            0,
            12,
            1.0,
        ),
        (
            "MIL_RET_DAY1",
            "Withdrawals",
            ["DOD_MIL_RET"],
            lambda y, m: [datetime.date(y, m, 1)],
            "PRECEDING",
            0,
            6,
            1.0,
        ),
        (
            "MEDICARE_MA_DAY1",
            "Withdrawals",
            ["MEDICARE_PART_A", "MEDICARE_PART_B", "MEDICARE_PART_D"],
            lambda y, m: [datetime.date(y, m, 1)],
            "PRECEDING",
            0,
            6,
            1.0,
        ),
        (
            "OPM_RET_DAY1",
            "Withdrawals",
            ["OPM_RET"],
            lambda y, m: [datetime.date(y, m, 1)],
            "FOLLOWING",
            0,
            6,
            1.0,
        ),
        (
            "COUPON_15",
            "Withdrawals",
            ["TREAS_INTEREST"],
            lambda y, m: [datetime.date(y, m, 15)],
            "FOLLOWING",
            0,
            6,
            1.0,
        ),
        (
            "COUPON_MEND",
            "Withdrawals",
            ["TREAS_INTEREST"],
            lambda y, m: [datetime.date(y, m, calendar.monthrange(y, m)[1])],
            "FOLLOWING",
            0,
            6,
            1.0,
        ),
        # Scheduled Inflow Events (ntf_sign = -1.0):
        # 1. Month-Start Payroll Withholding Surge (1st business day on/after the 1st)
        (
            "WITHHELD_MSTART",
            "Deposits",
            ["WITHHELD_FICA"],
            lambda y, m: [datetime.date(y, m, 1)],
            "FOLLOWING",
            0,
            6,
            -1.0,
        ),
        # 2. Mid-Month Payroll Withholding Surge:
        #    - D0 when the 15th falls on a weekend/Monday (Kimi P1-B)
        #    - P1 (next business day after 15th) when the 15th is a weekday
        (
            "WITHHELD_MID_D0",
            "Deposits",
            ["WITHHELD_FICA"],
            lambda y, m: [datetime.date(y, m, 15)] if datetime.date(y, m, 15).weekday() in (0, 5, 6) else [],
            "FOLLOWING",
            0,
            6,
            -1.0,
        ),
        (
            "WITHHELD_MID_P1",
            "Deposits",
            ["WITHHELD_FICA"],
            lambda y, m: [datetime.date(y, m, 15)] if datetime.date(y, m, 15).weekday() in (1, 2, 3, 4) else [],
            "FOLLOWING",
            1,
            6,
            -1.0,
        ),
        # 3. Separated Statutory Tax Deadline Cohorts (M1, D0, P1, P2):
        #    - Quarterly Corporate & Estimated Tax (Apr, Jun, Sep, Dec)
        (
            "TAX_CORP_EST_M1",
            "Deposits",
            ["CORP_INCOME", "NON_WITHHELD_SECA"],
            lambda y, m: [datetime.date(y, m, 15)] if m in (4, 6, 9, 12) else [],
            "FOLLOWING",
            -1,
            4,
            -1.0,
        ),
        (
            "TAX_CORP_EST_D0",
            "Deposits",
            ["CORP_INCOME", "NON_WITHHELD_SECA"],
            lambda y, m: [datetime.date(y, m, 15)] if m in (4, 6, 9, 12) else [],
            "FOLLOWING",
            0,
            4,
            -1.0,
        ),
        (
            "TAX_CORP_EST_P1",
            "Deposits",
            ["CORP_INCOME", "NON_WITHHELD_SECA"],
            lambda y, m: [datetime.date(y, m, 15)] if m in (4, 6, 9, 12) else [],
            "FOLLOWING",
            1,
            4,
            -1.0,
        ),
        (
            "TAX_CORP_EST_P2",
            "Deposits",
            ["CORP_INCOME", "NON_WITHHELD_SECA"],
            lambda y, m: [datetime.date(y, m, 15)] if m in (4, 6, 9, 12) else [],
            "FOLLOWING",
            2,
            4,
            -1.0,
        ),
        #    - January Individual Q4 Estimated Tax Deadline (Jan 15: M1, D0, P1)
        (
            "TAX_JAN_EST_M1",
            "Deposits",
            ["CORP_INCOME", "NON_WITHHELD_SECA"],
            lambda y, m: [datetime.date(y, m, 15)] if m == 1 else [],
            "FOLLOWING",
            -1,
            2,
            -1.0,
        ),
        (
            "TAX_JAN_EST_D0",
            "Deposits",
            ["CORP_INCOME", "NON_WITHHELD_SECA"],
            lambda y, m: [datetime.date(y, m, 15)] if m == 1 else [],
            "FOLLOWING",
            0,
            2,
            -1.0,
        ),
        (
            "TAX_JAN_EST_P1",
            "Deposits",
            ["CORP_INCOME", "NON_WITHHELD_SECA"],
            lambda y, m: [datetime.date(y, m, 15)] if m == 1 else [],
            "FOLLOWING",
            1,
            2,
            -1.0,
        ),
        #    - March Pass-Through (Mar 15) & October Extension (Oct 15): M1, D0, P1
        (
            "TAX_MAR_OCT_M1",
            "Deposits",
            ["CORP_INCOME", "NON_WITHHELD_SECA"],
            lambda y, m: [datetime.date(y, m, 15)] if m in (3, 10) else [],
            "FOLLOWING",
            -1,
            2,
            -1.0,
        ),
        (
            "TAX_MAR_OCT_D0",
            "Deposits",
            ["CORP_INCOME", "NON_WITHHELD_SECA"],
            lambda y, m: [datetime.date(y, m, 15)] if m in (3, 10) else [],
            "FOLLOWING",
            0,
            2,
            -1.0,
        ),
        (
            "TAX_MAR_OCT_P1",
            "Deposits",
            ["CORP_INCOME", "NON_WITHHELD_SECA"],
            lambda y, m: [datetime.date(y, m, 15)] if m in (3, 10) else [],
            "FOLLOWING",
            1,
            2,
            -1.0,
        ),
    ]

    expected_by_date = {d: 0.0 for d in all_bd_dates}
    realized_sched_by_date = {d: 0.0 for d in all_bd_dates}
    calendar_miss_by_date = {d: False for d in all_bd_dates}
    calendar_warmup_by_date = {d: False for d in all_bd_dates}
    active_events_by_date = {d: [] for d in all_bd_dates}
    tax_window_dates = set()

    counted_realized_cid = set()
    counted_expected_cid = set()

    for ev_key, side, cids, nom_fn, conv, bd_off, hist_n, ntf_sign in event_specs:
        eff_dates = sorted(
            {
                s_dt
                for (y, m) in sorted(ym_set)
                for nom_dt in nom_fn(y, m)
                for s_dt in [_day_offset(nom_dt, conv, bd_off)]
                if s_dt is not None
            }
        )
        hist_vals = []
        min_req = min(MIN_PRIOR_EVENTS, hist_n)
        for d in eff_dates:
            if ev_key.startswith("TAX_"):
                tax_window_dates.add(d)

            parts = [get_cval(side, cid, d, "today") for cid in cids]
            if not all(finite(v) for v in parts):
                calendar_warmup_by_date[d] = True
                continue
            obs_val = sum(parts)
            for cid in cids:
                if (d, side, cid) not in counted_realized_cid:
                    counted_realized_cid.add((d, side, cid))
                    realized_sched_by_date[d] += ntf_sign * get_cval(side, cid, d, "today")

            active_events_by_date[d].append(ev_key)

            if len(hist_vals) >= min_req:
                exp_val = statistics.median(hist_vals[-hist_n:])
                new_cids = [cid for cid in cids if (d, side, cid) not in counted_expected_cid]
                if new_cids:
                    for cid in new_cids:
                        counted_expected_cid.add((d, side, cid))
                    expected_by_date[d] += ntf_sign * exp_val

                if ntf_sign > 0 and exp_val > 5000.0:
                    if obs_val < 0.30 * exp_val or obs_val > 1.70 * exp_val:
                        calendar_miss_by_date[d] = True
            else:
                calendar_warmup_by_date[d] = True

            if obs_val >= 0.0:
                hist_vals.append(obs_val)

    # Part B: Symmetric Out-of-Sample Weekday Baseline for Continuous Daily Flows
    # Includes both recurrent Withdrawals and recurrent Deposits (Codeword §4 & Perplexity)
    continuous_specs = [
        ("Deposits", "WITHHELD_FICA", -1.0),
        ("Deposits", "CUSTOMS_DUTIES", -1.0),
        ("Deposits", "STATE_UI_DEP", -1.0),
        ("Deposits", "TSP_DEP", -1.0),
        ("Withdrawals", "FED_SALARIES_EFT", 1.0),
        ("Withdrawals", "MEDICAID", 1.0),
        ("Withdrawals", "MEDICARE_PART_A", 1.0),
        ("Withdrawals", "MEDICARE_PART_B", 1.0),
        ("Withdrawals", "BIZ_REFUNDS_EFT", 1.0),
        ("Withdrawals", "INDIV_REFUNDS_EFT", 1.0),
        ("Withdrawals", "TSP_WD", 1.0),
    ]

    for side, cid, ntf_sign in continuous_specs:
        wd_hist = {w: [] for w in range(5)}
        for d in all_bd_dates:
            if (d, side, cid) in counted_realized_cid:
                continue
            wd = datetime.date.fromisoformat(d).weekday()
            obs_v = get_cval(side, cid, d, "today")
            if not finite(obs_v):
                calendar_warmup_by_date[d] = True
                continue
            realized_sched_by_date[d] += ntf_sign * obs_v
            if len(wd_hist[wd]) >= 4:
                exp_v = statistics.median(wd_hist[wd][-8:])
                expected_by_date[d] += ntf_sign * exp_v
            else:
                calendar_warmup_by_date[d] = True
            wd_hist[wd].append(obs_v)

    return (
        expected_by_date,
        realized_sched_by_date,
        calendar_miss_by_date,
        calendar_warmup_by_date,
        active_events_by_date,
        tax_window_dates,
    )


def robust_zscore_out_of_sample(series, is_shock_day_flags, idx, window=60, mad_floor=MAD_FLOOR_MUSD):
    if idx < 20 or series[idx] is None:
        return None, False, 0
    start_i = max(0, idx - window)
    prior_clean = [
        series[j]
        for j in range(start_i, idx)
        if series[j] is not None and not math.isnan(series[j]) and not is_shock_day_flags[j]
    ]
    if len(prior_clean) < 15:
        prior_clean = [
            series[j]
            for j in range(start_i, idx)
            if series[j] is not None and not math.isnan(series[j])
        ]
    if len(prior_clean) < 15:
        return None, False, len(prior_clean)

    u_t = series[idx]
    med = statistics.median(prior_clean)
    abs_devs = [abs(x - med) for x in prior_clean]
    mad = statistics.median(abs_devs)
    raw_scale = 1.4826 * mad
    floor_hit = raw_scale < mad_floor
    scale = max(raw_scale, mad_floor)
    return round((u_t - med) / scale, 2), floor_hit, len(prior_clean)


def robust_zscore_weekday_out_of_sample(
    series, all_bd_dates, is_shock_day_flags, idx, lookback_bd=100, min_same_wd=10, mad_floor=MAD_FLOOR_MUSD
):
    """
    Weekday-Conditioned Out-of-Sample Robust MAD Z-score (`lookback_bd=100`, ~20 prior same-weekdays).
    Returns (z_val, floor_hit, sample_n, fallback_used).
    """
    if idx < 25 or series[idx] is None:
        return None, False, 0, False
    target_wd = datetime.date.fromisoformat(all_bd_dates[idx]).weekday()
    start_i = max(0, idx - lookback_bd)

    prior_wd_clean = [
        series[j]
        for j in range(start_i, idx)
        if series[j] is not None
        and not math.isnan(series[j])
        and not is_shock_day_flags[j]
        and datetime.date.fromisoformat(all_bd_dates[j]).weekday() == target_wd
    ]
    if len(prior_wd_clean) < min_same_wd:
        z_fb, fl_fb, n_fb = robust_zscore_out_of_sample(series, is_shock_day_flags, idx, window=60, mad_floor=mad_floor)
        return z_fb, fl_fb, n_fb, True

    u_t = series[idx]
    med = statistics.median(prior_wd_clean)
    abs_devs = [abs(x - med) for x in prior_wd_clean]
    mad = statistics.median(abs_devs)
    raw_scale = 1.4826 * mad
    floor_hit = raw_scale < mad_floor
    scale = max(raw_scale, mad_floor)
    return round((u_t - med) / scale, 2), floor_hit, len(prior_wd_clean), False


def rolling_empirical_percentile(z_series, idx, window=250):
    """Compute out-of-sample empirical percentile (0..100) of `z_series[idx]` over prior `window` days."""
    if idx < 30 or z_series[idx] is None:
        return None
    start_i = max(0, idx - window)
    prior_z = [z_series[j] for j in range(start_i, idx) if z_series[j] is not None]
    if len(prior_z) < 30:
        return None
    z_cur = z_series[idx]
    less_or_eq = sum(1 for v in prior_z if v <= z_cur)
    return round((less_or_eq / len(prior_z)) * 100.0, 1)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    bm = {}
    ahe_deflator_yoy = None
    ahe_vintage = None
    ahe_release_date = None
    consensus_loaded = False
    nfp_consensus_k = None
    nfp_model_calibrated = False
    slgs_window_policy_status = "UNKNOWN"

    if BENCHMARKS_PATH.exists():
        try:
            bm = json.loads(BENCHMARKS_PATH.read_text(encoding="utf-8"))
            if bm.get("ahe_deflator_yoy") is not None:
                ahe_deflator_yoy = float(bm["ahe_deflator_yoy"])
            if bm.get("ahe_vintage"):
                ahe_vintage = str(bm["ahe_vintage"])
            if bm.get("ahe_release_date"):
                ahe_release_date = str(bm["ahe_release_date"])
            consensus_loaded = bool(bm.get("consensus_loaded", False))
            nfp_consensus_k = bm.get("nfp_consensus_k")
            nfp_model_calibrated = bool(bm.get("nfp_model_calibrated", False))
            if bm.get("slgs_window_policy_status"):
                slgs_window_policy_status = str(bm["slgs_window_policy_status"]).upper()
        except Exception as exc:
            print(f"[WARN] Could not parse {BENCHMARKS_PATH}: {exc}")

    start_dt = (datetime.date.today() - datetime.timedelta(days=CAL_DAYS)).isoformat()
    print(f"[DTS NOWCASTER v6.0] Fetching 7 DTS tables since {start_dt} ...")

    try:
        t1_rows = fetch_paginated("operating_cash_balance", start_dt)
        t2_rows = fetch_paginated("deposits_withdrawals_operating_cash", start_dt)
        t3a_rows = fetch_paginated("public_debt_transactions", start_dt)
        t3b_rows = fetch_paginated("adjustment_public_debt_transactions_cash_basis", start_dt)
        t3c_rows = fetch_paginated("debt_subject_to_limit", start_dt)
        t4_rows = fetch_paginated("inter_agency_tax_transfers", start_dt)
        t5_rows = fetch_paginated("income_tax_refunds_issued", start_dt)
    except Exception as exc:
        mark_fetch_failure_on_existing_json(exc)
        raise

    # ── Organize Table I (Operating Cash Balance) ──
    t1_by_date = {}
    for r in t1_rows:
        d = r.get("record_date")
        if not d:
            continue
        at = (r.get("account_type") or "").strip()
        val_today = parse_num(r.get("open_today_bal"))
        if val_today is None:
            val_today = parse_num(r.get("close_today_bal"))
        val_mtd = parse_num(r.get("open_month_bal"))
        val_fytd = parse_num(r.get("open_fiscal_year_bal"))

        rec = t1_by_date.setdefault(d, {})
        at_low = at.lower()
        if "opening balance" in at_low:
            rec["tga_open"] = val_today
            rec["tga_open_mtd"] = val_mtd
            rec["tga_open_fytd"] = val_fytd
        elif "closing balance" in at_low:
            rec["tga_close"] = val_today
        elif "deposits" in at_low:
            rec["tga_dep_t1"] = val_today
            rec["tga_dep_mtd_t1"] = val_mtd
            rec["tga_dep_fytd_t1"] = val_fytd
        elif "withdrawals" in at_low:
            rec["tga_wd_t1"] = val_today
            rec["tga_wd_mtd_t1"] = val_mtd
            rec["tga_wd_fytd_t1"] = val_fytd

    all_bd_dates = sorted(t1_by_date.keys())
    if not all_bd_dates:
        mark_fetch_failure_on_existing_json("No operating_cash_balance dates found")
        raise RuntimeError("No operating_cash_balance dates found!")

    asof = all_bd_dates[-1]
    endpoint_dates = {name: max((r.get("record_date", "") for r in rows), default=None)
                      for name, rows in (("I",t1_rows),("II",t2_rows),("IIIA",t3a_rows),
                                         ("IIIB",t3b_rows),("IIIC",t3c_rows),("IV",t4_rows),("V",t5_rows))}
    endpoints_complete = all(value == asof for value in endpoint_dates.values())
    print(f"[DTS NOWCASTER v6.0] Latest business date (asof): {asof} (total business days: {len(all_bd_dates)})")

    # ── Organize Table II (Deposits and Withdrawals of Operating Cash) ──
    t2_raw = {}
    seen_t2_lines = set()
    for r in t2_rows:
        d = r.get("record_date")
        if not d:
            continue
        side = normalize_side(r.get("transaction_type"))
        if side not in ("Deposits", "Withdrawals"):
            continue
        line_nbr = str(r.get("src_line_nbr") or "")
        catg = get_catg_label(r)
        desc = (r.get("transaction_catg_desc") or "").strip()
        dedup_key = (d, side, catg, desc, line_nbr)
        if dedup_key in seen_t2_lines:
            continue
        seen_t2_lines.add(dedup_key)

        today_v, mtd_v, fytd_v = get_row_amounts(r)
        key = (side, catg, desc)
        day_map = t2_raw.setdefault(d, {})
        if key not in day_map:
            day_map[key] = [today_v, mtd_v, fytd_v]
        else:
            for idx_v, v in enumerate((today_v, mtd_v, fytd_v)):
                if v is not None:
                    day_map[key][idx_v] = (day_map[key][idx_v] or 0.0) + v

    for i, d in enumerate(all_bd_dates):
        day_map = t2_raw.get(d, {})
        prev_d = all_bd_dates[i - 1] if i > 0 else None
        prev_map = t2_raw.get(prev_d, {}) if prev_d else {}
        same_month = (prev_d is not None) and (d[:7] == prev_d[:7])
        for key, vals in day_map.items():
            if vals[0] is None and vals[1] is not None:
                if not same_month:
                    vals[0] = vals[1]
                elif key in prev_map and prev_map[key][1] is not None:
                    vals[0] = vals[1] - prev_map[key][1]

    t2_canon = {
        "Deposits": {},
        "Withdrawals": {},
    }
    t2_op_sums = {}
    reversals_by_date = {}

    for d in all_bd_dates:
        day_map = t2_raw.get(d, {})
        rev_list = []
        op_dep_sum = 0.0
        op_wd_sum = 0.0
        for (side, catg, desc), (today_v, mtd_v, fytd_v) in day_map.items():
            catg_low = catg.lower()
            is_total_or_debt = (
                "total" in catg_low
                or "public debt" in catg_low
                or "sub-total" in catg_low
            )
            if not is_total_or_debt and today_v is not None:
                if side == "Deposits":
                    op_dep_sum += today_v
                elif side == "Withdrawals":
                    op_wd_sum += today_v
                if today_v < 0:
                    code = REVERSAL_SHORT_CODES.get(
                        catg,
                        re.sub(r"[^A-Z0-9]+", "_", catg.upper()).strip("_")[:18],
                    )
                    rev_list.append(f"{code}:{int(round(today_v))}")

            cids = match_canonical(side, catg, desc)
            for cid in cids:
                c_map = t2_canon[side].setdefault(cid, {})
                rec = c_map.setdefault(d, {"today": 0.0, "mtd": 0.0, "fytd": 0.0, "present": set()})
                if today_v is not None:
                    rec["today"] += today_v
                    rec["present"].add("today")
                if mtd_v is not None:
                    rec["mtd"] += mtd_v
                    rec["present"].add("mtd")
                if fytd_v is not None:
                    rec["fytd"] += fytd_v
                    rec["present"].add("fytd")
        t2_op_sums[d] = {"dep": op_dep_sum, "wd": op_wd_sum}
        reversals_by_date[d] = sorted(rev_list, reverse=True)

    # ── Organize Table IIIA (Public Debt Transactions) ──
    t3a_by_date = {}
    for r in t3a_rows:
        d = r.get("record_date")
        if not d:
            continue
        side = normalize_side(r.get("transaction_type"))
        sec_type_raw = r.get("security_type")
        sec_desc_raw = r.get("security_type_desc")
        sec_type = "" if not sec_type_raw or str(sec_type_raw).lower() == "null" else str(sec_type_raw).strip()
        sec_desc = "" if not sec_desc_raw or str(sec_desc_raw).lower() == "null" else str(sec_desc_raw).strip()
        sec_low = sec_type.lower()
        desc_low = sec_desc.lower()
        today_v, mtd_v, fytd_v = get_row_amounts(r)
        t_val = today_v or 0.0
        f_val = fytd_v or 0.0

        rec = t3a_by_date.setdefault(
            d,
            {
                "bills_reg_iss": 0.0,
                "cmb_iss": 0.0,
                "cmb_iss_fytd": 0.0,
                "bills_iss_total": 0.0,
                "bills_red_total": 0.0,
                "slgs_iss": 0.0,
                "slgs_red": 0.0,
                "gas_iss": 0.0,
                "gas_red": 0.0,
            },
        )
        if side == "Issues":
            if "regular series" in desc_low or "regular series" in sec_low:
                rec["bills_reg_iss"] += t_val
                rec["bills_iss_total"] += t_val
            elif "cash management" in desc_low or "cash management" in sec_low:
                rec["cmb_iss"] += t_val
                rec["cmb_iss_fytd"] += f_val
                rec["bills_iss_total"] += t_val
            elif sec_low == "bills":
                rec["bills_iss_total"] += t_val
            elif "state and local" in sec_low or "state and local" in desc_low:
                rec["slgs_iss"] += t_val
            elif "government account series" in sec_low or "government account series" in desc_low:
                rec["gas_iss"] += t_val
        elif side == "Redemptions":
            if sec_low == "bills" or "regular series" in desc_low or "cash management" in desc_low:
                rec["bills_red_total"] += t_val
            elif "state and local" in sec_low or "state and local" in desc_low:
                rec["slgs_red"] += t_val
            elif "government account series" in sec_low or "government account series" in desc_low:
                rec["gas_red"] += t_val

    # ── Organize Table IIIB (Adjustment of Public Debt Transactions to Cash Basis) ──
    t3b_by_date = {}
    for r in t3b_rows:
        d = r.get("record_date")
        if not d:
            continue
        side = normalize_side(r.get("transaction_type"))
        label = get_catg_label(r).lower()
        today_v, mtd_v, fytd_v = get_row_amounts(r)
        t_val = today_v or 0.0
        rec = t3b_by_date.setdefault(
            d,
            {
                "iiia_issues": 0.0,
                "issues_adj": 0.0,
                "iiia_redemp": 0.0,
                "redemp_adj": 0.0,
            },
        )
        if "total public debt cash issues" in label or (
            side == "Issues" and "deposited in tga" in label
        ):
            rec["cash_issues_today"] = today_v
            rec["cash_issues_mtd"] = mtd_v
            rec["cash_issues_fytd"] = fytd_v
        elif "total public debt cash redemptions" in label or (
            side == "Redemptions" and "withdrawn from tga" in label
        ):
            rec["cash_redemp_today"] = today_v
            rec["cash_redemp_mtd"] = mtd_v
            rec["cash_redemp_fytd"] = fytd_v
        elif side == "Issues":
            if "public debt issues (table iiia)" in label:
                rec["iiia_issues"] += t_val
            elif "premium" in label:
                rec["iiia_issues"] += t_val
            elif "(-)" in label or "discount" in label:
                rec["issues_adj"] += t_val
        elif side == "Redemptions":
            if "public debt redemptions (table iiia)" in label:
                rec["iiia_redemp"] += t_val
            elif "premium" in label:
                rec["iiia_redemp"] += t_val
            elif "(-)" in label or "discount" in label:
                rec["redemp_adj"] += t_val

    for d, rec in t3b_by_date.items():
        if rec["iiia_issues"] > 0:
            rec["cash_issues_calc"] = rec["iiia_issues"] - rec["issues_adj"]
        if rec["iiia_redemp"] > 0:
            rec["cash_redemp_calc"] = rec["iiia_redemp"] - rec["redemp_adj"]

    # ── Organize Table IIIC (Debt Subject to Limit) ──
    t3c_by_date = {}
    for r in t3c_rows:
        d = r.get("record_date")
        if not d:
            continue
        catg = (r.get("debt_catg") or "").strip()
        desc = (r.get("debt_catg_desc") or "").strip()
        catg_low = catg.lower()
        desc_low = desc.lower()
        val = parse_num(r.get("close_today_bal"))
        if val is None:
            val = parse_num(r.get("open_today_bal"))
        v_num = val or 0.0
        rec = t3c_by_date.setdefault(
            d,
            {
                "debt_public": 0.0,
                "debt_intra": 0.0,
                "debt_total": None,
                "not_subj_limit": 0.0,
                "other_subj_limit": 0.0,
                "debt_subj_limit": None,
                "stat_debt_limit": 0.0,
            },
        )
        if "debt held by the public" in catg_low:
            rec["debt_public"] = v_num
        elif "intragovernmental holdings" in catg_low:
            rec["debt_intra"] = v_num
        elif "total public debt outstanding" in catg_low:
            rec["debt_total"] = v_num
        elif "debt not subject to limit" in catg_low:
            rec["not_subj_limit"] += v_num
        elif "other debt subject to limit" in catg_low or "guaranteed debt" in desc_low:
            rec["other_subj_limit"] += v_num
        elif "total public debt subject to limit" in catg_low:
            rec["debt_subj_limit"] = v_num
        elif "statutory debt limit" in catg_low:
            rec["stat_debt_limit"] = v_num

    for d, rec in t3c_by_date.items():
        if rec["debt_total"] is None:
            rec["debt_total"] = rec["debt_public"] + rec["debt_intra"]
        if rec["debt_subj_limit"] is None:
            rec["debt_subj_limit"] = (
                rec["debt_total"] - rec["not_subj_limit"] + rec["other_subj_limit"]
            )

    # ── Organize Table IV (Inter-agency Tax Transfers — diagnostic, never summed into Table II) ──
    t4_by_date = {}
    for r in t4_rows:
        d = r.get("record_date")
        if not d:
            continue
        label = get_catg_label(r).lower()
        today_v, mtd_v, fytd_v = get_row_amounts(r)
        rec = t4_by_date.setdefault(d, {"withheld_today": 0.0, "withheld_mtd": 0.0, "withheld_fytd": 0.0})
        if "withheld individual" in label or "fica" in label:
            if today_v is not None:
                rec["withheld_today"] += today_v
            if mtd_v is not None:
                rec["withheld_mtd"] += mtd_v
            if fytd_v is not None:
                rec["withheld_fytd"] += fytd_v

    # ── Organize Table V (Income Tax Refunds Issued) ──
    t5_by_date = {}
    for r in t5_rows:
        d = r.get("record_date")
        if not d:
            continue
        label = get_catg_label(r).lower()
        today_v, mtd_v, fytd_v = get_row_amounts(r)
        t_v = today_v or 0.0
        f_v = fytd_v or 0.0
        rec = t5_by_date.setdefault(
            d,
            {
                "biz_checks_today": 0.0,
                "biz_checks_fytd": 0.0,
                "biz_eft_today": 0.0,
                "biz_eft_fytd": 0.0,
                "indiv_checks_today": 0.0,
                "indiv_checks_fytd": 0.0,
                "indiv_eft_today": 0.0,
                "indiv_eft_fytd": 0.0,
            },
        )
        if "business" in label:
            if "check" in label:
                rec["biz_checks_today"] += t_v
                rec["biz_checks_fytd"] += f_v
            elif "eft" in label:
                rec["biz_eft_today"] += t_v
                rec["biz_eft_fytd"] += f_v
        elif "individual" in label:
            if "check" in label:
                rec["indiv_checks_today"] += t_v
                rec["indiv_checks_fytd"] += f_v
            elif "eft" in label:
                rec["indiv_eft_today"] += t_v
                rec["indiv_eft_fytd"] += f_v

    def get_cval(side, cid, d, field="today"):
        return t2_canon.get(side, {}).get(cid, {}).get(d, {}).get(field, 0.0)

    def nullable_cval(side, cid, d, field="today"):
        rec = t2_canon.get(side, {}).get(cid, {}).get(d, {})
        return rec.get(field) if field in rec.get("present", set()) else None

    def has_cval(side, cid, d):
        return finite(nullable_cval(side, cid, d))

    (
        expected_sched_by_date,
        realized_sched_by_date,
        calendar_miss_by_date,
        calendar_warmup_by_date,
        active_events_by_date,
        tax_window_dates,
    ) = build_asymmetric_calendar_schedule(all_bd_dates, nullable_cval)

    # ── Build Daily Accounting Series & Distinct Out-of-Sample Robust Z-Scores ──
    daily_records = {}
    ntf_realized_resid_series = []
    ntf_ex_ante_surp_series = []
    z_ex_ante_series = []
    shock_day_flags = []

    for idx, d in enumerate(all_bd_dates):
        t1 = t1_by_date.get(d, {})
        t3b = t3b_by_date.get(d, {})

        tga_close = t1.get("tga_close")
        tga_open = t1.get("tga_open")
        if tga_open is None and idx > 0:
            tga_open = t1_by_date.get(all_bd_dates[idx - 1], {}).get("tga_close")

        D_raw = t1.get("tga_dep_t1")
        if D_raw is None and has_cval("Deposits", "TOTAL_TGA_DEPOSITS_T2", d):
            D_raw = get_cval("Deposits", "TOTAL_TGA_DEPOSITS_T2", d, "today")
        W_raw = t1.get("tga_wd_t1")
        if W_raw is None and has_cval("Withdrawals", "TOTAL_TGA_WITHDRAWALS_T2", d):
            W_raw = get_cval("Withdrawals", "TOTAL_TGA_WITHDRAWALS_T2", d, "today")

        I_raw = t3b.get("cash_issues_today")
        if I_raw is None and has_cval("Deposits", "PUBLIC_DEBT_CASH_ISSUES_T2", d):
            I_raw = get_cval("Deposits", "PUBLIC_DEBT_CASH_ISSUES_T2", d, "today")
        if I_raw is None:
            I_raw = t3b.get("cash_issues_calc")

        R_raw = t3b.get("cash_redemp_today")
        if R_raw is None and has_cval("Withdrawals", "PUBLIC_DEBT_CASH_REDEMP_T2", d):
            R_raw = get_cval("Withdrawals", "PUBLIC_DEBT_CASH_REDEMP_T2", d, "today")
        if R_raw is None:
            R_raw = t3b.get("cash_redemp_calc")

        i_calc = t3b.get("cash_issues_calc")
        r_calc = t3b.get("cash_redemp_calc")

        inputs_complete = bool(
            tga_close is not None
            and tga_open is not None
            and D_raw is not None
            and W_raw is not None
            and I_raw is not None
            and R_raw is not None
            and i_calc is not None
            and r_calc is not None
        )

        D = D_raw or 0.0
        W = W_raw or 0.0
        I = I_raw or 0.0
        R = R_raw or 0.0

        op_dep_t2 = get_cval("Deposits", "TOTAL_DEPOSITS_EX_DEBT", d, "today") or t2_op_sums.get(d, {}).get("dep", 0.0)
        op_wd_t2 = get_cval("Withdrawals", "TOTAL_WITHDRAWALS_EX_DEBT", d, "today") or t2_op_sums.get(d, {}).get("wd", 0.0)

        net_debt_cash_iiib = I - R
        ntf_total = (W - R) - (D - I)
        dtga = (tga_close - tga_open) if (tga_close is not None and tga_open is not None) else (D - W)
        reserves_impact = -dtga

        diff_tga = abs(dtga - (D - W))
        diff_bf = abs(dtga - (net_debt_cash_iiib - ntf_total))
        diff_iiib_i = abs(I - i_calc) if i_calc is not None else 999.0
        diff_iiib_r = abs(R - r_calc) if r_calc is not None else 999.0
        diff_op_dep = abs((D - I) - op_dep_t2)
        diff_op_wd = abs((W - R) - op_wd_t2)
        recon_diff = max(diff_tga, diff_bf, diff_iiib_i, diff_iiib_r)
        recon_op_diff = max(diff_op_dep, diff_op_wd)

        ntf_scheduled = realized_sched_by_date.get(d, 0.0)
        is_warmup = calendar_warmup_by_date.get(d, False)
        ntf_expected_cal = None if is_warmup else expected_sched_by_date.get(d, 0.0)
        ntf_residual_realized = ntf_total - ntf_scheduled
        ntf_ex_expected = None if ntf_expected_cal is None else (ntf_total - ntf_expected_cal)

        # Shock day filter for MAD denominator:
        # Only exclude statutory tax deadline windows or extreme corporate/SECA tax days (> $20,000M).
        # Do NOT exclude Tuesday business refunds (which are now in `continuous_specs` weekday baseline)!
        corp_d = get_cval("Deposits", "CORP_INCOME", d, "today")
        nonw_d = get_cval("Deposits", "NON_WITHHELD_SECA", d, "today")
        is_shock = (d in tax_window_dates) or (corp_d + nonw_d > 20000.0)

        ntf_realized_resid_series.append(ntf_residual_realized if inputs_complete and recon_diff <= 5 and recon_op_diff <= 15 else None)
        ntf_ex_ante_surp_series.append(ntf_ex_expected if inputs_complete and recon_diff <= 5 and recon_op_diff <= 15 else None)
        shock_day_flags.append(is_shock)

        z_ex_ante_wd, floor_ex_ante, n_ex_ante, fb_ex_ante = robust_zscore_weekday_out_of_sample(
            ntf_ex_ante_surp_series, all_bd_dates, shock_day_flags, idx, lookback_bd=100, mad_floor=MAD_FLOOR_MUSD
        )
        z_realized_wd, floor_realized, n_realized, fb_realized = robust_zscore_weekday_out_of_sample(
            ntf_realized_resid_series, all_bd_dates, shock_day_flags, idx, lookback_bd=100, mad_floor=MAD_FLOOR_MUSD
        )
        z_uncond_60d, _, n_uncond = robust_zscore_out_of_sample(
            ntf_realized_resid_series, shock_day_flags, idx, window=60, mad_floor=MAD_FLOOR_MUSD
        )

        z_ex_ante_series.append(z_ex_ante_wd)
        z_pctile_250d = rolling_empirical_percentile(z_ex_ante_series, idx, window=250)

        daily_records[d] = {
            "tga_close": round(tga_close or 0.0),
            "tga_open": round(tga_open or 0.0),
            "dtga": round(dtga),
            "reserves_impact": round(reserves_impact),
            "D": round(D),
            "W": round(W),
            "I": round(I),
            "R": round(R),
            "op_dep": round(D - I),
            "op_wd": round(W - R),
            "net_debt_cash_iiib": round(net_debt_cash_iiib),
            "ntf_total": round(ntf_total),
            "ntf_scheduled": round(ntf_scheduled),
            "ntf_expected_cal": round(ntf_expected_cal) if ntf_expected_cal is not None else None,
            "ntf_residual_realized_cal": round(ntf_residual_realized),
            "ntf_ex_expected": round(ntf_ex_expected) if ntf_ex_expected is not None else None,
            "z_ntf_ex_exp_weekday_100bd": z_ex_ante_wd,
            "z_ex_ante_pctile_250d": z_pctile_250d,
            "z_ntf_realized_weekday_100bd": z_realized_wd,
            "z_ntf_uncond_60d": z_uncond_60d,
            "z_sample_n": n_ex_ante,
            "z_fallback_used": fb_ex_ante,
            "mad_floor_hit": bool(floor_ex_ante or floor_realized),
            "calendar_miss": calendar_miss_by_date.get(d, False),
            "calendar_warmup": is_warmup,
            "inputs_complete": inputs_complete,
            "recon_diff": round(recon_diff),
            "recon_op_diff": round(recon_op_diff),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 4. LAG 364 ENGINE WITH COVERAGE VALIDATION (>=85% MATCHED PAIRS REQUIRED)
    # ─────────────────────────────────────────────────────────────────────────
    bd_index = {d: i for i, d in enumerate(all_bd_dates)}
    bd_set = set(all_bd_dates)
    min_bd, max_bd = all_bd_dates[0], all_bd_dates[-1]

    def get_daily_flow_fn(flow_fn):
        return {d: flow_fn(d) for d in all_bd_dates}

    def compute_lag364_window_stats(flow_by_date, end_idx, window_bd=20):
        return lag364_stats(flow_by_date, all_bd_dates, end_idx, window_bd)

    def find_yoy_anchor_date(d_str):
        dt = datetime.date.fromisoformat(d_str)
        try:
            same_cal = dt.replace(year=dt.year - 1)
        except ValueError:
            same_cal = dt.replace(year=dt.year - 1, day=28)

        for delta in range(0, -7, -1):
            cand = (same_cal + datetime.timedelta(days=delta)).isoformat()
            if cand in bd_index:
                return cand
        for delta in range(1, 7):
            cand = (same_cal + datetime.timedelta(days=delta)).isoformat()
            if cand in bd_index:
                return cand
        lag364 = (dt - datetime.timedelta(days=364)).isoformat()
        return lag364 if lag364 in bd_index else None

    yoy_anchor = find_yoy_anchor_date(asof)
    last_idx = len(all_bd_dates) - 1
    print(f"[DTS NOWCASTER v6.0] FYTD YoY anchor date for {asof}: {yoy_anchor}")

    fy_cur = fiscal_year_for_date(asof)
    bd_fy = sum(1 for d in all_bd_dates if fiscal_year_for_date(d) == fy_cur and d <= asof)
    fy_prev = fiscal_year_for_date(yoy_anchor) if yoy_anchor else (fy_cur - 1)
    bd_fy_prev = (
        sum(1 for d in all_bd_dates if fiscal_year_for_date(d) == fy_prev and d <= yoy_anchor)
        if yoy_anchor
        else None
    )
    bd_skew_fytd = (bd_fy - bd_fy_prev) if bd_fy_prev is not None else None

    def pct_yoy(cur_val, prev_val):
        if cur_val is None or prev_val is None or abs(prev_val) < 1e-6:
            return None
        return round(((cur_val / prev_val) - 1.0) * 100.0, 2)

    def pct_yoy_per_bd(cur_val, prev_val):
        if (
            cur_val is None
            or prev_val is None
            or abs(prev_val) < 1e-6
            or not bd_fy
            or not bd_fy_prev
        ):
            return None
        cur_rate = cur_val / bd_fy
        prev_rate = prev_val / bd_fy_prev
        return round(((cur_rate / prev_rate) - 1.0) * 100.0, 2)

    # ─────────────────────────────────────────────────────────────────────────
    # 5. DATA QUALITY (dq): SEPARATE HARD `block` FROM `warn` (Perplexity #5)
    # ─────────────────────────────────────────────────────────────────────────
    asof_rec = daily_records[asof]
    now_utc_dt = datetime.datetime.now(datetime.timezone.utc)
    now_utc = now_utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    exp_asof, valid_until_utc = expected_latest_bd_and_validity(now_utc_dt)
    is_stale = bool(asof < exp_asof)

    critical_fytd = {
        "WITHHELD_FICA": finite(nullable_cval("Deposits", "WITHHELD_FICA", asof, "fytd")),
        "CORP_INCOME": finite(nullable_cval("Deposits", "CORP_INCOME", asof, "fytd")),
        "CUSTOMS_DUTIES": finite(nullable_cval("Deposits", "CUSTOMS_DUTIES", asof, "fytd")),
        "SSA_BENEFITS": finite(nullable_cval("Withdrawals", "SSA_BENEFITS", asof, "fytd")),
        "TREAS_INTEREST": finite(nullable_cval("Withdrawals", "TREAS_INTEREST", asof, "fytd")),
    }
    critical_series_ok = all(critical_fytd.values())

    ahe_age_days = None
    if ahe_release_date:
        try:
            ahe_age_days = (datetime.date.fromisoformat(asof) - datetime.date.fromisoformat(ahe_release_date)).days
        except Exception:
            ahe_age_days = None
    ahe_stale = bool(ahe_age_days is None or ahe_age_days > 35)

    unclass_wd_today = get_cval("Withdrawals", "UNCLASSIFIED_WD", asof, "today")
    op_wd_today = max(1.0, float(asof_rec["op_wd"]))
    unclass_wd_pct = round((unclass_wd_today / op_wd_today) * 100.0, 2)
    recon_diff_musd = int(asof_rec["recon_diff"])
    recon_op_diff_musd = int(asof_rec["recon_op_diff"])
    recon_ok = bool(
        asof_rec["inputs_complete"]
        and recon_diff_musd <= 5
        and recon_op_diff_musd <= 15
        and critical_series_ok
    )
    # Hard block only on accounting breach, missing critical inputs, staleness, or >15% unclassified
    dq_block = bool(not recon_ok or not endpoints_complete or unclass_wd_pct > 15.0 or is_stale)
    # Warning flag on single-event calendar_miss, warmup, or AHE benchmark age > 35d
    dq_warn = bool(asof_rec["calendar_miss"] or asof_rec["calendar_warmup"] or ahe_stale)

    def overlaps_shutdown_2025(start_d, end_d):
        if not start_d or not end_d:
            return False
        return not (end_d < "2025-10-01" or start_d > "2025-11-15")

    base_is_shutdown_2025 = bool(
        yoy_anchor and ("2025-10-01" <= yoy_anchor <= "2025-12-15")
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 6. COMPUTE THE 4 INSTITUTIONAL NOWCAST CARDS
    # ─────────────────────────────────────────────────────────────────────────

    # ── CARD 1: nfp_wage_bill (Empleo y Masa Salarial — Ficha B2) ──
    withheld_t2_daily = get_daily_flow_fn(lambda d: nullable_cval("Deposits", "WITHHELD_FICA", d, "today"))

    norm_w_20d, raw_w_20d, hol_skew_20d, _, _, min_p20, max_p20, pairs_20d = compute_lag364_window_stats(
        withheld_t2_daily, last_idx, 20
    )
    norm_w_60d, raw_w_60d, hol_skew_60d, _, _, min_p60, max_p60, pairs_60d = compute_lag364_window_stats(
        withheld_t2_daily, last_idx, 60
    )
    norm_w_prev40d, raw_w_prev40d, _, _, _, min_p40, max_p40, _ = compute_lag364_window_stats(
        withheld_t2_daily, max(0, last_idx - 20), 40
    )

    withheld_t2_20d_yoy = raw_w_20d
    withheld_t2_20d_norm_yoy = norm_w_20d
    withheld_t2_60d_yoy = raw_w_60d

    withheld_t2_fytd_cur = get_cval("Deposits", "WITHHELD_FICA", asof, "fytd")
    withheld_t2_fytd_prev = get_cval("Deposits", "WITHHELD_FICA", yoy_anchor, "fytd") if yoy_anchor else None
    withheld_t2_fytd_yoy = pct_yoy(withheld_t2_fytd_cur, withheld_t2_fytd_prev)
    withheld_t2_fytd_per_bd_yoy = pct_yoy_per_bd(withheld_t2_fytd_cur, withheld_t2_fytd_prev)

    withheld_t4_fytd_cur = t4_by_date.get(asof, {}).get("withheld_fytd", 0.0)

    if (
        withheld_t2_20d_yoy is not None
        and ahe_deflator_yoy is not None
        and ahe_vintage is not None
        and not ahe_stale
    ):
        raw_less_ahe_pp = round(withheld_t2_20d_yoy - ahe_deflator_yoy, 2)
        raw_emp_hours_proxy = round(
            (((1.0 + (withheld_t2_20d_norm_yoy or withheld_t2_20d_yoy) / 100.0) / (1.0 + ahe_deflator_yoy / 100.0)) - 1.0)
            * 100.0,
            2,
        )
    else:
        raw_less_ahe_pp = None
        raw_emp_hours_proxy = None

    proxy_implausible = bool(raw_emp_hours_proxy is not None and abs(raw_emp_hours_proxy) > 2.5)
    w20_overlaps_shutdown = overlaps_shutdown_2025(min_p20, max_p20) or base_is_shutdown_2025
    w20_overlaps_obbba = bool(min_p20 and min_p20 < "2025-10-01")

    impulse_non_overlap_40d = (
        round(withheld_t2_20d_norm_yoy - (norm_w_prev40d if norm_w_prev40d is not None else withheld_t2_60d_yoy), 2)
        if (withheld_t2_20d_norm_yoy is not None and (norm_w_prev40d is not None or withheld_t2_60d_yoy is not None))
        else None
    )

    nfp_flags = []
    if w20_overlaps_shutdown:
        nfp_flags.append("base_shutdown_2025_fedsal_distortion")
    if w20_overlaps_obbba:
        nfp_flags.append("obbba_withholding_regime_2025_09")
    if proxy_implausible:
        nfp_flags.append("proxy_spread_exceeds_2.5pct_band")
    if ahe_stale:
        nfp_flags.append(f"ahe_vintage_stale_{ahe_age_days}d")
    if not (consensus_loaded and nfp_consensus_k is not None and nfp_model_calibrated):
        nfp_flags.append("no_calibrated_consensus_info_only")

    # Card 1 (`nfp_wage_bill`) remains strictly `INFO_ONLY` with `dir: null` and `surprise_bias: "NOT_ESTIMATED"`
    # while displaying descriptive nominal cash withholding growth (`withheld_t2_20d_norm_yoy`, `withheld_t2_fytd_per_bd_yoy`)
    # so the card is informative without ever triggering an uncalibrated directional trade (Codeword & Cursor).
    if dq_block:
        nfp_state = "BLOCKED"
        nfp_dir = None
        nfp_surprise_bias = "BLOCKED_BY_DQ"
    else:
        nfp_state = "INFO_ONLY"
        nfp_dir = None
        nfp_surprise_bias = "NOT_ESTIMATED"

    # ── CARD 2: retail_household (Impulso al Consumo vs Estrés Social) ──
    t5_cur = t5_by_date.get(asof, {})
    t5_prev = t5_by_date.get(yoy_anchor, {}) if yoy_anchor else {}

    # Strict Table V comparability (ChatGPT #5: never fall back from Table V EFT+Checks to Table II EFT-only!)
    has_t5_cur = (asof in t5_by_date) and (
        (t5_cur.get("indiv_eft_fytd", 0.0) + t5_cur.get("indiv_checks_fytd", 0.0)) > 0
    )
    has_t5_prev = bool(
        yoy_anchor
        and (yoy_anchor in t5_by_date)
        and ((t5_prev.get("indiv_eft_fytd", 0.0) + t5_prev.get("indiv_checks_fytd", 0.0)) > 0)
    )
    indiv_refunds_fytd_cur = (
        (t5_cur.get("indiv_eft_fytd", 0.0) + t5_cur.get("indiv_checks_fytd", 0.0))
        if has_t5_cur
        else None
    )
    indiv_refunds_fytd_prev = (
        (t5_prev.get("indiv_eft_fytd", 0.0) + t5_prev.get("indiv_checks_fytd", 0.0))
        if has_t5_prev
        else None
    )

    indiv_refunds_total_fytd_yoy = pct_yoy(indiv_refunds_fytd_cur, indiv_refunds_fytd_prev)
    indiv_refunds_eft_only_yoy = pct_yoy(
        t5_cur.get("indiv_eft_fytd") if has_t5_cur else None,
        t5_prev.get("indiv_eft_fytd") if has_t5_prev else None,
    )

    snap_fytd_cur = get_cval("Withdrawals", "USDA_SNAP", asof, "fytd")
    snap_fytd_prev = get_cval("Withdrawals", "USDA_SNAP", yoy_anchor, "fytd") if yoy_anchor else None
    snap_fytd_raw_yoy = pct_yoy(snap_fytd_cur, snap_fytd_prev)

    asof_dt = datetime.date.fromisoformat(asof)
    in_refund_season = (
        (asof_dt.month == 1 and asof_dt.day >= 15)
        or (asof_dt.month in (2, 3, 4))
        or (asof_dt.month == 5 and asof_dt.day <= 15)
    )

    retail_flags = []
    if in_refund_season:
        retail_flags.append("refund_season_active")
    else:
        retail_flags.append("out_of_refund_season")
    if (
        indiv_refunds_eft_only_yoy is not None
        and indiv_refunds_total_fytd_yoy is not None
        and abs(indiv_refunds_eft_only_yoy - indiv_refunds_total_fytd_yoy) > 10.0
    ):
        retail_flags.append("irs_check_to_eft_shift_active")
    if base_is_shutdown_2025:
        retail_flags.append("base_shutdown_2025_distorts_snap_and_fedsal")

    # Keep `retail_household` descriptive (`INFO_ONLY` in season, `DORMANT` out of season, `dir: null`)
    # until a calibrated Retail Sales model is attached (ChatGPT #5 & Cursor).
    if dq_block:
        retail_state = "BLOCKED"
        retail_dir = None
    elif not in_refund_season:
        retail_state = "DORMANT"
        retail_dir = None
    else:
        retail_state = "INFO_ONLY"
        retail_dir = None

    # ── CARD 3: corp_and_tariffs (Caja Corporativa y Aranceles EA-1) ──
    corp_fytd_cur = get_cval("Deposits", "CORP_INCOME", asof, "fytd")
    corp_fytd_prev = get_cval("Deposits", "CORP_INCOME", yoy_anchor, "fytd") if yoy_anchor else None
    corp_tax_fytd_yoy = pct_yoy(corp_fytd_cur, corp_fytd_prev)

    non_withheld_fytd_cur = get_cval("Deposits", "NON_WITHHELD_SECA", asof, "fytd")
    non_withheld_fytd_prev = get_cval("Deposits", "NON_WITHHELD_SECA", yoy_anchor, "fytd") if yoy_anchor else None
    non_withheld_fytd_yoy = pct_yoy(non_withheld_fytd_cur, non_withheld_fytd_prev)

    biz_refund_today_musd = round(
        t5_cur.get("biz_eft_today", 0.0) + t5_cur.get("biz_checks_today", 0.0)
    )

    biz_ref_hist = sorted(
        (t5_by_date.get(d, {}).get("biz_eft_today", 0.0) + t5_by_date.get(d, {}).get("biz_checks_today", 0.0))
        for d in all_bd_dates
    )
    p95_idx = min(len(biz_ref_hist) - 1, int(0.95 * len(biz_ref_hist)))
    biz_refund_p95_musd = round(biz_ref_hist[p95_idx]) if biz_ref_hist else 1000

    customs_fytd_cur = get_cval("Deposits", "CUSTOMS_DUTIES", asof, "fytd")
    customs_fytd_prev = get_cval("Deposits", "CUSTOMS_DUTIES", yoy_anchor, "fytd") if yoy_anchor else None
    customs_fytd_raw_spliced_yoy = pct_yoy(customs_fytd_cur, customs_fytd_prev)

    customs_daily = get_daily_flow_fn(lambda d: get_cval("Deposits", "CUSTOMS_DUTIES", d, "today"))
    customs_20d_norm_yoy, _, _, _, _, min_c20_prev, _, _ = compute_lag364_window_stats(customs_daily, last_idx, 20)

    in_corp_tax_window = False
    corp_window_yoy = None
    if asof_dt.month in (1, 3, 4, 6, 9, 10, 12):
        stat_15_cur = settle_date(
            datetime.date(asof_dt.year, asof_dt.month, 15), bd_set, min_bd, max_bd, "FOLLOWING"
        )
        if stat_15_cur and stat_15_cur in bd_index:
            s_idx = bd_index[stat_15_cur]
            w_start = max(0, s_idx - 1)
            w_end = min(len(all_bd_dates) - 1, s_idx + 3)
            if w_start <= last_idx <= w_end:
                in_corp_tax_window = True
                cur_win_dates = all_bd_dates[w_start : last_idx + 1]
                offset_len = len(cur_win_dates)
                stat_15_prev = settle_date(
                    datetime.date(asof_dt.year - 1, asof_dt.month, 15), bd_set, min_bd, max_bd, "FOLLOWING"
                )
                if stat_15_prev and stat_15_prev in bd_index:
                    p_idx = bd_index[stat_15_prev]
                    pw_start = max(0, p_idx - 1)
                    prev_win_dates = all_bd_dates[pw_start : pw_start + offset_len]
                    cur_w_sum = sum(
                        get_cval("Deposits", "CORP_INCOME", d, "today")
                        + get_cval("Deposits", "NON_WITHHELD_SECA", d, "today")
                        for d in cur_win_dates
                    )
                    prev_w_sum = sum(
                        get_cval("Deposits", "CORP_INCOME", d, "today")
                        + get_cval("Deposits", "NON_WITHHELD_SECA", d, "today")
                        for d in prev_win_dates
                    )
                    corp_window_yoy = pct_yoy(cur_w_sum, prev_w_sum)

    customs_20d_clean = bool(min_c20_prev and min_c20_prev >= SERIES_SPLICE_META["CUSTOMS_DUTIES"]["splice_date"])
    customs_fytd_clean = bool(asof >= SERIES_SPLICE_META["CUSTOMS_DUTIES"]["clean_fytd_yoy_from"])
    customs_splice_active = not (customs_20d_clean and customs_fytd_clean)

    corp_flags = []
    if not in_corp_tax_window:
        corp_flags.append("outside_15th_tax_window")
    else:
        corp_flags.append("active_15th_tax_window")

    if biz_refund_today_musd >= max(1000, biz_refund_p95_musd):
        corp_flags.append("biz_refund_shock_today")

    if not customs_fytd_clean:
        corp_flags.append("series_splice_2025_11_10_fytd_suspended")

    if dq_block:
        corp_state, corp_dir = "BLOCKED", None
    elif in_corp_tax_window:
        corp_state, corp_dir = "INFO_ONLY", None
    else:
        corp_state, corp_dir = "DORMANT", None

    # ── CARD 4: mmt_liquidity (Liquidez Diaria del Tesoro, Strip de Calendario y Techo de Deuda) ──
    t3a_asof = t3a_by_date.get(asof, {})
    t3c_asof = t3c_by_date.get(asof, {})

    bills_net_iiia = round(
        t3a_asof.get("bills_iss_total", 0.0) - t3a_asof.get("bills_red_total", 0.0)
    )
    cmb_today = round(t3a_asof.get("cmb_iss", 0.0))
    slgs_issues_today_musd = round(t3a_asof.get("slgs_iss", 0.0))
    slgs_issues_5d_musd = round(
        sum(t3a_by_date.get(d, {}).get("slgs_iss", 0.0) for d in all_bd_dates[-5:])
    )
    if slgs_window_policy_status == "OPEN":
        slgs_open = True
    elif slgs_window_policy_status == "CLOSED":
        slgs_open = False
    else:
        slgs_open = None

    policy_asof = bm.get("slgs_policy_asof") if BENCHMARKS_PATH.exists() else None
    try:
        policy_age = (asof_dt - datetime.date.fromisoformat(policy_asof)).days
    except (ValueError, TypeError):
        policy_age = 999
    if not 0 <= policy_age <= 3:
        slgs_window_policy_status, slgs_open = "UNKNOWN", None
    stat_limit = t3c_asof.get("stat_debt_limit") or 0.0
    subj_limit = t3c_asof.get("debt_subj_limit") or 0.0
    debt_headroom_iiic = round(stat_limit - subj_limit) if stat_limit > 0 else None

    interest_today = round(get_cval("Withdrawals", "TREAS_INTEREST", asof, "today"))
    interest_mtd = round(get_cval("Withdrawals", "TREAS_INTEREST", asof, "mtd"))
    interest_fytd = round(get_cval("Withdrawals", "TREAS_INTEREST", asof, "fytd"))

    # Govern funding_state strictly by Ex-Ante Weekday-Conditioned Z-score AND Empirical 250d Percentile
    # (Perplexity #1 & ChatGPT #2: requires |z| >= 3.0 AND two-sided 5% empirical tail pctile <= 2.5 or >= 97.5)
    z_gov = asof_rec["z_ntf_ex_exp_weekday_100bd"]
    z_pct = asof_rec["z_ex_ante_pctile_250d"]
    if dq_block:
        funding_state = "BLOCKED"
    elif z_gov is None or z_pct is None or asof_rec["calendar_warmup"] or asof_rec["calendar_miss"]:
        funding_state = "WARMUP_NOT_ESTIMATED"
    elif (z_gov >= 3.0 and z_pct >= 97.5) or (z_gov <= -3.0 and z_pct <= 2.5):
        funding_state = "SURPRISE_INJECTION" if z_gov > 0 else "SURPRISE_DRAIN"
    else:
        funding_state = "INLINE_CALENDAR"

    ssa_today = get_cval("Withdrawals", "SSA_BENEFITS", asof, "today")
    biz_shock = biz_refund_today_musd >= max(1000, biz_refund_p95_musd)
    if ssa_today > 10000 and abs(bills_net_iiia) > 10000:
        base_drv = "ssa_day3_and_bills" if asof_dt.day <= 5 else "ssa_wed_and_bills"
        funding_driver = f"{base_drv}_plus_biz_refund_shock" if biz_shock else base_drv
    elif biz_shock:
        funding_driver = "biz_refund_shock"
    elif abs(bills_net_iiia) > 20000:
        funding_driver = "bills_settlement"
    elif interest_today > 10000:
        funding_driver = "coupon_interest_payment"
    else:
        funding_driver = "regular_operations"

    z_method_gov = (
        "unconditional_mad_60bd_fallback"
        if asof_rec["z_fallback_used"]
        else "ex_ante_weekday_mad_100bd"
    )

    nowcast_payload = {
        "v": "dts-g8-6.0",
        "asof": asof,
        "expected_asof": exp_asof,
        "valid_until_utc": valid_until_utc,
        "generated_at": now_utc,
        "fy": fy_cur,
        "bd_fy": bd_fy,
        "bd_fy_prev": bd_fy_prev,
        "bd_skew_fytd": bd_skew_fytd,
        "sign_convention": "ntf>0 = net_fiscal_injection_nfa; tga_reserve_drain = -dtga",
        "dq": {
            "status": "OK" if (recon_ok and not is_stale) else ("STALE" if is_stale else "BREACH"),
            "stale": is_stale,
            "recon_ok": recon_ok,
            "inputs_complete": asof_rec["inputs_complete"],
            "endpoint_dates": endpoint_dates,
            "endpoints_complete": endpoints_complete,
            "critical_series_ok": critical_series_ok,
            "recon_diff_musd": recon_diff_musd,
            "recon_op_diff_musd": recon_op_diff_musd,
            "calendar_miss": asof_rec["calendar_miss"],
            "calendar_warmup": asof_rec["calendar_warmup"],
            "mad_floor_hit": asof_rec["mad_floor_hit"],
            "holiday_skew_20d_bd": hol_skew_20d,
            "bd_skew_fytd": bd_skew_fytd,
            "ahe_age_days": ahe_age_days,
            "ahe_stale": ahe_stale,
            "series_splice_customs": customs_splice_active,
            "reversals": reversals_by_date.get(asof, []),
            "unclass_wd_pct": unclass_wd_pct,
            "warn": dq_warn,
            "block": dq_block,
        },
        "mmt_liquidity": {
            "tga_close": asof_rec["tga_close"],
            "tga_open": asof_rec["tga_open"],
            "dtga": asof_rec["dtga"],
            "reserves_impact": asof_rec["reserves_impact"],
            "tga_reserve_drain_musd": asof_rec["reserves_impact"],
            "ntf_total": asof_rec["ntf_total"],
            "ntf_scheduled": asof_rec["ntf_scheduled"],
            "ntf_expected_cal": asof_rec["ntf_expected_cal"],
            "ntf_residual_realized_cal": asof_rec["ntf_residual_realized_cal"],
            "ntf_ex_expected": asof_rec["ntf_ex_expected"],
            "z_method_governor": z_method_gov,
            "z_fallback_used": asof_rec["z_fallback_used"],
            "z_sample_n": asof_rec["z_sample_n"],
            "z_ntf_ex_exp_weekday_100bd": asof_rec["z_ntf_ex_exp_weekday_100bd"],
            "z_ex_ante_pctile_250d": asof_rec["z_ex_ante_pctile_250d"],
            "z_ntf_realized_weekday_100bd": asof_rec["z_ntf_realized_weekday_100bd"],
            "z_ntf_uncond_60d": asof_rec["z_ntf_uncond_60d"],
            "net_debt_cash_iiib": asof_rec["net_debt_cash_iiib"],
            "bills_net_iiia": bills_net_iiia,
            "interest_today": interest_today,
            "interest_mtd": interest_mtd,
            "interest_fytd": interest_fytd,
            "cmb_today": cmb_today,
            "debt_headroom_iiic": debt_headroom_iiic,
            "slgs_issues_today_musd": slgs_issues_today_musd,
            "slgs_issues_5d_musd": slgs_issues_5d_musd,
            "slgs_window_policy_status": slgs_window_policy_status,
            "slgs_policy_asof": policy_asof,
            "slgs_open": slgs_open,
            "funding_state": funding_state,
            "funding_driver": funding_driver,
        },
        "nowcast_cards": {
            "nfp_wage_bill": {
                "state": nfp_state,
                "dir": nfp_dir,
                "surprise_bias": nfp_surprise_bias,
                "matched_pairs_20d": pairs_20d,
                "withheld_t2_20d_norm_yoy": withheld_t2_20d_norm_yoy,
                "withheld_t2_fytd_per_bd_yoy": withheld_t2_fytd_per_bd_yoy,
                "withheld_t4_fytd_musd": round(withheld_t4_fytd_cur),
                "ahe_deflator_yoy": round(ahe_deflator_yoy, 2) if ahe_deflator_yoy is not None else None,
                "ahe_vintage": ahe_vintage,
                "withholding_less_ahe_pp": None if (proxy_implausible or w20_overlaps_shutdown or ahe_stale) else raw_less_ahe_pp,
                "emp_hours_proxy_yoy": None if (proxy_implausible or w20_overlaps_shutdown or ahe_stale) else raw_emp_hours_proxy,
                "impulse_non_overlap_40d": None if w20_overlaps_shutdown else impulse_non_overlap_40d,
                "flags": nfp_flags,
            },
            "retail_household": {
                "state": retail_state,
                "dir": retail_dir,
                "indiv_refunds_fytd_musd": round(indiv_refunds_fytd_cur) if indiv_refunds_fytd_cur is not None else None,
                "indiv_refunds_total_fytd_yoy": indiv_refunds_total_fytd_yoy if in_refund_season else None,
                "snap_fytd_yoy": None if (not in_refund_season or base_is_shutdown_2025) else snap_fytd_raw_yoy,
                "flags": retail_flags,
            },
            "corp_and_tariffs": {
                "state": corp_state,
                "dir": corp_dir,
                "corp_window_yoy": corp_window_yoy if in_corp_tax_window else None,
                "corp_tax_fytd_yoy": corp_tax_fytd_yoy if in_corp_tax_window else None,
                "non_withheld_fytd_yoy": non_withheld_fytd_yoy if in_corp_tax_window else None,
                "biz_refund_today_musd": biz_refund_today_musd,
                "biz_refund_p95_musd": biz_refund_p95_musd,
                "customs_fytd_musd": round(customs_fytd_cur),
                "customs_20d_yoy": customs_20d_norm_yoy if customs_20d_clean else None,
                "customs_fytd_yoy": customs_fytd_raw_spliced_yoy if customs_fytd_clean else None,
                "customs_yoy_basis": "clean" if customs_fytd_clean else "spliced_suspended",
                "customs_20d_clean_after": SERIES_SPLICE_META["CUSTOMS_DUTIES"]["clean_20d_yoy_from"],
                "customs_fytd_clean_after": SERIES_SPLICE_META["CUSTOMS_DUTIES"]["clean_fytd_yoy_from"],
                "flags": corp_flags,
            },
        },
    }

    nowcast_payload = cash_contract(nowcast_payload, now_utc_dt)
    atomic_json(NOWCAST_PATH, nowcast_payload)
    print(f"[DTS NOWCASTER v6.0] Wrote {NOWCAST_PATH} ({NOWCAST_PATH.stat().st_size} bytes)")

    atomic_json(DATA_DIR / "treasury_book.json", build_book(t1_by_date, t2_canon, t3b_by_date, daily_records, nowcast_payload, t3c_by_date), compact=True)

    hist_dates = all_bd_dates[-HISTORY_BD_LIMIT:]
    history_rows = []
    for d in hist_dates:
        rec = daily_records[d]
        t3c_d = t3c_by_date.get(d, {})
        history_rows.append(
            {
                "d": d,
                "tga": rec["tga_close"],
                "dtga": rec["dtga"],
                "res_imp": rec["reserves_impact"],
                "D": rec["D"],
                "W": rec["W"],
                "I": rec["I"],
                "R": rec["R"],
                "op_dep": rec["op_dep"],
                "op_wd": rec["op_wd"],
                "ntf": rec["ntf_total"],
                "ntf_sched": rec["ntf_scheduled"],
                "ntf_exp": rec["ntf_expected_cal"],
                "ntf_surp": rec["ntf_residual_realized_cal"],
                "ntf_ex_exp": rec["ntf_ex_expected"],
                "z_exp_wd": rec["z_ntf_ex_exp_weekday_100bd"],
                "z_pctile": rec["z_ex_ante_pctile_250d"],
                "z_surp": rec["z_ntf_realized_weekday_100bd"],
                "z_uncond": rec["z_ntf_uncond_60d"],
                "debt_iiib": rec["net_debt_cash_iiib"],
                "headroom": round(
                    (t3c_d.get("stat_debt_limit") or 0.0) - (t3c_d.get("debt_subj_limit") or 0.0)
                )
                if (t3c_d.get("stat_debt_limit") or 0.0) > 0
                else None,
                "withheld_t2": round(get_cval("Deposits", "WITHHELD_FICA", d, "today")),
                "withheld_t4": round(t4_by_date.get(d, {}).get("withheld_today", 0.0)),
                "corp_tax": round(get_cval("Deposits", "CORP_INCOME", d, "today")),
                "non_withheld": round(get_cval("Deposits", "NON_WITHHELD_SECA", d, "today")),
                "customs": round(get_cval("Deposits", "CUSTOMS_DUTIES", d, "today")),
                "dol_ub": round(get_cval("Withdrawals", "DOL_UNEMP_BEN", d, "today")),
                "snap": round(get_cval("Withdrawals", "USDA_SNAP", d, "today")),
                "ssa": round(get_cval("Withdrawals", "SSA_BENEFITS", d, "today")),
                "interest": round(get_cval("Withdrawals", "TREAS_INTEREST", d, "today")),
            }
        )

    history_payload = {
        "v": "dts-g8-history-5.0",
        "asof": asof,
        "generated_at": now_utc,
        "count": len(history_rows),
        "series": history_rows,
    }
    atomic_json(HISTORY_PATH, history_payload, compact=True)
    print(f"[DTS NOWCASTER v6.0] Wrote {HISTORY_PATH} ({HISTORY_PATH.stat().st_size} bytes, {len(history_rows)} business days)")


if __name__ == "__main__":
    main()

