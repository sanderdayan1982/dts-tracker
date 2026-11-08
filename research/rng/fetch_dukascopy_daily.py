"""Download Dukascopy daily BID candles (yearly .bi5 files) for the 28 G8 pairs + XAUUSD.
Output: one CSV in RSF_daily_ohlcv format (date,open,high,low,close,volume,n_hours,pair).
Completed years: yearly day candles (00:00 UTC), n_hours = 24 on weekdays, 0 on weekends.
Current year: monthly hour candles aggregated to UTC days, n_hours = real traded hours.
The frozen filter (n_hours >= 20) drops weekend and holiday stubs in both cases.
Usage: python fetch_dukascopy_daily.py OUT.csv 2016 2026
"""
import csv, lzma, os, struct, sys, time, urllib.error, urllib.request
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


CACHE = os.environ.get("DK_CACHE", "/tmp/dkcache")


def fetch_path(path, tries=8):
    """Polite fetch with on-disk cache. Returns bytes, b"" for a real 404, None on failure."""
    os.makedirs(CACHE, exist_ok=True)
    cpath = os.path.join(CACHE, path.replace("/", "_"))
    if os.path.exists(cpath):
        return open(cpath, "rb").read()
    url = "https://datafeed.dukascopy.com/datafeed/" + path
    for k in range(tries):
        time.sleep(1.0)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "g8-research/1.0"})
            raw = urllib.request.urlopen(req, timeout=60).read()
            data = lzma.decompress(raw) if raw else b""
            open(cpath, "wb").write(data)
            return data
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return b""
            wait = min(90, 5 * 2 ** k)
        except Exception:  # noqa: BLE001
            wait = min(90, 5 * 2 ** k)
        time.sleep(wait)
    print(f"FAIL {path}", file=sys.stderr, flush=True)
    return None


def year_rows(sym, year, pt):
    """Completed years: one yearly file of day candles."""
    data = fetch_path(f"{sym}/{year}/BID_candles_day_1.bi5")
    if data is None:
        return None
    base = datetime(year, 1, 1, tzinfo=timezone.utc)
    rows = []
    for off in range(0, len(data) - 23, 24):
        t, o, c, lo, hi, vol = struct.unpack(">5if", data[off:off + 24])
        d = base + timedelta(seconds=t)
        rows.append([d.date().isoformat(), o / pt, hi / pt, lo / pt, c / pt, round(vol, 2),
                     24 if d.weekday() < 5 else 0, sym])
    return rows


def month_rows(sym, year, month0, pt):
    """Current year: monthly files of hour candles, aggregated to UTC days (n_hours = real count)."""
    data = fetch_path(f"{sym}/{year}/{month0:02d}/BID_candles_hour_1.bi5")
    if data is None:
        return None
    base = datetime(year, month0 + 1, 1, tzinfo=timezone.utc)
    days = {}
    for off in range(0, len(data) - 23, 24):
        t, o, c, lo, hi, vol = struct.unpack(">5if", data[off:off + 24])
        if vol <= 0:
            continue  # empty hour (market closed)
        d = (base + timedelta(seconds=t)).date().isoformat()
        if d not in days:
            days[d] = [o, hi, lo, c, vol, 1]
        else:
            r = days[d]
            r[1] = max(r[1], hi); r[2] = min(r[2], lo); r[3] = c; r[4] += vol; r[5] += 1
    return [[d, r[0] / pt, r[1] / pt, r[2] / pt, r[3] / pt, round(r[4], 2), r[5], sym] for d, r in sorted(days.items())]


def main(out, y0, y1):
    syms = pairs()
    assert len(syms) == 29, len(syms)
    rows, missing = [], []
    now = datetime.now(timezone.utc)
    for sym in syms:
        pt = point(sym)
        for year in range(y0, y1 + 1):
            if year < now.year:
                got = year_rows(sym, year, pt)
                if got is None:
                    missing.append(f"{sym}:{year}")
                else:
                    rows += got
            else:
                for m0 in range(0, now.month - 1):  # completed months only
                    got = month_rows(sym, year, m0, pt)
                    if got is None:
                        missing.append(f"{sym}:{year}-{m0 + 1:02d}")
                    else:
                        rows += got
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
