"""Make the synthetic SAMPLE data set that tests src/load_eastwater.py and src/baseline_vs_today.py end to end.

Usage:  python data_request/samples/make_samples.py

Writes SAMPLE_*.csv next to this script, in the template formats. Every file name starts with SAMPLE_ and every
file's first line says SAMPLE. The data are invented: a rule-based operator runs the model's pumps for March 2026 to
follow a made-up demand, with made-up pump flows and powers and the POC's assumed energy rates. They are NOT
Eastwater data and must never be presented as such. PLANTED lists the errors put in on purpose, so the validation
report has something to find.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
from load_eastwater import QUESTIONS, SCHEMA, read_model  # noqa: E402

NOTE = ("# SAMPLE - synthetic test data made by data_request/samples/make_samples.py. NOT Eastwater data: never use "
        "or present these numbers as real.")
START, DAYS = pd.Timestamp("2026-03-01"), 31
HOLIDAY = pd.Timestamp("2026-03-16")                               # fictional holiday, to test off-peak pricing
Q_PUMP = {"NPL2": 1390.0, "NPL3": 2250.0, "TM_Pond": 2400.0}       # m3/h per running pump (invented)
KW_PUMP = {"NPL2": 430.0, "NPL3": 790.0, "TM_Pond": 950.0}         # kW per running pump (invented)
BASE_KW = {"NPL2": 35.0, "NPL3": 45.0, "TM_Pond": 25.0}            # other loads on each meter (invented)
METER = {"NPL2": "SAMPLE-CA-0001", "NPL3": "SAMPLE-CA-0002", "TM_Pond": "SAMPLE-CA-0003"}
ZONE = {"NPL2_HT": ("NPL2", 0.40, 0.45), "NPL3_HT": ("NPL3", 0.60, 0.55)}   # station, demand share, TM Pond share
RATES = dict(peak=4.1839, off=2.6037, demand=132.93, ft=0.20, service=312.24, vat=7.0)
PLANTED = [
    "pump_operation: NPL2-04p has no rows 2026-03-10 08:00-13:00 (6-hour gap)",
    "pump_operation: NPL2-03p pumps_running = 2 at 2026-03-05 10:00 (above 1, removed)",
    "pump_operation: NPL2-01p 2026-03-07 00:00-02:00 sent twice (exact duplicates)",
    "pump_operation: NPL2-02p 2026-03-08 05:00 sent twice with different values",
    "pump_operation: NPL3 pumps written NPL3-1 ... NPL3-6 (loose match); TM Pond pumps as tags TMP-P1 ... TMP-P6 "
    "(id_map)",
    "station_energy: SAMPLE-CA-0002 (NPL3) kwh = -5 at 2026-03-22 03:00 (removed, so that day is incomplete)",
    "station_energy: no meter data for TM Pond, which has a bill only",
    "customer_delivery: NEW-CUSTOMER-X is not in the model (removed); MTP-IEAT3 sent as tag EW-C-0012 (id_map)",
    "customer_delivery: EIE2 -4,321 m3 on 2026-03-12 (removed, so that day is incomplete); AIE 2026-03-20 sent twice",
    "customer_delivery: hourly file uses day/month/Buddhist-era year (02/03/2569 00:00)",
    "customer_delivery: no data for nodes 71 and 678",
    "scada: NPL3_HT sent as tag NPL3.HT.LVL in m_msl; Burapa pressure in bar; MTP-IEAT3 in kg/cm2; IEAT4 times in UTC",
    "scada: NPL2_HT 35 m at 2026-03-18 14:00 (above the tank, removed); point PT-UNKNOWN not in the model",
]


def write(name, rows, key):
    cols = [c.name for c in SCHEMA[key].cols]
    df = pd.DataFrame(rows).reindex(columns=cols)
    path = HERE / f"SAMPLE_{name}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        f.write(NOTE + "\n")
        df.to_csv(f, index=False, lineterminator="\n")
    print(f"{path.name}: {len(df):,} rows")


def ts(t):
    return t.strftime("%Y-%m-%d %H:%M")


def simulate(model, rng):
    """Hourly pumps running per station and tank levels for a rule-based operator; daily volume per customer."""
    hours = pd.date_range(START, periods=DAYS * 24, freq="h")
    days = pd.date_range(START, periods=DAYS, freq="D")
    factor = np.where(days == HOLIDAY, 0.90, np.where(days.dayofweek >= 5, 0.93, 0.96))
    cust = model["customers"].drop(index=["71", "678"])["base_demand_m3_day"]
    daily = pd.DataFrame({n: b * factor * (1 + 0.02 * rng.standard_normal(DAYS)) for n, b in cust.items()},
                         index=days)
    shape = 1 + 0.06 * np.sin(2 * np.pi * (np.arange(24) - 8) / 24)          # mean 1, peak at 14:00
    demand = (daily.sum(axis=1).reindex(hours.normalize()).to_numpy() / 24) * shape[hours.hour]
    tanks = model["tanks"]
    area = {t: np.pi * r.diameter_m ** 2 / 4 for t, r in tanks.iterrows()}
    level = {t: 0.75 * r.max_level_m for t, r in tanks.iterrows()}
    target = {t: 0.80 * r.max_level_m for t, r in tanks.iterrows()}
    rows = []
    for i, t in enumerate(hours):
        n_tm = 2 if 6 <= t.hour < 22 else 1                 # habit: both TM Pond pumps through the day
        q_tm = n_tm * Q_PUMP["TM_Pond"]
        rec = dict(timestamp=t, TM_Pond=n_tm)
        for tank, (st, d_share, tm_share) in ZONE.items():
            need = d_share * demand[i] - tm_share * q_tm + 0.5 * (target[tank] - level[tank]) * area[tank]
            n = float(np.clip(np.round(need / Q_PUMP[st] * 4) / 4, 0, 6))   # quarter-hour resolution
            inflow = n * Q_PUMP[st] + tm_share * q_tm
            level[tank] = float(np.clip(level[tank] + (inflow - d_share * demand[i]) / area[tank],
                                        tanks.loc[tank, "min_level_m"], tanks.loc[tank, "max_level_m"]))
            rec[st], rec[tank] = n, level[tank]
        rows.append(rec)
    return pd.DataFrame(rows), daily, shape


def per_pump(model, ops, rng):
    """Split each station's pump count over its pumps, rotating duty by day; flow and power with 1% noise."""
    out = []
    for st, pumps in model["pumps"].groupby("station_id").groups.items():
        pumps = list(pumps)
        usable = pumps[:2] if st == "TM_Pond" else pumps
        for r in ops.itertuples():
            n = getattr(r, st)
            k = r.timestamp.day % len(usable)
            order = usable[k:] + usable[:k]
            for p in pumps:
                j = order.index(p) if p in order else 99
                run = 1.0 if j < int(n) else (n - int(n) if j == int(n) else 0.0)
                out.append(dict(timestamp=r.timestamp, pump=p, station=st, pumps_running=run,
                                flow_m3_h=Q_PUMP[st] * run * (1 + 0.01 * rng.standard_normal()) if run else 0.0,
                                power_kw=KW_PUMP[st] * run * (1 + 0.01 * rng.standard_normal()) if run else 0.0))
    return pd.DataFrame(out)


def on_peak(t):
    return (t.dayofweek < 5) & (t.normalize() != HOLIDAY) & (t.hour >= 9) & (t.hour < 22)


def main():
    rng = np.random.default_rng(20260301)
    model = read_model()
    ops, daily, shape = simulate(model, rng)
    pp = per_pump(model, ops, rng)
    hours = ops["timestamp"]

    # id_map: client tags used in the other sample files
    tags = [dict(epanet_id=f"TM_Pond_0{k}p", element_type="pump", client_tag=f"TMP-P{k}",
                 client_name=f"SAMPLE TM Pond pump {k}") for k in range(1, 7)]
    tags += [dict(epanet_id="MTP-IEAT3", element_type="customer", client_tag="EW-C-0012",
                  client_name="SAMPLE customer"),
             dict(epanet_id="NPL3_HT", element_type="tank", client_tag="NPL3.HT.LVL", client_name="SAMPLE tag")]
    write("id_map", tags, "id_map")

    # Pump operation, with the planted errors
    name = {p: (p.replace("NPL3-0", "NPL3-").removesuffix("p") if p.startswith("NPL3") else
                f"TMP-P{int(p[-3:-1])}" if p.startswith("TM_Pond") else p) for p in model["pumps"].index}
    po = pp.assign(timestamp=pp["timestamp"].map(ts), pump_id=pp["pump"].map(name), interval_min=60,
                   speed_pct=100).round({"pumps_running": 2, "flow_m3_h": 1, "power_kw": 1})
    gap = (pp["pump"] == "NPL2-04p") & pp["timestamp"].between("2026-03-10 08:00", "2026-03-10 13:00")
    po = po[~gap.values].copy()
    po.loc[(po["pump_id"] == "NPL2-03p") & (po["timestamp"] == "2026-03-05 10:00"), "pumps_running"] = 2
    dup = po[(po["pump_id"] == "NPL2-01p") & po["timestamp"].isin(["2026-03-07 00:00", "2026-03-07 01:00",
                                                                     "2026-03-07 02:00"])]
    clash = po[(po["pump_id"] == "NPL2-02p") & (po["timestamp"] == "2026-03-08 05:00")].assign(
        pumps_running=0.5, flow_m3_h=700.0, power_kw=220.0)
    write("pump_operation", pd.concat([po, dup, clash]).to_dict("records"), "pump_operation")

    # Station meters: hourly for NPL2 and NPL3; TM Pond has a bill only
    kwh = pp.groupby(["timestamp", "station"])["power_kw"].sum().unstack()
    for st in kwh:
        kwh[st] = (kwh[st] + BASE_KW[st]) * (1 + 0.003 * rng.standard_normal(len(kwh)))
    se = [dict(timestamp=ts(t), meter_id=METER[st], station_id=st, kwh=round(kwh.loc[t, st], 1), interval_min=60)
          for st in ("NPL2", "NPL3") for t in kwh.index]
    for r in se:
        if r["meter_id"] == METER["NPL3"] and r["timestamp"] == "2026-03-22 03:00":
            r["kwh"] = -5
    write("station_energy", se, "station_energy")

    peak = on_peak(kwh.index)
    bills = []
    for st in kwh:
        on, off = kwh.loc[peak, st].sum(), kwh.loc[~peak, st].sum()
        kw_on, kw_off = kwh.loc[peak, st].max() * 1.015, kwh.loc[~peak, st].max() * 1.015
        energy = on * RATES["peak"] + off * RATES["off"]
        demand = round(kw_on, 1) * RATES["demand"]
        ft = (on + off) * RATES["ft"]
        ex = energy + demand + ft + RATES["service"]
        bills.append(dict(meter_id=METER[st], station_id=st, period_start="2026-03-01", period_end="2026-03-31",
                          tariff_code="SAMPLE 4.2.2 TOU", kwh_on_peak=round(on), kwh_off_peak=round(off),
                          kwh_total=round(on) + round(off), kw_max_on_peak=round(kw_on, 1),
                          kw_max_off_peak=round(kw_off, 1), energy_charge_thb=round(energy, 2),
                          demand_charge_thb=round(demand, 2), ft_charge_thb=round(ft, 2), ft_thb_per_kwh=RATES["ft"],
                          service_charge_thb=RATES["service"], pf_charge_thb=0, other_charge_thb=0,
                          total_ex_vat_thb=round(ex, 2), vat_thb=round(ex * RATES["vat"] / 100, 2),
                          total_thb=round(ex * (1 + RATES["vat"] / 100), 2)))
    write("electricity_bills", bills, "electricity_bills")

    rows = [("energy", "weekday", "09:00", "22:00", RATES["peak"], "THB/kWh", "On Peak"),
            ("energy", "weekday", "22:00", "09:00", RATES["off"], "THB/kWh", "Off Peak"),
            ("energy", "weekend", "00:00", "24:00", RATES["off"], "THB/kWh", "Off Peak"),
            ("energy", "holiday", "00:00", "24:00", RATES["off"], "THB/kWh", "Off Peak"),
            ("demand", "weekday", "09:00", "22:00", RATES["demand"], "THB/kW", "On Peak"),
            ("ft", "", "", "", RATES["ft"], "THB/kWh", ""), ("service", "", "", "", RATES["service"], "THB/month", ""),
            ("vat", "", "", "", RATES["vat"], "%", "")]
    tariff = [dict(meter_id="ALL", valid_from="2026-01-01", valid_to="2026-04-30" if c == "ft" else "", component=c,
                   day_type=d, start_time=s, end_time=e, rate=r, unit=u, period_name=p,
                   notes="SAMPLE: energy rates as the POC's assumed tariff; demand, Ft and service illustrative")
              for c, d, s, e, r, u, p in rows]
    tariff.append(dict(tariff[5], valid_from="2026-05-01", valid_to="2026-08-31", rate=0.25))
    write("tariff", tariff, "tariff")
    write("holidays", [dict(date="2026-03-16", name="SAMPLE holiday (fictional, to test off-peak pricing)")],
          "holidays")

    # Customers: daily for 26 nodes (none for 71 and 678), an unknown node, and a client tag
    cd = []
    for n in daily.columns:
        for t, v in daily[n].items():
            cd.append(dict(timestamp=t.strftime("%Y-%m-%d"), node_id="EW-C-0012" if n == "MTP-IEAT3" else n,
                           volume_m3=round(v), interval_min=1440, customer_name="SAMPLE customer", quality="measured"))
    cd += [dict(timestamp=t.strftime("%Y-%m-%d"), node_id="NEW-CUSTOMER-X", volume_m3=1200, interval_min=1440,
                customer_name="SAMPLE customer not in the model") for t in daily.index]
    for r in cd:
        if r["node_id"] == "EIE2" and r["timestamp"] == "2026-03-12":
            r["volume_m3"] = -4321
    cd += [r for r in cd if r["node_id"] == "AIE" and r["timestamp"] == "2026-03-20"]
    write("customer_delivery_daily", cd, "customer_delivery")
    ch = []
    for n in ("MTP-IEAT3", "EIE3", "AIE"):
        for t, v in daily[n]["2026-03-02":"2026-03-08"].items():
            for h in range(24):
                ch.append(dict(timestamp=f"{t.day:02d}/{t.month:02d}/{t.year + 543} {h:02d}:00", node_id=n,
                               volume_m3=round(round(v) * shape[h] / shape.sum(), 2), interval_min=60,
                               customer_name="SAMPLE customer", quality="measured"))
    write("customer_delivery_hourly", ch, "customer_delivery")

    # SCADA: tank levels hourly, pressures hourly, source levels daily at 08:00
    sc = []
    mean2, mean3 = ops["NPL2_HT"].mean(), ops["NPL3_HT"].mean()
    for r in ops.itertuples():
        lv2 = r.NPL2_HT + 0.05 * rng.standard_normal()
        lv3 = r.NPL3_HT + 0.05 * rng.standard_normal()
        sc.append(dict(timestamp=ts(r.timestamp), point_id="NPL2_HT", quantity="level",
                       value=35.0 if r.timestamp == pd.Timestamp("2026-03-18 14:00") else round(lv2, 2), unit="m"))
        sc.append(dict(timestamp=ts(r.timestamp), point_id="NPL3.HT.LVL", quantity="level", value=round(81 + lv3, 2),
                       unit="m_msl"))
        swing = 0.6 * ((lv2 - mean2) + (lv3 - mean3)) / 2
        utc = (r.timestamp - pd.Timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for point, p0, unit, div, when in (("IEAT4", 9.0, "m", 1, utc), ("Burapa", 13.0, "bar", 10.1972, None),
                                           ("MTP-IEAT3", 31.5, "kg/cm2", 10.0, None),
                                           ("Banchang-PWA", 37.5, "m", 1, None)):
            sc.append(dict(timestamp=when or ts(r.timestamp), point_id=point, quantity="pressure",
                           value=round((p0 + swing + 0.3 * rng.standard_normal()) / div, 3), unit=unit))
    for t in pd.date_range(START, periods=DAYS, freq="D") + pd.Timedelta(hours=8):
        k = (t - START).days
        for point, h0 in (("NPL_Res2", 44.6), ("NPL_Res3", 44.6), ("R10885", 24.2)):
            sc.append(dict(timestamp=ts(t), point_id=point, quantity="level", unit="m_msl",
                           value=round(h0 - 0.01 * k + 0.05 * rng.standard_normal(), 2)))
    sc += [dict(timestamp="2026-03-02 09:00", point_id="PT-UNKNOWN", quantity="pressure", value=25.0, unit="m"),
           dict(timestamp="2026-03-02 10:00", point_id="PT-UNKNOWN", quantity="pressure", value=24.6, unit="m")]
    write("scada_levels_pressures", sc, "scada")

    spec = {"NPL2": (1500, 85, 500, 82), "NPL3": (2300, 90, 900, 80), "TM_Pond": (2400, 100, 1100, 80)}
    reg = []
    for p, r in model["pumps"].iterrows():
        q, h, kw, eff = spec[r.station_id]
        reg.append(dict(pump_id=p, station_id=r.station_id,
                        status="standby" if r.station_id == "TM_Pond" and p[-3:-1] > "02" else "duty",
                        rated_flow_m3_h=q, rated_head_m=h, rated_power_kw=kw, pump_efficiency_pct=eff,
                        motor_efficiency_pct=95, vsd="no", year_installed=2010, model_curve=r.curve_text,
                        model_status=r.model_status, notes="SAMPLE values"))
    write("pump_register", reg, "pump_register")
    write("pump_tests", [
        dict(pump_id="NPL2-01p", test_date="2025-11-20", flow_m3_h=1400, head_m=83, power_kw=432, source="SAMPLE"),
        dict(pump_id="NPL3-02p", test_date="2025-11-21", flow_m3_h=2240, head_m=84, power_kw=788, source="SAMPLE"),
        dict(pump_id="TM_Pond_01p", test_date="2025-11-22", flow_m3_h=2390, head_m=98, power_kw=948, source="SAMPLE"),
    ], "pump_tests")
    answers = {"Q1": "SAMPLE answer (invented): placeholders for future demand; nothing delivered there today",
               "Q2": "SAMPLE answer (invented): standby; at most 2 TM Pond pumps run together",
               "Q3": "SAMPLE answer (invented): NPL intakes 44-46 m MSL, TM Pond 23.5-25 m MSL"}
    conf = [dict(question_id=q, topic=t, topic_th=th, question=qq, model_value=mv, answer=answers.get(q, ""),
                 answered_by="SAMPLE" if q in answers else "") for q, t, th, qq, mv in QUESTIONS]
    write("confirmations", conf, "confirmations")
    print("planted errors:\n  " + "\n  ".join(PLANTED))


if __name__ == "__main__":
    main()
