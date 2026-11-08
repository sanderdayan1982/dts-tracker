"""Download Dukascopy daily BID candles (yearly .bi5 files) for the 28 G8 pairs + XAUUSD.
Output: one CSV in RSF_daily_ohlcv format (date,open,high,low,close,volume,n_hours,pair).
Dukascopy day candles are anchored at 00:00 UTC. n_hours is set to 24 on weekdays and 0 on
weekends, so the frozen filter (n_hours >= 20) drops weekend stubs.
Usage: python fetch_dukascopy_daily.py OUT.csv 2016 2026
"""
import csv, lzma, struct, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

CCY = ["USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"]
ORDER = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]  # market quoting convention


def pairs():
    out = []
    for i, a in enumerate(ORDER):
        for b in ORDER[i + 1:]:
            out.append(a + b)
    return out + ["XAUUSD"]


def point(sym):
    if sym == "XAUUSD":
        return 1e3
    return 1e3 if sym.endswith("JPY") else 1e5


def fetch(sym, year, tries=4):
    url = f"https://datafeed.dukascopy.com/datafeed/{sym}/{year}/BID_candles_day_1.bi5"
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "g8-research/1.0"})
            raw = urllib.request.urlopen(req, timeout=60).read()
            return lzma.decompress(raw) if raw else b""
        except Exception as exc:  # noqa: BLE001
            if k == tries - 1:
                print(f"FAIL {sym} {year}: {exc}", file=sys.stderr)
                return None
            time.sleep(2 + 3 * k)


def main(out, y0, y1):
    syms = pairs()
    assert len(syms) == 29, len(syms)
    rows, missing = [], []
    for sym in syms:
        pt = point(sym)
        for year in range(y0, y1 + 1):
            data = fetch(sym, year)
            if data is None:
                missing.append(f"{sym}:{year}")
                continue
            base = datetime(year, 1, 1, tzinfo=timezone.utc)
            for off in range(0, len(data) - 23, 24):
                t, o, c, lo, hi, vol = struct.unpack(">5if", data[off:off + 24])
                d = base + timedelta(seconds=t)
                weekday = d.weekday() < 5
                rows.append([d.date().isoformat(), o / pt, hi / pt, lo / pt, c / pt, round(vol, 2),
                             24 if weekday else 0, sym])
        print(sym, "ok", flush=True)
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "open", "high", "low", "close", "volume", "n_hours", "pair"])
        w.writerows(sorted(rows, key=lambda r: (r[7], r[0])))
    print(f"rows={len(rows)} missing={missing}")
    if missing:
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
