"""Auditable primitives. No network, no model fitting with future observations."""
from __future__ import annotations
import calendar
import datetime as dt
import json
import math
import os
from pathlib import Path

UTC = dt.timezone.utc

def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

def utcnow():
    return dt.datetime.now(UTC)

def iso(value):
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

def parse_time(value):
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None

def atomic_json(path, value, compact=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                   indent=None if compact else 2) + "\n", encoding="utf-8")
    os.replace(temporary, path)

def business_day(day, calendar_kind="federal"):
    """Federal administrative vs Reserve Bank settlement holidays; never infer from missing rows."""
    if day.weekday() >= 5:
        return False
    holidays = set()
    for year in (day.year - 1, day.year, day.year + 1):
        for month, date in ((1, 1), (6, 19), (7, 4), (11, 11), (12, 25)):
            d = dt.date(year, month, date)
            if d.weekday() == 6:
                d += dt.timedelta(days=1)
            elif d.weekday() == 5 and calendar_kind == "federal":
                d -= dt.timedelta(days=1)
            holidays.add(d)
        for month, weekday, occurrence in ((1,0,3),(2,0,3),(5,0,-1),(9,0,1),(10,0,2),(11,3,4)):
            days = [dt.date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1]+1)
                    if dt.date(year, month, d).weekday() == weekday]
            holidays.add(days[occurrence-1] if occurrence>0 else days[-1])
    return day not in holidays

def radar_valid_until(now, base_hours=26):
    """Validity that does not expire over weekends/federal holidays.

    No official monthly/weekly macro release, FRED daily observation or scheduled
    refresh occurs on a non-business day, so each such day inside the window
    extends it by 24h. A business-day failure still expires after base_hours.
    """
    deadline = now + dt.timedelta(hours=base_hours)
    day = now.date()
    while day <= deadline.date():
        if not business_day(day, "federal"):
            deadline += dt.timedelta(days=1)
        day += dt.timedelta(days=1)
    return deadline

def shift_business(day, convention, calendar_kind="federal"):
    if convention not in ("PRECEDING", "FOLLOWING"):
        raise ValueError("Unknown settlement convention")
    step = -1 if convention == "PRECEDING" else 1
    for _ in range(15):
        if business_day(day, calendar_kind):
            return day
        day += dt.timedelta(days=step)
    raise ValueError("Settlement calendar exhausted")

def settlement(nominal, observed_dates, minimum, maximum, convention="PRECEDING", calendar_kind="federal"):
    effective = shift_business(nominal, convention, calendar_kind).isoformat()
    # A missing observation is a data gap. Never relocate a payment to a different day.
    return effective if minimum <= effective <= maximum and effective in observed_dates else None

def lag364_stats(flow, dates, end_idx, window=20):
    current = dates[max(0, end_idx-window+1):end_idx+1]
    empty = (None, None, 0, len(current), 0, None, None, 0)
    if len(current) != window:
        return empty
    start = dt.date.fromisoformat(current[0])-dt.timedelta(days=364)
    end = dt.date.fromisoformat(current[-1])-dt.timedelta(days=364)
    base = [d for d in dates if start.isoformat() <= d <= end.isoformat()]
    pairs = [(d, (dt.date.fromisoformat(d)-dt.timedelta(days=364)).isoformat()) for d in current]
    pairs = [(d,p) for d,p in pairs if finite(flow.get(d)) and finite(flow.get(p))]
    minimum = min((p for _,p in pairs), default=None)
    maximum = max((p for _,p in pairs), default=None)
    metadata = (len(current)-len(base), len(current), len(base), minimum, maximum, len(pairs))
    # No nearest-date substitution. Coverage checks include independently expected business days.
    expected_base = []
    d = start
    while d <= end:
        if business_day(d): expected_base.append(d.isoformat())
        d += dt.timedelta(days=1)
    full = (len(pairs) >= math.ceil(.95*window) and all(finite(flow.get(d)) for d in current)
            and all(finite(flow.get(d)) for d in expected_base) and base
            and all(finite(flow.get(d)) for d in base))
    if not full:
        return (None, None, *metadata)
    numerator = sum(flow[d] for d,p in pairs)
    denominator = sum(flow[p] for d,p in pairs)
    baseline = sum(flow[d] for d in base)/len(base)
    if denominator <= 0 or baseline <= 0:
        return (None, None, *metadata)
    raw = 100*(numerator/denominator-1)
    normalized = 100*((sum(flow[d] for d in current)/len(current))/baseline-1)
    return (round(normalized,2), round(raw,2), *metadata)

def cash_contract(payload, now=None):
    """One fail-closed contract shared by publication, agent output and browser tests."""
    now = now or utcnow()
    dq = payload.setdefault("dq", {})
    until = parse_time(payload.get("valid_until_utc"))
    generated = parse_time(payload.get("generated_at"))
    expired = until is None or now >= until
    future = generated is None or generated > now + dt.timedelta(minutes=5)
    mmt = payload.setdefault("mmt_liquidity", {})
    complete=all(finite(mmt.get(k)) for k in ("ntf_total","dtga","reserves_impact","tga_close","net_debt_cash_iiib"))
    blocked = bool(dq.get("block", True) or dq.get("stale", True) or expired or future or not complete)
    payload["v"] = "dts-g8-6.0"
    payload["units"] = "USD_millions"
    payload["sign_convention"] = "ntf>0: net non-debt cash outflow; tga_reserve_contribution=-dtga (other factors unchanged)"
    payload["model_status"] = "DESCRIPTIVE_FISCAL_CASH_NOT_CONSENSUS_FORECAST"
    dq["block"] = blocked
    dq["stale"] = bool(dq.get("stale", True) or expired)
    if expired: dq["status"] = "EXPIRED"
    if future: dq["status"] = "INVALID_TIMESTAMP"
    mmt = payload.setdefault("mmt_liquidity", {})
    if blocked:
        mmt["funding_state"] = "BLOCKED"
    elif dq.get("calendar_warmup") or dq.get("calendar_miss"):
        mmt["funding_state"] = "CALENDAR_UNCERTAIN"
    mmt["probability_of_macro_surprise"] = None
    for card in payload.get("nowcast_cards", {}).values():
        card["dir"] = None
        card["surprise_bias"] = "NOT_ESTIMATED"
        if blocked: card["state"] = "BLOCKED"
        elif card.get("state") not in ("DORMANT", "INFO_ONLY"): card["state"] = "INFO_ONLY"
    return payload
