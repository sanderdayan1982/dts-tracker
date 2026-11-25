#!/usr/bin/env python3
"""Data-driven refresh calendar for the DTS tracker (orden Sander t383u).

Pure functions, no network. A runner (outside this repo) calls ``plan`` every few
minutes, refreshes only when a pass is due, and sends the alerts returned by
``alerts``. Nothing here depends on fixed GitHub cron times.

Every macro card with a ``release_date`` and every Daily Treasury Statement
publication is a *target*. Passes run at release_at +15 min, +45 min, +2 h and
+4 h until the official value has entered the published file. If the value is
still missing at release_at +2 h the runner must alert, with the card, the
expected time and the cause (source delayed, source down or job error).
``valid_until_utc`` can never be expired without a pass and, if the pass does not
renew it, an alert.

The US federal calendar comes from ``institutional_core.business_day`` (the same
one used by the DTS and radar validity rules): no DTS target exists on a federal
holiday, so a holiday never triggers a pass or an alert.
"""
from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

from institutional_core import business_day, iso, parse_time

NY = ZoneInfo("America/New_York")
WAT = ZoneInfo("Africa/Malabo")
PASS_OFFSETS_MIN = (15, 45, 120, 240)
ALERT_AFTER_MIN = 120
FINAL_AFTER_MIN = 240
KEEP_DAYS = 7
# Official release clock (ET). BLS/BEA/Census/DOL: 08:30. Fed G.17: 09:15.
RELEASE_TIME_ET = {"INDPRO": (9, 15)}
DEFAULT_RELEASE_TIME_ET = (8, 30)
DTS_PUBLICATION_ET = (16, 45)   # same clock as build_dts_nowcast.expected_latest_bd_and_validity
# Republish an unchanged radar only when its published validity is about to lapse.
VALIDITY_MARGIN = dt.timedelta(hours=8)
VOLATILE_KEYS = frozenset({
    "generated_at", "retrieved_at", "source_retrieved_at", "last_attempt_at", "last_fetch_attempt_utc",
    "valid_until_utc", "captured_at", "at", "expires", "dts_driver_expires", "updated_at",
})
# Floating-point noise (last ulp, interpreter version) is not a publication.
SIGNIFICANT_DIGITS = 10

CAUSE_DELAYED = "fuente con retraso"
CAUSE_DOWN = "fuente caída"
CAUSE_ERROR = "error del job"


def _release_at(card):
    """Official release instant of the card's next publication (UTC)."""
    day = card.get("release_date")
    if not day:
        return None
    cons = card.get("consensus") or {}
    at = parse_time(cons.get("release_at")) if isinstance(cons, dict) else None
    if at is not None and at.astimezone(NY).date().isoformat() == day:
        return at.astimezone(dt.timezone.utc)
    h, m = RELEASE_TIME_ET.get(card.get("series_id"), DEFAULT_RELEASE_TIME_ET)
    d = dt.date.fromisoformat(day)
    return dt.datetime(d.year, d.month, d.day, h, m, tzinfo=NY).astimezone(dt.timezone.utc)


def _prev_business_day(day):
    day -= dt.timedelta(days=1)
    while not business_day(day, "federal"):
        day -= dt.timedelta(days=1)
    return day


def dts_target(dts):
    """Next DTS publication from dts_nowcast.json: (release_at, expected record date)."""
    until = parse_time((dts or {}).get("valid_until_utc"))
    if until is None:
        return None
    pub_day = until.astimezone(NY).date()
    if not business_day(pub_day, "federal"):
        return None
    h, m = DTS_PUBLICATION_ET
    release = dt.datetime(pub_day.year, pub_day.month, pub_day.day, h, m, tzinfo=NY).astimezone(dt.timezone.utc)
    return release, _prev_business_day(pub_day).isoformat()


def current_targets(radar, dts):
    """Targets visible in the files now. Key is stable across refreshes."""
    out = {}
    for card in (radar or {}).get("cards", []):
        release = _release_at(card)
        ref = card.get("reference_period")
        if release is None or not ref:
            continue
        key = "%s:%s" % (card["id"], card["release_date"])
        out[key] = {"kind": "card", "card": card["id"], "series_id": card.get("series_id"),
                    "release_at": iso(release), "target": ref}
    t = dts_target(dts)
    if t:
        release, expected = t
        out["dts:%s" % release.date().isoformat()] = {"kind": "dts", "card": "dts", "series_id": "DTS",
                                                       "release_at": iso(release), "target": expected}
    return out


def entered(target, radar, dts):
    """True once the published files contain the official value for *target*."""
    if target["kind"] == "dts":
        asof = (dts or {}).get("asof")
        return bool(asof) and asof >= target["target"]
    for card in (radar or {}).get("cards", []):
        if card.get("id") == target["card"]:
            obs = card.get("observed_period") or ""
            ref = target["target"]
            return bool(obs) and obs[:len(ref)] >= ref
    return False


def _slots(target):
    release = parse_time(target["release_at"])
    return [iso(release + dt.timedelta(minutes=m)) for m in PASS_OFFSETS_MIN]


def register(state, radar, dts, now):
    """Merge current targets into state; drop old ones. Returns the state."""
    targets = state.setdefault("targets", {})
    for key, t in current_targets(radar, dts).items():
        if key not in targets:
            targets[key] = dict(t, slots_done=[], alerted=False, final=False, entered=False)
    for key in list(targets):
        t = targets[key]
        t["entered"] = t.get("entered") or entered(t, radar, dts)
        if now - parse_time(t["release_at"]) > dt.timedelta(days=KEEP_DAYS):
            del targets[key]
    return state


def plan(state, radar, dts, now):
    """Decide whether a refresh pass is due now. Returns (due, reasons)."""
    register(state, radar, dts, now)
    reasons = []
    for key, t in sorted(state["targets"].items()):
        if t["entered"]:
            continue
        due = [s for s in _slots(t) if parse_time(s) <= now and s not in t["slots_done"]]
        if due:
            minutes = int((parse_time(due[-1]) - parse_time(t["release_at"])).total_seconds() // 60)
            reasons.append("%s+%dm" % (key, minutes))
    until = parse_time((radar or {}).get("valid_until_utc"))
    if until is not None and until <= now and state.get("validity_pass") != iso(until):
        reasons.append("valid_until_utc vencido %s" % iso(until))
    return bool(reasons), reasons


def mark_pass(state, now, radar):
    """Record that a pass ran at *now*: every slot already due counts as done."""
    for t in state.get("targets", {}).values():
        for s in _slots(t):
            if parse_time(s) <= now and s not in t["slots_done"]:
                t["slots_done"].append(s)
    until = parse_time((radar or {}).get("valid_until_utc"))
    if until is not None and until <= now:
        state["validity_pass"] = iso(until)
    state["last_pass"] = iso(now)
    return state


def source_cause(target, sources, job_error=None):
    """Classify why a value is missing: job error, source down or source delayed."""
    if job_error:
        return "%s (%s)" % (CAUSE_ERROR, job_error)
    src = (sources or {}).get(target.get("series_id")) or {}
    if src.get("status") and src.get("status") != "OK":
        return "%s (%s)" % (CAUSE_DOWN, src.get("error") or src.get("status"))
    return "%s (publicado en la fuente pero aún sin el dato)" % CAUSE_DELAYED


def _wat(ts):
    return parse_time(ts).astimezone(WAT).strftime("%d-%b %H:%M WAT")


def alerts(state, radar, dts, now, sources=None, job_error=None):
    """Alert messages due now. Each one is sent once (state is updated)."""
    register(state, radar, dts, now)
    out = []
    for key, t in sorted(state["targets"].items()):
        if t["entered"]:
            continue
        release = parse_time(t["release_at"])
        if not t["alerted"] and now >= release + dt.timedelta(minutes=ALERT_AFTER_MIN):
            t["alerted"] = True
            out.append("DTS tracker · %s sin dato a release_at+2h · esperado %s · causa: %s"
                       % (t["card"], _wat(t["release_at"]), source_cause(t, sources, job_error)))
        if not t["final"] and now >= release + dt.timedelta(minutes=FINAL_AFTER_MIN) and \
                len(t["slots_done"]) >= len(PASS_OFFSETS_MIN):
            t["final"] = True
            out.append("DTS tracker · %s sigue sin dato tras la última pasada (+4h) · esperado %s · causa: %s"
                       % (t["card"], _wat(t["release_at"]), source_cause(t, sources, job_error)))
    until = parse_time((radar or {}).get("valid_until_utc"))
    if until is not None and until <= now and state.get("validity_alerted") != iso(until) \
            and state.get("validity_pass") == iso(until):
        state["validity_alerted"] = iso(until)
        out.append("DTS tracker · macro_radar valid_until_utc vencido (%s) y la pasada no lo renovó"
                   % _wat(iso(until)))
    return out


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    if isinstance(value, float):
        return float("%.*g" % (SIGNIFICANT_DIGITS, value))
    return value


def substantive_change(old_text, new_text):
    """True if two JSON documents differ beyond timestamps/validity stamps."""
    try:
        return _strip(json.loads(old_text)) != _strip(json.loads(new_text))
    except (TypeError, ValueError):
        return old_text != new_text


def validity_needs_renewal(published_radar, now, margin=VALIDITY_MARGIN):
    """True if the published radar's validity lapses within *margin* (republish even if unchanged)."""
    until = parse_time((published_radar or {}).get("valid_until_utc"))
    return until is None or until - now <= margin
