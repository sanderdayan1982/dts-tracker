#!/usr/bin/env python3
"""Official-series release radar. Transparent statistical baselines, never invented consensus.

Monthly/weekly data are the latest revised vintage. Walk-forward holdouts measure
historical accuracy on that vintage, NOT real-time first-release trading performance.
Only the immutable forward archive can establish the latter after deployment.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import csv
import datetime as dt
import hashlib
import html
import io
import json
import math
import re
import statistics as stats
import time
import urllib.request
from pathlib import Path
from argos_dts import dts_summary, attach_dts_drivers
import dts_bridge
from fiscal_pulse import build_pulse, pulse_contract
from institutional_core import atomic_json, cash_contract, finite, iso, parse_time, radar_valid_until, utcnow

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Units are explicit. ICSA is published in persons; our display is thousands.
SERIES = {
    "nfp": {"id":"PAYEMS", "frequency":"monthly", "transform":"difference", "unit":"thousand_jobs", "agency":"BLS", "group":"labor", "sign":1},
    "unemployment": {"id":"UNRATE", "frequency":"monthly", "transform":"level", "unit":"percent", "agency":"BLS", "group":"labor", "sign":-1},
    "claims": {"id":"ICSA", "frequency":"weekly", "transform":"level", "scale":.001, "unit":"thousand_claims", "agency":"DOL", "group":"labor", "sign":-1},
    "retail": {"id":"RSAFS", "frequency":"monthly", "transform":"pct", "unit":"percent_mom", "agency":"Census", "group":"growth", "sign":1},
    "cpi": {"id":"CPIAUCSL", "frequency":"monthly", "transform":"pct", "unit":"percent_mom", "agency":"BLS", "group":"inflation", "sign":1},
    "core_cpi": {"id":"CPILFESL", "frequency":"monthly", "transform":"pct", "unit":"percent_mom", "agency":"BLS", "group":"inflation", "sign":1},
    "core_pce": {"id":"PCEPILFE", "frequency":"monthly", "transform":"pct", "unit":"percent_mom", "agency":"BEA", "group":"inflation", "sign":1},
    "production": {"id":"INDPRO", "frequency":"monthly", "transform":"pct", "unit":"percent_mom", "agency":"Federal Reserve", "group":"growth", "sign":1},
    "housing": {"id":"HOUST", "frequency":"monthly", "transform":"level", "unit":"thousand_homes_saar", "agency":"Census / HUD", "group":"growth", "sign":1},
    "trade": {"id":"BOPGSTB", "frequency":"monthly", "transform":"level", "scale":.001, "unit":"usd_billions", "agency":"BEA / Census", "group":"growth", "sign":1},
}
CONTEXT = {
    "reserves": {"id":"WRESBAL","frequency":"weekly","unit":"usd_billions","scale":.001,"basis":"weekly_average"},
    "fed_assets": {"id":"WALCL","frequency":"weekly","unit":"usd_billions","scale":.001,"basis":"wednesday_level"},
    "bank_credit": {"id":"TOTBKCR","frequency":"weekly","unit":"usd_billions","scale":1,"basis":"weekly_sa"},
    "rrp": {"id":"RRPONTSYD","frequency":"daily","unit":"usd_billions","scale":1,"basis":"daily_operation"},
    "two_year": {"id":"DGS2","frequency":"daily","unit":"percent","scale":1,"basis":"constant_maturity"},
    "ten_year": {"id":"DGS10","frequency":"daily","unit":"percent","scale":1,"basis":"constant_maturity"},
    "financial_stress": {"id":"STLFSI4","frequency":"weekly","unit":"standard_deviations","scale":1,"basis":"st_louis_fed_index"},
}

def request_text(url):
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"DTS-Tracker/6.0 official data research","Accept":"text/csv,text/html,*/*"})
            with urllib.request.urlopen(req, timeout=25) as response:
                return response.read().decode("utf-8-sig")
        except Exception as exc:
            last = exc
            if attempt < 2: time.sleep(2**attempt)
    raise RuntimeError(f"{type(last).__name__}: official feed unavailable")

def parse_csv(text, series_id, now):
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or series_id not in reader.fieldnames:
        raise ValueError("Unexpected FRED CSV schema")
    date_key = reader.fieldnames[0]
    found = {}
    for row in reader:
        try:
            date = dt.date.fromisoformat(row[date_key])
            value = float(row[series_id])
        except (ValueError, TypeError, KeyError):
            continue
        if date > now.date() or not finite(value): continue
        if date.isoformat() in found: raise ValueError("Duplicate observation date")
        found[date.isoformat()] = value
    if not found: raise ValueError("Empty official series")
    return [{"date":d,"value":found[d]} for d in sorted(found)]

def load_series(spec, now, offline=False):
    sid = spec["id"]
    path = DATA / "sources" / f"{sid}.json"
    if offline:
        result = json.loads(path.read_text()) if path.exists() else {"observations":[],"status":"UNAVAILABLE"}
        result["mode"] = "cached_replay"
        return result
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=2010-01-01"
    try:
        body = request_text(url)
        observations = parse_csv(body, sid, now)
        result = {"series_id":sid,"status":"OK","retrieved_at":iso(now),
                  "source_url":f"https://fred.stlouisfed.org/series/{sid}","download_url":url,
                  "sha256":hashlib.sha256(body.encode()).hexdigest(),"vintage":"latest_revised",
                  "observations":observations,"next_release_date":None}
        # FRED's primary-source series page supplies the next release date without guessing a weekday.
        try:
            page = request_text(result["source_url"])
            plain = html.unescape(re.sub(r"<[^>]+>"," ",page))
            match = re.search(r"Next Release Date\s*:\s*([A-Za-z]{3,9}\.?\s+\d{1,2},\s*\d{4})",plain)
            if match:
                label = re.sub(r"\s+", " ", match.group(1)).replace(".", "")
                for fmt in ("%b %d, %Y", "%B %d, %Y"):
                    try:
                        result["next_release_date"] = dt.datetime.strptime(label,fmt).date().isoformat()
                        break
                    except ValueError: pass
        except Exception:
            result["calendar_status"] = "UNVERIFIED"
        atomic_json(path, result, compact=True)
        return result
    except Exception as exc:
        previous = json.loads(path.read_text()) if path.exists() else {"observations":[]}
        previous.update(status="FETCH_FAIL", last_attempt_at=iso(now),error=str(exc))
        # Preserve the data vintage and old observations; never freshen a failed download.
        atomic_json(path, previous, compact=True)
        return previous

def quantile(values, probability):
    ordered = sorted(values)
    if not ordered: return None
    index = (len(ordered)-1)*probability
    lo = int(index); hi = min(lo+1,len(ordered)-1)
    return ordered[lo]+(ordered[hi]-ordered[lo])*(index-lo)

def month_step(date):
    day = dt.date.fromisoformat(date)
    return dt.date(day.year+(day.month==12), day.month%12+1, 1).isoformat()

def transform(observations, spec):
    rows=[]
    scale=spec.get("scale",1)
    for i,row in enumerate(observations):
        value=row["value"]*scale
        if spec["transform"] != "level":
            if i==0: continue
            prior=observations[i-1]["value"]*scale
            consecutive = (month_step(observations[i-1]["date"])==row["date"] if spec["frequency"]=="monthly"
                           else (dt.date.fromisoformat(row["date"])-dt.date.fromisoformat(observations[i-1]["date"])).days==7)
            value=(value-prior if spec["transform"]=="difference" else (100*(value/prior-1) if prior>0 else None)) if consecutive else None
        rows.append({"date":row["date"],"value":value})
    return rows

def continuous(rows, frequency):
    for a,b in zip(rows, rows[1:]):
        expected = month_step(a["date"]) if frequency=="monthly" else (dt.date.fromisoformat(a["date"])+dt.timedelta(days=7)).isoformat()
        if expected != b["date"]: return False
    return True

def baseline(values, mode):
    return values[-1] if mode=="level" else stats.fmean(values[-3:])

def autoregression(values):
    """AR(1), rolling 120 observations, fixed ridge shrinkage; no hyperparameter search."""
    values=values[-120:]
    pairs=[(a,b) for a,b in zip(values,values[1:]) if finite(a) and finite(b)]
    if len(pairs)<12:return values[-1]
    x,y=zip(*pairs)
    mx,my=stats.fmean(x),stats.fmean(y)
    variance=sum((v-mx)**2 for v in x)
    slope=sum((a-mx)*(b-my) for a,b in zip(x,y))/(variance*1.1+1e-12)
    slope=max(-.95,min(.95,slope))
    return my+slope*(values[-1]-mx)

def estimate(values, mode):
    if sum(finite(v) for v in values)<120 or not all(finite(v) for v in values[-3:]): return None
    # Last 60 origins: first 30 choose AR vs naive, last 30 are untouched holdout.
    errors={"baseline":[],"ar1":[]}
    origins=[i for i in range(60,len(values)) if all(finite(v) for v in values[i-3:i+1])][-60:]
    if len(origins)<60:return None
    for i in origins:
        past=values[:i]
        errors["baseline"].append(values[i]-baseline(past,mode))
        errors["ar1"].append(values[i]-autoregression(past))
    mae=lambda seq:stats.fmean(abs(v) for v in seq)
    selected="ar1" if mae(errors["ar1"][:30]) < .95*mae(errors["baseline"][:30]) else "baseline"
    # The holdout never promotes a model. It can only demote the selected AR1 back to the
    # simpler null model when AR1 fails to beat it out of sample (conservative guard).
    naive_mae=mae(errors["baseline"][30:])
    ar1_holdout_mae=mae(errors["ar1"][30:])
    demoted=selected=="ar1" and not ar1_holdout_mae<naive_mae
    choice="baseline" if demoted else selected
    residuals=errors[choice][30:]
    selected_mae=mae(residuals)
    point=autoregression(values) if choice=="ar1" else baseline(values,mode)
    beats=choice=="ar1" and selected_mae<.95*naive_mae
    return {"point":point,"range80":[point+quantile(residuals,.1),point+quantile(residuals,.9)],
            "method":choice,"selected_on_training":selected,"demoted_on_holdout":demoted,
            "edge":"DEMONSTRATED" if beats else "NONE",
            "validation":{"kind":"chronological_latest_vintage_holdout", "selection_n":30,"holdout_n":30,
            "mae":selected_mae,"baseline_mae":naive_mae,"ar1_holdout_mae":ar1_holdout_mae,
            "improvement_pct":100*(1-selected_mae/naive_mae) if naive_mae>0 else None,
            "beats_baseline":beats,
            "first_release_verified":False},
            "probability_above_consensus":None}

def verified_consensus(config, target, period, unit, now):
    entry=config.get(target,{})
    captured=parse_time(entry.get("captured_at")); release=parse_time(entry.get("release_at"))
    valid=(finite(entry.get("value")) and entry.get("reference_period")==period and entry.get("unit")==unit
           and entry.get("source") and captured is not None and release is not None
           and captured<=now<release and captured<release and now-captured<=dt.timedelta(days=7))
    return entry if valid else None

# Market consensus from the desk's own RadarNews feed (ForexFactory calendar, refreshed every 5 min).
RADAR_NEWS_URL="https://raw.githubusercontent.com/sanderdayan1982/g8-radar-news/main/public/data/radar_news_full.json"
FF_TITLES={"nfp":"Non-Farm Employment Change","unemployment":"Unemployment Rate","claims":"Unemployment Claims",
           "retail":"Retail Sales m/m","cpi":"CPI m/m","core_cpi":"Core CPI m/m","core_pce":"Core PCE Price Index m/m",
           "production":"Industrial Production m/m","housing":"Housing Starts","trade":"Trade Balance"}
FF_SCALE={"K":1e3,"M":1e6,"B":1e9,"T":1e12}
UNIT_DIVISOR={"thousand_jobs":1e3,"thousand_claims":1e3,"thousand_homes_saar":1e3,"usd_billions":1e9}

def parse_ff_value(text,unit):
    """'65K'->65 thousand jobs, '0.3%'->0.3, '-107.9B'->-107.9 bn, '1.32M'->1320 thousand homes. None if not numeric."""
    m=re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*([KMBT%]?)\s*",str(text or ""))
    if not m:return None
    value,suffix=float(m.group(1)),m.group(2)
    if unit in UNIT_DIVISOR:
        return value*FF_SCALE.get(suffix,1)/UNIT_DIVISOR[unit] if suffix in FF_SCALE else None
    return value if suffix in ("%","") else None

def radar_news_consensus(cards,now,feed=None):
    """Same release only: FF title + New York release date equal to the card's verified FRED release date."""
    if feed is None:
        try: feed=json.loads(request_text(RADAR_NEWS_URL))
        except Exception as exc:
            print("consensus feed unavailable:",type(exc).__name__); return {}
    captured=parse_time(str(feed.get("generated_at","")).replace(".000Z","Z"))
    if captured is None or captured>now+dt.timedelta(minutes=5):return {}
    out={}
    for card in cards:
        title=FF_TITLES.get(card["id"])
        if not title or not card.get("release_date") or not card.get("reference_period"):continue
        for ev in feed.get("calendar",[]):
            at=parse_time(str(ev.get("event_at","")).replace(".000Z","Z"))
            if ev.get("currency")!="USD" or ev.get("title")!=title or at is None:continue
            # 13:30Z -> 08:30 ET. A 5h shift keeps 08:30/10:00 ET releases on their New York date in both EST and EDT.
            if (at-dt.timedelta(hours=5)).date().isoformat()!=card["release_date"]:continue
            value=parse_ff_value(ev.get("forecast"),card["unit"])
            if value is None:continue
            out[card["id"]]={"value":value,"reference_period":card["reference_period"],"unit":card["unit"],
                             "source":"ForexFactory via G8 RadarNews","source_text":ev.get("forecast"),
                             "captured_at":iso(min(captured,now)),"release_at":iso(at),"automatic":True}
    return out

def apply_consensus(card,entry):
    if not entry or not card.get("forecast"):return card
    card["consensus"]=entry
    card["model_minus_consensus"]=card["forecast"]["point"]-entry["value"]
    card["surprise_bias"]="RESEARCH_GAP_ONLY"
    if "NOT_MARKET_CONSENSUS" in card["flags"]:card["flags"].remove("NOT_MARKET_CONSENSUS")
    return card

def make_card(key,spec,source,now,consensus):
    observations=source.get("observations",[])
    rows=transform(observations,spec)
    card={"id":key,"group":spec["group"],"series_id":spec["id"],"agency":spec["agency"],"unit":spec["unit"],
          "frequency":spec["frequency"],"source_url":f"https://fred.stlouisfed.org/series/{spec['id']}",
          "source_retrieved_at":source.get("retrieved_at"),"source_sha256":source.get("sha256"),
          "release_date":source.get("next_release_date"),"status":"UNAVAILABLE","forecast":None,
          "consensus":None,"surprise_bias":"NOT_ESTIMATED","probability_above_consensus":None,
          "direction_vs_previous":None,"signal":None,"flags":[],"history":rows[-36:]}
    if not rows:return card
    last=rows[-1]; day=dt.date.fromisoformat(last["date"])
    card.update(last=last["value"],observed_period=last["date"],
                reference_period=month_step(last["date"])[:7] if spec["frequency"]=="monthly" else (day+dt.timedelta(days=7)).isoformat())
    observation_age=(now.date()-day).days
    retrieved=parse_time(source.get("retrieved_at"))
    stale=(observation_age>(80 if spec["frequency"]=="monthly" else 16)
           or retrieved is None or now-retrieved>dt.timedelta(hours=26))
    if source.get("status")!="OK" or stale:
        card.update(status="STALE" if stale else "FETCH_FAIL")
        return card
    if not continuous(observations[-3:],spec["frequency"]) or not all(finite(r["value"]) for r in rows[-3:]):
        card.update(status="DATA_GAP");return card
    # Preserve holes in the historical sequence. Do not interpolate a shutdown or
    # call a two-month price change a one-month change. Skip invalid forecast origins.
    dense=[]; by_date={r["date"]:r["value"] for r in rows}; d=rows[0]["date"]
    while d<=rows[-1]["date"]:
        dense.append(by_date.get(d))
        d=month_step(d) if spec["frequency"]=="monthly" else (dt.date.fromisoformat(d)+dt.timedelta(days=7)).isoformat()
    forecast=estimate(dense,spec["transform"])
    if forecast is None:
        card.update(status="INSUFFICIENT_HISTORY");return card
    # Physical bounds apply to a level, never to payroll change or the trade balance.
    if key in ("claims","housing","unemployment"):
        forecast["point"]=max(0,forecast["point"])
        forecast["range80"]=[max(0,x) for x in forecast["range80"]]
    card.update(status="RESEARCH_ESTIMATE",forecast=forecast,edge=forecast["edge"],
                flags=["LATEST_REVISED_DATA", "NOT_FIRST_RELEASE_VALIDATED", "NOT_MARKET_CONSENSUS"])
    if forecast["edge"]=="NONE":card["flags"].append("NO_DEMONSTRATED_EDGE")
    if forecast["demoted_on_holdout"]:card["flags"].append("AR1_DEMOTED_ON_HOLDOUT")
    if any(v is None for v in dense):card["flags"].append("HISTORICAL_GAPS_SKIPPED_NOT_IMPUTED")
    delta=forecast["point"]-last["value"]
    # Use forecast uncertainty to distinguish a material change from noise.
    material=max(forecast["validation"]["mae"]*.25,1e-9)
    direction=1 if delta>material else -1 if delta < -material else 0
    card["direction_vs_previous"]=direction
    card["signal"]=("HOTTER" if direction>0 else "COOLER" if direction<0 else "SIMILAR") if spec["group"]=="inflation" else ("STRONGER" if direction*spec["sign"]>0 else "WEAKER" if direction*spec["sign"]<0 else "SIMILAR")
    entry=verified_consensus(consensus,key,card["reference_period"],spec["unit"],now)
    if entry:
        card["consensus"]=entry
        card["model_minus_consensus"]=forecast["point"]-entry["value"]
        # A numerical research gap is useful; it is not a calibrated probability or trading permission.
        card["surprise_bias"]="RESEARCH_GAP_ONLY"
        card["flags"].remove("NOT_MARKET_CONSENSUS")
    return card

def context_card(key,spec,source,now):
    rows=source.get("observations",[])
    out={"id":key,"series_id":spec["id"],"source_url":f"https://fred.stlouisfed.org/series/{spec['id']}",
         "unit":spec["unit"],"frequency":spec["frequency"],"basis":spec["basis"],"status":"UNAVAILABLE",
         "observed_at":None,"value":None,"change":None,"history":[]}
    if not rows:return out
    r=rows[-1]; retrieved=parse_time(source.get("retrieved_at"))
    valid=(source.get("status")=="OK" and retrieved is not None and now-retrieved<dt.timedelta(hours=26)
           and (now.date()-dt.date.fromisoformat(r["date"])).days<=(7 if spec["frequency"]=="daily" else 21))
    out.update(status="OK" if valid else "STALE",observed_at=r["date"],value=r["value"]*spec["scale"],
               change=(r["value"]-rows[-2]["value"])*spec["scale"] if len(rows)>1 else None,
               history=[{"date":x["date"],"value":x["value"]*spec["scale"]} for x in rows[-60:]])
    return out

def bridge_view(model, card):
    """Compact, fail-closed projection of a DTS bridge model onto a radar card."""
    if not model or model.get("reference_period")!=card.get("reference_period") or "point" not in model:
        return {"status":"UNAVAILABLE","edge":"NONE"}
    v=model.get("validation") or {}; added=v.get("dts_added_value") or {}
    r=lambda x,d=4:round(x,d) if finite(x) else None
    return {"status":model["status"],"edge":model["edge"],"point":r(model["point"]),"range80":[r(x) for x in model["range80"]],
            "baseline":r(model.get("baseline")),"dts_contribution":r(model.get("dts_contribution")),"dts_direction":model.get("dts_direction"),
            "dts_asof":model.get("dts_cutoff_used"),"dts_cutoff_scheduled":model.get("dts_cutoff_scheduled"),
            "dts_sessions_missing":model.get("dts_sessions_missing"),"driver_en":model.get("driver_en"),"driver_es":model.get("driver_es"),
            "validation":{"n":v.get("n"),"first":v.get("first"),"last":v.get("last"),"improvement_pct":r(v.get("improvement_pct"),2),
                          "dm_p_one_sided":r(v.get("dm_p_one_sided"),3),"recent_improvement_pct":r(v.get("recent_improvement_pct"),2),
                          "added_value_pct":r(added.get("improvement_pct"),2),"added_value_dm_p":r(added.get("dm_p_one_sided"),3),
                          "mae_bridge":r(v.get("mae_bridge")),"mae_baseline":r(v.get("mae_baseline"))}}

def attach_bridge(cards,now,offline):
    """DTS bridge v7. Any failure leaves an explicit UNAVAILABLE state; it never blocks the radar."""
    try:
        store=None
        if not offline:
            try: store=dts_bridge.update_series(now)
            except Exception as exc: print("bridge DTS update failed:",type(exc).__name__)
        result=dts_bridge.build(now,store)
        stale=result.get("dts_asof") is None or (now.date()-dt.date.fromisoformat(result["dts_asof"])).days>10
    except Exception as exc:
        print("bridge failed:",type(exc).__name__,exc); result,stale={"models":{}},True
    for card in cards:
        if card["id"] not in dts_bridge.TARGETS: continue
        view=bridge_view(None if stale else result["models"].get(card["id"]),card)
        card["dts_bridge"]=view
        # The bridge replaces the published estimate only with a demonstrated DTS contribution.
        card["primary_estimate"]="DTS_BRIDGE" if view["edge"]=="DEMONSTRATED" and card.get("forecast") else "STATISTICAL"

def main(offline=False):
    now=utcnow()
    specs={**SERIES,**CONTEXT}
    sources={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(load_series,spec,now,offline):key for key,spec in specs.items()}
        for future in concurrent.futures.as_completed(futures):
            key=futures[future]
            try:sources[key]=future.result()
            except Exception as exc:sources[key]={"status":"UNAVAILABLE","observations":[],"error":type(exc).__name__}
            print(key,sources[key].get("status"),len(sources[key].get("observations",[])))
    config_path=DATA/"consensus.json"
    consensus=json.loads(config_path.read_text()) if config_path.exists() else {}
    cards=[make_card(k,spec,sources[k],now,consensus) for k,spec in SERIES.items()]
    # File entries take precedence; otherwise the desk's RadarNews feed supplies the consensus automatically.
    auto={} if offline else radar_news_consensus(cards,now)
    for card in cards:
        if not card.get("consensus") and card["id"] in auto:
            apply_consensus(card,verified_consensus(auto,card["id"],card.get("reference_period"),card["unit"],now))
    context=[context_card(k,spec,sources[k],now) for k,spec in CONTEXT.items()]
    dts_path=DATA/"dts_nowcast.json"
    dts=json.loads(dts_path.read_text()) if dts_path.exists() else {}
    dts=cash_contract(dts,now)
    summary=dts_summary(dts,now)
    attach_dts_drivers(cards,summary)
    attach_bridge(cards,now,offline)
    valid_until=radar_valid_until(now)
    for card in cards:
        if card.get("consensus"):
            valid_until=min(valid_until,parse_time(card["consensus"]["release_at"]))
    payload={"schema":"macro-radar-1.0","generated_at":iso(now),"valid_until_utc":iso(valid_until),
             "mode":"cached_replay" if offline else "live_fetch", "cards":cards,"context":context,
             "dts_asof":dts.get("asof"),"dts_status":dts.get("dq",{}).get("status"),
             "research_policy":"NO_AUTOTRADE_NO_SURPRISE_PROBABILITY_BEFORE_FIRST_RELEASE_VALIDATION"}
    atomic_json(DATA/"macro_radar.json",payload)
    # Fiscal pulse: DTS cash vs the same session last year (reading of direction, not a release forecast).
    try:
        book=json.loads((DATA/"treasury_book.json").read_text()) if (DATA/"treasury_book.json").exists() else {}
        pulse=pulse_contract(build_pulse(book,sources.get("cpi",{}).get("observations",[]),now),now)
    except Exception as exc:
        print("fiscal pulse failed:",type(exc).__name__,exc); pulse={"schema":"fiscal-pulse-1.0","status":"UNAVAILABLE","indicators":[]}
    atomic_json(DATA/"fiscal_pulse.json",pulse,compact=True)
    # Immutable issue snapshots: never rewrite a previously issued forecast of the same vintage.
    if not offline:
        archive=DATA/"forecast_archive"/now.strftime("%Y-%m-%d")
        for c in cards:
            if c["status"]=="RESEARCH_ESTIMATE":
                path=archive/f"{c['id']}-{c['reference_period']}.json"
                if not path.exists(): atomic_json(path,{"issued_at":iso(now),"card":c},compact=True)
    # Compact contract for ARGOS. Explicit directions refer to previous data, never surprise odds.
    compact={"v":1,"at":iso(now),"expires":iso(valid_until),"dts":summary,
             "basis":"research_vs_previous_not_consensus","probabilities":None,"events":[]}
    for c in cards:
        f=c.get("forecast")
        compact["events"].append({"id":c["id"],"period":c.get("reference_period"),"unit":c["unit"],"status":c["status"],
                                  "point":round(f["point"],3) if f else None,"edge":c.get("edge"),
                                  # Fail closed: a direction without demonstrated edge is not an agent signal.
                                  "signal":c["signal"] if c.get("edge")=="DEMONSTRATED" else None,
                                  "signal_research":c["signal"],"consensus":c["consensus"]["value"] if c["consensus"] else None})
    for event, card in zip(compact["events"], cards):
        if "dts_driver" in card:
            event["dts_driver"]=card["dts_driver"]
        b=card.get("dts_bridge")
        if b:
            event["dts_bridge"]={"status":b["status"],"edge":b["edge"],"point":b.get("point"),
                                 "dts_direction":b.get("dts_direction"),"dts_contribution":b.get("dts_contribution")}
            if card.get("primary_estimate")=="DTS_BRIDGE":
                event["point"]=round(b["point"],3); event["primary_estimate"]="DTS_BRIDGE"
    compact["fiscal_pulse"]={"status":pulse.get("status"),"asof":pulse.get("asof"),"basis":"dts_vs_same_session_last_year_not_forecast",
                             "verdicts":{k:v["verdict"] for k,v in (pulse.get("verdicts") or {}).items()},
                             "indicators":{x["id"]:{"fytd_change":x["fytd"]["change"],"real":x["fytd"]["real_change"],"state":x["state"]} for x in pulse.get("indicators",[])}}
    atomic_json(DATA/"argos_summary.json",compact,compact=True)
    atomic_json(DATA/"dts_nowcast.json",dts)
    return payload

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--offline",action="store_true")
    result=main(parser.parse_args().offline)
    if not any(c["forecast"] for c in result["cards"]):
        raise SystemExit("No valid macro estimate; failure state has been published")
