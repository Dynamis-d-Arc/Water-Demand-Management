"""Clean the Bang Phra daily water balance and save it for Python and MATLAB.

Usage:  python src/clean_bangphra.py [path/to/water_daily_report_sample.xlsx]

Writes to data/clean/:
  bangphra_daily.csv / .mat         one row per day, NaN where a value is missing or invalid
  bangphra_flags.csv                every value that was changed or looks suspicious, with the raw value
  bangphra_data_dictionary.csv      column name, Excel column, unit, Thai header, coverage
  bangphra_level_storage_area.csv   level -> storage/area table from recent years
and reports/data_quality_bangphra.md.
"""
import datetime as dt
import sys

import numpy as np
import pandas as pd
from scipy.io import savemat

from config import (CAPACITY_MCM, CLEAN_DIR, COLUMNS, DEFAULT_XLSX, EVAP_MM_PER_DAY,
                    FIRST_DATA_ROW, REPORT_DIR, SHEET)

NAMES = [c[1] for c in COLUMNS]
META = {c[1]: dict(col=c[0], unit=c[2], kind=c[3], blank=c[4], thai=c[5]) for c in COLUMNS}
FLOW_KINDS = {"loss", "release", "use", "use_total", "diversion", "outflow"}
SMOOTH_USES = ["use_total_m3", "use_pwa_chonburi_m3"]
BURSTY_USES = ["use_thai_oil_m3", "use_egat_bangpakong_m3"]
CONTINUOUS_USES = SMOOTH_USES + BURSTY_USES


def load_raw(xlsx):
    raw = pd.read_excel(xlsx, sheet_name=SHEET, header=None, usecols="A:AF",
                        skiprows=FIRST_DATA_ROW - 1, engine="openpyxl")
    raw.columns = NAMES
    raw = raw[raw["date"].map(lambda v: isinstance(v, (dt.datetime, pd.Timestamp)))].copy()
    raw["date"] = pd.to_datetime(raw["date"]).dt.normalize()
    return raw.reset_index(drop=True)


class Flags:
    def __init__(self):
        self.rows = []

    def add(self, df, mask, column, flag, raw_values=None):
        mask = mask.fillna(False)
        vals = df.loc[mask, column] if raw_values is None else raw_values[mask]
        for d, v in zip(df.loc[mask, "date"], vals):
            self.rows.append((d.date().isoformat(), column, flag, v))
        return int(mask.sum())

    def frame(self):
        return pd.DataFrame(self.rows, columns=["date", "column", "flag", "raw_value"])


def hampel(s, window=31, n_sigmas=6.0, min_rel=0.3):
    """Flag points far from the centred rolling median (both in MAD units and relative size)."""
    med = s.rolling(window, center=True, min_periods=window // 3).median()
    mad = (s - med).abs().rolling(window, center=True, min_periods=window // 3).median() * 1.4826
    dev = (s - med).abs()
    return (dev > n_sigmas * mad) & (dev > min_rel * med.abs())


def spikes(s, window=365, factor=4.0):
    """Flag draws above `factor` x the centred one-year 95th percentile of drawing days."""
    p95 = s.where(s > 0).rolling(window, center=True, min_periods=60).quantile(0.95)
    return s > factor * p95


def clean(raw):
    flags = Flags()
    notes = {}
    df = raw.copy()

    # "-" means no draw that day (the sheet's own SUM counts it as 0); other text is unreadable
    for c in NAMES[1:]:
        num = pd.to_numeric(df[c], errors="coerce")
        text = df[c].notna() & num.isna()
        dash = text & df[c].astype(str).str.strip().isin(["-", "."])
        if META[c]["kind"] in FLOW_KINDS:
            flags.add(df, dash, c, "dash_as_zero")
            num[dash] = 0.0
            text &= ~dash
        flags.add(df, text, c, "non_numeric_text")
        df[c] = num

    # The sheet is pre-filled with formula rows to 31 Dec; keep only days with a recorded level.
    has_level = df["level_m_msl"] > 0
    last = df.loc[has_level, "date"].max()
    notes["rows_in_sheet"] = len(df)
    notes["placeholder_rows_dropped"] = int((df["date"] > last).sum())
    df = df[df["date"] <= last].reset_index(drop=True)
    for c in ["level_m_msl", "storage_mcm", "area_km2"]:
        flags.add(df, df[c] <= 0, c, "zero_state")
        df.loc[df[c] <= 0, c] = np.nan

    # Blank cells: zero for intermittent flows, missing otherwise
    for c in NAMES[1:]:
        if META[c]["blank"] == "zero":
            df[c] = df[c].fillna(0.0)

    # Negative flows come from differencing meter readings with no next reading
    for c in NAMES[1:]:
        if META[c]["kind"] in FLOW_KINDS:
            neg = df[c] < 0
            flags.add(df, neg, c, "negative_flow")
            df.loc[neg, c] = np.nan

    # A total is only valid if all of its parts are
    uses = [c for c in NAMES if META[c]["kind"] == "use"]
    parts_bad = df[uses].isna().any(axis=1)
    flags.add(df, parts_bad & df["use_total_m3"].notna(), "use_total_m3", "component_invalid")
    df.loc[parts_bad, "use_total_m3"] = np.nan
    flow_parts = ["evap_seepage_m3", "release_spillway_m3", "release_river_outlet_m3",
                  "release_canal_outlet_m3", "release_agriculture_m3", "use_total_m3"]
    out_bad = df[flow_parts].isna().any(axis=1)
    flags.add(df, out_bad & df["outflow_total_m3"].notna(), "outflow_total_m3", "component_invalid")
    df.loc[out_bad, "outflow_total_m3"] = np.nan

    # Consistency checks against the sheet's own formulas (flag only, before outlier removal)
    tot = df[uses].sum(axis=1, min_count=1)
    tot_off = (tot - df["use_total_m3"]).abs() > 1
    flags.add(df, tot_off, "use_total_m3", "total_differs_from_parts", raw_values=tot - df["use_total_m3"])
    notes["use_total_matches_parts_pct"] = pct(~tot_off, df["use_total_m3"].notna())
    outflow = df[flow_parts].sum(axis=1, min_count=len(flow_parts))
    notes["outflow_matches_parts_pct"] = pct((outflow - df["outflow_total_m3"]).abs() <= 1, df["outflow_total_m3"].notna())
    rain_calc = df["rain_mm"] * df["area_km2"] * 1000
    notes["rain_vol_matches_pct"] = pct((rain_calc - df["rain_vol_m3"]).abs() <= 1 + 0.01 * rain_calc, df["rain_mm"] > 0)
    rate = df["date"].dt.month.map(lambda m: EVAP_MM_PER_DAY[m - 1])
    evap_calc = df["area_km2"] * rate * 1000
    notes["evap_is_area_x_monthly_rate_pct"] = pct((evap_calc - df["evap_seepage_m3"]).abs() <= 0.01 * evap_calc, df["evap_seepage_m3"].notna())

    # Natural inflow (runoff + rain on the reservoir) as the sheet computes it in AF:
    # day t is balanced against the next morning's storage reading.
    divs = [c for c in NAMES if META[c]["kind"] == "diversion"]
    df["div_in_total_m3"] = df[divs].sum(axis=1)
    df["inflow_recalc_m3"] = ((df["storage_mcm"].shift(-1) - df["storage_mcm"]) * 1e6
                              + df["outflow_total_m3"] - df["div_in_total_m3"])
    both = df["inflow_recalc_m3"].notna() & df["runoff_in_m3"].notna()
    notes["inflow_recalc_matches_AF_pct"] = pct((df["inflow_recalc_m3"] - df["runoff_in_m3"]).abs() <= 1000, both)

    dl = df["level_m_msl"].diff()
    flags.add(df, (dl < -0.15) | (dl > 1.0), "level_m_msl", "level_jump", raw_values=dl)

    # Zero on a day-every-day series means the reading is missing
    for c in ["use_total_m3", "use_pwa_chonburi_m3"]:
        z = df[c] == 0
        flags.add(df, z, c, "zero_in_continuous_series")
        df.loc[z, c] = np.nan

    # Spikes and drops on the smooth series
    for c in SMOOTH_USES:
        out = hampel(df[c])
        flags.add(df, out, c, "outlier_hampel")
        df.loc[out, c] = np.nan
    # Thai Oil / EGAT draw in bursts with real zero days; only remove extreme spikes
    for c in BURSTY_USES:
        out = spikes(df[c])
        flags.add(df, out, c, "spike")
        df.loc[out, c] = np.nan

    notes["last_date"] = last.date().isoformat()
    notes["first_date"] = df["date"].min().date().isoformat()
    return df, flags.frame(), notes


def md_table(t):
    head = "| " + " | ".join(map(str, t.columns)) + " |"
    sep = "|" + "---|" * len(t.columns)
    body = ["| " + " | ".join("" if pd.isna(v) else f"{v:,.0f}" if isinstance(v, float) and abs(v) >= 100 else str(v)
                              for v in row) + " |" for row in t.itertuples(index=False)]
    return "\n".join([head, sep, *body])


def pct(ok, base):
    base = base.fillna(False)
    return round(100.0 * (ok & base).sum() / max(int(base.sum()), 1), 1)


def level_storage_table(df, since="2020-01-01"):
    recent = df[(df["date"] >= since) & df["level_m_msl"].notna() & df["storage_mcm"].notna()]
    t = (recent.assign(level_m=recent["level_m_msl"].round(2))
               .groupby("level_m")
               .agg(storage_mcm=("storage_mcm", "median"), area_km2=("area_km2", "median"),
                    n_days=("storage_mcm", "size"))
               .reset_index())
    return t


def storage_curve_drift(df, table):
    """Median storage residual per year against the recent level->storage table."""
    curve = np.interp(df["level_m_msl"], table["level_m"], table["storage_mcm"], left=np.nan, right=np.nan)
    resid = df["storage_mcm"] - curve
    return resid.groupby(df["date"].dt.year).median().round(2)


def save(df, flags, table):
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_csv(CLEAN_DIR / "bangphra_daily.csv", index=False, na_rep="")
    flags.to_csv(CLEAN_DIR / "bangphra_flags.csv", index=False)
    table.to_csv(CLEAN_DIR / "bangphra_level_storage_area.csv", index=False)

    datenum = np.array([d.toordinal() + 366 for d in df["date"].dt.date], dtype=float)
    s = {"date_iso": np.array(out["date"].tolist(), dtype=object), "datenum": datenum}
    for c in df.columns[1:]:
        s[c] = df[c].to_numpy(dtype=float)
    units = {c: META[c]["unit"] if c in META else "m3" for c in df.columns[1:]}
    savemat(CLEAN_DIR / "bangphra_daily.mat", {"bangphra": s, "bangphra_units": units}, do_compression=True)

    rows = []
    for c in df.columns[1:]:
        m = META.get(c, dict(col="(derived)", unit="m3", kind="derived", blank="", thai=""))
        valid = df.loc[df[c].notna(), "date"]
        rows.append(dict(name=c, excel_col=m["col"], unit=m["unit"], kind=m["kind"], blank_rule=m["blank"],
                         thai_header=m["thai"], n_valid=len(valid),
                         first_valid=valid.min().date() if len(valid) else "", last_valid=valid.max().date() if len(valid) else ""))
    pd.DataFrame(rows).to_csv(CLEAN_DIR / "bangphra_data_dictionary.csv", index=False, encoding="utf-8-sig")


def write_report(df, flags, notes, drift):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    yearly = df.groupby(df["date"].dt.year).agg(
        days=("date", "size"),
        **{f"{c.replace('use_', '').replace('_m3', '')}_mean": (c, "mean") for c in CONTINUOUS_USES},
        **{f"{c.replace('use_', '').replace('_m3', '')}_nan": (c, lambda s: int(s.isna().sum())) for c in CONTINUOUS_USES},
        storage_min_mcm=("storage_mcm", "min"), storage_max_mcm=("storage_mcm", "max"),
        div_in_mcm=("div_in_total_m3", lambda s: s.sum() / 1e6),
    ).round(1)
    flag_counts = flags.groupby(["column", "flag"]).size().rename("n").reset_index()
    lines = [
        "# Bang Phra data quality",
        "",
        f"Source sheet `{SHEET}`; {notes['rows_in_sheet']} dated rows, kept {notes['first_date']} to {notes['last_date']} "
        f"({len(df)} days). Dropped {notes['placeholder_rows_dropped']} pre-filled formula rows after the last recorded level.",
        "",
        "## Consistency checks",
        "",
        f"- Total use equals the sum of the user columns: {notes['use_total_matches_parts_pct']}% of days",
        f"- Total outflow equals evaporation + releases + total use: {notes['outflow_matches_parts_pct']}% of days",
        f"- Rain volume equals rain (mm) x surface area: {notes['rain_vol_matches_pct']}% of rainy days",
        f"- Evaporation equals surface area x the sheet's monthly pan rate: {notes['evap_is_area_x_monthly_rate_pct']}% of days "
        "(evaporation is computed, not measured)",
        f"- Natural inflow recomputed as next-day storage change + outflow - diversions matches column AF within 1,000 m3: "
        f"{notes['inflow_recalc_matches_AF_pct']}% of days (AF includes rain falling on the reservoir)",
        "",
        "## Flags",
        "",
        "| column | flag | days |",
        "|---|---|---|",
        *[f"| {r.column} | {r.flag} | {r.n} |" for r in flag_counts.itertuples()],
        "",
        "## Storage vs the 2020+ level-storage table (median residual, MCM)",
        "",
        "A non-zero residual means the level->storage table used that year differs from the current one.",
        "",
        "| year | residual |",
        "|---|---|",
        *[f"| {y} | {v} |" for y, v in drift.items() if pd.notna(v)],
        "",
        "## Yearly summary (m3/day means; *_nan = days missing after cleaning)",
        "",
        md_table(yearly.rename_axis("year").reset_index()),
        "",
        f"Storage capacity used for % full: {CAPACITY_MCM} MCM.",
    ]
    (REPORT_DIR / "data_quality_bangphra.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    xlsx = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_XLSX
    raw = load_raw(xlsx)
    df, flags, notes = clean(raw)
    table = level_storage_table(df)
    drift = storage_curve_drift(df, table)
    save(df, flags, table)
    write_report(df, flags, notes, drift)
    print(f"kept {len(df)} days {notes['first_date']} .. {notes['last_date']}, {len(flags)} flags")
    for k, v in notes.items():
        print(f"  {k}: {v}")
    print(flags.groupby(["column", "flag"]).size().to_string())


if __name__ == "__main__":
    main()
