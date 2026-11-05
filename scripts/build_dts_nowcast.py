#!/usr/bin/env python3
"""
DTS Fiscal Nowcaster & MMT Liquidity Engine (v3.0 — dts-g8-3.0)
Institutional serverless pipeline for `dts-tracker` & `ARGOS`.
Incorporates Round-2 6-AI Red-Team Triangulation fixes:
  1. Event-date-only asymmetric settlement calendar (PRECEDING vs FOLLOWING, DFAS MIL_RET=PRECEDING,
     Medicare Part D capitated Day-1 only, scheduled tax-deadline inflows EST_TAX_15) with strict
     >=3-prior-realization warm-up (zero look-ahead bias; never sets expected = observed).
  2. Weekday-Conditioned Out-of-Sample Robust MAD Z-Score (`z_ntf_weekday_60d`) eliminating the
     -2.29 sigma Monday withholding drain bias identified by Perplexity across the 400-day sample.
  3. 6-point independent accounting reconciliation (TGA, Op Flows, Table IIIB Issues & Redemptions,
     and Table II Operational Deposits & Withdrawals sums) that NEVER aborts before writing JSON
     (writes `dq.status="BREACH"`, `dq.block=true`, and forces all card `dir=null` on breach).
  4. Card 1 (`nfp_wage_bill`) institutional discipline:
     - Renames `real_wage_impulse` -> `withholding_less_ahe_pp`
     - Removes `withheld_gross_fytd_yoy` (never sums Table IV inter-agency transfers into Table II)
     - Removes `DOL_UNEMP_BEN` and `FUTA` from driving `nfp_dir`
     - Applies `base_shutdown_2025` & `obbba_withholding_regime_2025_09` guards + sets
       `state="INFO_ONLY"`, `dir=null`, `surprise_bias="NOT_ESTIMATED"` when consensus is absent.
  5. Statutory tax-window calendar (`FOLLOWING`-shifted 15th of Jan/Apr/Jun/Sep/Oct/Dec, [-1,+3] bd)
     with window-specific YoY and explicit `null` (never `0.0`) on missing/spliced series.
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

BASE_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts"
CAL_DAYS = 620          # ~427 business days -> covers 400bd history + 60bd window with 364d lag
HISTORY_BD_LIMIT = 400  # Keep last 400 business days in dts_history_400d.json
MAD_FLOOR_MUSD = 1500.0 # Minimum MAD scale ($1,500M) to avoid Z-score explosion on quiet windows
MIN_PRIOR_EVENTS = 3    # Minimum prior realizations required before emitting ex-ante expected payment

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
NOWCAST_PATH = DATA_DIR / "dts_nowcast.json"
HISTORY_PATH = DATA_DIR / "dts_history_400d.json"
BENCHMARKS_PATH = DATA_DIR / "macro_benchmarks.json"

# ─────────────────────────────────────────────────────────────────────────────
# 1. VERSIONED CANONICAL ALIAS DICTIONARY (Strictly separated by side)
#    Includes explicit splice metadata for Customs Duties (2025-11-10 break)
# ─────────────────────────────────────────────────────────────────────────────
SERIES_SPLICE_META = {
    "CUSTOMS_DUTIES": {
        "old_label": "DHS - Customs and Certain Excise Taxes",
        "new_label": "DHS - Customs Duties, Taxes, and Fees",
        "splice_date": "2025-11-10",
        "clean_yoy_from": "2026-11-10",
        "note": "Old series included Certain Excise Taxes (~3% level shift); zero overlap.",
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
        "FED_SALARIES": [
            "Federal Salaries (EFT)",
            "DoD - Military Active Duty Pay",
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
    """Parse numeric value from FiscalData string without ever calling abs()."""
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
    """Fetch 100% of records across all pages with page[size]=10000 and retries."""
    all_rows = []
    page_num = 1
    total_pages = 1

    while page_num <= total_pages:
        params = {
            "filter": f"record_date:gte:{start_date}",
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
                        "User-Agent": "dts-tracker-g8-nowcaster/3.0 (Institutional Macro Pipeline)",
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

    return all_rows


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
    """Extract clean category label from a FiscalData row."""
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
    """Return list of canonical IDs matched by (side, label/desc)."""
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
    """Return (today, mtd, fytd) from any DTS table row."""
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
# 2. ASYMMETRIC SETTLEMENT CALENDAR ENGINE (PRECEDING vs FOLLOWING)
#    Verified against 31 CFR 356.30, SSA Handbook §121, and DFAS rules
#    + Strict Out-of-Sample Warm-Up (>=3 prior events; never expected=observed)
# ─────────────────────────────────────────────────────────────────────────────
def settle_date(nominal_dt, bd_set, min_bd, max_bd, convention="PRECEDING"):
    """
    Shift a nominal calendar date to its effective DTS settlement date using the
    empirical set of Treasury business days (`bd_set`):
      - PRECEDING: SSA (day 3 & 2nd/3rd/4th Wed), SSI (day 1), VA (day 1),
                   Military Active Duty (day 1 & 15), Military Retirement (day 1),
                   Medicare Part D Capitated Prescription Drug Payments (day 1).
      - FOLLOWING: Treasury Coupon Interest (15th & Month-End, 31 CFR 356.30),
                   OPM Civil Service Retirement (day 1),
                   Statutory Quarterly/Extension Tax Deadlines (15th of Jan/Apr/Jun/Sep/Oct/Dec).
    """
    step = -1 if convention == "PRECEDING" else 1
    cur = nominal_dt
    for _ in range(10):
        iso = cur.isoformat()
        if iso in bd_set:
            return iso
        if iso < min_bd or iso > max_bd:
            return None
        cur += datetime.timedelta(days=step)
    return None


def nth_wednesdays(year, month, ns=(2, 3, 4)):
    """Return 2nd, 3rd, and 4th Wednesdays of (year, month)."""
    weds = []
    _, last_day = calendar.monthrange(year, month)
    for day in range(1, last_day + 1):
        dt = datetime.date(year, month, day)
        if dt.weekday() == 2:
            weds.append(dt)
    return [weds[n - 1] for n in ns if n - 1 < len(weds)]


def build_asymmetric_calendar_schedule(all_bd_dates, get_cval):
    """
    Build per-date scheduled calendar strip using asymmetric PRECEDING / FOLLOWING
    rules and rolling median of prior realizations per event type:
      - `realized_sched_by_date`: realized fixed-date payments settled ONLY on event dates `d`
        (outflows positive, scheduled tax-deadline inflows negative so NTF = W_op - D_op aligns)
      - `expected_by_date`: frozen prior-median expected net payments for `d`
        (None if a scheduled event on `d` has fewer than MIN_PRIOR_EVENTS=3 prior realizations)
      - `calendar_miss_by_date`: True if an expected payday had <30% of median realization
    """
    bd_set = set(all_bd_dates)
    min_bd, max_bd = all_bd_dates[0], all_bd_dates[-1]

    # Collect all (year, month) pairs plus adjacent months so cross-month shifts
    # (e.g. Nov 1 Sunday -> Oct 30 Friday for VA/Military/SSI/Medicare Part D) are captured!
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

    # Event classes:
    # (event_key, side, canonical_ids, shift_convention, nominal_dates_fn, history_len, ntf_sign)
    # Note: Withdrawals have ntf_sign = +1.0 (increase NTF); Deposits have ntf_sign = -1.0 (decrease NTF).
    event_specs = [
        (
            "SSA_DAY3",
            "Withdrawals",
            ["SSA_BENEFITS"],
            "PRECEDING",
            lambda y, m: [datetime.date(y, m, 3)],
            6,
            1.0,
        ),
        (
            "SSA_WED",
            "Withdrawals",
            ["SSA_BENEFITS"],
            "PRECEDING",
            lambda y, m: nth_wednesdays(y, m, (2, 3, 4)),
            12,
            1.0,
        ),
        (
            "SSI_DAY1",
            "Withdrawals",
            ["SSA_SSI"],
            "PRECEDING",
            lambda y, m: [datetime.date(y, m, 1)],
            6,
            1.0,
        ),
        (
            "VA_DAY1",
            "Withdrawals",
            ["VA_BENEFITS"],
            "PRECEDING",
            lambda y, m: [datetime.date(y, m, 1)],
            6,
            1.0,
        ),
        (
            "MIL_ACTIVE_1_15",
            "Withdrawals",
            ["DOD_ACTIVE_PAY"],
            "PRECEDING",
            lambda y, m: [datetime.date(y, m, 1), datetime.date(y, m, 15)],
            12,
            1.0,
        ),
        (
            "MIL_RET_DAY1",
            "Withdrawals",
            ["DOD_MIL_RET"],
            "PRECEDING",
            lambda y, m: [datetime.date(y, m, 1)],
            6,
            1.0,
        ),
        (
            "MEDICARE_D_DAY1",
            "Withdrawals",
            ["MEDICARE_PART_D"],
            "PRECEDING",
            lambda y, m: [datetime.date(y, m, 1)],
            6,
            1.0,
        ),
        (
            "OPM_RET_DAY1",
            "Withdrawals",
            ["OPM_RET"],
            "FOLLOWING",
            lambda y, m: [datetime.date(y, m, 1)],
            6,
            1.0,
        ),
        (
            "COUPON_15",
            "Withdrawals",
            ["TREAS_INTEREST"],
            "FOLLOWING",
            lambda y, m: [datetime.date(y, m, 15)],
            6,
            1.0,
        ),
        (
            "COUPON_MEND",
            "Withdrawals",
            ["TREAS_INTEREST"],
            "FOLLOWING",
            lambda y, m: [datetime.date(y, m, calendar.monthrange(y, m)[1])],
            6,
            1.0,
        ),
        (
            "TAX_DEADLINE_15",
            "Deposits",
            ["CORP_INCOME", "NON_WITHHELD_SECA"],
            "FOLLOWING",
            lambda y, m: [datetime.date(y, m, 15)] if m in (1, 4, 6, 9, 10, 12) else [],
            6,
            -1.0,
        ),
    ]

    expected_by_date = {d: 0.0 for d in all_bd_dates}
    realized_sched_by_date = {d: 0.0 for d in all_bd_dates}
    calendar_miss_by_date = {d: False for d in all_bd_dates}
    calendar_warmup_by_date = {d: False for d in all_bd_dates}
    active_events_by_date = {d: [] for d in all_bd_dates}

    # Track which (date, side, cid) has already been counted in realized_sched_by_date or expected_by_date
    counted_realized_cid = set()
    counted_expected_cid = set()

    for ev_key, side, cids, conv, nom_fn, hist_n, ntf_sign in event_specs:
        eff_dates = sorted(
            {
                s_dt
                for (y, m) in sorted(ym_set)
                for nom_dt in nom_fn(y, m)
                for s_dt in [settle_date(nom_dt, bd_set, min_bd, max_bd, conv)]
                if s_dt is not None
            }
        )
        hist_vals = []
        for d in eff_dates:
            obs_val = sum(get_cval(side, cid, d, "today") for cid in cids)
            for cid in cids:
                if (d, side, cid) not in counted_realized_cid:
                    counted_realized_cid.add((d, side, cid))
                    realized_sched_by_date[d] += ntf_sign * get_cval(side, cid, d, "today")

            active_events_by_date[d].append(ev_key)

            # Strict out-of-sample warm-up: require >= MIN_PRIOR_EVENTS prior realizations
            if len(hist_vals) >= MIN_PRIOR_EVENTS:
                exp_val = statistics.median(hist_vals[-hist_n:])
                # Deduplicate if multiple rules for the same (side, cid) land on the same date `d`
                new_cids = [cid for cid in cids if (d, side, cid) not in counted_expected_cid]
                if new_cids:
                    for cid in new_cids:
                        counted_expected_cid.add((d, side, cid))
                    expected_by_date[d] += ntf_sign * exp_val

                # Check for calendar miss on major scheduled outflows (> $2,000M expected)
                if ntf_sign > 0 and exp_val > 2000.0 and obs_val < 0.30 * exp_val:
                    calendar_miss_by_date[d] = True
            else:
                calendar_warmup_by_date[d] = True

            if obs_val > 100.0:
                hist_vals.append(obs_val)

    return (
        expected_by_date,
        realized_sched_by_date,
        calendar_miss_by_date,
        calendar_warmup_by_date,
        active_events_by_date,
    )


def robust_zscore_out_of_sample(series, is_shock_day_flags, idx, window=60, mad_floor=MAD_FLOOR_MUSD):
    """
    Out-of-sample Robust MAD Z-score:
      Z_t = (u_t - median(u_{t-60:t-1})) / max(1.4826 * MAD(u_{t-60:t-1}), mad_floor)
    Excludes `u_t` from its own reference distribution and filters out known tax/refund
    shock days from the scale estimation so quarterly tax days don't blind the MAD for 3 months.
    """
    if idx < 20 or series[idx] is None:
        return None, False
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
        return None, False

    u_t = series[idx]
    med = statistics.median(prior_clean)
    abs_devs = [abs(x - med) for x in prior_clean]
    mad = statistics.median(abs_devs)
    raw_scale = 1.4826 * mad
    floor_hit = raw_scale < mad_floor
    scale = max(raw_scale, mad_floor)
    return round((u_t - med) / scale, 2), floor_hit


def robust_zscore_weekday_out_of_sample(
    series, all_bd_dates, is_shock_day_flags, idx, lookback_bd=100, min_same_wd=10, mad_floor=MAD_FLOOR_MUSD
):
    """
    Weekday-Conditioned Out-of-Sample Robust MAD Z-score (`z_ntf_weekday_60d`):
      Neutralizes the structural intra-week pattern of Treasury cash flows (specifically
      Monday `WITHHELD_FICA` payroll tax settlement surges and Tuesday/Thursday bill cycles)
      by comparing `u_t` on weekday `w` against the prior `lookback_bd` out-of-sample
      non-shock business days of the SAME weekday `w` (up to ~20 prior Mondays for a Monday).
    """
    if idx < 25 or series[idx] is None:
        return None, False
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
        prior_wd_clean = [
            series[j]
            for j in range(0, idx)
            if series[j] is not None
            and not math.isnan(series[j])
            and not is_shock_day_flags[j]
            and datetime.date.fromisoformat(all_bd_dates[j]).weekday() == target_wd
        ][-16:]

    if len(prior_wd_clean) < 8:
        return robust_zscore_out_of_sample(series, is_shock_day_flags, idx, window=60, mad_floor=mad_floor)

    u_t = series[idx]
    med = statistics.median(prior_wd_clean)
    abs_devs = [abs(x - med) for x in prior_wd_clean]
    mad = statistics.median(abs_devs)
    raw_scale = 1.4826 * mad
    floor_hit = raw_scale < mad_floor
    scale = max(raw_scale, mad_floor)
    return round((u_t - med) / scale, 2), floor_hit


def expected_latest_bd(now_utc_dt):
    """
    Compute the expected latest published DTS business date given current UTC time.
    DTS for business day T is published at ~16:00 ET (20:00/21:00 UTC) on business day T+1.
    """
    et_dt = now_utc_dt - datetime.timedelta(hours=5)
    d = et_dt.date()
    # Step back at least 1 business day (or 2 if before 16:30 ET)
    steps_back = 1 if et_dt.hour >= 17 else 2
    while steps_back > 0 or d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
        if d.weekday() < 5:
            steps_back -= 1
    return d.isoformat()


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Load macro benchmarks (AHE deflator YoY, vintage, consensus, and SLGS policy status)
    ahe_deflator_yoy = None
    ahe_vintage = None
    consensus_loaded = False
    nfp_consensus_k = None
    slgs_window_policy_status = "OPEN"

    if BENCHMARKS_PATH.exists():
        try:
            bm = json.loads(BENCHMARKS_PATH.read_text(encoding="utf-8"))
            if bm.get("ahe_deflator_yoy") is not None:
                ahe_deflator_yoy = float(bm["ahe_deflator_yoy"])
            if bm.get("ahe_vintage"):
                ahe_vintage = str(bm["ahe_vintage"])
            consensus_loaded = bool(bm.get("consensus_loaded", False))
            nfp_consensus_k = bm.get("nfp_consensus_k")
            if bm.get("slgs_window_policy_status"):
                slgs_window_policy_status = str(bm["slgs_window_policy_status"]).upper()
        except Exception as exc:
            print(f"[WARN] Could not parse {BENCHMARKS_PATH}: {exc}")

    start_dt = (datetime.date.today() - datetime.timedelta(days=CAL_DAYS)).isoformat()
    print(f"[DTS NOWCASTER v3.0] Fetching 7 DTS tables since {start_dt} ...")

    t1_rows = fetch_paginated("operating_cash_balance", start_dt)
    t2_rows = fetch_paginated("deposits_withdrawals_operating_cash", start_dt)
    t3a_rows = fetch_paginated("public_debt_transactions", start_dt)
    t3b_rows = fetch_paginated("adjustment_public_debt_transactions_cash_basis", start_dt)
    t3c_rows = fetch_paginated("debt_subject_to_limit", start_dt)
    t4_rows = fetch_paginated("inter_agency_tax_transfers", start_dt)
    t5_rows = fetch_paginated("income_tax_refunds_issued", start_dt)

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
        raise RuntimeError("No operating_cash_balance dates found!")

    asof = all_bd_dates[-1]
    print(f"[DTS NOWCASTER v3.0] Latest business date (asof): {asof} (total business days: {len(all_bd_dates)})")

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

    # Footnote recovery pass: if today_v is None on a date where mtd_v is present, recover today_v from mtd delta
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
                rec = c_map.setdefault(d, {"today": 0.0, "mtd": 0.0, "fytd": 0.0})
                if today_v is not None:
                    rec["today"] += today_v
                if mtd_v is not None:
                    rec["mtd"] += mtd_v
                if fytd_v is not None:
                    rec["fytd"] += fytd_v
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

    # Build asymmetric calendar schedule (PRECEDING vs FOLLOWING + >=3 prior realizations warm-up)
    (
        expected_sched_by_date,
        realized_sched_by_date,
        calendar_miss_by_date,
        calendar_warmup_by_date,
        active_events_by_date,
    ) = build_asymmetric_calendar_schedule(all_bd_dates, get_cval)

    # ── Build Daily Accounting Series & Out-of-Sample Weekday-Adjusted Robust Z-Score ──
    daily_records = {}
    ntf_surprise_series = []
    ntf_ex_exp_series = []
    shock_day_flags = []

    for idx, d in enumerate(all_bd_dates):
        t1 = t1_by_date.get(d, {})
        t3b = t3b_by_date.get(d, {})
        t5_d = t5_by_date.get(d, {})

        tga_close = t1.get("tga_close")
        tga_open = t1.get("tga_open")
        if tga_open is None and idx > 0:
            tga_open = t1_by_date.get(all_bd_dates[idx - 1], {}).get("tga_close")

        D = t1.get("tga_dep_t1")
        if D is None:
            D = get_cval("Deposits", "TOTAL_TGA_DEPOSITS_T2", d, "today")
        W = t1.get("tga_wd_t1")
        if W is None:
            W = get_cval("Withdrawals", "TOTAL_TGA_WITHDRAWALS_T2", d, "today")

        I = t3b.get("cash_issues_today")
        if I is None:
            I = get_cval("Deposits", "PUBLIC_DEBT_CASH_ISSUES_T2", d, "today")
        if I is None:
            I = t3b.get("cash_issues_calc")

        R = t3b.get("cash_redemp_today")
        if R is None:
            R = get_cval("Withdrawals", "PUBLIC_DEBT_CASH_REDEMP_T2", d, "today")
        if R is None:
            R = t3b.get("cash_redemp_calc")

        D = D or 0.0
        W = W or 0.0
        I = I or 0.0
        R = R or 0.0

        op_dep_t2 = get_cval("Deposits", "TOTAL_DEPOSITS_EX_DEBT", d, "today") or t2_op_sums.get(d, {}).get("dep", 0.0)
        op_wd_t2 = get_cval("Withdrawals", "TOTAL_WITHDRAWALS_EX_DEBT", d, "today") or t2_op_sums.get(d, {}).get("wd", 0.0)

        # Exact Accounting Identities:
        # B = I - R
        # F = (W - R) - (D - I)
        # dtga = TGA_close - TGA_open
        net_debt_cash_iiib = I - R
        ntf_total = (W - R) - (D - I)
        dtga = (tga_close - tga_open) if (tga_close is not None and tga_open is not None) else (D - W)
        reserves_impact = -dtga

        # 6-Point Independent Accounting Reconciliation (Table I, Table II, Table IIIA, Table IIIB)
        i_calc = t3b.get("cash_issues_calc")
        r_calc = t3b.get("cash_redemp_calc")
        diff_tga = abs(dtga - (D - W))
        diff_bf = abs(dtga - (net_debt_cash_iiib - ntf_total))
        diff_iiib_i = abs(I - i_calc) if i_calc is not None else 0.0
        diff_iiib_r = abs(R - r_calc) if r_calc is not None else 0.0
        diff_op_dep = abs((D - I) - op_dep_t2)
        diff_op_wd = abs((W - R) - op_wd_t2)
        recon_diff = max(diff_tga, diff_bf, diff_iiib_i, diff_iiib_r)
        recon_op_diff = max(diff_op_dep, diff_op_wd)

        ntf_scheduled = realized_sched_by_date.get(d, 0.0)
        is_warmup = calendar_warmup_by_date.get(d, False)
        ntf_expected_cal = None if is_warmup else expected_sched_by_date.get(d, 0.0)
        ntf_surprise = ntf_total - ntf_scheduled
        ntf_ex_expected = None if ntf_expected_cal is None else (ntf_total - ntf_expected_cal)

        # Flag quarterly tax deadline days or >$1,000M business refund shock days
        # so they are excluded from the MAD scale denominator
        corp_d = get_cval("Deposits", "CORP_INCOME", d, "today")
        nonw_d = get_cval("Deposits", "NON_WITHHELD_SECA", d, "today")
        biz_ref_d = t5_d.get("biz_eft_today", 0.0) + t5_d.get("biz_checks_today", 0.0)
        is_shock = (corp_d + nonw_d > 15000.0) or (biz_ref_d >= 1000.0)

        ntf_surprise_series.append(ntf_surprise)
        ntf_ex_exp_series.append(ntf_ex_expected)
        shock_day_flags.append(is_shock)

        # Weekday-conditioned out-of-sample Z-score eliminates the -2.29 sigma Monday withholding bias
        z_weekday_60d, mad_floor_hit = robust_zscore_weekday_out_of_sample(
            ntf_surprise_series, all_bd_dates, shock_day_flags, idx, lookback_bd=100, mad_floor=MAD_FLOOR_MUSD
        )
        z_ex_exp_60d, _ = robust_zscore_weekday_out_of_sample(
            ntf_ex_exp_series, all_bd_dates, shock_day_flags, idx, lookback_bd=100, mad_floor=MAD_FLOOR_MUSD
        )
        z_uncond_60d, _ = robust_zscore_out_of_sample(
            ntf_surprise_series, shock_day_flags, idx, window=60, mad_floor=MAD_FLOOR_MUSD
        )

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
            "ntf_surprise": round(ntf_surprise),
            "ntf_ex_expected": round(ntf_ex_expected) if ntf_ex_expected is not None else None,
            "z_ntf_surprise_60d": z_weekday_60d,
            "z_ntf_weekday_60d": z_weekday_60d,
            "z_ntf_uncond_60d": z_uncond_60d,
            "z_ntf_ex_exp_60d": z_ex_exp_60d,
            "mad_floor_hit": mad_floor_hit,
            "calendar_miss": calendar_miss_by_date.get(d, False),
            "calendar_warmup": is_warmup,
            "recon_diff": round(recon_diff),
            "recon_op_diff": round(recon_op_diff),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 3. LAG 364 ENGINE WITH UNIQUE 1-TO-1 MATCHING, EFFECTIVE-BD NORMALIZATION
    #    AND NON-OVERLAPPING ACCELERATION
    # ─────────────────────────────────────────────────────────────────────────
    bd_index = {d: i for i, d in enumerate(all_bd_dates)}
    bd_set = set(all_bd_dates)
    min_bd, max_bd = all_bd_dates[0], all_bd_dates[-1]

    def get_daily_flow_fn(flow_fn):
        return {d: float(flow_fn(d) or 0.0) for d in all_bd_dates}

    def compute_lag364_window_stats(flow_by_date, end_idx, window_bd=20):
        """
        Compute Lag-364 YoY over `all_bd_dates[end_idx - window_bd + 1 : end_idx + 1]`:
          - Strict 1-to-1 unique base date pairing (never reuses a base date twice!)
          - Normalized by effective business days (`per_bd`) so federal holiday count
            skews between years never distort the YoY growth rate.
        Returns (yoy_per_bd_pct, raw_yoy_pct, holiday_skew_bd, used_cur_n, used_prev_n, min_prev_date, max_prev_date)
        """
        start_idx = max(0, end_idx - window_bd + 1)
        window_dates = all_bd_dates[start_idx : end_idx + 1]
        if not window_dates:
            return None, None, 0, 0, 0, None, None

        cal_start_cur = datetime.date.fromisoformat(window_dates[0])
        cal_end_cur = datetime.date.fromisoformat(window_dates[-1])
        cal_start_prev = cal_start_cur - datetime.timedelta(days=364)
        cal_end_prev = cal_end_cur - datetime.timedelta(days=364)

        prev_span_dates = [
            d
            for d in all_bd_dates
            if cal_start_prev.isoformat() <= d <= cal_end_prev.isoformat()
        ]
        holiday_skew_bd = len(window_dates) - len(prev_span_dates)

        used_prev_dates = []
        cur_sum = 0.0
        prev_sum = 0.0

        for d in window_dates:
            dt = datetime.date.fromisoformat(d)
            target_dt = dt - datetime.timedelta(days=364)
            target_str = target_dt.isoformat()

            matched_prev = None
            if target_str in flow_by_date and target_str not in used_prev_dates:
                matched_prev = target_str
            else:
                for delta_d in (-1, 1, -2, 2):
                    cand = (target_dt + datetime.timedelta(days=delta_d)).isoformat()
                    if cand in flow_by_date and cand not in used_prev_dates:
                        matched_prev = cand
                        break

            if matched_prev is not None:
                used_prev_dates.append(matched_prev)
                cur_sum += flow_by_date[d]
                prev_sum += flow_by_date[matched_prev]

        n_pairs = len(used_prev_dates)
        min_prev = min(used_prev_dates) if used_prev_dates else None
        max_prev = max(used_prev_dates) if used_prev_dates else None
        if n_pairs < max(5, window_bd // 2) or abs(prev_sum) < 1e-6:
            return None, None, holiday_skew_bd, len(window_dates), len(prev_span_dates), min_prev, max_prev

        raw_yoy = round(((cur_sum / prev_sum) - 1.0) * 100.0, 2)

        if prev_span_dates and abs(sum(flow_by_date[d] for d in prev_span_dates)) > 1e-6:
            cur_per_bd = sum(flow_by_date[d] for d in window_dates) / len(window_dates)
            prev_per_bd = sum(flow_by_date[d] for d in prev_span_dates) / len(prev_span_dates)
            norm_yoy = round(((cur_per_bd / prev_per_bd) - 1.0) * 100.0, 2)
        else:
            norm_yoy = raw_yoy

        return norm_yoy, raw_yoy, holiday_skew_bd, len(window_dates), len(prev_span_dates), min_prev, max_prev

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
    print(f"[DTS NOWCASTER v3.0] FYTD YoY anchor date for {asof}: {yoy_anchor}")

    # Effective business day count in current FY vs prior FY up to anchor date
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
        """Return percentage YoY or None (never 0.0!) when base is missing or zero."""
        if cur_val is None or prev_val is None or abs(prev_val) < 1e-6:
            return None
        return round(((cur_val / prev_val) - 1.0) * 100.0, 2)

    def pct_yoy_per_bd(cur_val, prev_val):
        """Return effective-business-day normalized FYTD YoY or None."""
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
    # 4. DATA QUALITY (dq) & RECONCILIATION GATE (Evaluated first so dq.block
    #    can govern all 4 cards and never abort before writing JSON!)
    # ─────────────────────────────────────────────────────────────────────────
    asof_rec = daily_records[asof]
    now_utc_dt = datetime.datetime.now(datetime.timezone.utc)
    now_utc = now_utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    exp_asof = expected_latest_bd(now_utc_dt)
    is_stale = bool(asof < exp_asof)

    unclass_wd_today = get_cval("Withdrawals", "UNCLASSIFIED_WD", asof, "today")
    op_wd_today = max(1.0, float(asof_rec["op_wd"]))
    unclass_wd_pct = round((unclass_wd_today / op_wd_today) * 100.0, 2)
    recon_diff_musd = int(asof_rec["recon_diff"])
    recon_op_diff_musd = int(asof_rec["recon_op_diff"])
    recon_ok = bool(recon_diff_musd <= 5 and recon_op_diff_musd <= 15)
    dq_block = bool(not recon_ok or unclass_wd_pct > 15.0 or asof_rec["calendar_miss"] or is_stale)

    # Base shutdown 2025 check (2025-10-01 to 2025-11-12 lapse in appropriations)
    def overlaps_shutdown_2025(start_d, end_d):
        if not start_d or not end_d:
            return False
        return not (end_d < "2025-10-01" or start_d > "2025-11-15")

    base_is_shutdown_2025 = bool(
        yoy_anchor and ("2025-10-01" <= yoy_anchor <= "2025-12-15")
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 5. COMPUTE THE 4 INSTITUTIONAL NOWCAST CARDS
    # ─────────────────────────────────────────────────────────────────────────

    # ── CARD 1: nfp_wage_bill (Empleo y Masa Salarial — Ficha B2) ──
    withheld_t2_daily = get_daily_flow_fn(lambda d: get_cval("Deposits", "WITHHELD_FICA", d, "today"))

    norm_w_20d, raw_w_20d, hol_skew_20d, _, _, min_p20, max_p20 = compute_lag364_window_stats(
        withheld_t2_daily, last_idx, 20
    )
    norm_w_60d, raw_w_60d, hol_skew_60d, _, _, min_p60, max_p60 = compute_lag364_window_stats(
        withheld_t2_daily, last_idx, 60
    )
    norm_w_prev40d, raw_w_prev40d, _, _, _, _, _ = compute_lag364_window_stats(
        withheld_t2_daily, max(0, last_idx - 20), 40
    )

    withheld_t2_20d_yoy = raw_w_20d
    withheld_t2_20d_norm_yoy = norm_w_20d
    withheld_t2_60d_yoy = raw_w_60d

    # Table II Withheld FYTD (sole canonical cash withholding series; Table IV is NEVER added!)
    withheld_t2_fytd_cur = get_cval("Deposits", "WITHHELD_FICA", asof, "fytd")
    withheld_t2_fytd_prev = get_cval("Deposits", "WITHHELD_FICA", yoy_anchor, "fytd") if yoy_anchor else None
    withheld_t2_fytd_yoy = pct_yoy(withheld_t2_fytd_cur, withheld_t2_fytd_prev)
    withheld_t2_fytd_per_bd_yoy = pct_yoy_per_bd(withheld_t2_fytd_cur, withheld_t2_fytd_prev)

    withheld_t4_fytd_cur = t4_by_date.get(asof, {}).get("withheld_fytd", 0.0)

    # Nominal withholding spread vs AHE & multiplicative proxy (only if explicit ahe_vintage is loaded)
    if withheld_t2_20d_yoy is not None and ahe_deflator_yoy is not None and ahe_vintage is not None:
        withholding_less_ahe_pp = round(withheld_t2_20d_yoy - ahe_deflator_yoy, 2)
        emp_hours_proxy_yoy = round(
            (((1.0 + (withheld_t2_20d_norm_yoy or withheld_t2_20d_yoy) / 100.0) / (1.0 + ahe_deflator_yoy / 100.0)) - 1.0)
            * 100.0,
            2,
        )
    else:
        withholding_less_ahe_pp = None
        emp_hours_proxy_yoy = None

    impulse_vs_60d = (
        round(withheld_t2_20d_yoy - withheld_t2_60d_yoy, 2)
        if (withheld_t2_20d_yoy is not None and withheld_t2_60d_yoy is not None)
        else None
    )
    impulse_non_overlap_40d = (
        round(withheld_t2_20d_norm_yoy - (norm_w_prev40d if norm_w_prev40d is not None else withheld_t2_60d_yoy), 2)
        if (withheld_t2_20d_norm_yoy is not None and (norm_w_prev40d is not None or withheld_t2_60d_yoy is not None))
        else None
    )

    w20_overlaps_shutdown = overlaps_shutdown_2025(min_p20, max_p20) or base_is_shutdown_2025

    nfp_flags = []
    if w20_overlaps_shutdown:
        nfp_flags.append("base_shutdown_2025_fedsal_distortion")
    if min_p60 and min_p60 < "2025-10-01":
        nfp_flags.append("obbba_withholding_regime_2025_09")
    if not consensus_loaded:
        nfp_flags.append("no_consensus_loaded_info_only")
    if hol_skew_20d and abs(hol_skew_20d) >= 1:
        nfp_flags.append(f"holiday_skew_{hol_skew_20d:+d}bd")
    if bd_skew_fytd and abs(bd_skew_fytd) >= 1:
        nfp_flags.append(f"fytd_bd_skew_{bd_skew_fytd:+d}bd")

    # Institutional gating on Card 1 (Grok, ChatGPT, Perplexity, Kimi):
    # If dq.block is True, or base overlaps the 2025 Federal Shutdown, or no NFP consensus is loaded,
    # emit state="INFO_ONLY" and dir=None so ARGOS never takes an uncalibrated directional NFP bet!
    if dq_block:
        nfp_state = "BLOCKED"
        nfp_dir = None
        nfp_surprise_bias = "BLOCKED_BY_DQ"
    elif w20_overlaps_shutdown or not consensus_loaded:
        nfp_state = "INFO_ONLY"
        nfp_dir = None
        nfp_surprise_bias = "NOT_ESTIMATED"
    else:
        if impulse_non_overlap_40d is not None and abs(impulse_non_overlap_40d) < 0.5:
            nfp_state = "NEUTRAL"
            nfp_dir = 0
            nfp_surprise_bias = "INLINE"
        elif (
            emp_hours_proxy_yoy is not None
            and emp_hours_proxy_yoy > 1.5
            and impulse_non_overlap_40d is not None
            and impulse_non_overlap_40d >= 0.75
        ):
            nfp_state = "BULLISH_BIAS"
            nfp_dir = 1
            nfp_surprise_bias = "ABOVE_CONSENSUS"
        elif (
            emp_hours_proxy_yoy is not None
            and emp_hours_proxy_yoy < -0.5
            and impulse_non_overlap_40d is not None
            and impulse_non_overlap_40d <= -0.75
        ):
            nfp_state = "BEARISH_BIAS"
            nfp_dir = -1
            nfp_surprise_bias = "BELOW_CONSENSUS"
        else:
            nfp_state = "WATCH"
            nfp_dir = 0
            nfp_surprise_bias = "INLINE"

    # ── CARD 2: retail_household (Impulso al Consumo vs Estrés Social) ──
    t5_cur = t5_by_date.get(asof, {})
    t5_prev = t5_by_date.get(yoy_anchor, {}) if yoy_anchor else {}

    indiv_refunds_fytd_cur = (
        t5_cur.get("indiv_eft_fytd", 0.0) + t5_cur.get("indiv_checks_fytd", 0.0)
    )
    if indiv_refunds_fytd_cur == 0.0:
        indiv_refunds_fytd_cur = get_cval("Withdrawals", "INDIV_REFUNDS_EFT", asof, "fytd")

    indiv_refunds_fytd_prev = (
        (t5_prev.get("indiv_eft_fytd", 0.0) + t5_prev.get("indiv_checks_fytd", 0.0))
        if yoy_anchor
        else None
    )
    if indiv_refunds_fytd_prev == 0.0 and yoy_anchor:
        indiv_refunds_fytd_prev = get_cval("Withdrawals", "INDIV_REFUNDS_EFT", yoy_anchor, "fytd")

    indiv_refunds_total_fytd_yoy = pct_yoy(indiv_refunds_fytd_cur, indiv_refunds_fytd_prev)
    indiv_refunds_eft_fytd_cur = (
        t5_cur.get("indiv_eft_fytd", 0.0)
        or get_cval("Withdrawals", "INDIV_REFUNDS_EFT", asof, "fytd")
    )
    indiv_refunds_eft_fytd_prev = (
        (
            t5_prev.get("indiv_eft_fytd", 0.0)
            or get_cval("Withdrawals", "INDIV_REFUNDS_EFT", yoy_anchor, "fytd")
        )
        if yoy_anchor
        else None
    )
    indiv_refunds_eft_only_yoy = pct_yoy(indiv_refunds_eft_fytd_cur, indiv_refunds_eft_fytd_prev)

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

    if dq_block:
        retail_state = "BLOCKED"
        retail_dir = None
    elif not in_refund_season:
        retail_state = "DORMANT"
        retail_dir = None
    elif indiv_refunds_total_fytd_yoy is not None and indiv_refunds_total_fytd_yoy > 5.0:
        retail_state = "BULLISH_BIAS"
        retail_dir = 1
    elif indiv_refunds_total_fytd_yoy is not None and indiv_refunds_total_fytd_yoy < -5.0:
        retail_state = "BEARISH_BIAS"
        retail_dir = -1
    else:
        retail_state = "NEUTRAL"
        retail_dir = 0

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
    if biz_refund_today_musd == 0:
        biz_refund_today_musd = round(get_cval("Withdrawals", "BIZ_REFUNDS_EFT", asof, "today"))

    biz_ref_hist = sorted(
        (t5_by_date.get(d, {}).get("biz_eft_today", 0.0) + t5_by_date.get(d, {}).get("biz_checks_today", 0.0))
        for d in all_bd_dates
    )
    p95_idx = min(len(biz_ref_hist) - 1, int(0.95 * len(biz_ref_hist)))
    biz_refund_p95_musd = round(biz_ref_hist[p95_idx]) if biz_ref_hist else 1000

    customs_fytd_cur = get_cval("Deposits", "CUSTOMS_DUTIES", asof, "fytd")
    customs_fytd_prev = get_cval("Deposits", "CUSTOMS_DUTIES", yoy_anchor, "fytd") if yoy_anchor else None
    customs_fytd_raw_spliced_yoy = pct_yoy(customs_fytd_cur, customs_fytd_prev)

    # Statutory quarterly/extension tax deadlines: FOLLOWING-shifted 15th of Jan, Apr, Jun, Sep, Oct, Dec
    # Active window is [-1, +3] business days around the shifted statutory deadline.
    in_corp_tax_window = False
    corp_window_yoy = None
    if asof_dt.month in (1, 4, 6, 9, 10, 12):
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

    customs_splice_active = bool(asof < SERIES_SPLICE_META["CUSTOMS_DUTIES"]["clean_yoy_from"])

    corp_flags = []
    if not in_corp_tax_window:
        corp_flags.append("outside_15th_tax_window")
    else:
        corp_flags.append("active_15th_tax_window")

    if biz_refund_today_musd >= max(1000, biz_refund_p95_musd):
        corp_flags.append("biz_refund_shock_today")

    if customs_splice_active:
        corp_flags.append("series_splice_2025_11_10")
    corp_flags.append("tariff_regime_shift")

    if dq_block:
        corp_state, corp_dir = "BLOCKED", None
    elif in_corp_tax_window and corp_window_yoy is not None:
        if corp_window_yoy > 5.0:
            corp_state, corp_dir = "BULLISH_BIAS", 1
        elif corp_window_yoy < -5.0:
            corp_state, corp_dir = "BEARISH_BIAS", -1
        else:
            corp_state, corp_dir = "WATCH", 0
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
    # Use explicit policy status from macro_benchmarks.json if available, else infer from positive issuance
    slgs_open = bool(slgs_window_policy_status == "OPEN" or slgs_issues_5d_musd > 0)

    stat_limit = t3c_asof.get("stat_debt_limit") or 0.0
    subj_limit = t3c_asof.get("debt_subj_limit") or 0.0
    debt_headroom_iiic = round(stat_limit - subj_limit) if stat_limit > 0 else None

    interest_today = round(get_cval("Withdrawals", "TREAS_INTEREST", asof, "today"))
    interest_mtd = round(get_cval("Withdrawals", "TREAS_INTEREST", asof, "mtd"))
    interest_fytd = round(get_cval("Withdrawals", "TREAS_INTEREST", asof, "fytd"))

    # Govern funding_state using the weekday- and calendar-adjusted Z-score
    z_gov = (
        asof_rec["z_ntf_weekday_60d"]
        if asof_rec["z_ntf_weekday_60d"] is not None
        else asof_rec["z_ntf_ex_exp_60d"]
    )
    if dq_block:
        funding_state = "BLOCKED"
    elif z_gov is not None and abs(z_gov) >= 2.0:
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

    nowcast_payload = {
        "v": "dts-g8-3.0",
        "asof": asof,
        "expected_asof": exp_asof,
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
            "recon_diff_musd": recon_diff_musd,
            "recon_op_diff_musd": recon_op_diff_musd,
            "calendar_miss": asof_rec["calendar_miss"],
            "calendar_warmup": asof_rec["calendar_warmup"],
            "mad_floor_hit": asof_rec["mad_floor_hit"],
            "holiday_skew_20d_bd": hol_skew_20d,
            "bd_skew_fytd": bd_skew_fytd,
            "series_splice_customs": customs_splice_active,
            "reversals": reversals_by_date.get(asof, []),
            "unclass_wd_pct": unclass_wd_pct,
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
            "ntf_surprise": asof_rec["ntf_surprise"],
            "ntf_ex_expected": asof_rec["ntf_ex_expected"],
            "z_ntf_surprise_60d": asof_rec["z_ntf_surprise_60d"],
            "z_ntf_weekday_60d": asof_rec["z_ntf_weekday_60d"],
            "z_ntf_uncond_60d": asof_rec["z_ntf_uncond_60d"],
            "z_ntf_ex_exp_60d": asof_rec["z_ntf_ex_exp_60d"],
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
            "slgs_open": slgs_open,
            "funding_state": funding_state,
            "funding_driver": funding_driver,
        },
        "nowcast_cards": {
            "nfp_wage_bill": {
                "state": nfp_state,
                "dir": nfp_dir,
                "surprise_bias": nfp_surprise_bias,
                "withheld_t2_20d_yoy": withheld_t2_20d_yoy,
                "withheld_t2_20d_norm_yoy": withheld_t2_20d_norm_yoy,
                "withheld_t2_fytd_yoy": withheld_t2_fytd_yoy,
                "withheld_t2_fytd_per_bd_yoy": withheld_t2_fytd_per_bd_yoy,
                "withheld_t4_fytd_musd": round(withheld_t4_fytd_cur),
                "ahe_deflator_yoy": round(ahe_deflator_yoy, 2) if ahe_deflator_yoy is not None else None,
                "ahe_vintage": ahe_vintage,
                "withholding_less_ahe_pp": withholding_less_ahe_pp,
                "emp_hours_proxy_yoy": emp_hours_proxy_yoy,
                "impulse_vs_60d": impulse_vs_60d,
                "impulse_non_overlap_40d": impulse_non_overlap_40d,
                "flags": nfp_flags,
            },
            "retail_household": {
                "state": retail_state,
                "dir": retail_dir,
                "indiv_refunds_fytd_musd": round(indiv_refunds_fytd_cur),
                "indiv_refunds_total_fytd_yoy": indiv_refunds_total_fytd_yoy if in_refund_season else None,
                "indiv_refunds_total_fytd_offseason_yoy": indiv_refunds_total_fytd_yoy,
                "indiv_refunds_eft_only_fytd_yoy": indiv_refunds_eft_only_yoy,
                "snap_fytd_yoy": None if base_is_shutdown_2025 else snap_fytd_raw_yoy,
                "snap_fytd_raw_yoy": snap_fytd_raw_yoy,
                "flags": retail_flags,
            },
            "corp_and_tariffs": {
                "state": corp_state,
                "dir": corp_dir,
                "corp_window_yoy": corp_window_yoy,
                "corp_tax_fytd_yoy": corp_tax_fytd_yoy if in_corp_tax_window else None,
                "corp_tax_fytd_offwindow_yoy": corp_tax_fytd_yoy,
                "non_withheld_fytd_yoy": non_withheld_fytd_yoy if in_corp_tax_window else None,
                "non_withheld_fytd_offwindow_yoy": non_withheld_fytd_yoy,
                "biz_refund_today_musd": biz_refund_today_musd,
                "biz_refund_p95_musd": biz_refund_p95_musd,
                "customs_fytd_musd": round(customs_fytd_cur),
                "customs_fytd_yoy": None if customs_splice_active else customs_fytd_raw_spliced_yoy,
                "customs_fytd_raw_spliced_yoy": customs_fytd_raw_spliced_yoy,
                "customs_clean_after": SERIES_SPLICE_META["CUSTOMS_DUTIES"]["clean_yoy_from"],
                "flags": corp_flags,
            },
        },
    }

    # Always write nowcast_payload FIRST so any reconciliation breach is recorded in JSON
    # rather than leaving a stale "OK" file on main!
    NOWCAST_PATH.write_text(
        json.dumps(nowcast_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[DTS NOWCASTER v3.0] Wrote {NOWCAST_PATH} ({NOWCAST_PATH.stat().st_size} bytes)")

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
                "ntf_surp": rec["ntf_surprise"],
                "z_surp": rec["z_ntf_surprise_60d"],
                "z_uncond": rec["z_ntf_uncond_60d"],
                "z_exp": rec["z_ntf_ex_exp_60d"],
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
        "v": "dts-g8-history-3.0",
        "asof": asof,
        "generated_at": now_utc,
        "count": len(history_rows),
        "series": history_rows,
    }
    HISTORY_PATH.write_text(
        json.dumps(history_payload, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[DTS NOWCASTER v3.0] Wrote {HISTORY_PATH} ({HISTORY_PATH.stat().st_size} bytes, {len(history_rows)} business days)")


if __name__ == "__main__":
    main()
