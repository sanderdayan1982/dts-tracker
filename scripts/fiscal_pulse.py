"""Fiscal pulse: DTS cash flows compared with the same point of the previous year.

Reading, not forecasting: each indicator says whether that part of the economy is running
hotter or colder than a year ago, using official cumulative DTS amounts (MTD and FYTD).
Comparisons use the same number of DTS sessions (same position in the month or fiscal year),
never calendar sums. Income-type lines are also shown net of CPI inflation.
"""
from __future__ import annotations
import datetime as dt
from institutional_core import finite, iso, parse_time

# kind: pct (YoY %), net (level difference in USD bn). good: up | down | none (pressure/context)
INDICATORS = [
  # ---- Labour market -> NFP and unemployment rate
  {"id": "withheld", "theme": "labor", "parts": ["WITHHELD_FICA"], "good": "up", "real": True,
   "es": "Retenciones de nómina (IRPF + FICA)", "en": "Payroll withholding (income tax + FICA)",
   "up_es": "Más masa salarial: más empleo, horas o salarios que hace un año", "down_es": "Menos masa salarial que hace un año: empleo u horas pierden fuerza",
   "up_en": "Larger wage bill than a year ago: more jobs, hours or pay", "down_en": "Smaller wage bill than a year ago: labour losing momentum",
   "note_es": "Nominal: mezcla empleo, horas, salarios y normas fiscales. Se compara también descontando la inflación.",
   "note_en": "Nominal: mixes jobs, hours, pay and tax rules. Also shown net of inflation.", "feeds": ["nfp", "unemployment"]},
  {"id": "dol", "theme": "labor", "parts": ["DOL_UNEMP_BEN"], "good": "down",
   "es": "Prestaciones por desempleo (DOL)", "en": "Unemployment benefits (DOL)",
   "up_es": "Más prestaciones pagadas: más personas cobrando el paro", "down_es": "Menos prestaciones pagadas: menos personas cobrando el paro",
   "up_en": "More benefits paid: more people drawing unemployment", "down_en": "Fewer benefits paid: fewer people drawing unemployment",
   "note_es": "Va por detrás de las solicitudes iniciales; refleja el paro de continuación.", "note_en": "Lags initial claims; reflects continuing unemployment.",
   "feeds": ["unemployment", "claims"]},
  {"id": "snap", "theme": "labor", "parts": ["USDA_SNAP"], "good": "down",
   "es": "SNAP (cupones de alimentos)", "en": "SNAP (food stamps)",
   "up_es": "Más SNAP: más estrés en hogares de bajo ingreso", "down_es": "Menos SNAP: menos estrés en hogares de bajo ingreso",
   "up_en": "More SNAP: more stress in low-income households", "down_en": "Less SNAP: less stress in low-income households",
   "note_es": "También lo mueven las normas de elegibilidad y el ajuste anual de prestaciones de octubre.",
   "note_en": "Also driven by eligibility rules and the October benefit adjustment.", "feeds": ["unemployment", "retail"]},
  {"id": "fed_salaries", "theme": "labor", "parts": ["FED_SALARIES_EFT"], "good": "up", "real": True,
   "es": "Salarios federales (empleo público)", "en": "Federal salaries (public employment)",
   "up_es": "Más nómina federal que hace un año", "down_es": "Menos nómina federal: recorte de empleo público (DOGE); resta al PIB",
   "up_en": "Larger federal payroll than a year ago", "down_en": "Smaller federal payroll: public-sector cuts (DOGE); a drag on GDP",
   "note_es": "Nóminas quincenales: un mes puede tener una nómina más o menos. Incluye subidas salariales.",
   "note_en": "Bi-weekly payrolls: a month can hold one more or fewer payday. Includes pay raises.", "feeds": ["nfp"]},
  # ---- Consumption and saving -> retail sales
  {"id": "refunds", "theme": "consumption", "parts": ["INDIV_REFUNDS_EFT"], "good": "up",
   "es": "Devoluciones de impuestos a hogares", "en": "Individual tax refunds",
   "up_es": "Más devoluciones: más liquidez para consumo a corto plazo o ahorro", "down_es": "Menos devoluciones: menos liquidez extra para los hogares",
   "up_en": "More refunds: more cash for near-term spending or saving", "down_en": "Fewer refunds: less extra cash for households",
   "note_es": "Muy estacional (febrero-abril) y depende del ritmo del IRS.", "note_en": "Highly seasonal (Feb-Apr) and depends on IRS processing.",
   "feeds": ["retail"]},
  {"id": "tsp_in", "theme": "consumption", "parts": ["TSP_DEP"], "good": "up",
   "es": "Plan de ahorro federal TSP · aportaciones", "en": "Thrift Savings Plan · contributions",
   "up_es": "Más aportaciones: más capacidad de ahorro de los empleados públicos", "down_es": "Menos aportaciones: menos ahorro o menos empleados aportando",
   "up_en": "More contributions: more saving by federal staff", "down_en": "Fewer contributions: less saving or fewer contributors",
   "note_es": "Indicador de ahorro del empleo federal, no de todo el país.", "note_en": "Saving gauge for federal staff, not the whole country.", "feeds": []},
  {"id": "tsp_out", "theme": "consumption", "parts": ["TSP_WD"], "good": "none",
   "es": "Plan de ahorro federal TSP · retiradas", "en": "Thrift Savings Plan · withdrawals",
   "up_es": "Más retiradas: jubilaciones, salidas del empleo público o necesidad de liquidez", "down_es": "Menos retiradas que hace un año",
   "up_en": "More withdrawals: retirements, separations or liquidity needs", "down_en": "Fewer withdrawals than a year ago",
   "note_es": "Con recortes federales suben las salidas y las retiradas; no es por sí solo sentimiento.",
   "note_en": "Federal cuts raise separations and withdrawals; not sentiment on its own.", "feeds": []},
  # ---- Growth and profits -> GDP
  {"id": "corporate", "theme": "growth", "parts": ["CORP_INCOME"], "good": "up", "real": True,
   "es": "Impuesto de sociedades", "en": "Corporate income tax",
   "up_es": "Más recaudación corporativa: beneficios empresariales más altos", "down_es": "Menos recaudación corporativa: beneficios más bajos o cambios fiscales",
   "up_en": "More corporate tax: higher profits", "down_en": "Less corporate tax: lower profits or tax changes",
   "note_es": "Pagos trimestrales (15 de abril, junio, septiembre y diciembre): el FYTD es la lectura fiable; los meses sin vencimiento son ruido.",
   "note_en": "Quarterly payments (15 Apr, Jun, Sep, Dec): FYTD is the reliable reading; non-payment months are noise.", "feeds": ["gdp"]},
  {"id": "self_employed", "theme": "growth", "parts": ["NON_WITHHELD_ELEC", "NON_WITHHELD_OTHER"], "good": "up", "real": True,
   "es": "Renta no retenida / SECA (autónomos)", "en": "Non-withheld income / SECA (self-employed)",
   "up_es": "Más ingresos de autónomos y rentas no salariales: economía informal y pequeña empresa más fuerte", "down_es": "Menos ingresos de autónomos y rentas no salariales",
   "up_en": "Higher self-employment and non-wage income", "down_en": "Lower self-employment and non-wage income",
   "note_es": "Suma electrónico + otros. Pagos trimestrales y liquidación de abril. Los aplazamientos del IRS por desastres (p. ej., plazos movidos a octubre) crean efectos base.", "note_en": "Electronic + other. Quarterly estimates and April settlement.", "feeds": ["gdp"]},
  # ---- External sector -> trade balance, imports
  {"id": "customs", "theme": "trade", "parts": ["CUSTOMS_DUTIES"], "good": "none",
   "es": "Aduanas (aranceles, impuestos y tasas)", "en": "Customs duties, taxes and fees",
   "up_es": "Más aduanas: más aranceles y/o más importaciones", "down_es": "Menos aduanas: menos importaciones o aranceles más bajos",
   "up_en": "More customs: higher tariffs and/or more imports", "down_en": "Less customs: fewer imports or lower tariffs",
   "note_es": "Desde 2025 la subida la dominan los aranceles, no el volumen importado. Ruptura de serie el 10-11-2025.",
   "note_en": "Since 2025 tariffs, not import volume, dominate. Series break on 2025-11-10.", "feeds": ["trade", "retail"]},
  # ---- Debt and rates -> 2Y / 10Y
  {"id": "net_issuance", "theme": "rates", "kind": "net", "parts": ["I-R"], "good": "none",
   "es": "Emisión neta de deuda (emisiones − amortizaciones)", "en": "Net debt issuance (issues − redemptions)",
   "up_es": "Más emisión neta que hace un año: más oferta de bonos y letras, presión al alza en rendimientos", "down_es": "Menos emisión neta: menos oferta de deuda que hace un año",
   "up_en": "More net issuance than a year ago: more supply, upward pressure on yields", "down_en": "Less net issuance: less supply than a year ago",
   "note_es": "Diferencia en miles de millones frente al año pasado. Lo que mueve la curva es la emisión neta, no la bruta.",
   "note_en": "Difference in USD bn versus last year. Net, not gross, issuance moves the curve.", "feeds": ["two_year", "ten_year"]},
  {"id": "interest", "theme": "rates", "parts": ["TREAS_INTEREST"], "good": "none",
   "es": "Intereses de títulos del Tesoro", "en": "Interest on Treasury securities",
   "up_es": "Más intereses pagados: más coste fiscal de la deuda (y, en lectura MMT, más ingreso para el sector privado)",
   "down_es": "Menos intereses pagados que hace un año",
   "up_en": "More interest paid: higher debt-service cost (and, in an MMT reading, more private income)", "down_en": "Less interest paid than a year ago",
   "note_es": "Se paga en fechas de cupón (día 15 y fin de mes): el FYTD es la lectura fiable.", "note_en": "Paid on coupon dates (15th and month-end): FYTD is the reliable reading.",
   "feeds": ["ten_year"]},
  # ---- Public spending and fiscal pressure
  {"id": "health", "theme": "fiscal", "parts": ["MEDICARE_PART_A", "MEDICARE_PART_B", "MEDICARE_PART_D", "MEDICAID", "HHS_MISC_WD"], "good": "none",
   "es": "Gasto sanitario HHS (Medicare + Medicaid)", "en": "HHS health spending (Medicare + Medicaid)",
   "up_es": "Más gasto sanitario: más presión fiscal (y más ingreso para hogares y proveedores)", "down_es": "Menos gasto sanitario que hace un año",
   "up_en": "More health spending: more fiscal pressure (and more income for households and providers)", "down_en": "Less health spending than a year ago",
   "note_es": "Medicare A, B y D, Medicaid y HHS varios. El calendario de transferencias a los estados añade ruido mensual.",
   "note_en": "Medicare A, B, D, Medicaid and HHS misc. State-grant timing adds monthly noise.", "feeds": []},
]
THEMES = {
  "labor": {"es": "Empleo y desempleo", "en": "Jobs and unemployment", "feeds_es": "NFP · tasa de paro · solicitudes", "feeds_en": "NFP · unemployment rate · claims"},
  "consumption": {"es": "Consumo y ahorro", "en": "Consumption and saving", "feeds_es": "Ventas minoristas · tasa de ahorro", "feeds_en": "Retail sales · saving rate"},
  "growth": {"es": "Crecimiento y beneficios", "en": "Growth and profits", "feeds_es": "PIB", "feeds_en": "GDP"},
  "trade": {"es": "Sector exterior", "en": "External sector", "feeds_es": "Importaciones · balanza comercial", "feeds_en": "Imports · trade balance"},
  "rates": {"es": "Deuda y tipos", "en": "Debt and rates", "feeds_es": "Rendimientos 2 y 10 años", "feeds_en": "2- and 10-year yields"},
  "fiscal": {"es": "Gasto público y presión fiscal", "en": "Public spending and fiscal pressure", "feeds_es": "Déficit · aportación de activos financieros netos (NFA)", "feeds_en": "Deficit · net financial assets"},
}
# Known one-off events in the comparison base. If the base window overlaps an event, the
# indicator is shown as "distorted" and excluded from the block verdict (never silently scored).
BASE_EVENTS = [
  {"id": "shutdown_2025", "start": "2025-10-01", "end": "2025-11-12",
   "affects": ["fed_salaries", "tsp_in", "tsp_out", "snap", "dol"],
   "es": "Cierre del Gobierno federal (1-oct a 12-nov-2025): nóminas federales, TSP, SNAP y prestaciones alterados en el año base",
   "en": "Federal government shutdown (Oct 1-Nov 12, 2025): federal payroll, TSP, SNAP and benefits disrupted in the base year"},
  {"id": "irs_disaster_postponement_2025", "start": "2025-10-01", "end": "2025-10-31",
   "affects": ["self_employed", "corporate"],
   "es": "Aplazamientos del IRS por desastres (pagos movidos a octubre de 2025) inflan la base",
   "en": "IRS disaster postponements (payments moved into October 2025) inflate the base"},
]
STABLE_PCT = 3.0     # |YoY| below this is "stable"
STABLE_NET_BN = 25.0  # net issuance difference below this (USD bn) is "stable"
MIN_MTD_SESSIONS = 10  # early in the month, payment-date shifts dominate the MTD comparison

def _value(row, part, mode):
    if part == "I-R":
        p = row.get("periods", {}).get(mode, {})
        return p["I"] - p["R"] if finite(p.get("I")) and finite(p.get("R")) else None
    v = row.get("components", {}).get(part)
    return v[{"today": 0, "mtd": 1, "fytd": 2}[mode]] if v else None

def value(row, parts, mode):
    vals = [_value(row, p, mode) for p in parts]
    return sum(vals) if vals and all(finite(v) for v in vals) else None

def monthly_yoy(rows, parts, net=False, months=13):
    """Calendar-month totals from daily DTS amounts; change vs the same month a year earlier.
    A month counts only if every DTS session in it reported the item (missing is never zero).
    The current month is partial and flagged as such."""
    totals, complete = {}, {}
    for r in rows:
        k = r["d"][:7]; v = value(r, parts, "today")
        totals[k] = totals.get(k, 0.0) + (v if finite(v) else 0.0)
        complete[k] = complete.get(k, True) and finite(v)
    keys = sorted(totals); current = rows[-1]["d"][:7] if rows else None
    out = []
    for k in keys[-months:]:
        prev = f"{int(k[:4]) - 1}{k[4:]}"
        ok = complete.get(k) and complete.get(prev) and prev in totals and k != current
        if not ok: chg = None
        elif net: chg = (totals[k] - totals[prev]) / 1000
        else: chg = 100 * (totals[k] / totals[prev] - 1) if totals[prev] > 0 else None
        out.append({"month": k, "change": None if chg is None else round(chg, 2), "partial": k == current})
    return out

def session_index(rows, i, key):
    k = key(rows[i]); n = 0
    for r in rows[: i + 1]:
        if key(r) == k: n += 1
    return n

def same_session(rows, key_value, key, n):
    """n-th DTS session of a period (fiscal year or month); never a calendar-day substitute."""
    hits = [r for r in rows if key(r) == key_value]
    return hits[n - 1] if 0 < n <= len(hits) else None

def cpi_yoy(cpi_obs):
    obs = {o["date"]: o["value"] for o in cpi_obs or [] if finite(o.get("value"))}
    if not obs: return None, None
    last = max(obs); d = dt.date.fromisoformat(last); prev = dt.date(d.year - 1, d.month, 1).isoformat()
    return (100 * (obs[last] / obs[prev] - 1), last[:7]) if prev in obs else (None, None)

def classify(spec, change):
    if change is None: return "na"
    stable = STABLE_NET_BN if spec.get("kind") == "net" else STABLE_PCT
    if abs(change) < stable: return "stable"
    direction = "up" if change > 0 else "down"
    if spec["good"] == "none": return "pressure_" + direction
    return "better" if direction == spec["good"] else "worse"

def fmt_change(x):
    f = x["fytd"]; v = f["real_change"] if f["real_change"] is not None else f["change"]
    if v is None: return "n/d"
    suffix = " bn" if x["kind"] == "net" else " %" + (" real" if f["real_change"] is not None else "")
    return f"{v:+.1f}{suffix}".replace(".", ",")

def build_pulse(book, cpi_obs=None, now=None):
    rows = (book or {}).get("rows", [])
    out = {"schema": "fiscal-pulse-1.0", "asof": (book or {}).get("asof"), "generated_at": iso(now) if now else None,
           "valid_until_utc": (book or {}).get("valid_until_utc"), "unit": "USD_billions",
           "method": "Official DTS MTD/FYTD amounts compared with the same session number of the previous year; reading of direction, not a forecast of the release figure.",
           "themes": THEMES, "indicators": [], "status": "UNAVAILABLE"}
    if not rows: return out
    i = len(rows) - 1; last = rows[i]
    fy_key = lambda r: r["fy"]; mo_key = lambda r: r["d"][:7]
    n_fy = session_index(rows, i, fy_key); n_mo = session_index(rows, i, mo_key)
    prior_fy = same_session(rows, last["fy"] - 1, fy_key, n_fy)
    y, m = int(last["d"][:4]), last["d"][5:7]
    prior_mo = same_session(rows, f"{y-1}-{m}", mo_key, n_mo)
    inflation, inflation_period = cpi_yoy(cpi_obs)
    out.update(status="OK", sessions_fytd=n_fy, sessions_mtd=n_mo, compare_fytd_date=prior_fy and prior_fy["d"],
               compare_mtd_date=prior_mo and prior_mo["d"], cpi_yoy_pct=inflation, cpi_period=inflation_period)
    for spec in INDICATORS:
        net = spec.get("kind") == "net"
        def compare(prior, mode):
            cur, old = value(last, spec["parts"], mode), value(prior, spec["parts"], mode) if prior else None
            if not finite(cur) or not finite(old): return cur, old, None
            if net: return cur, old, (cur - old) / 1000
            return cur, old, (100 * (cur / old - 1) if old > 0 else None)
        f_cur, f_old, f_chg = compare(prior_fy, "fytd")
        m_cur, m_old, m_chg = compare(prior_mo, "mtd")
        real = f_chg - inflation if spec.get("real") and finite(f_chg) and finite(inflation) else None
        state = classify(spec, real if real is not None else f_chg)
        base_start = next((r["d"] for r in rows if r["fy"] == last["fy"] - 1), None)
        base_end = prior_fy and prior_fy["d"]
        events = [ev for ev in BASE_EVENTS if spec["id"] in ev["affects"] and base_start and base_end
                  and ev["start"] <= base_end and ev["end"] >= base_start]
        if events and f_chg is not None: state = "distorted"
        # Charts: cumulative FYTD path by session, this fiscal year vs the previous one (USD bn).
        cur_path = [value(r, spec["parts"], "fytd") for r in rows if r["fy"] == last["fy"]]
        old_path = [value(r, spec["parts"], "fytd") for r in rows if r["fy"] == last["fy"] - 1]
        to_bn = lambda xs: [round(x / 1000, 3) if finite(x) else None for x in xs]
        text = (spec["up_es"], spec["up_en"]) if (f_chg or 0) > 0 else (spec["down_es"], spec["down_en"])
        out["indicators"].append({
            "id": spec["id"], "theme": spec["theme"], "es": spec["es"], "en": spec["en"], "kind": "net" if net else "pct",
            "good": spec["good"], "feeds": spec["feeds"], "note_es": spec["note_es"], "note_en": spec["note_en"],
            "fytd": {"current_bn": None if f_cur is None else round(f_cur / 1000, 3), "prior_bn": None if f_old is None else round(f_old / 1000, 3),
                     "change": None if f_chg is None else round(f_chg, 2), "real_change": None if real is None else round(real, 2)},
            "mtd": {"current_bn": None if m_cur is None else round(m_cur / 1000, 3), "prior_bn": None if m_old is None else round(m_old / 1000, 3),
                    # Shown only once the month has enough sessions; before that, payment-date shifts dominate.
                    "change": None if m_chg is None or n_mo < MIN_MTD_SESSIONS else round(m_chg, 2),
                    "sessions": n_mo, "reliable": n_mo >= MIN_MTD_SESSIONS},
            "base_effects": [{"id": ev["id"], "es": ev["es"], "en": ev["en"]} for ev in events],
            "state": state, "reading_es": text[0] if f_chg is not None and state != "stable" else "Sin cambio relevante frente al año pasado",
            "reading_en": text[1] if f_chg is not None and state != "stable" else "No material change versus last year",
            "chart": {"current": to_bn(cur_path), "prior": to_bn(old_path)},
            "monthly": monthly_yoy(rows, spec["parts"], net)})
    # Theme verdicts: count indicators better/worse than a year ago (pressure lines are reported, not scored).
    verdicts = {}
    for theme in THEMES:
        items = [x for x in out["indicators"] if x["theme"] == theme]
        better = sum(x["state"] == "better" for x in items); worse = sum(x["state"] == "worse" for x in items)
        pressure = sum(x["state"].startswith("pressure_up") for x in items)
        relief = sum(x["state"] == "pressure_down" for x in items)
        if better + worse == 0: verdict = "pressure" if pressure else "relief" if relief else "neutral"
        elif better > worse: verdict = "stronger"
        elif worse > better: verdict = "weaker"
        else: verdict = "mixed"
        def names(state_set, lang):
            return ", ".join(f"{x[lang]} ({fmt_change(x)})" for x in items if x["state"] in state_set)
        lead_es = {"stronger": "Mejor que hace un año", "weaker": "Peor que hace un año", "mixed": "Señales mixtas",
                   "pressure": "Más presión que hace un año", "relief": "Menos presión que hace un año", "neutral": "Sin cambio relevante"}[verdict]
        lead_en = {"stronger": "Better than a year ago", "weaker": "Worse than a year ago", "mixed": "Mixed signals",
                   "pressure": "More pressure than a year ago", "relief": "Less pressure than a year ago", "neutral": "No material change"}[verdict]
        parts_es, parts_en = [], []
        for st, es, en in ((("better",), "a favor", "supporting"), (("worse",), "en contra", "against"),
                           (("pressure_up",), "más presión", "more pressure"), (("pressure_down",), "menos presión", "less pressure"),
                           (("stable",), "sin cambio", "unchanged"), (("distorted",), "efecto base (excluido)", "base effect (excluded)")):
            if names(st, "es"): parts_es.append(f"{es}: {names(st, 'es')}"); parts_en.append(f"{en}: {names(st, 'en')}")
        verdicts[theme] = {"verdict": verdict, "better": better, "worse": worse, "pressure": pressure, "n": len(items),
                           "summary_es": f"{lead_es}. " + "; ".join(parts_es).capitalize()[:1] + "; ".join(parts_es)[1:] + "." if parts_es else lead_es + ".",
                           "summary_en": f"{lead_en}. " + "; ".join(parts_en)[:1].upper() + "; ".join(parts_en)[1:] + "." if parts_en else lead_en + "."}
    out["verdicts"] = verdicts
    return out

def pulse_contract(pulse, now):
    """Fail closed: an expired cash book blocks the pulse reading."""
    until = parse_time(pulse.get("valid_until_utc") or "")
    if pulse.get("status") == "OK" and (until is None or now >= until):
        pulse["status"] = "EXPIRED"
    return pulse
