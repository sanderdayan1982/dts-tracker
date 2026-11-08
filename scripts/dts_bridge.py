#!/usr/bin/env python3
"""DTS bridge models v7: Treasury cash -> official macro releases.

Pre-registered design (fixed before looking at out-of-sample results; no search):
  nfp     PAYEMS m/m change   ~ baseline(3m mean) + withheld-tax growth surprise
  claims  ICSA weekly level   ~ prior week change + DOL UI-benefit growth surprise   (modelled in logs)
  retail  RSAFS % m/m         ~ baseline(3m mean) + withheld-tax growth surprise + refund cash impulse
  trade   BOPGSTB level       ~ customs-duty growth surprise                            (modelled as level change)

Point-in-time rules
  * DTS daily amounts are not revised; an observation dated d is public on the next
    business day at 16:00 ET. The feature only uses DTS days published before the
    release (cutoff = release date minus 2 business days, or the month-end for retail).
  * Targets are the latest revised FRED vintage (first-release vintages are not free
    without an API key). This is disclosed in every output.
  * Coefficients for an origin are fitted only on earlier periods whose actual value
    had already been published. Mar-2020..Dec-2021 is excluded from fitting and from
    evaluation (pandemic transfers and programme shutdowns broke every fiscal channel).
  * Edge = DEMONSTRATED only if, versus the radar baseline on the same origins:
      MAE improvement >= 5 %, Diebold-Mariano one-sided p < 0.10 (Newey-West, 3 lags),
      and improvement > 0 over the most recent 24 origins; AND, versus an ablation that
      re-fits the same regression without the DTS regressors, MAE improvement >= 2 % with
      DM p < 0.10. The ablation test isolates what DTS adds beyond statistical shrinkage.
      (The ablation gate was added after the first run showed that a retail gain came from
      shrinking the baseline, not from DTS. It can only make the rule stricter.)
"""
from __future__ import annotations
import calendar, datetime as dt, json, math, statistics as st, urllib.parse, urllib.request, time
from pathlib import Path
from institutional_core import atomic_json, business_day, finite, iso, parse_time, radar_valid_until, utcnow

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SERIES_PATH = DATA / "bridge" / "dts_daily_series.json"
OUT_PATH = DATA / "dts_bridge.json"
API = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts"
COVID = ("2020-03", "2021-12")
MIN_TRAIN, ROLL = 36, 96          # monthly origins; weekly models use 4x
EDGE_MIN_IMPROVEMENT, EDGE_MAX_P, RECENT = 5.0, 0.10, 24

T2_MAP = {"Deposits": {"Taxes - Withheld Individual/FICA": "WITHHELD", "Customs and Certain Excise Taxes": "CUSTOMS",
                       "DHS - Customs and Certain Excise Taxes": "CUSTOMS", "DHS - Customs Duties, Taxes, and Fees": "CUSTOMS"},
          "Withdrawals": {"Unemployment Insurance Benefits": "DOL_UI", "DOL - Unemployment Benefits": "DOL_UI"}}
T2_ACCOUNTS = {"Treasury General Account (TGA)", "Federal Reserve Account"}
T5_INDIVIDUAL = {"IRS Tax Refunds Individual", "Taxes - Individual Tax Refunds (EFT)", "Taxes - Individual Tax Refunds (Checks)"}

# ----------------------------------------------------------------------------- DTS series
def _num(x):
    try:
        v = float(x); return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None

def accumulate(series, t2_rows=(), t4_rows=(), t5_rows=()):
    """Map raw DTS rows to daily series (USD millions). Replaces whole days to stay idempotent."""
    fresh = {}
    def add(name, day, value):
        if value is None: return
        fresh.setdefault(name, {}).setdefault(day, 0.0)
        fresh[name][day] += value
    for r in t2_rows:
        if r.get("account_type") not in T2_ACCOUNTS: continue
        name = T2_MAP.get(r.get("transaction_type"), {}).get(r.get("transaction_catg"))
        if name: add(name, r["record_date"], _num(r.get("transaction_today_amt")))
    for r in t4_rows:
        if r.get("tax_deposit_type") == "Withheld Income and Employment Taxes":
            add("WITHHELD", r["record_date"], _num(r.get("tax_deposit_today_amt")))
    for r in t5_rows:
        if r.get("tax_refund_type") in T5_INDIVIDUAL:
            add("REFUNDS_IND", r["record_date"], _num(r.get("tax_refund_today_amt")))
    for name, days in fresh.items():
        series.setdefault(name, {}).update({d: round(v, 3) for d, v in days.items()})
    return series

def _pages(endpoint, start, fields):
    out, page, total = [], 1, 1
    while page <= total:
        q = urllib.parse.urlencode({"filter": f"record_date:gte:{start}", "sort": "record_date", "fields": ",".join(fields),
                                    "page[size]": "10000", "page[number]": str(page)})
        for attempt in range(3):
            try:
                req = urllib.request.Request(f"{API}/{endpoint}?{q}", headers={"User-Agent": "dts-tracker-bridge/7.0", "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=40) as r: body = json.loads(r.read())
                break
            except Exception:
                if attempt == 2: raise
                time.sleep(2 ** attempt)
        total = int(body["meta"]["total-pages"]); out += body["data"]; page += 1
    return out

def update_series(now):
    """Incremental refresh from the last stored DTS date (minus a week of overlap)."""
    store = json.loads(SERIES_PATH.read_text()) if SERIES_PATH.exists() else {"series": {}}
    series = store["series"]
    last = max((max(v) for v in series.values() if v), default="2014-01-01")
    start = (dt.date.fromisoformat(last) - dt.timedelta(days=7)).isoformat()
    t2 = _pages("deposits_withdrawals_operating_cash", start, ["record_date", "account_type", "transaction_type", "transaction_catg", "transaction_today_amt"])
    t5 = _pages("income_tax_refunds_issued", start, ["record_date", "tax_refund_type", "tax_refund_today_amt"])
    accumulate(series, t2, (), t5)
    store.update(series={k: dict(sorted(v.items())) for k, v in series.items()}, updated_at=iso(now),
                 asof=max(max(v) for v in series.values() if v), units="USD_millions",
                 source=API, note="Daily 'today' amounts; withheld taxes before 2023-02-14 come from Table IV (federal tax deposits).")
    atomic_json(SERIES_PATH, store, compact=True)
    return store

# ----------------------------------------------------------------------------- calendars
def add_bd(day, n):
    step = 1 if n > 0 else -1
    while n:
        day += dt.timedelta(days=step)
        if business_day(day): n -= step
    return day

def month_add(period, k):
    y, m = int(period[:4]), int(period[5:7]) + k
    y += (m - 1) // 12; m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"

def nfp_release(period):
    """BLS: third Friday after the week (Sun-Sat) that contains the 12th."""
    y, m = int(period[:4]), int(period[5:7])
    twelfth = dt.date(y, m, 12)
    saturday = twelfth + dt.timedelta(days=(5 - twelfth.weekday()) % 7)
    return saturday + dt.timedelta(days=6 + 14)

def last_bd(period):
    y, m = int(period[:4]), int(period[5:7])
    d = dt.date(y, m, calendar.monthrange(y, m)[1])
    while not business_day(d): d -= dt.timedelta(days=1)
    return d

def cutoff_for(target, period):
    if target == "nfp": return add_bd(nfp_release(period), -2)
    if target == "claims": return dt.date.fromisoformat(period) + dt.timedelta(days=3)   # Tuesday after week end
    if target == "retail": return last_bd(period)
    if target == "trade":
        nxt = month_add(period, 1); return dt.date(int(nxt[:4]), int(nxt[5:7]), 25)
    raise KeyError(target)

# ----------------------------------------------------------------------------- features
def window_sum(daily, end, n):
    """Sum of the last n published business days <= end. None if any expected day is missing."""
    days, d = [], end
    while not business_day(d): d -= dt.timedelta(days=1)
    while len(days) < n:
        if business_day(d): days.append(d.isoformat())
        d -= dt.timedelta(days=1)
    vals = [daily.get(x) for x in days]
    return None if any(v is None for v in vals) else sum(vals)

def lag364_growth(daily, end, n):
    cur, base = window_sum(daily, end, n), window_sum(daily, end - dt.timedelta(days=364), n)
    return None if cur is None or base is None or base <= 0 else math.log(cur / base)

def month_sum(daily, period):
    vals = [v for d, v in daily.items() if d.startswith(period)]
    return sum(vals) if vals else None

# ----------------------------------------------------------------------------- statistics
def solve(a, b):
    n = len(b); m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12: return None
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]

def ridge(X, y, lam=1.0):
    """OLS with an intercept and a fixed ridge penalty on standardized slopes (no tuning)."""
    k = len(X[0]); mu = [st.fmean(r[j] for r in X) for j in range(k)]
    sd = [st.pstdev([r[j] for r in X]) or 1.0 for j in range(k)]
    Z = [[(r[j] - mu[j]) / sd[j] for j in range(k)] for r in X]; ym = st.fmean(y)
    A = [[sum(z[i] * z[j] for z in Z) + (lam if i == j else 0) for j in range(k)] for i in range(k)]
    b = [sum(z[i] * (t - ym) for z, t in zip(Z, y)) for i in range(k)]
    beta = solve(A, b)
    if beta is None: return None
    slopes = [beta[j] / sd[j] for j in range(k)]
    return {"intercept": ym - sum(s * m for s, m in zip(slopes, mu)), "slopes": slopes}

def predict(model, x):
    return model["intercept"] + sum(s * v for s, v in zip(model["slopes"], x))

def quantile(values, p):
    v = sorted(values); i = (len(v) - 1) * p; lo = int(i); hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)

def diebold_mariano(e_model, e_base, lags=3):
    d = [abs(a) - abs(b) for a, b in zip(e_model, e_base)]; n = len(d); m = st.fmean(d)
    gamma = lambda k: sum((d[t] - m) * (d[t - k] - m) for t in range(k, n)) / n
    var = gamma(0) + 2 * sum((1 - k / (lags + 1)) * gamma(k) for k in range(1, lags + 1))
    if var <= 0: return None, None
    stat = m / math.sqrt(var / n)
    return stat, 0.5 * (1 + math.erf(stat / math.sqrt(2)))     # one-sided: model better if stat << 0

def in_covid(period):
    return COVID[0] <= period[:7] <= COVID[1]

# ----------------------------------------------------------------------------- target definitions
def load_target(series_id):
    path = DATA / "sources" / f"{series_id}.json"
    src = json.loads(path.read_text()) if path.exists() else {"observations": []}
    return src, {o["date"]: o["value"] for o in src.get("observations", [])}

def build_rows(target, dts, obs):
    """One row per reference period: (period, y, baseline, features, cutoff)."""
    rows, dates = [], sorted(obs)
    W, U, R, C = (dts.get(k, {}) for k in ("WITHHELD", "DOL_UI", "REFUNDS_IND", "CUSTOMS"))
    if target in ("nfp", "retail"):
        if target == "nfp":
            chg = {d: obs[d] - obs[p] for p, d in zip(dates, dates[1:]) if month_add(p[:7], 1) == d[:7]}
        else:
            chg = {d: 100 * (obs[d] / obs[p] - 1) for p, d in zip(dates, dates[1:]) if month_add(p[:7], 1) == d[:7]}
        growth = {}
        for d in dates:
            per = d[:7]; cut = cutoff_for(target, per)
            growth[per] = lag364_growth(W, cut, 20)
        for d in dates:
            per = d[:7]; prev = [month_add(per, -k) for k in (1, 2, 3)]
            if d not in chg or not all(p + "-01" in chg for p in prev): continue
            hist = [growth.get(month_add(per, -k)) for k in range(1, 13)]
            if growth.get(per) is None or any(h is None for h in hist): continue
            surprise = growth[per] - st.fmean(hist)
            base = st.fmean(chg[p + "-01"] for p in prev)
            feats = [base, 100 * surprise]
            if target == "retail":
                rm, rl = month_sum(R, per), month_sum(R, month_add(per, -12))
                w12 = [month_sum(W, month_add(per, -k)) for k in range(1, 13)]
                if rm is None or rl is None or any(x is None for x in w12): continue
                feats.append(100 * (rm - rl) / st.fmean(w12))
            rows.append({"period": per, "y": chg[d], "baseline": base, "x": feats, "cutoff": cutoff_for(target, per).isoformat()})
    elif target == "claims":
        for p, d in zip(dates, dates[1:]):
            if (dt.date.fromisoformat(d) - dt.date.fromisoformat(p)).days != 7: continue
            pp = (dt.date.fromisoformat(p) - dt.timedelta(days=7)).isoformat()
            if pp not in obs: continue
            cut = cutoff_for("claims", d)
            g_now, g_prev = lag364_growth(U, cut, 5), lag364_growth(U, cut - dt.timedelta(days=7), 5)
            if g_now is None or g_prev is None: continue
            y = math.log(obs[d] / obs[p]); prior = math.log(obs[p] / obs[pp])
            rows.append({"period": d, "y": y, "baseline": 0.0, "x": [prior, 100 * (g_now - g_prev)], "cutoff": cut.isoformat(),
                         "level_prev": obs[p], "level": obs[d]})
    elif target == "trade":
        growth = {}
        for d in dates:
            per = d[:7]; growth[per] = lag364_growth(C, cutoff_for("trade", per), 15)
        for p, d in zip(dates, dates[1:]):
            per = d[:7]
            if month_add(p[:7], 1) != per or growth.get(per) is None: continue
            hist = [growth.get(month_add(per, -k)) for k in range(1, 13)]
            if any(h is None for h in hist): continue
            rows.append({"period": per, "y": (obs[d] - obs[p]) / 1000, "baseline": 0.0,
                         "x": [100 * (growth[per] - st.fmean(hist))], "cutoff": cutoff_for("trade", per).isoformat(),
                         "level_prev": obs[p] / 1000, "level": obs[d] / 1000})
    return rows

NON_DTS = {"nfp": [0], "retail": [0], "claims": [0], "trade": []}   # regressor indices kept in the ablation

TARGETS = {
    "nfp": {"series": "PAYEMS", "unit": "thousand_jobs", "freq": "monthly", "features": ["baseline_3m", "withheld_growth_surprise_pp"],
            "driver_en": "Withheld income/FICA taxes, 20 sessions, Lag-364 growth vs its own 12-month average",
            "driver_es": "Retenciones IRPF/FICA, 20 sesiones, crecimiento Lag 364 frente a su media de 12 meses"},
    "claims": {"series": "ICSA", "unit": "thousand_claims", "freq": "weekly", "features": ["prior_week_log_change", "dol_ui_growth_change_pp"],
               "driver_en": "DOL unemployment-benefit payments, 5 sessions, change in Lag-364 growth",
               "driver_es": "Pagos de prestaciones por desempleo DOL, 5 sesiones, cambio del crecimiento Lag 364"},
    "retail": {"series": "RSAFS", "unit": "percent_mom", "freq": "monthly", "features": ["baseline_3m", "withheld_growth_surprise_pp", "refund_impulse_pct_of_withholding"],
               "driver_en": "Withholding growth surprise plus individual refund cash vs a year earlier",
               "driver_es": "Sorpresa de retenciones más caja de devoluciones individuales frente al año anterior"},
    "trade": {"series": "BOPGSTB", "unit": "usd_billions", "freq": "monthly", "features": ["customs_growth_surprise_pp"],
              "driver_en": "Customs duties, 15 sessions of the following month, Lag-364 growth vs its 12-month average",
              "driver_es": "Aduanas, 15 sesiones del mes siguiente, crecimiento Lag 364 frente a su media de 12 meses"},
}

def to_level(target, row, value_change):
    """Convert a model in changes to the published unit."""
    if target == "claims": return row["level_prev"] * math.exp(value_change) / 1000
    if target == "trade": return row["level_prev"] + value_change
    return value_change

def backtest(target, rows):
    weekly = TARGETS[target]["freq"] == "weekly"
    min_train, roll = (MIN_TRAIN * 4, ROLL * 4) if weekly else (MIN_TRAIN, ROLL)
    clean = [r for r in rows if not in_covid(r["period"])]
    results = []
    for i, r in enumerate(clean):
        # Only periods whose actual was published before this release (strictly two periods back for monthly safety).
        train = [q for q in clean[:i] if q["period"] < r["period"]][:-1][-roll:]
        if len(train) < min_train: continue
        model = ridge([q["x"] for q in train], [q["y"] for q in train])
        if model is None: continue
        fit = predict(model, r["x"])
        if target == "claims":
            actual, bridge, base = r["level"] / 1000, to_level(target, r, fit), r["level_prev"] / 1000
        elif target == "trade":
            actual, bridge, base = r["level"], to_level(target, r, fit), r["level_prev"]
        else:
            actual, bridge, base = r["y"], fit, r["baseline"]
        results.append({"period": r["period"], "actual": actual, "bridge": bridge, "baseline": base})
    return results

def ablate(target, rows):
    keep = NON_DTS[target]
    return [dict(r, x=[r["x"][i] for i in keep] if keep else [0.0]) for r in rows]

def evaluate(results, ablation=None):
    if len(results) < 30: return None
    eb = [r["actual"] - r["bridge"] for r in results]; e0 = [r["actual"] - r["baseline"] for r in results]
    mae_b, mae_0 = st.fmean(map(abs, eb)), st.fmean(map(abs, e0))
    stat, p = diebold_mariano(eb, e0)
    recent_b, recent_0 = st.fmean(map(abs, eb[-RECENT:])), st.fmean(map(abs, e0[-RECENT:]))
    imp = 100 * (1 - mae_b / mae_0) if mae_0 > 0 else None
    recent_imp = 100 * (1 - recent_b / recent_0) if recent_0 > 0 else None
    edge = (imp is not None and imp >= EDGE_MIN_IMPROVEMENT and p is not None and p < EDGE_MAX_P
            and recent_imp is not None and recent_imp > 0)
    hits = sum((r["bridge"] - r["baseline"]) * (r["actual"] - r["baseline"]) > 0 for r in results)
    vs_abl = None
    if ablation:
        by = {r["period"]: r for r in ablation}
        pairs = [(r, by[r["period"]]) for r in results if r["period"] in by]
        ea = [a["actual"] - a["bridge"] for _, a in pairs]; ebp = [r["actual"] - r["bridge"] for r, _ in pairs]
        ma, mb = st.fmean(map(abs, ea)), st.fmean(map(abs, ebp))
        s2, p2 = diebold_mariano(ebp, ea)
        vs_abl = {"n": len(pairs), "mae_ablation": ma, "improvement_pct": 100 * (1 - mb / ma) if ma > 0 else None,
                  "dm_stat": s2, "dm_p_one_sided": p2}
        edge = edge and vs_abl["improvement_pct"] is not None and vs_abl["improvement_pct"] >= 2.0 and p2 is not None and p2 < EDGE_MAX_P
    return {"n": len(results), "first": results[0]["period"], "last": results[-1]["period"],
            "mae_bridge": mae_b, "mae_baseline": mae_0, "improvement_pct": imp,
            "dm_stat": stat, "dm_p_one_sided": p, "recent_n": min(RECENT, len(results)), "recent_improvement_pct": recent_imp,
            "direction_hit_rate_vs_baseline_pct": 100 * hits / len(results), "dts_added_value": vs_abl,
            "edge": "DEMONSTRATED" if edge else "NONE",
            "residual_p10": quantile(eb[-36:], .1), "residual_p90": quantile(eb[-36:], .9)}

# ----------------------------------------------------------------------------- live nowcast
def live_row(target, dts, obs, period, now_dts_asof):
    """Feature row for the next unreleased period using only DTS published so far."""
    sched = cutoff_for(target, period)
    asof = dt.date.fromisoformat(now_dts_asof)
    cut = min(sched, asof)
    missing = 0; d = cut
    while d < sched:
        d += dt.timedelta(days=1)
        if business_day(d): missing += 1
    rows = build_rows(target, dts, obs)          # history for training
    dates = sorted(obs); last = dates[-1]
    W, U, R, C = (dts.get(k, {}) for k in ("WITHHELD", "DOL_UI", "REFUNDS_IND", "CUSTOMS"))
    if target in ("nfp", "retail"):
        if target == "nfp":
            chg = [obs[d] - obs[p] for p, d in zip(dates[-4:], dates[-3:])]
        else:
            chg = [100 * (obs[d] / obs[p] - 1) for p, d in zip(dates[-4:], dates[-3:])]
        base = st.fmean(chg)
        g = lag364_growth(W, cut, 20)
        hist = [lag364_growth(W, cutoff_for(target, month_add(period, -k)), 20) for k in range(1, 13)]
        if g is None or any(h is None for h in hist): return None, rows, cut, missing
        x = [base, 100 * (g - st.fmean(hist))]
        if target == "retail":
            rm, rl = month_sum(R, period), month_sum(R, month_add(period, -12))
            w12 = [month_sum(W, month_add(period, -k)) for k in range(1, 13)]
            if rm is None or rl is None or any(v is None for v in w12): return None, rows, cut, missing
            x.append(100 * (rm - rl) / st.fmean(w12))
        return {"x": x, "baseline": base}, rows, cut, missing
    if target == "claims":
        g_now, g_prev = lag364_growth(U, cut, 5), lag364_growth(U, cut - dt.timedelta(days=7), 5)
        prev = dates[-2]
        if g_now is None or g_prev is None: return None, rows, cut, missing
        return {"x": [math.log(obs[last] / obs[prev]), 100 * (g_now - g_prev)], "level_prev": obs[last], "baseline": obs[last] / 1000}, rows, cut, missing
    if target == "trade":
        g = lag364_growth(C, cut, 15)
        hist = [lag364_growth(C, cutoff_for("trade", month_add(period, -k)), 15) for k in range(1, 13)]
        if g is None or any(h is None for h in hist): return None, rows, cut, missing
        return {"x": [100 * (g - st.fmean(hist))], "level_prev": obs[last] / 1000, "baseline": obs[last] / 1000}, rows, cut, missing

def build(now=None, dts_store=None):
    now = now or utcnow()
    store = dts_store or (json.loads(SERIES_PATH.read_text()) if SERIES_PATH.exists() else {"series": {}})
    dts, asof = store.get("series", {}), store.get("asof")
    out = {"schema": "dts-bridge-1.0", "generated_at": iso(now), "valid_until_utc": iso(radar_valid_until(now)),
           "dts_asof": asof, "vintage": "latest_revised_targets_point_in_time_dts",
           "policy": {"edge_rule": f"vs baseline: improvement>={EDGE_MIN_IMPROVEMENT}% AND DM one-sided p<{EDGE_MAX_P} AND recent {RECENT} improvement>0; vs no-DTS ablation: improvement>=2% AND DM p<{EDGE_MAX_P}",
                      "covid_excluded": list(COVID), "rolling_window_months": ROLL, "min_train_months": MIN_TRAIN,
                      "ridge_lambda": 1.0, "first_release_verified": False, "probabilities": None},
           "models": {}}
    for target, spec in TARGETS.items():
        src, obs = load_target(spec["series"])
        entry = {"series_id": spec["series"], "unit": spec["unit"], "features": spec["features"],
                 "driver_en": spec["driver_en"], "driver_es": spec["driver_es"], "status": "UNAVAILABLE", "edge": "NONE"}
        out["models"][target] = entry
        if not obs or not asof: continue
        rows = build_rows(target, dts, obs)
        results = backtest(target, rows)
        ev = evaluate(results, backtest(target, ablate(target, rows)))
        entry["validation"] = ev
        entry["history"] = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in results[-36:]]
        if ev is None:
            entry["status"] = "INSUFFICIENT_HISTORY"; continue
        entry["edge"] = ev["edge"]
        last = sorted(obs)[-1]
        period = month_add(last[:7], 1) if spec["freq"] == "monthly" else (dt.date.fromisoformat(last) + dt.timedelta(days=7)).isoformat()
        live, hist_rows, cut, missing = live_row(target, dts, obs, period, asof)
        clean = [r for r in hist_rows if not in_covid(r["period"])]
        weekly = spec["freq"] == "weekly"
        model = ridge([q["x"] for q in clean[-(ROLL * (4 if weekly else 1)):]], [q["y"] for q in clean[-(ROLL * (4 if weekly else 1)):]]) if clean else None
        entry.update(reference_period=period if weekly else period, dts_cutoff_used=cut.isoformat(),
                     dts_cutoff_scheduled=cutoff_for(target, period).isoformat(), dts_sessions_missing=missing)
        if live is None or model is None:
            entry["status"] = "DTS_GAP"; continue
        fit = predict(model, live["x"])
        dts_idx = [i for i in range(len(live["x"])) if i not in NON_DTS[target]]
        contribution = sum(model["slopes"][i] * live["x"][i] for i in dts_idx)
        # Contribution in the published unit: difference between the full fit and the fit with DTS terms at zero.
        if target in ("claims", "trade"):
            contribution = to_level(target, live, fit) - to_level(target, live, fit - contribution)
        point = to_level(target, live, fit) if target in ("claims", "trade") else fit
        entry.update(status="PRELIMINARY" if missing else "FINAL_INFORMATION_SET",
                     point=point, baseline=live["baseline"],
                     range80=[point + ev["residual_p10"], point + ev["residual_p90"]],
                     coefficients={"intercept": model["intercept"], "slopes": dict(zip(spec["features"], model["slopes"]))},
                     feature_values=dict(zip(spec["features"], live["x"])), dts_contribution=contribution,
                     dts_direction=("UP" if contribution > 0 else "DOWN" if contribution < 0 else "FLAT"))
    atomic_json(OUT_PATH, out)
    return out

if __name__ == "__main__":
    import sys
    if "--rebuild" in sys.argv:
        import csv, gzip
        raw = Path(sys.argv[sys.argv.index("--rebuild") + 1])
        rd = lambda name: csv.DictReader(gzip.open(raw / name, "rt"))
        series = accumulate({}, rd("table2.csv.gz"), rd("table4_ftd.csv.gz"), rd("table5.csv.gz"))
        atomic_json(SERIES_PATH, {"series": {k: dict(sorted(v.items())) for k, v in series.items()},
                                  "asof": max(max(v) for v in series.values()), "updated_at": iso(utcnow()),
                                  "units": "USD_millions", "source": API,
                                  "note": "Daily 'today' amounts; withheld taxes before 2023-02-14 come from Table IV (federal tax deposits)."}, compact=True)
    if "--update" in sys.argv:
        update_series(utcnow())
    result = build()
    for k, m in result["models"].items():
        v = m.get("validation") or {}
        print(k, m["status"], m["edge"], v.get("n"), v.get("improvement_pct"), v.get("dm_p_one_sided"), v.get("recent_improvement_pct"), m.get("point"))
