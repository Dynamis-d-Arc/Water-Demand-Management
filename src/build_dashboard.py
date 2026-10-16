"""Build the executive dashboard from the POC outputs.

Usage:  python src/build_dashboard.py

Reads the cleaned Bang Phra data, the MATLAB reports (forecast backtest, supply outlook,
pump plans, storage what-if) and the EPANET check, gathers the numbers the page shows into one JSON block,
and writes dashboard/poc_dashboard.html from dashboard/template.html. The page is a single
file: it needs no network (the web fonts are optional and fall back to system fonts).
Re-run it after any of the analysis scripts so the page shows the same numbers as the reports.
"""
import json
import math
import re
from datetime import date

import numpy as np
import pandas as pd

from config import CAPACITY_MCM, CLEAN_DIR, DEFAULT_INP, REPORT_DIR, ROOT

MAT = REPORT_DIR / "matlab"
TEMPLATE = ROOT / "dashboard" / "template.html"
OUT = ROOT / "dashboard" / "poc_dashboard.html"
CRITICAL = 0.3 * CAPACITY_MCM
SERIES_NAMES = {"use_total_m3": "Total use", "use_pwa_chonburi_m3": "PWA Chonburi"}
MODEL_NAMES = {"naive": "Yesterday's value", "snaive_week": "Same day last week", "ma7": "7-day average",
               "ma28": "28-day average", "ma91": "91-day average", "snaive_year_scaled": "Same day last year",
               "trend7": "7-day trend", "climatology": "Seasonal average", "gbm": "Machine learning"}


def r(x, nd=2):
    """Round for JSON (one more place than the page shows, so it rounds once); NaN/inf become null."""
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return round(float(x), nd)


def storage_section(d):
    s = d.set_index("date")["storage_mcm"]
    last = s.last_valid_index()
    recent = s.loc[last - pd.Timedelta(days=119):last]
    monthly = s.resample("MS").mean().dropna()
    low = monthly.idxmin()
    return {
        "asOf": last.date().isoformat(),
        "now": r(s[last]),
        "pct": r(100 * s[last] / CAPACITY_MCM, 1),
        "recent": [[t.date().isoformat(), r(v)] for t, v in recent.dropna().items()],
        "monthly": [[t.strftime("%Y-%m"), r(v)] for t, v in monthly.items()],
        "lowest": {"month": low.strftime("%Y-%m"), "mcm": r(monthly[low])},
        "daysBelow30pctSince2010": int((s.loc["2010":] < CRITICAL).sum()),
    }


def outlook_section(d):
    p = pd.read_csv(MAT / "supply_outlook_paths.csv")
    scenarios = []
    for name, g in p.groupby("scenario", sort=False):
        g = g.sort_values("day")
        at = lambda day, col: r(g.loc[g["day"] == day, col].iloc[0])
        risky = g[g["p10_mcm"] < CRITICAL]
        scenarios.append({
            "name": name,
            "demand": "plan" if name.startswith("Allocation") else "recent",
            "diversions": g["diversions"].iloc[0],
            "useStart": r(g["use_m3_per_day"].iloc[0], 0),
            "useMax": r(g["use_m3_per_day"].max(), 0),
            "rows": [[t, r(a), r(b), r(c), r(pb, 3)] for t, a, b, c, pb in
                     zip(g["date"], g["p10_mcm"], g["p50_mcm"], g["p90_mcm"], g["prob_below_30pct_by_day"])],
            "p50_30": at(30, "p50_mcm"), "p50_90": at(90, "p50_mcm"), "p10_90": at(90, "p10_mcm"),
            "p50_end": at(g["day"].max(), "p50_mcm"),
            "probBy90": r(100 * g.loc[g["day"] == 90, "prob_below_30pct_by_day"].iloc[0], 0),
            "probByEnd": r(100 * g["prob_below_30pct_by_day"].iloc[-1], 0),
            "riskDate": risky["date"].iloc[0] if len(risky) else None,
            "endDate": g["date"].iloc[-1],
        })
    years = sorted(set(d["date"].dt.year))
    return {"scenarios": scenarios, "horizonDays": int(p["day"].max()),
            "inflowYears": [years[0], years[-2]], "nYears": len(years) - 1}


def demand_section(d, plan):
    full = d[d["date"].dt.year <= 2024]
    a = full.groupby(full["date"].dt.year).agg(total=("use_total_m3", "mean"), pwa=("use_pwa_chonburi_m3", "mean"))
    local = ["use_cassava_starch_m3", "use_panya_resort_m3", "use_siam_livestock_m3", "use_fisheries_research_m3",
             "use_bangphra_golf_m3", "use_private_1_m3", "use_bangkok_livestock_m3", "use_private_2_m3"]
    act = d.set_index("date").assign(local=lambda x: x[local].sum(axis=1, min_count=1))
    pl = plan.set_index("date")
    pairs = [("PWA Chonburi", "use_pwa_chonburi_m3", "plan_pwa_chonburi_m3"),
             ("Eastwater", "use_eastwater_m3", "plan_eastwater_m3"),
             ("Thai Oil", "use_thai_oil_m3", "plan_thai_oil_m3"),
             ("EGAT Bang Pakong", "use_egat_bangpakong_m3", "plan_egat_bangpakong_m3"),
             ("Local users", "local", "plan_local_users_m3"),
             ("All users", "use_total_m3", "plan_use_total_m3")]
    rows = []
    for label, ac, pc in pairs:
        j = pd.concat([act[ac], pl[pc]], axis=1, join="inner").dropna()
        rows.append({"user": label, "plan": r(j[pc].mean(), 0), "actual": r(j[ac].mean(), 0),
                     "pct": r(100 * j[ac].sum() / j[pc].sum(), 0), "first": j.index.min().date().isoformat(),
                     "last": j.index.max().date().isoformat()})
    return {"annual": [[int(y), r(t, 0), r(p, 0)] for y, t, p in a.itertuples()],
            "first": {"year": int(a.index[0]), "total": r(a["total"].iloc[0], 0), "pwa": r(a["pwa"].iloc[0], 0)},
            "last": {"year": int(a.index[-1]), "total": r(a["total"].iloc[-1], 0), "pwa": r(a["pwa"].iloc[-1], 0)},
            "planVsActual": rows}


def accuracy_section(d):
    m = pd.read_csv(MAT / "backtest_metrics_matlab.csv")
    daily = {}
    for series, label in SERIES_NAMES.items():
        g = m[(m["series"] == series) & (m["product"] == "daily")]
        rows = []
        for step, gs in g.groupby("step"):
            base = gs[gs["model"] != "gbm"].sort_values("wape_pct").iloc[0]
            ml = gs[gs["model"] == "gbm"].iloc[0]
            rows.append([int(step), r(base["wape_pct"], 3), MODEL_NAMES[base["model"]], r(ml["wape_pct"], 3),
                         r(ml["p10_p90_coverage_pct"], 0)])
        daily[label] = rows

    b = pd.read_csv(MAT / "supply_outlook_backtest.csv")
    b["origin"] = pd.to_datetime(b["origin"], format="%d-%b-%Y")
    s = d.set_index("date")["storage_mcm"]
    base_rate = float((s.loc[:"2018"].dropna() < CRITICAL).mean())
    storage = []
    for step, gs in m[m["product"] == "storage"].groupby("step"):
        e = b[b["step"] == step]
        obs = (e["actual"] < CRITICAL).astype(float)
        bs = float(((e["prob_below_30pct"] - obs) ** 2).mean())
        bs_ref = float(((base_rate - obs) ** 2).mean())
        storage.append({
            "days": int(step),
            "climatology": r(gs.loc[gs["model"] == "climatology", "mae"].iloc[0], 3),
            "ml": r(gs.loc[gs["model"] == "gbm", "mae"].iloc[0], 3),
            "mlCover": r(gs.loc[gs["model"] == "gbm", "p10_p90_coverage_pct"].iloc[0], 0),
            "esp": r((e["p50"] - e["actual"]).abs().mean(), 3),
            "espCover": r(100 * ((e["actual"] >= e["p10"]) & (e["actual"] <= e["p90"])).mean(), 0),
            "espBias": r((e["p50"] - e["actual"]).mean()),
            "brierSkill": r(1 - bs / bs_ref, 3),
            "n": int(len(e)),
        })
    period = [b["origin"].min().date().isoformat(), b["origin"].max().date().isoformat()]
    return {"daily": daily, "storage": storage, "storagePeriod": period,
            "demandPeriod": ["2022-01-01", d["date"].max().date().isoformat()]}


def tanks_from_inp(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    block = re.search(r"\[TANKS\](.*?)\n\[", text, re.S).group(1)
    tanks = []
    for line in block.splitlines():
        parts = line.split(";")[0].split()
        if len(parts) >= 6:
            name, _, init, lo, hi, diam = parts[:6]
            area = math.pi * float(diam) ** 2 / 4
            tanks.append({"name": name, "volume_m3": r(area * (float(hi) - float(lo)), 0)})
    return tanks


def network_section():
    nodes = pd.read_csv(REPORT_DIR / "epanet_demand_nodes.csv")
    k = pd.read_csv(MAT / "pump_plans_kpis.csv")
    info = pd.read_csv(MAT / "pump_plans_scenarios.csv")
    sch = pd.read_csv(MAT / "pump_plans_schedule.csv")
    tanks = tanks_from_inp(DEFAULT_INP)
    model = k[k["scenario"] == "Model as supplied"].iloc[0]
    demand_model = float(info.loc[info["key"] == "model_demand", "demand_m3_day"].iloc[0])
    storage_m3 = sum(t["volume_m3"] for t in tanks)

    def plans(scenario):
        g = k[k["scenario"] == scenario]
        out = []
        for row in g.itertuples():
            out.append({"schedule": row.schedule, "feasible": bool(row.feasible), "status": row.status,
                        "converged": bool(row.converged), "energy": r(row.energy_kwh, 0), "cost": r(row.cost_thb, 0),
                        "kwhPerM3": r(row.kwh_per_m3, 4), "thbPerM3": r(row.thb_per_m3, 4),
                        "vsPct": r(row.cost_vs_comparator_pct, 1), "comparator": row.comparator,
                        "minPressure": r(row.min_customer_pressure_m), "reserve": "" if pd.isna(row.tank_reserve)
                        else row.tank_reserve, "starts": None if pd.isna(row.pump_starts) else int(row.pump_starts)})
        return out

    scenarios = []
    for row in info.itertuples():
        scenarios.append({"key": row.key, "name": row.scenario, "demand": r(row.demand_m3_day, 0),
                          "maxPumping": row.max_pumping_npl2_npl3_tm, "maxTm": int(row.max_tm_pond_pumps),
                          "tankFlows": [[row.tank1, r(row.tank1_net_flow_m3_day, 0)],
                                        [row.tank2, r(row.tank2_net_flow_m3_day, 0)]],
                          "plans": plans(row.scenario)})
    schedules = {}
    for (scen, name), g in sch.groupby(["scenario", "schedule"], sort=False):
        schedules.setdefault(scen, {})[name] = [[int(h), int(a), int(b), int(c), r(t, 4)] for h, a, b, c, t in
                                                zip(g["hour"], g["npl2_pumps"], g["npl3_pumps"],
                                                    g["tm_pond_pumps"], g["tariff_thb_per_kwh"])]
    tariff = sch.drop_duplicates("hour").sort_values("hour")["tariff_thb_per_kwh"]
    return {
        "nodes": [[n.node, r(n.min_pressure_m), r(n.base_demand_cmd, 0), r(n.elevation_m, 1)] for n in
                  nodes.sort_values("min_pressure_m").itertuples()],
        "target": 10,
        "model": {"status": model.status, "energy": r(model.energy_kwh, 0), "kwhPerM3": r(model.kwh_per_m3, 4),
                  "thbPerM3": r(model.thb_per_m3, 4), "cost": r(model.cost_thb, 0), "demand": r(demand_model, 0),
                  "minPressure": r(model.min_customer_pressure_m)},
        "tanks": tanks,
        "tankStorage": r(storage_m3, 0),
        "tankMinutes": {s["key"]: r(storage_m3 / (s["demand"] / 1440), 0) for s in scenarios},
        "tariff": {"peak": r(tariff.max(), 4), "offPeak": r(tariff.min(), 4), "peakHours": "09:00-22:00"},
        "scenarios": scenarios,
        "schedules": schedules,
    }


def savings_section():
    """Storage what-if and cost per m3 by station (matlab/whatif_storage_sources.m)."""
    w = pd.read_csv(MAT / "whatif_storage_kpis.csv")
    st = pd.read_csv(MAT / "whatif_station_cost.csv")
    k = pd.read_csv(MAT / "pump_plans_kpis.csv")
    storage = []
    for scale, g in w[w["plan"].isin(["Reference (lowest energy)", "Lowest cost (tariff-aware)"])].groupby("storage_scale"):
        ref = g[g["plan"] == "Reference (lowest energy)"].iloc[0]
        low = g[g["plan"] == "Lowest cost (tariff-aware)"].iloc[0]
        storage.append({"scale": int(scale), "volume": r(ref["usable_volume_m3"], 0), "hours": r(ref["storage_hours"], 4),
                        "refCost": r(ref["cost_thb"], 0), "lowCost": r(low["cost_thb"], 0),
                        "bothPass": bool(ref["passes"]) and bool(low["passes"]),
                        "savingPct": r(low["saving_pct"], 6), "savingThb": r(low["saving_thb_per_day"], 0),
                        "vsTodayPct": r(low["saving_vs_today_pct"], 6)})
    # Lower-tank lever: the what-if's lowest-energy plan for today's tanks vs the pump-plans reference
    high = k[(k["scenario"] == "Without placeholder nodes 71 and 678") & k["schedule"].str.startswith("Reference")].iloc[0]
    lowp = w[(w["storage_scale"] == 1) & (w["plan"] == "Reference (lowest energy)")].iloc[0]
    lever = {"highKwh": r(high["kwh_per_m3"], 6), "highEnergy": r(high["energy_kwh"], 0), "highCost": r(high["cost_thb"], 0),
             "highPass": high["status"] == "Pass" and bool(high["converged"]),
             "lowKwh": r(lowp["kwh_per_m3"], 6), "lowEnergy": r(lowp["energy_kwh"], 0), "lowCost": r(lowp["cost_thb"], 0),
             "lowPass": bool(lowp["passes"]),
             "energyPct": r(100 * (1 - lowp["energy_kwh"] / high["energy_kwh"]), 6),
             "thbDay": r(high["cost_thb"] - lowp["cost_thb"], 0),
             "levels": {"NPL2_HT": [r(lowp["npl2ht_min_pct"], 0), r(lowp["npl2ht_max_pct"], 0)],
                        "NPL3_HT": [r(lowp["npl3ht_min_pct"], 0), r(lowp["npl3ht_max_pct"], 0)]}}
    stations = [[s.station, int(s.pumps), r(s.kwh_per_m3_85, 6), r(s.thb_per_m3_offpeak, 6), r(s.thb_per_m3_peak, 6),
                 r(s.flow_m3h, 0), r(s.head_m, 1), r(s.efficiency_pct, 1), s.efficiency_source]
                for s in st[st["valid_85"] == 1].itertuples()]
    return {"storage": storage, "lever": lever, "stations": stations}


def main():
    d = pd.read_csv(CLEAN_DIR / "bangphra_daily.csv", parse_dates=["date"])
    plan = pd.read_csv(CLEAN_DIR / "bangphra_allocation_plan.csv", parse_dates=["date"])
    data = {
        "built": date.today().isoformat(),
        "capacity": CAPACITY_MCM,
        "critical": r(CRITICAL, 1),
        "storage": storage_section(d),
        "outlook": outlook_section(d),
        "demand": demand_section(d, plan),
        "accuracy": accuracy_section(d),
        "network": network_section(),
        "savings": savings_section(),
    }
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/{}", blob)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")
    s = data["outlook"]["scenarios"]
    print("outlook:", [(x["name"], x["probByEnd"], x["riskDate"]) for x in s])
    print("storage accuracy:", data["accuracy"]["storage"])
    print("plan vs actual:", [(x["user"], x["pct"]) for x in data["demand"]["planVsActual"]])
    print("network model:", data["network"]["model"], "tanks", data["network"]["tankStorage"], data["network"]["tankMinutes"])
    sv = data["savings"]
    print("savings: lever energy -%.1f%%, %d THB/day | storage" % (sv["lever"]["energyPct"], sv["lever"]["thbDay"]),
          [(x["scale"], round(x["savingPct"], 2), x["bothPass"]) for x in sv["storage"]])


if __name__ == "__main__":
    main()
