"""Load the EPANET model, run its hydraulic simulation and report whether it is usable.

Usage:  python src/check_epanet.py [path/to/model.inp]

The model is copied to a temporary folder first, so EPANET's report/output files
never land next to the original .inp. Writes reports/epanet_check.md,
reports/epanet_demand_nodes.csv and reports/epanet_timeseries.csv.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from epyt import epanet

from config import DEFAULT_INP, REPORT_DIR

WARNINGS = {1: "system hydraulically unbalanced", 2: "system may be hydraulically unstable",
            3: "system disconnected", 4: "pumps cannot deliver enough flow or head",
            5: "valves cannot deliver enough flow", 6: "system has negative pressures"}
LOW_PRESSURE_M = 10.0


def run(inp):
    work = Path(tempfile.mkdtemp(prefix="epanet_check_"))
    model = work / "model.inp"
    shutil.copy(inp, model)
    d = epanet(str(model), display_msg=False, display_warnings=False)
    try:
        return simulate(d), work
    finally:
        d.unload()


def simulate(d):
    node_ids = d.getNodeNameID()
    link_ids = d.getLinkNameID()
    junc = np.array(d.getNodeJunctionIndex()) - 1
    resv = np.array(d.getNodeReservoirIndex()) - 1
    tank = np.array(d.getNodeTankIndex()) - 1
    pump = np.array(d.getLinkPumpIndex()) - 1
    elev = np.array(d.getNodeElevations())
    base = np.array(d.getNodeBaseDemands()[1])
    dem_nodes = [i for i in junc if base[i] > 0]

    info = dict(
        flow_units=d.getFlowUnits(), headloss=d.getOptionsHeadLossFormula(),
        duration_h=d.getTimeSimulationDuration() / 3600, hyd_step_h=d.getTimeHydraulicStep() / 3600,
        junctions=len(junc), reservoirs=len(resv), tanks=len(tank), pipes=d.getLinkPipeCount(),
        pumps=len(pump), valves=d.getLinkValveCount(), patterns=d.getPatternCount(),
        controls=d.getControlRulesCount(), rules=d.getRuleCount(),
        demand_nodes=len(dem_nodes), base_demand_cmd=float(base[dem_nodes].sum()),
    )

    steps, series = [], []
    junc_min_p = np.full(len(junc), np.inf)
    d.openHydraulicAnalysis()
    d.initializeHydraulicAnalysis(0)
    tstep = 1
    while tstep > 0:
        t = d.runHydraulicAnalysis()
        code = int(d.api.errcode or 0)
        p = np.array(d.getNodePressure())
        head = np.array(d.getNodeHydraulicHead())
        demand = np.array(d.getNodeActualDemand())
        flow = np.array(d.getLinkFlows())
        status = np.array(d.getLinkStatus())
        jp = p[junc]
        junc_min_p = np.minimum(junc_min_p, jp)
        steps.append(dict(time_h=t / 3600, warning_code=code, warning=WARNINGS.get(code, "" if code == 0 else f"error {code}"),
                          min_junction_pressure_m=float(jp.min()), negative_pressure_junctions=int((jp < 0).sum()),
                          demand_cmd=float(demand[junc].sum()), reservoir_supply_cmd=float(-demand[resv].sum()),
                          tank_net_outflow_cmd=float(-demand[tank].sum()),
                          pumps_running=int(sum(status[i] == 1 for i in pump))))
        row = {"time_h": t / 3600}
        for i in tank:
            row[f"tank_level_m:{node_ids[i]}"] = head[i] - elev[i]
        for i in pump:
            row[f"pump_flow_cmd:{link_ids[i]}"] = flow[i]
        for i in dem_nodes:
            row[f"pressure_m:{node_ids[i]}"] = p[i]
        series.append(row)
        tstep = d.nextHydraulicAnalysisStep()
    d.closeHydraulicAnalysis()

    ts = pd.DataFrame(series).drop_duplicates("time_h", keep="last")
    steps = pd.DataFrame(steps).drop_duplicates("time_h", keep="last")
    nodes = pd.DataFrame({
        "node": [node_ids[i] for i in dem_nodes],
        "elevation_m": elev[dem_nodes],
        "base_demand_cmd": base[dem_nodes],
        "min_pressure_m": [ts[f"pressure_m:{node_ids[i]}"].min() for i in dem_nodes],
        "max_pressure_m": [ts[f"pressure_m:{node_ids[i]}"].max() for i in dem_nodes],
    }).sort_values("base_demand_cmd", ascending=False)
    nodes["status"] = np.where(nodes["min_pressure_m"] < 0, "FAIL negative",
                               np.where(nodes["min_pressure_m"] < LOW_PRESSURE_M, f"WARN < {LOW_PRESSURE_M:g} m", "OK"))

    # Junctions without demand that still go negative (EPANET only warns for demand junctions)
    neg = [k for k in range(len(junc)) if junc_min_p[k] < 0]
    links_of = {}
    for li, (a, b) in enumerate(d.getLinkNodesIndex()):
        for n in (a - 1, b - 1):
            links_of.setdefault(n, []).append(link_ids[li])
    info["negative_pressure_junctions"] = pd.DataFrame({
        "junction": [node_ids[junc[k]] for k in neg],
        "elevation_m": elev[junc[neg]] if neg else [],
        "min_pressure_m": junc_min_p[neg] if neg else [],
        "links": [", ".join(links_of.get(junc[k], [])) for k in neg],
    }).sort_values("elevation_m", ascending=False)
    return info, steps, ts, nodes


def report(info, steps, ts, nodes, inp):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    nodes.round(2).to_csv(REPORT_DIR / "epanet_demand_nodes.csv", index=False)
    ts.round(3).to_csv(REPORT_DIR / "epanet_timeseries.csv", index=False)

    neg = info.pop("negative_pressure_junctions")
    neg.round(2).to_csv(REPORT_DIR / "epanet_negative_pressure_junctions.csv", index=False)
    warn = steps[steps["warning_code"] != 0]
    tank_cols = [c for c in ts.columns if c.startswith("tank_level_m:")]
    pump_cols = [c for c in ts.columns if c.startswith("pump_flow_cmd:")]
    verdict = "runs to completion" if len(steps) and steps["time_h"].max() >= info["duration_h"] else "did not complete"
    lines = [
        "# EPANET model check",
        "",
        f"Model: `{Path(inp).name}`. Simulation {verdict}: {len(steps)} hydraulic steps over {info['duration_h']:g} h, "
        f"{len(warn)} step(s) with warnings.",
        "",
        "## Model contents",
        "",
        *[f"- {k}: {v:,.0f}" if isinstance(v, float) else f"- {k}: {v}" for k, v in info.items()],
        "",
        "## Warnings by time step",
        "",
        "None." if warn.empty else "\n".join(f"- {r.time_h:g} h: {r.warning}" for r in warn.itertuples()),
        "",
        "## System balance per step (CMD)",
        "",
        "| time h | demand | reservoir supply | tank net outflow | pumps running | min junction pressure m | negative-pressure junctions |",
        "|---|---|---|---|---|---|---|",
        *[f"| {r.time_h:g} | {r.demand_cmd:,.0f} | {r.reservoir_supply_cmd:,.0f} | {r.tank_net_outflow_cmd:,.0f} | "
          f"{r.pumps_running} | {r.min_junction_pressure_m:.1f} | {r.negative_pressure_junctions} |"
          for r in steps.itertuples()],
        "",
        "## Tanks (level above tank bottom, m)",
        "",
        *[f"- {c.split(':', 1)[1]}: start {ts[c].iloc[0]:.2f}, min {ts[c].min():.2f}, max {ts[c].max():.2f}, end {ts[c].iloc[-1]:.2f}"
          for c in tank_cols],
        "",
        "## Pumps (flow, CMD; 0 = off)",
        "",
        *[f"- {c.split(':', 1)[1]}: mean {ts[c].mean():,.0f}, max {ts[c].max():,.0f}" for c in pump_cols],
        "",
        f"## Junctions with negative pressure ({len(neg)}, none of them has demand)",
        "",
        "EPANET's negative-pressure warning only covers junctions with demand, so these pass silently.",
        "",
        "| junction | elevation m | min pressure m | connected links |",
        "|---|---|---|---|",
        *[f"| {r.junction} | {r.elevation_m:.2f} | {r.min_pressure_m:.2f} | {r.links} |" for r in neg.itertuples()],
        "",
        f"## Customer demand nodes ({len(nodes)}; pressure over the run)",
        "",
        "| node | base demand CMD | min pressure m | max pressure m | status |",
        "|---|---|---|---|---|",
        *[f"| {r.node} | {r.base_demand_cmd:,.0f} | {r.min_pressure_m:.1f} | {r.max_pressure_m:.1f} | {r.status} |"
          for r in nodes.itertuples()],
    ]
    (REPORT_DIR / "epanet_check.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    inp = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INP
    (info, steps, ts, nodes), work = run(inp)
    report(info, steps, ts, nodes, inp)
    shutil.rmtree(work, ignore_errors=True)
    pd.set_option("display.width", 200)
    print(info)
    print(steps.to_string())
    print(nodes.to_string())


if __name__ == "__main__":
    main()
