"""Today's pumping baseline from Eastwater's data, and the saving the POC pump plans would give against it.

Usage:  python src/baseline_vs_today.py [--sample]

Reads the clean files src/load_eastwater.py wrote to data/eastwater/ (as listed in its manifest.json; the SAMPLE_
set when no Eastwater data have been loaded yet, or with --sample) and the plans in
reports/matlab/pump_plans_kpis.csv and pump_plans_schedule.csv. Writes reports/baseline_vs_today.md,
baseline_vs_today_kpis.csv and baseline_vs_today_daily.csv; for the sample set the names end in _SAMPLE.

Today's baseline is measured on days with complete energy and delivery data: kWh/day, kWh/m3 delivered, energy cost
(time-of-use energy + Ft) and THB/m3, the share of energy bought on-peak, and the peak demand (kW) in each
demand-charge window per meter and month when the tariff has a demand charge.

Saving vs today (like-for-like, weekdays): each plan's hourly pump counts per station are costed with the kWh per
pump-hour measured today at each meter, plus the meter's load with no pumps running when the data show it, and with
Eastwater's tariff. Pump efficiency, other loads and prices are then the same on both sides, so what differs is the
schedule: how many pumps run, at which station and when. Only plans that passed the EPANET check get a saving.
"""
import argparse
import json

import numpy as np
import pandas as pd

from config import REPORT_DIR
from load_eastwater import EW_DIR, SAMPLE_NOTE, Tariff, id_key, read_model, rel

PLAN_DIR = REPORT_DIR / "matlab"
TARGET_PCT = (3.0, 5.0)          # saving the client hopes for
MIN_COVER = 0.8                  # a customer node counts towards delivered volume if it reports on 80% of days
GAP_FILL_H = 2                   # gaps in a pump's status up to this long take its previous state
ID_COLS = ("pump_id", "station_id", "meter_id", "node_id", "point_id", "question_id")


# ------------------------------------------------------------------ inputs

def read(path, *dates):
    df = pd.read_csv(path, encoding="utf-8-sig", dtype={c: str for c in ID_COLS})
    for c in dates:
        if c in df:
            df[c] = pd.to_datetime(df[c], format="ISO8601")
    return df


def load_inputs(sample):
    """The clean tables listed in the loader's manifest (None for a dataset that was not loaded)."""
    prefix = "SAMPLE_" if sample else ""
    man = json.loads((EW_DIR / f"{prefix}manifest.json").read_text(encoding="utf-8"))
    have = {n for v in man["outputs"].values() for n in v}

    def get(name, *dates):
        return read(EW_DIR / f"{prefix}{name}", *dates) if f"{prefix}{name}" in have else None

    data = dict(ops=get("pump_operation_hourly.csv", "timestamp"), energy=get("station_energy.csv", "timestamp"),
                bills=get("electricity_bills.csv", "period_start", "period_end"), tariff=get("tariff.csv"),
                holidays=get("holidays.csv", "date"), delivery=get("customer_delivery_daily.csv", "date"),
                scada=get("scada_hourly.csv", "timestamp"), register=get("pump_register.csv"),
                tests=get("pump_tests.csv", "test_date"), confirmations=get("confirmations.csv"))
    return man, data


def poc_tariff(schedule, holidays):
    """The POC's assumed tariff as tariff rows: the weekday hourly prices in pump_plans_schedule.csv, and weekends
    and holidays at the lowest of them."""
    price = schedule.groupby("hour")["tariff_thb_per_kwh"].first().reindex(range(24)).to_numpy()
    rows, start = [], 0
    for h in range(1, 25):
        if h == 24 or price[h] != price[start]:
            rows.append(("weekday", start, h, price[start]))
            start = h
    rows.append(("weekend", 0, 24, price.min()))
    t = pd.DataFrame([dict(meter_id="ALL", valid_from="2000-01-01", valid_to=None, component="energy", day_type=d,
                           start_time=f"{s:02d}:00", end_time=f"{e:02d}:00", rate=r, unit="THB/kWh", period_name="")
                      for d, s, e, r in rows])
    return Tariff(t, holidays, name="the POC's assumed tariff")


# ------------------------------------------------------------------ today's operation

def fill_short_gaps(s, limit=GAP_FILL_H):
    """Fill gaps of up to `limit` values inside a series with the value before them."""
    gap = s.isna()
    run = gap.groupby((gap != gap.shift()).cumsum()).transform("sum")
    short = gap & (run <= limit) & s.ffill().notna() & s.bfill().notna()
    return s.where(~short, s.ffill()), int(short.sum())


def station_hours(ops, register, model, hours):
    """Pumps running, flow, pump power and rated power of running pumps, per station and hour (NaN where unknown)."""
    pumps, stations = model["pumps"], model["stations"].index
    n, q, p, r = (pd.DataFrame(np.nan, index=hours, columns=stations) for _ in range(4))
    notes = []
    if ops is None:
        return n, q, p, r, ["no pump operation data"]
    rated = register.set_index("pump_id")["rated_power_kw"] if register is not None else pd.Series(dtype=float)
    pp = ops[ops["level"] == "pump"]
    filled = 0
    for st in stations:
        mine = list(pumps.index[pumps["station_id"] == st])
        have = [x for x in mine if x in set(pp["pump_id"])]
        if have:
            def wide(col):
                return pp.pivot(index="timestamp", columns="pump_id", values=col).reindex(index=hours, columns=have)
            run = wide("pumps_running")
            for c in have:
                run[c], k = fill_short_gaps(run[c])
                filled += k
            known = run.notna().all(axis=1)
            n[st] = run.sum(axis=1).where(known)
            flow, power = wide("flow_m3_h").where(run > 0, 0.0), wide("power_kw").where(run > 0, 0.0)
            q[st] = flow.sum(axis=1).where(known & flow.notna().all(axis=1))
            p[st] = power.sum(axis=1).where(known & power.notna().all(axis=1))
            kw = rated.reindex(have)
            if kw.notna().all():
                r[st] = (run * kw).sum(axis=1).where(known)
            silent = [x for x in mine if x not in have]
            if silent:
                notes.append(f"{st}: no records for {', '.join(silent)}, taken as off")
        else:
            rows = ops[(ops["level"] == "station") & (ops["pump_id"] == st)].set_index("timestamp")
            if len(rows):
                n[st], q[st], p[st] = (rows[c].reindex(hours) for c in ("pumps_running", "flow_m3_h", "power_kw"))
                notes.append(f"{st}: station totals only")
            else:
                notes.append(f"{st}: no pump operation data")
    if filled:
        notes.append(f"{filled} pump-hour{'s' if filled != 1 else ''} in gaps of up to {GAP_FILL_H} h took the "
                     "pump's previous state")
    return n, q, p, r, notes


def meter_list(energy, bills, model):
    """Meter -> stations it supplies; a station on no meter becomes its own meter (energy from pump data)."""
    meters = {}
    for df in (energy, bills):
        if df is not None:
            for mid, st in df.groupby("meter_id")["station_id"].first().items():
                meters.setdefault(str(mid), st.split("+"))
    covered = {s for v in meters.values() for s in v}
    for st in model["stations"].index:
        if st not in covered:
            meters[st] = [st]
    return meters


def spread(total, weight, group):
    """Share each group's total over its hours in proportion to weight; unknown weights take the group's mean and a
    group with no weight shares equally."""
    w = weight.fillna(weight.groupby(group).transform("mean")).fillna(1.0)
    w = w.where(w.groupby(group).transform("sum") > 0, 1.0)
    return total * w / w.groupby(group).transform("sum")


def price_frame(tariff, meter, hours):
    days = hours.normalize().unique()
    return pd.DataFrame({"rate": np.concatenate([tariff.energy(meter, d.date()) for d in days]),
                         "ft": np.repeat([tariff.ft(meter, d.date()) for d in days], 24)}, index=hours)


def meter_energy(meter, stations, data, n, p, r, prices, hours):
    """kWh in each hour for one meter, and where the numbers come from (best source first)."""
    energy, bills = data["energy"], data["bills"]
    shape = p[stations].sum(axis=1, min_count=len(stations))
    if shape.isna().all():
        shape = n[stations].sum(axis=1, min_count=len(stations))
    e = energy[energy["meter_id"] == meter] if energy is not None else pd.DataFrame()
    if len(e) and e["interval_min"].min() <= 60:
        e = e[e["interval_min"] <= 60]
        g = e.groupby(e["timestamp"].dt.floor("h")).agg(kwh=("kwh", "sum"), minutes=("interval_min", "sum"))
        return g["kwh"].where(g["minutes"] >= 60).reindex(hours), "meter, hourly"
    if len(e):
        daily = e.groupby(e["timestamp"].dt.normalize())["kwh"].sum()
        day = pd.Series(hours.normalize(), index=hours)
        return spread(day.map(daily), shape, day), "meter, daily kWh shared over the day's pump-hours"
    b = bills[bills["meter_id"] == meter] if bills is not None else pd.DataFrame()
    if len(b):
        total, group = pd.Series(np.nan, index=hours), pd.Series(pd.NA, index=hours, dtype="object")
        rate = prices["rate"]
        for i, row in b.iterrows():
            inside = (hours >= row["period_start"]) & (hours < row["period_end"] + pd.Timedelta(days=1))
            top = rate[inside].max()
            if pd.notna(row["kwh_on_peak"]) and pd.notna(row["kwh_off_peak"]) and rate[inside].nunique() > 1:
                on = inside & (rate == top).to_numpy()
                total[on], group[on] = row["kwh_on_peak"], f"{i} on"
                total[inside & ~on], group[inside & ~on] = row["kwh_off_peak"], f"{i} off"
            else:
                total[inside], group[inside] = row["kwh_total"], f"{i}"
        return spread(total, shape, group), "bills: on- and off-peak kWh shared over pump-hours"
    if p[stations].notna().any().any():
        return p[stations].sum(axis=1, min_count=len(stations)), "pump power from SCADA (excludes other loads)"
    if r[stations].notna().any().any():
        return r[stations].sum(axis=1, min_count=len(stations)), "rated kW x hours run (estimate, likely high)"
    return pd.Series(np.nan, index=hours), "none"


def windows(tariff, meter, hours):
    """{demand window: DataFrame(rate, inside)} over the hours."""
    out = {}
    for k, d in enumerate(hours.normalize().unique()):
        for name, rate, mask in tariff.demand(meter, d.date()):
            w = out.setdefault(name, pd.DataFrame({"rate": np.nan, "inside": False}, index=hours))
            w.iloc[24 * k:24 * (k + 1), 0] = rate
            w.iloc[24 * k:24 * (k + 1), 1] = mask
    return out


def demand_charges(kw, wins):
    """Peak hourly kW in each demand window and month, and the charge."""
    rows = []
    for name, w in wins.items():
        x = kw.where(w["inside"])
        for month, g in x.groupby(x.index.to_period("M")):
            if g.notna().any():
                at = g.idxmax()
                rows.append(dict(month=str(month), window=name, peak_kw=g.max(), at=at, rate=w.loc[at, "rate"],
                                 charge=w.loc[at, "rate"] * g.max()))
    return pd.DataFrame(rows, columns=["month", "window", "peak_kw", "at", "rate", "charge"])


def per_day(charges, days):
    """Monthly charges spread evenly over the days of each month."""
    out = pd.Series(0.0, index=days)
    for c in charges.itertuples():
        per = pd.Period(c.month)
        out[days.to_period("M") == per] += c.charge / per.days_in_month
    return out


def site_peak(charges):
    """Sum over meters of each meter's highest hourly kW in a demand window, averaged over months."""
    rows = [c.assign(meter=m) for m, c in charges.items() if len(c)]
    if not rows:
        return np.nan
    return float(pd.concat(rows).groupby(["month", "meter"])["peak_kw"].max().groupby("month").sum().mean())


def delivered(delivery, model, days):
    """m3 delivered per day over the customer nodes that report on most days (NaN when one of them is missing)."""
    absent = list(model["customers"].index)
    if delivery is None:
        return pd.Series(np.nan, index=days), [], [], absent
    v = delivery.pivot_table(index="date", columns="node_id", values="volume_m3", aggfunc="sum")
    v = v.reindex(pd.date_range(v.index.min(), v.index.max(), freq="D"))
    cover = v.notna().mean()
    nodes, sparse = list(cover.index[cover >= MIN_COVER]), list(cover.index[cover < MIN_COVER])
    total = v[nodes].sum(axis=1).where(v[nodes].notna().all(axis=1)).reindex(days)
    return total, nodes, sparse, [c for c in absent if c not in v.columns]


def summary(daily, mask, stations):
    d = daily[mask]
    e, v, nd = d["kwh"].sum(), d["delivered_m3"].sum(), len(d)
    ph = d[[f"pump_hours:{s}" for s in stations]].sum().sum()
    if not nd:
        return {}
    return dict(days=nd, delivered_m3_day=v / nd, kwh_day=e / nd, kwh_per_m3=e / v,
                energy_cost_thb_day=d["energy_cost_thb"].sum() / nd,
                demand_charge_thb_day=d["demand_charge_thb"].sum() / nd,
                thb_per_m3_energy=d["energy_cost_thb"].sum() / v,
                thb_per_m3=(d["energy_cost_thb"].sum() + d["demand_charge_thb"].sum()) / v,
                demand_thb_per_m3=d["demand_charge_thb"].sum() / v, thb_per_kwh=d["energy_cost_thb"].sum() / e,
                on_peak_share=d["on_peak_kwh"].sum() / e, pump_hours_day=ph / nd if ph else np.nan,
                m3_per_pump_hour=v / ph if ph else np.nan, poc_thb_per_m3=d["poc_cost_thb"].sum() / v)


def meter_coefficients(E, n, q, meters, mask):
    """Per meter, over the hours in mask: the load with no pumps running (kW), and net of it the kWh per pump-hour
    and, where pump flows are measured on most of those hours, the kWh per m3 pumped."""
    rows = {}
    for m, sts in meters.items():
        nm = n[sts].sum(axis=1, min_count=len(sts))
        qm = q[sts].sum(axis=1, min_count=len(sts))
        ok = mask & E[m].notna() & nm.notna()
        idle = ok & (nm == 0)
        base = float(E[m][idle].median()) if idle.sum() >= 6 else 0.0
        on = ok & (nm > 0)
        k = (E[m][on] - base).sum() / nm[on].sum() if nm[on].sum() > 0 else np.nan
        onq = on & (qm > 0)
        e = ((E[m][onq] - base).sum() / qm[onq].sum() if onq.sum() >= 0.5 * max(on.sum(), 1) and qm[onq].sum() > 0
             else np.nan)
        rows[m] = dict(stations="+".join(sts), kwh_per_pump_hour=k, kwh_per_m3_pumped=e, base_kw=base,
                       base_known=bool(idle.sum() >= 6), hours=int(ok.sum()))
    return pd.DataFrame.from_dict(rows, orient="index")


# ------------------------------------------------------------------ plans

def plan_profiles(schedule, stations):
    """{(scenario, schedule): 24 x stations pumps running} from pump_plans_schedule.csv."""
    cols = {}
    for c in schedule.columns:
        if c.endswith("_pumps"):
            st = next((s for s in stations if id_key(s) == id_key(c[:-len("_pumps")])), None)
            if st:
                cols[c] = st
    return {k: g.sort_values("hour").set_index("hour")[list(cols)].rename(columns=cols)
                .reindex(index=range(24), columns=stations, fill_value=0).astype(float)
            for k, g in schedule.groupby(["scenario", "schedule"], sort=False)}


def plan_volumes(prof, q_model, volume, ratio):
    """m3 pumped per station and hour in a plan: pumps running x the model's flow per running pump, scaled so the
    stations add up to the plan's delivered volume times today's pumped-to-delivered ratio."""
    q = q_model.reindex(prof.columns)
    raw = prof * (q if q.notna().all() else 1.0)
    return raw * (volume * ratio / raw.sum().sum())


def cost_plan(drive, per_unit, prof, coef, meters, prices, poc_prices, wins, wk_days, volume):
    """KPIs of a plan run on each weekday in wk_days. drive is the plan's hourly pumping per station (m3 or
    pump-hours) and per_unit the matching column of coef: today's measured kWh per m3 pumped or per pump-hour."""
    kwh = {m: coef.loc[m, "base_kw"] + coef.loc[m, per_unit] * drive[sts].sum(axis=1).to_numpy()
           for m, sts in meters.items()}
    cost = poc = dem = on_peak = 0.0
    peaks = []
    months = {}
    for d in wk_days:
        hrs = pd.date_range(d, periods=24, freq="h")
        for m in meters:
            pr = prices[m].loc[hrs]
            cost += float((kwh[m] * (pr["rate"] + pr["ft"]).to_numpy()).sum())
            poc += float((kwh[m] * poc_prices[m].loc[hrs, "rate"].to_numpy()).sum())
            top = prices[m]["rate"].max()
            if prices[m]["rate"].nunique() > 1:
                on_peak += float(kwh[m][(pr["rate"] == top).to_numpy()].sum())
        months.setdefault(d.to_period("M"), []).append(hrs)
    for per, days in months.items():
        for m in meters:
            for name, w in wins[m].items():
                inside = w.loc[days[0], "inside"].to_numpy()
                if inside.any():
                    peak = float(kwh[m][inside].max())
                    rate = float(w.loc[days[0], "rate"].max())
                    dem += rate * peak / per.days_in_month * len(days)
                    peaks.append(dict(meter=m, window=name, month=str(per), peak_kw=peak, charge=rate * peak))
    nd, e = len(wk_days), sum(float(v.sum()) for v in kwh.values())
    ph = float(prof.sum().sum())
    return dict(days=nd, delivered_m3_day=volume, kwh_day=e, kwh_per_m3=e / volume, energy_cost_thb_day=cost / nd,
                demand_charge_thb_day=dem / nd, thb_per_m3_energy=cost / nd / volume,
                thb_per_m3=(cost + dem) / nd / volume, demand_thb_per_m3=dem / nd / volume,
                thb_per_kwh=cost / nd / e, on_peak_share=on_peak / nd / e, pump_hours_day=ph,
                m3_per_pump_hour=volume / ph if ph else np.nan, poc_thb_per_m3=poc / nd / volume,
                peak_kw=site_peak({m: pd.DataFrame([x for x in peaks if x["meter"] == m]) for m in meters})
                if peaks else np.nan)


def saving_split(t, p):
    """Saving in THB/m3 and its parts (fractions of today's cost): fewer kWh per m3, cheaper hours, lower peak."""
    c = t["thb_per_m3"]
    k_t, k_p = t["kwh_per_m3"], p["kwh_per_m3"]
    p_t, p_p = t["thb_per_kwh"], p["thb_per_kwh"]
    return dict(saving=1 - p["thb_per_m3"] / c, saving_kwh=(k_t - k_p) * p_t / c, saving_timing=k_p * (p_t - p_p) / c,
                saving_demand=(t["demand_thb_per_m3"] - p["demand_thb_per_m3"]) / c,
                saving_model_as_is=1 - p["modelled_thb_per_m3"] / t["poc_thb_per_m3"])


# ------------------------------------------------------------------ checks

def model_flow_per_pump(model):
    """Mean flow per running pump at each station in the model as supplied (reports/epanet_timeseries.csv)."""
    path = REPORT_DIR / "epanet_timeseries.csv"
    if not path.exists():
        return pd.Series(dtype=float)
    ts = pd.read_csv(path)
    out = {}
    for st in model["stations"].index:
        cols = [f"pump_flow_cmd:{p}" for p in model["pumps"].index[model["pumps"]["station_id"] == st]]
        f = ts[[c for c in cols if c in ts]]
        f = f.where(f > 1)
        if f.notna().any().any():
            out[st] = float(np.nanmean(f.to_numpy())) / 24
    return pd.Series(out)


def bill_check(bills, E, src, prices, wins):
    rows = []
    if bills is None:
        return pd.DataFrame()
    for b in bills.itertuples():
        m = str(b.meter_id)
        if m not in E or not src[m].startswith("meter"):
            continue
        hrs = E.index[(E.index >= b.period_start) & (E.index < b.period_end + pd.Timedelta(days=1))]
        e = E.loc[hrs, m]
        rate = prices[m].loc[hrs, "rate"]
        on = rate == prices[m]["rate"].max()
        peak = np.nan
        for _, w in wins[m].items():
            peak = np.nanmax([peak, e[w.loc[hrs, "inside"]].max()])
        rows.append(dict(meter=m, period=f"{b.period_start:%Y-%m-%d} to {b.period_end:%Y-%m-%d}",
                         hours_with_data=f"{e.notna().mean():.1%}", kwh_billed=b.kwh_total, kwh_data=e.sum(),
                         kwh_on_peak_billed=b.kwh_on_peak, kwh_on_peak_data=e[on].sum(),
                         energy_charge_billed=b.energy_charge_thb, energy_charge_data=(e * rate).sum(),
                         kw_max_billed=b.kw_max_on_peak, kw_max_hourly_data=peak))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ report

def f0(x):
    return "-" if pd.isna(x) else f"{x:,.0f}"


def f2(x):
    return "-" if pd.isna(x) else f"{x:,.2f}"


def f4(x):
    return "-" if pd.isna(x) else f"{x:.4f}"


def pc(x, sign=False):
    return "-" if pd.isna(x) else (f"{100 * x:+.1f}%" if sign else f"{100 * x:.1f}%")


def diff(a, b):
    return "-" if pd.isna(a) or pd.isna(b) or not b else f"{100 * (a / b - 1):+.1f}%"


def analyse(data, model):
    sched = read(PLAN_DIR / "pump_plans_schedule.csv")
    kpis = read(PLAN_DIR / "pump_plans_kpis.csv")
    hol = list(data["holidays"]["date"]) if data["holidays"] is not None else []
    poc = poc_tariff(sched, hol)
    east = Tariff(data["tariff"], hol) if data["tariff"] is not None else poc
    stations = list(model["stations"].index)

    dates = []
    for key, cols in (("ops", ["timestamp"]), ("energy", ["timestamp"]), ("bills", ["period_start", "period_end"]),
                      ("delivery", ["date"])):
        if data[key] is not None:
            dates += [data[key][c].min().normalize() for c in cols] + [data[key][c].max().normalize() for c in cols]
    days = pd.date_range(min(dates), max(dates), freq="D")
    hours = pd.date_range(days[0], days[-1] + pd.Timedelta(hours=23), freq="h")
    day_of = pd.Series(hours.normalize(), index=hours)

    n, q, p, r, notes = station_hours(data["ops"], data["register"], model, hours)
    meters = meter_list(data["energy"], data["bills"], model)
    prices = {m: price_frame(east, m, hours) for m in meters}
    poc_prices = {m: price_frame(poc, m, hours) for m in meters}
    wins = {m: windows(east, m, hours) for m in meters}
    E, src = {}, {}
    for m, sts in meters.items():
        E[m], src[m] = meter_energy(m, sts, data, n, p, r, prices[m], hours)
    E = pd.DataFrame(E)

    full = E.notna().all(axis=1).groupby(day_of).all()
    V, nodes, sparse, absent = delivered(data["delivery"], model, days)
    daily = pd.DataFrame(index=days)
    daily["day_type"] = [east.day_type(d.date()) for d in days]
    daily["delivered_m3"] = V
    daily["kwh"] = E.sum(axis=1).groupby(day_of).sum().where(full)
    cost_h = sum(E[m] * (prices[m]["rate"] + prices[m]["ft"]) for m in meters)
    daily["energy_cost_thb"] = cost_h.groupby(day_of).sum(min_count=24)     # NaN if an hour has no price
    daily["poc_cost_thb"] = sum(E[m] * poc_prices[m]["rate"] for m in meters).groupby(day_of).sum(min_count=24)
    on_peak = sum(E[m].where(prices[m]["rate"] == prices[m]["rate"].max(), 0.0) if prices[m]["rate"].nunique() > 1
                  else 0.0 * E[m] for m in meters)
    daily["on_peak_kwh"] = on_peak.groupby(day_of).sum()
    charges = {m: demand_charges(E[m], wins[m]) for m in meters}
    daily["demand_charge_thb"] = sum((per_day(c, days) for c in charges.values()), pd.Series(0.0, index=days))
    for st in stations:
        daily[f"pump_hours:{st}"] = n[st].groupby(day_of).sum(min_count=24)
    for m in meters:
        daily[f"kwh:{m}"] = E[m].groupby(day_of).sum(min_count=24)
    daily["complete"] = full & daily["delivered_m3"].notna()
    for c in ("energy_cost_thb", "poc_cost_thb", "on_peak_kwh"):
        daily[c] = daily[c].where(full)
    daily["kwh_per_m3"] = daily["kwh"] / daily["delivered_m3"]
    daily["thb_per_m3"] = (daily["energy_cost_thb"] + daily["demand_charge_thb"]) / daily["delivered_m3"]
    unpriced = sorted({str(d.date()) for m in meters for d in prices[m].index[prices[m]["rate"].isna()].normalize()
                       if daily.loc[d, "complete"]})

    kpi_days = daily["complete"] & daily["energy_cost_thb"].notna()
    weekdays = kpi_days & (daily["day_type"] == "weekday")
    basis = weekdays if weekdays.sum() >= 3 else kpi_days
    today_all, today_wk = summary(daily, kpi_days, stations), summary(daily, basis, stations)
    for t in (today_all, today_wk):
        if t:
            t["peak_kw"] = site_peak(charges)
    wk_hours = day_of.map(basis).fillna(False).astype(bool)

    checks = dict(bills=bill_check(data["bills"], E, src, prices, wins))
    q_model = model_flow_per_pump(model)
    run_h = n.where(q.notna() & (n > 0))
    checks["flow"] = pd.DataFrame({"measured_m3_h": (q.where(run_h.notna()).sum() / run_h.sum()).where(run_h.sum() > 0),
                                   "model_m3_h": q_model})
    pumped = q[stations].sum(axis=1, min_count=len(stations)).groupby(day_of).sum(min_count=24)
    both = kpi_days & pumped.notna()
    ratio = pumped[both].sum() / daily.loc[both, "delivered_m3"].sum() if both.sum() >= 3 else np.nan
    checks["pumped_vs_delivered"] = (ratio, int(both.sum())) if both.any() else None

    # Like-for-like: cost each plan with today's measured energy. With pump flows measured at every meter, a plan's
    # pumped volume per station is costed at today's kWh per m3 pumped there, so a model whose pumps move more (or
    # less) water than the real ones does not bias the result. Without measured flows, each station's flow is taken
    # as the model's flow times one factor that makes today's pumping match today's delivered volume. Without model
    # flows either, plans are costed per pump-hour.
    coef = meter_coefficients(E, n, q, meters, wk_hours)
    method, flow_factor = "flow", np.nan
    running = [s for s in stations if (n[s] > 0).any()]
    if coef["kwh_per_m3_pumped"].isna().any():
        if q_model.reindex(running).notna().all() and basis.any():
            modelled = (n[running] * q_model[running]).sum(axis=1, min_count=len(running)).groupby(day_of).sum(
                min_count=24)
            same = basis & modelled.notna()
            flow_factor = daily.loc[same, "delivered_m3"].sum() / modelled[same].sum()
            q_est = n.mul(q_model.reindex(stations).fillna(0.0) * flow_factor, axis=1)
            coef = meter_coefficients(E, n, q_est, meters, wk_hours)
            method, ratio = "estimated flow", 1.0
        else:
            method = "pump-hours"
    unit = "kwh_per_pump_hour" if method == "pump-hours" else "kwh_per_m3_pumped"
    reason = ("no day has complete energy and delivery data" if not daily["complete"].any() else
              f"the tariff leaves hours without a price on {len(unpriced)} day(s), from {unpriced[0]}; see the "
              "validation report" if unpriced else
              "today's energy per pump-hour could not be measured (pump operation data missing)"
              if coef[unit].isna().any() else "")
    can_compare = not reason
    profiles = plan_profiles(sched, stations)
    plans = []
    for row in kpis.itertuples():
        rec = dict(scenario=row.scenario, schedule=row.schedule, status=row.status,
                   valid=row.status == "Pass" and row.converged == 1, modelled_kwh_per_m3=row.kwh_per_m3,
                   modelled_thb_per_m3=row.thb_per_m3,
                   volume=row.energy_kwh / row.kwh_per_m3 if row.kwh_per_m3 and pd.notna(row.kwh_per_m3) else np.nan)
        prof = profiles.get((row.scenario, row.schedule))
        if can_compare and prof is not None and pd.notna(rec["volume"]):
            drive = prof if method == "pump-hours" else plan_volumes(
                prof, q_model, rec["volume"], ratio if pd.notna(ratio) else 1.0)
            rec.update(cost_plan(drive, unit, prof, coef, meters, prices, poc_prices, wins,
                                 list(daily.index[basis]), rec["volume"]))
            rec.update(saving_split(dict(today_wk), rec))
        plans.append(rec)
    plans = pd.DataFrame(plans)
    plans["volume"] = plans["volume"].fillna(plans.groupby("scenario")["volume"].transform("first"))
    return dict(daily=daily, today_all=today_all, today_wk=today_wk, basis_is_weekdays=weekdays.sum() >= 3,
                plans=plans, coef=coef, meters=meters, src=src, charges=charges, east=east, poc=poc,
                notes=notes, nodes=nodes, sparse=sparse, absent=absent, checks=checks, E=E, n=n, days=days,
                can_compare=can_compare, reason=reason, kpi_days=kpi_days, method=method, ratio=ratio,
                flow_factor=flow_factor)


def write_report(res, man, data, model, paths):
    sample = man["sample"]
    t, ta, plans, daily = res["today_wk"], res["today_all"], res["plans"], res["daily"]
    method = res["method"]
    per_unit = {"flow": "today's measured kWh per m3 pumped at each station",
                "estimated flow": "today's kWh per m3 pumped at each station (flows estimated, see Checks)",
                "pump-hours": "today's measured kWh per pump-hour at each station"}[method]
    days_word = "weekdays" if res["basis_is_weekdays"] else "days"
    tariff_name = "Eastwater's tariff" if data["tariff"] is not None else "the POC's assumed tariff"
    L = ["# Saving vs today's operation", ""]
    if sample:
        L += [f"> **{SAMPLE_NOTE} The saving below only shows that the calculation runs.**", ""]
    valid = plans[plans["valid"] & plans["saving"].notna()] if "saving" in plans else plans.iloc[0:0]
    lo, hi = TARGET_PCT
    if len(valid):
        best = valid.loc[valid["saving"].idxmax()]
        sv = 100 * best["saving"]
        verdict = ("SAMPLE numbers, not compared with the target" if sample else
                   f"{'within' if lo <= sv <= hi else 'above' if sv > hi else 'below'} the {lo:g}-{hi:g}% target")
        others = " ".join(f"{r.schedule}: {100 * r.saving:.1f}%." for r in valid.itertuples() if r.Index != best.name)
        L += [f"**{'[SAMPLE] ' if sample else ''}Saving vs today's operation: {sv:.1f}% of the cost per m3 delivered, "
              f"with {best['schedule']}** ({verdict}). {others}", "",
              f"Like-for-like on {t['days']} {days_word}: each plan is costed with {per_unit} and {tariff_name}, "
              "the same as today's operation, so the difference is the schedule alone. Cost per "
              "m3 delivered includes Ft"
              + (" and the demand charge" if t.get("demand_charge_thb_day") else "") + ", ex VAT. Only plans that "
              "passed the EPANET check count.", ""]
    else:
        why = res["reason"] or "no plan passed the EPANET check"
        L += [f"**Saving vs today's operation: not available yet**, because {why}.", ""]

    L += ["## Today's operation", ""]
    kd = res["kpi_days"]
    cust = model["customers"]
    share = cust.loc[[c for c in res["nodes"] if c in cust.index], "base_demand_m3_day"].sum() / cust[
        "base_demand_m3_day"].sum()
    L += [(f"Measured on {int(kd.sum())} days with complete energy and delivery data "
           f"({daily.index[kd].min():%d %b %Y} to {daily.index[kd].max():%d %b %Y}) out of {len(daily)} loaded. "
           if kd.any() else "No day has complete energy and delivery data yet. ")
          + f"Delivered volume is the sum over {len(res['nodes'])} of the model's {len(cust)} customer nodes "
          f"({share:.0%} of its base demand)"
          + (f"; no data for {', '.join(res['absent'])}" if res["absent"] else "")
          + (f"; left out for reporting on fewer than {MIN_COVER:.0%} of days: {', '.join(res['sparse'])}"
             if res["sparse"] else "") + ".", ""]
    rows = [("Delivered (m3/day)", "delivered_m3_day", f0), ("Pumping energy (kWh/day)", "kwh_day", f0),
            ("kWh per m3", "kwh_per_m3", f4), ("Energy cost, time-of-use + Ft (THB/day)", "energy_cost_thb_day", f0),
            ("Demand charge, monthly charge spread over the month (THB/day)", "demand_charge_thb_day", f0),
            ("THB per m3, energy + Ft", "thb_per_m3_energy", f4),
            ("**THB per m3, incl. demand charge**", "thb_per_m3", f4),
            ("Average price (THB/kWh)", "thb_per_kwh", f4), ("Energy bought on-peak", "on_peak_share", pc),
            ("Pump-hours per day", "pump_hours_day", f0), ("m3 delivered per pump-hour", "m3_per_pump_hour", f0),
            ("THB per m3 at the POC's assumed tariff (energy only)", "poc_thb_per_m3", f4)]
    L += [f"| | all complete days ({ta.get('days', 0)}) | {days_word} ({t.get('days', 0)}) |", "|---|---|---|"]
    L += [f"| {label} | {fmt(ta.get(k, np.nan))} | {fmt(t.get(k, np.nan))} |" for label, k, fmt in rows]
    L += ["", "Ex VAT. The monthly service charge is left out: it is the same whatever the schedule.", ""]

    L += ["### By meter", "", "| meter | stations | energy from | kWh/day | pump-hours/day | kWh per pump-hour | "
          "kWh per m3 pumped | load with no pumps, kW |", "|---|---|---|---|---|---|---|---|"]
    for m, sts in res["meters"].items():
        c = res["coef"].loc[m]
        L.append(f"| {m} | {', '.join(sts)} | {res['src'][m]} | {f0(daily.loc[kd, f'kwh:{m}'].mean())} | "
                 f"{f0(sum(daily.loc[kd, f'pump_hours:{s}'].mean() for s in sts))} | {f0(c['kwh_per_pump_hour'])} | "
                 f"{f4(c['kwh_per_m3_pumped'])} | {f0(c['base_kw']) if c['base_known'] else 'not seen (taken as 0)'} |")
    L += ["", f"kWh per pump-hour and per m3 pumped are net of the load with no pumps running, over the {days_word}.",
          ""]
    ch = [c.assign(meter=m) for m, c in res["charges"].items() if len(c)]
    if ch:
        L += ["### Peak demand in the demand-charge windows", "",
              "| meter | month | window | peak kW (hourly mean) | when | THB/kW | charge THB |",
              "|---|---|---|---|---|---|---|"]
        L += [f"| {c.meter} | {c.month} | {c.window} | {f0(c.peak_kw)} | {c.at:%Y-%m-%d %H:00} | {f2(c.rate)} | "
              f"{f0(c.charge)} |" for c in pd.concat(ch).itertuples()]
        L += ["", "Bills charge the highest 15-minute demand, a little above the hourly mean used here for both "
              "today and the plans.", ""]
    elif data["tariff"] is not None:
        L += ["The tariff has no demand charge.", ""]

    L += ["## Plans vs today", "",
          f"*Modelled* = the plan's own EPANET results (pump efficiency {model['pump_efficiency_pct']:g}% for every "
          "pump, the POC's assumed tariff). *Like-for-like* = "
          + ("the plan's hourly pump counts costed at today's measured kWh per pump-hour" if method == "pump-hours"
             else "the plan's pumped volume at each station (pumps running x the model's flow per pump, scaled to "
             "the plan's delivered volume" + (" and today's pumped-to-delivered ratio" if method == "flow" else "")
             + f") costed at {per_unit.replace(' at each station', ' there')}")
          + f", plus each meter's load with no pumps running, at the tariff above on the same {days_word} as today.",
          "", "| schedule | demand | EPANET check | modelled kWh/m3 | modelled THB/m3 | like-for-like kWh/m3 "
          "| like-for-like THB/m3 | energy on-peak | saving vs today |", "|---|---|---|---|---|---|---|---|---|"]
    if t:
        L.append(f"| **Today (measured)** | {t['delivered_m3_day']:,.0f} m3/day | - | {f4(t['kwh_per_m3'])}\\* | "
                 f"{f4(t['poc_thb_per_m3'])}\\* | {f4(t['kwh_per_m3'])} | {f4(t['thb_per_m3'])} | "
                 f"{pc(t['on_peak_share'])} | - |")
    for r in plans.itertuples():
        if r.status == "no feasible schedule":
            L.append(f"| {r.schedule} | {r.volume:,.0f} m3/day | no feasible schedule | | | | | | |")
            continue
        sav = getattr(r, "saving", np.nan)
        s = (f"**{pc(sav, True)}**" if r.valid and pd.notna(sav) else
             "reference only" if r.schedule.startswith("Model operation") else
             f"not counted ({r.status})" if not r.valid else "-")
        L.append(f"| {r.schedule} | {r.volume:,.0f} m3/day | {r.status} | {f4(r.modelled_kwh_per_m3)} | "
                 f"{f4(r.modelled_thb_per_m3)} | {f4(getattr(r, 'kwh_per_m3', np.nan))} | "
                 f"{f4(getattr(r, 'thb_per_m3', np.nan))} | {pc(getattr(r, 'on_peak_share', np.nan))} | {s} |")
    L += ["", "\\* For today: the measured kWh/m3, and the measured energy priced at the POC's assumed tariff, to "
          "compare with the modelled columns. Saving = 1 - plan / today, in like-for-like THB per m3.", ""]
    if len(valid):
        L += ["Where the saving comes from, in percentage points of today's cost per m3:", "",
              "| plan | fewer kWh per m3 | cheaper hours | lower peak demand | total | "
              "modelled vs today, same tariff |",
              "|---|---|---|---|---|---|"]
        L += [f"| {r.schedule} | {100 * r.saving_kwh:+.1f} | {100 * r.saving_timing:+.1f} | "
              f"{100 * r.saving_demand:+.1f} | **{100 * r.saving:+.1f}** | {100 * r.saving_model_as_is:+.1f} |"
              for r in valid.itertuples()]
        L += ["", "The last column compares the plan's modelled THB/m3 with today's measured energy at the same "
              f"tariff. It includes the gap between the model's {model['pump_efficiency_pct']:g}% pump efficiency and "
              "the real pumps, so it is not a saving a schedule can deliver.", ""]

    L += ["## Checks", ""]
    flow = res["checks"]["flow"].dropna(how="all")
    if len(flow):
        L += ["**Flow per running pump, measured vs model.** "
              + {"flow": "The like-for-like costing uses the measured kWh per m3 pumped, so a gap here does not "
                 "bias the saving. A gap of more than about 10% means the model's pump curves need calibrating.",
                 "estimated flow": "Pump flows are not measured at every meter, so each station's flow per running "
                 f"pump is taken as the model's x {res['flow_factor']:.3f}, the factor that makes today's pumping "
                 "match today's delivered volume. Send pump or station flows to replace this estimate.",
                 "pump-hours": "Pump flows are not measured, so plans are costed per pump-hour: if the model's "
                 "pumps move more water than the real ones, the saving is too high by about that share."}[method],
              "", "| station | measured m3/h | model m3/h (as supplied) | model vs measured |", "|---|---|---|---|"]
        if method == "estimated flow":
            flow = flow.assign(measured_m3_h=flow["model_m3_h"] * res["flow_factor"])
        est = " (estimated)" if method == "estimated flow" else ""
        L += [f"| {s} | {f0(r.measured_m3_h)}{est} | {f0(r.model_m3_h)} | {diff(r.model_m3_h, r.measured_m3_h)} |"
              for s, r in flow.iterrows()]
        L.append("")
    pvd = res["checks"]["pumped_vs_delivered"]
    if pvd and pd.notna(pvd[0]):
        L += [f"**Pumped vs delivered:** the pumps moved {pvd[0]:.3f} m3 for each m3 delivered over {pvd[1]} days. "
              "Anything above 1 is losses, unmetered use and tank level change.", ""]
    b = res["checks"]["bills"]
    if len(b):
        L += ["**Bills vs meter data.** A gap of more than 1-2% points to a meter, tariff or billing-period problem.",
              "", "| meter | period | hours with data | kWh billed | kWh in data | on-peak kWh | energy charge | max "
              "demand kW, bill (15-min) vs data (hourly) |", "|---|---|---|---|---|---|---|---|"]
        L += [f"| {r.meter} | {r.period} | {r.hours_with_data} | {f0(r.kwh_billed)} | {f0(r.kwh_data)} "
              f"({diff(r.kwh_data, r.kwh_billed)}) | {diff(r.kwh_on_peak_data, r.kwh_on_peak_billed)} | "
              f"{diff(r.energy_charge_data, r.energy_charge_billed)} | {f0(r.kw_max_billed)} vs "
              f"{f0(r.kw_max_hourly_data)} |" for r in b.itertuples()]
        L.append("")
    if data["tests"] is not None:
        L += [f"**Pump tests** (wire-to-water efficiency; the model uses {model['pump_efficiency_pct']:g}% for every "
              "pump):", "", "| pump | date | flow m3/h | head m | power kW | efficiency |", "|---|---|---|---|---|---|"]
        L += [f"| {r.pump_id} | {r.test_date:%Y-%m-%d} | {f0(r.flow_m3_h)} | {f0(r.head_m)} | {f0(r.power_kw)} | "
              f"{r.wire_to_water_pct:.1f}% |" for r in data["tests"].itertuples()]
        L.append("")
    sc = data["scada"]
    if sc is not None:
        tk = sc[sc["point_id"].isin(model["tanks"].index) & (sc["quantity"] == "level")]
        if len(tk):
            L += ["**Head tanks today** (m above the floor):", "", "| tank | mean | lowest | highest | model range | "
                  "mean change over a day |", "|---|---|---|---|---|---|"]
            for tank, g in tk.groupby("point_id"):
                s = g.set_index("timestamp")["value_m"]
                first, last = s.groupby(s.index.normalize()).first(), s.groupby(s.index.normalize()).last()
                rng = model["tanks"].loc[tank]
                L.append(f"| {tank} | {s.mean():.2f} | {s.min():.2f} | {s.max():.2f} | {rng.min_level_m:g}-"
                         f"{rng.max_level_m:g} | {(last - first).mean():+.2f} |")
            L.append("")
    reg = data["register"]
    if reg is not None and data["ops"] is not None:
        idle = reg[reg["status"].isin(["standby", "out_of_service", "removed"])]
        ran = data["ops"][data["ops"]["pump_id"].isin(idle["pump_id"]) & (data["ops"]["pumps_running"] > 0)]
        L += [f"**Pumps not on duty** (pump register): {', '.join(idle['pump_id']) or 'none'}; "
              + (f"they ran {ran['pumps_running'].sum():.0f} pump-hours in the data." if len(ran)
                 else "none of them ran in the data."), ""]
    conf = data["confirmations"]
    if conf is not None:
        ans = conf[conf["question_id"].isin(["Q1", "Q2", "Q3"])]
        L += ["**Answers to the key questions:**", ""]
        L += [f"- {r.question_id} {r.topic}: {r.answer if isinstance(r.answer, str) else 'not answered yet'}"
              for r in ans.itertuples()]
        L.append("")
    if res["notes"]:
        L += ["**Pump operation data:** " + "; ".join(res["notes"]) + ".", ""]

    L += ["## Before quoting the saving", ""]
    vol = (valid if len(valid) else plans[plans["valid"]]).dropna(subset=["volume"]).drop_duplicates("scenario")
    if t and len(vol):
        L += ["- The plans were optimised for a flat " + ", ".join(
            f"{r.volume:,.0f} m3/day ({r.scenario})" for r in vol.itertuples()) + " with the POC's assumed tariff; "
            f"today's {'weekday' if res['basis_is_weekdays'] else 'daily'} delivery is {t['delivered_m3_day']:,.0f} "
            f"m3/day ({diff(t['delivered_m3_day'], vol['volume'].iloc[0])}). Comparing per m3 allows for that "
            "roughly. For a firm figure, re-run `matlab/optimize_pumps.m` with Eastwater's demand pattern, tariff "
            "and pump availability, then this script."]
    L += ["- " + {"flow": "Like-for-like assumes each station uses the same kWh per m3 pumped in a plan as today. "
                  "Running fewer pumps in parallel usually lowers it, so if anything the saving is understated.",
                  "estimated flow": "Without measured flows, like-for-like assumes the model's pump flows are off by "
                  "the same share at every station. Send pump flows (pump operation, flow_m3_h) to firm this up.",
                  "pump-hours": "Like-for-like assumes a pump-hour at each station costs the same kWh and moves the "
                  "same water in a plan as today. Send pump flows (pump operation, flow_m3_h) to remove this "
                  "assumption."}[method],
          "- Only plans graded Pass by EPANET get a saving; the others are shown but not counted.",
          f"- Sources: `{rel(EW_DIR / man['report'])}` (data checks), `reports/matlab/pump_plans_kpis.csv` and "
          "`pump_plans_schedule.csv` (plans).", ""]
    L += ["Outputs: " + ", ".join(f"`{rel(p)}`" for p in paths[1:]) + "."]
    paths[0].write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sample", action="store_true", help="use the SAMPLE set even if Eastwater data are loaded")
    a = ap.parse_args()
    sample = a.sample or not (EW_DIR / "manifest.json").exists()
    if not (EW_DIR / f"{'SAMPLE_' if sample else ''}manifest.json").exists():
        raise SystemExit("No loaded data: run python src/load_eastwater.py first.")
    if sample and not a.sample:
        print("No Eastwater data loaded yet; using the SAMPLE set.")
    man, data = load_inputs(sample)
    model = read_model()
    res = analyse(data, model)
    tag = "_SAMPLE" if man["sample"] else ""
    paths = [REPORT_DIR / f"baseline_vs_today{tag}.md", REPORT_DIR / f"baseline_vs_today_kpis{tag}.csv",
             REPORT_DIR / f"baseline_vs_today_daily{tag}.csv"]
    t = res["today_wk"]
    rows = [dict(schedule="Today (measured, all complete days)", **res["today_all"]),
            dict(schedule=f"Today (measured, {'weekdays' if res['basis_is_weekdays'] else 'all days'})", **t)]
    kp = pd.concat([pd.DataFrame(rows), res["plans"].drop(columns=["valid"]).assign(
        valid_plan=res["plans"]["valid"])], ignore_index=True)
    if man["sample"]:
        kp.insert(0, "data", "SAMPLE (synthetic, not Eastwater data)")
    kp.round(6).to_csv(paths[1], index=False, encoding="utf-8-sig")
    daily = res["daily"].rename_axis("date").reset_index()
    daily["date"] = daily["date"].dt.strftime("%Y-%m-%d")
    if man["sample"]:
        daily.insert(0, "data", "SAMPLE")
    daily.round(4).to_csv(paths[2], index=False, encoding="utf-8-sig")
    write_report(res, man, data, model, paths)
    print(f"{'SAMPLE: ' if man['sample'] else ''}today ({t.get('days', 0)} days): "
          f"{t.get('kwh_per_m3', np.nan):.4f} kWh/m3, {t.get('thb_per_m3', np.nan):.4f} THB/m3")
    for r in res["plans"].itertuples():
        if pd.notna(getattr(r, "thb_per_m3", np.nan)):
            print(f"  {r.schedule:45s} {r.status:10s} {r.thb_per_m3:.4f} THB/m3  saving "
                  f"{100 * r.saving:+.1f}%{'' if r.valid else ' (not a valid plan)'}")
    print(f"report -> {rel(paths[0])}")


if __name__ == "__main__":
    main()
