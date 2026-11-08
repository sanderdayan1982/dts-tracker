"""GATE RNG — HAR range-variance forecast vs desk sigma21. Spec: PRE-REG_GATE_RNG.md (frozen).
Usage: python3 gate_rng.py <ohlcv.csv> <partition: dev|conf> <out_dir> [label] [PAIR,PAIR,...|all]
"""
import sys, json, math
import numpy as np, pandas as pd
from scipy import stats

SRC, PART, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
LABEL = sys.argv[4] if len(sys.argv) > 4 else "majors"
SEL = None if len(sys.argv) <= 5 or sys.argv[5] == "all" else set(sys.argv[5].split(","))
WIN = {"dev": ("2019-01-01", "2022-12-31"), "conf": ("2023-01-01", "2026-06-30")}[PART]
MIN_TRAIN = 750

df = pd.read_csv(SRC, parse_dates=["date"])
df = df[(df.n_hours >= 20) & (df.high > df.low)].copy()
if SEL is not None:
    df = df[df.pair.isin(SEL)].copy()
NPAIRS = df.pair.nunique()
NEED = math.ceil(6 / 7 * NPAIRS - 1e-9)  # frozen ratio of G3 (6 of 7)
df["v"] = np.log(df.high / df.low) ** 2 / (4 * math.log(2))

def nw_dm(d, lags):
    d = np.asarray(d); n = len(d); m = d.mean(); u = d - m
    s = u @ u / n
    for k in range(1, lags + 1):
        s += 2 * (1 - k / (lags + 1)) * (u[k:] @ u[:-k]) / n
    t = m / math.sqrt(s / n)
    return t, stats.norm.cdf(t)  # one-sided: HAR loss lower => d<0 => small p

def qlike(y, f): r = y / f; return r - np.log(r) - 1

rows = []
for pair, g in df.groupby("pair"):
    g = g.sort_values("date").reset_index(drop=True)
    v = g.v.values; n = len(v); lv = np.log(v)
    m5 = pd.Series(v).rolling(5).mean().values
    m21 = pd.Series(v).rolling(21).mean().values
    m22 = pd.Series(v).rolling(22).mean().values
    ew = pd.Series(v).ewm(alpha=0.06, adjust=False).mean().values
    X = np.column_stack([np.ones(n), lv, np.log(m5), np.log(m22)])
    for h in (1, 5):
        y = np.full(n, np.nan)
        for t in range(n - h):
            y[t] = v[t + 1] if h == 1 else v[t + 1:t + 1 + h].mean()
        ly = np.log(y)
        for t in range(n - h):
            d = g.date[t]
            if not (pd.Timestamp(WIN[0]) <= d <= pd.Timestamp(WIN[1])):
                continue
            # training rows s with target known at t: s + h <= t
            idx = np.arange(22, t - h + 1)
            idx = idx[np.isfinite(ly[idx]) & np.isfinite(X[idx]).all(1)]
            if len(idx) < MIN_TRAIN or not np.isfinite(X[t]).all():
                continue
            b, *_ = np.linalg.lstsq(X[idx], ly[idx], rcond=None)
            res = ly[idx] - X[idx] @ b
            f_har = math.exp(X[t] @ b + 0.5 * res.var())
            rows.append(dict(pair=pair, h=h, date=d, y=y[t], har=f_har, b1=m21[t], b2=v[t], b3=ew[t]))

R = pd.DataFrame(rows)
for m in ("har", "b1", "b2", "b3"):
    R["q_" + m] = qlike(R.y, R[m]); R["e_" + m] = (R.y - R[m]) ** 2
R.to_csv(f"{OUT}/rng_forecasts_{LABEL}_{PART}.csv", index=False)

res = {"label": LABEL, "partition": PART, "window": WIN, "n": int(len(R)), "by_h": {}}
for h in (1, 5):
    S = R[R.h == h].sort_values(["date", "pair"])
    Q = {m: S["q_" + m].mean() for m in ("har", "b1", "b2", "b3")}
    daily = S.groupby("date").apply(lambda x: (x.q_har - x.q_b1).mean())
    t, p = nw_dm(daily.values, h + 4)
    per = {}
    for pair, x in S.groupby("pair"):
        tp, pp = nw_dm((x.q_har - x.q_b1).values, h + 4)
        per[pair] = dict(n=len(x), qlike_har=round(x.q_har.mean(), 4), qlike_b1=round(x.q_b1.mean(), 4),
                         gain_pct=round(100 * (1 - x.q_har.mean() / x.q_b1.mean()), 2), dm_p=round(pp, 4))
    gain = 100 * (1 - Q["har"] / Q["b1"])
    wins = sum(1 for v in per.values() if v["gain_pct"] > 0)
    G = dict(G1=gain >= 5, G2=p < 0.05, G3=wins >= NEED, G4=Q["har"] <= Q["b2"] and Q["har"] <= Q["b3"])
    res["by_h"][h] = dict(qlike={k: round(v, 4) for k, v in Q.items()}, gain_vs_b1_pct=round(gain, 2),
                          gain_vs_b2_pct=round(100 * (1 - Q["har"] / Q["b2"]), 2),
                          gain_vs_b3_pct=round(100 * (1 - Q["har"] / Q["b3"]), 2),
                          dm_t=round(t, 3), dm_p=float(f"{p:.3g}"), pairs_won=f"{wins}/{NPAIRS}", pairs_needed=NEED,
                          mse_gain_vs_b1_pct=round(100 * (1 - S.e_har.mean() / S.e_b1.mean()), 2),
                          gates={k: bool(v) for k, v in G.items()}, PASS=bool(all(G.values())), per_pair=per)
json.dump(res, open(f"{OUT}/rng_result_{LABEL}_{PART}.json", "w"), indent=1, default=str)
print(json.dumps({h: {k: v for k, v in d.items() if k != "per_pair"} for h, d in res["by_h"].items()}, indent=1, default=str))
