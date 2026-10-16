"""Rolling-origin backtest of baseline forecasts on the cleaned Bang Phra data.

Usage:  python src/backtest.py

Three products, each tested on origins the models never trained on (retrained
on an expanding window at every test block):
  daily   next 1..7 days of use, for the smooth series (total, PWA Chonburi)
  window  next 7 / 28-day total use, for all four demand series
  storage storage change over the next 7 / 30 / 90 days (supply side)

Models: simple baselines plus one gradient-boosted tree model (GBM) with
P10/P90 quantile models. Writes reports/backtest_metrics.csv,
reports/backtest_predictions.csv, reports/backtest_summary.md and figures.
"""
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from config import CAPACITY_MCM, CLEAN_DIR, FIG_DIR, REPORT_DIR

warnings.filterwarnings("ignore", category=RuntimeWarning)

DAILY_TARGETS = ["use_total_m3", "use_pwa_chonburi_m3"]
WINDOW_TARGETS = ["use_total_m3", "use_pwa_chonburi_m3", "use_thai_oil_m3", "use_egat_bangpakong_m3"]
LABELS = {"use_total_m3": "Total use", "use_pwa_chonburi_m3": "PWA Chonburi",
          "use_thai_oil_m3": "Thai Oil", "use_egat_bangpakong_m3": "EGAT Bang Pakong",
          "storage_mcm": "Storage"}
HORIZONS = range(1, 8)
WINDOWS = [7, 28]
STORAGE_H = [7, 30, 90]
DEMAND_TEST_START = "2022-01-01"
STORAGE_TEST_START = "2019-01-01"
GBM_ARGS = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=40,
                l2_regularization=1.0, random_state=0)


# ---------------------------------------------------------------- data

def load():
    d = pd.read_csv(CLEAN_DIR / "bangphra_daily.csv", parse_dates=["date"]).set_index("date").asfreq("D")
    return d


def filled(s, limit=3):
    """Series used as model input: short gaps (<= limit days) interpolated."""
    return s.interpolate(limit=limit, limit_area="inside")


def calendar(idx):
    idx = pd.DatetimeIndex(idx)
    doy = idx.dayofyear.to_numpy()
    md = idx.month * 100 + idx.day
    return pd.DataFrame({
        "dow": idx.dayofweek, "month": idx.month,
        "doy_sin": np.sin(2 * np.pi * doy / 365.25), "doy_cos": np.cos(2 * np.pi * doy / 365.25),
        # Fixed-date holidays only (Songkran, New Year); lunar holidays are not in the calendar yet
        "holiday": ((md >= 413) & (md <= 415)) | (md >= 1231) | (md <= 102),
    }, index=idx).astype(float)


def weather(d):
    r = d["rain_mm"].fillna(0)
    return pd.DataFrame({"rain_7": r.rolling(7).sum(), "rain_30": r.rolling(30).sum(),
                         "rain_90": r.rolling(90).sum(),
                         "pct_full": d["storage_mcm"] / CAPACITY_MCM}, index=d.index)


# ---------------------------------------------------------------- GBM helper

def fit_predict(train_X, train_y, test_X):
    out = {}
    for name, kw in [("gbm", dict(loss="squared_error")),
                     ("gbm_p10", dict(loss="quantile", quantile=0.1)),
                     ("gbm_p90", dict(loss="quantile", quantile=0.9))]:
        m = HistGradientBoostingRegressor(**GBM_ARGS, **kw).fit(train_X, train_y)
        out[name] = m.predict(test_X)
    return out


def rolling_fit(frame, feature_cols, target_col, target_date_col, origin_col, test_start, block):
    """Retrain at the start of each test block on rows whose target date is before it."""
    preds = []
    frame = frame.copy()
    frame[feature_cols] = frame[feature_cols].replace([np.inf, -np.inf], np.nan)
    starts = pd.date_range(test_start, frame[origin_col].max(), freq=block)
    for i, q in enumerate(starts):
        q_end = starts[i + 1] if i + 1 < len(starts) else frame[origin_col].max() + pd.Timedelta(days=1)
        train = frame[(frame[target_date_col] < q) & frame[target_col].notna()].dropna(subset=feature_cols, how="all")
        test = frame[(frame[origin_col] >= q) & (frame[origin_col] < q_end)]
        if len(test) == 0 or len(train) < 500:
            continue
        p = fit_predict(train[feature_cols], train[target_col], test[feature_cols])
        preds.append(pd.DataFrame(p, index=test.index))
    return pd.concat(preds) if preds else pd.DataFrame(columns=["gbm", "gbm_p10", "gbm_p90"])


# ---------------------------------------------------------------- products

def daily_product(d, col):
    y = d[col]
    yf = filled(y)
    ma7, ma28 = yf.rolling(7).mean(), yf.rolling(28).mean()
    ma91 = yf.rolling(91).mean()
    w = weather(d)
    rows = []
    for h in HORIZONS:
        tgt_idx = d.index + pd.Timedelta(days=h)
        f = pd.DataFrame(index=d.index)
        f["origin"] = d.index
        f["target_date"] = tgt_idx
        f["h"] = h
        f["actual"] = y.reindex(tgt_idx).to_numpy()
        # baselines
        f["naive"] = yf
        f["snaive_week"] = yf.shift(7 - h)
        f["ma7"] = ma7
        f["ma28"] = ma28
        growth = ma28 / ma28.shift(364)
        f["snaive_year_scaled"] = yf.shift(364 - h) * growth
        # GBM features: everything relative to the last 7-day mean so trees cope with level shifts
        for k in range(7):
            f[f"lag{k}_rel"] = yf.shift(k) / ma7
        f["ma28_rel"] = ma28 / ma7
        f["ma91_rel"] = ma91 / ma7
        f["snaive_week_rel"] = yf.shift(7 - h) / ma7
        f["year_ago_rel"] = yf.shift(364 - h) / ma28.shift(364)
        cal = calendar(tgt_idx)
        for c in cal.columns:
            f[f"tgt_{c}"] = cal[c].to_numpy()
        for c in w.columns:
            f[c] = w[c]
        f["scale"] = ma7
        f["y_rel"] = np.log(f["actual"] / ma7)
        rows.append(f)
    frame = pd.concat(rows, ignore_index=True)
    feats = [c for c in frame.columns if c.endswith("_rel") and c != "y_rel"] + \
            [c for c in frame.columns if c.startswith("tgt_")] + list(w.columns) + ["h"]
    frame = frame[np.isfinite(frame["scale"]) & (frame["scale"] > 0)]
    p = rolling_fit(frame, feats, "y_rel", "target_date", "origin", DEMAND_TEST_START, "QS")
    frame = frame.loc[p.index]
    for c in p.columns:
        frame[c] = np.exp(p[c]) * frame["scale"]
    frame["series"] = col
    frame["product"] = "daily"
    frame["step"] = frame["h"]
    return frame


def window_product(d, col):
    y = d[col]
    yf = filled(y)
    ma28, ma91 = yf.rolling(28).mean(), yf.rolling(91).mean()
    w = weather(d)
    rows = []
    for W in WINDOWS:
        fut = yf[::-1].rolling(W).sum()[::-1].shift(-1)          # sum of the next W days
        f = pd.DataFrame(index=d.index)
        f["origin"] = d.index
        f["target_date"] = d.index + pd.Timedelta(days=W)
        f["W"] = W
        f["actual"] = fut
        f["naive"] = yf.rolling(W).sum()                          # last W days
        f["ma28"] = ma28 * W
        f["ma91"] = ma91 * W
        growth = (ma91 / ma91.shift(364)).replace([np.inf, -np.inf], np.nan).clip(0.25, 4)
        f["snaive_year_scaled"] = fut.shift(364) * growth
        scale = ma91 * W
        f["last_W_rel"] = f["naive"] / scale
        f["ma28_rel"] = f["ma28"] / scale
        f["year_ago_rel"] = fut.shift(364) / (ma91.shift(364) * W)
        f["zero_share_28"] = (yf == 0).rolling(28).mean()
        cal = calendar(d.index + pd.Timedelta(days=W // 2))
        for c in ["month", "doy_sin", "doy_cos"]:
            f[f"tgt_{c}"] = cal[c].to_numpy()
        for c in w.columns:
            f[c] = w[c]
        f["scale"] = scale
        f["y_rel"] = f["actual"] / scale
        rows.append(f)
    frame = pd.concat(rows, ignore_index=True)
    feats = ["last_W_rel", "ma28_rel", "year_ago_rel", "zero_share_28", "tgt_month", "tgt_doy_sin",
             "tgt_doy_cos", *w.columns, "W"]
    frame = frame[np.isfinite(frame["scale"]) & (frame["scale"] > 0)]
    p = rolling_fit(frame, feats, "y_rel", "target_date", "origin", DEMAND_TEST_START, "QS")
    frame = frame.loc[p.index]
    for c in p.columns:
        frame[c] = p[c] * frame["scale"]
    frame["series"] = col
    frame["product"] = "window"
    frame["step"] = frame["W"]
    return frame


def storage_product(d):
    s = d["storage_mcm"].interpolate(limit=3, limit_area="inside")
    w = weather(d)
    use = filled(d["use_total_m3"]).rolling(28).mean() / 1e6
    div = d["div_in_total_m3"].rolling(28).mean() / 1e6
    ds = s.diff()
    rows = []
    for H in STORAGE_H:
        f = pd.DataFrame(index=d.index)
        f["origin"] = d.index
        f["target_date"] = d.index + pd.Timedelta(days=H)
        f["H"] = H
        f["now"] = s
        f["actual"] = s.shift(-H)
        f["dS"] = f["actual"] - s
        f["trend7"] = s + H * ds.rolling(7).mean()
        f["naive"] = s
        f["ds7"], f["ds30"] = ds.rolling(7).sum(), ds.rolling(30).sum()
        f["use28"], f["div28"] = use, div
        cal = calendar(d.index)
        for c in ["doy_sin", "doy_cos", "month"]:
            f[c] = cal[c].to_numpy()
        for c in w.columns:
            f[c] = w[c]
        rows.append(f)
    frame = pd.concat(rows, ignore_index=True)
    frame["doy"] = frame["origin"].dt.dayofyear

    # Climatology: mean change for the same time of year in training years only (recomputed per block)
    feats = ["now", "ds7", "ds30", "use28", "div28", "doy_sin", "doy_cos", "month", *w.columns, "H"]
    frame["climatology"] = np.nan
    starts = pd.date_range(STORAGE_TEST_START, frame["origin"].max(), freq="YS")
    for i, q in enumerate(starts):
        q_end = starts[i + 1] if i + 1 < len(starts) else frame["origin"].max() + pd.Timedelta(days=1)
        train = frame[frame["target_date"] < q]
        clim = train.groupby(["H", "doy"])["dS"].mean()
        clim = clim.groupby(level=0, group_keys=False).apply(
            lambda c: c.rolling(15, center=True, min_periods=1).mean())
        test = (frame["origin"] >= q) & (frame["origin"] < q_end)
        key = pd.MultiIndex.from_arrays([frame.loc[test, "H"], frame.loc[test, "doy"]])
        frame.loc[test, "climatology"] = frame.loc[test, "now"] + clim.reindex(key).to_numpy()
    p = rolling_fit(frame, feats, "dS", "target_date", "origin", STORAGE_TEST_START, "YS")
    frame = frame.loc[p.index]
    for c in p.columns:
        frame[c] = frame["now"] + p[c]
    frame["series"] = "storage_mcm"
    frame["product"] = "storage"
    frame["step"] = frame["H"]
    return frame


# ---------------------------------------------------------------- scoring

POINT_MODELS = ["naive", "snaive_week", "ma7", "ma28", "ma91", "snaive_year_scaled", "trend7", "climatology", "gbm"]


def score(frame):
    rows = []
    for (series, product, step), g in frame.groupby(["series", "product", "step"]):
        g = g[g["actual"].notna()]
        models = [m for m in POINT_MODELS if m in g.columns and g[m].notna().any()]
        for m in models:
            gg = g[g[m].notna()]
            e = gg[m] - gg["actual"]
            denom = gg["actual"].abs().sum()
            row = dict(series=series, product=product, step=int(step), model=m, n=len(gg),
                       wape_pct=100 * e.abs().sum() / denom if denom else np.nan,
                       bias_pct=100 * e.sum() / denom if denom else np.nan,
                       mae=e.abs().mean(), rmse=np.sqrt((e ** 2).mean()))
            if m == "gbm":
                row["p10_p90_coverage_pct"] = 100 * ((gg["actual"] >= gg["gbm_p10"]) & (gg["actual"] <= gg["gbm_p90"])).mean()
            rows.append(row)
    met = pd.DataFrame(rows)
    naive = met[met["model"] == "naive"].set_index(["series", "product", "step"])["mae"]
    met["skill_vs_naive_pct"] = 100 * (1 - met["mae"] / naive.reindex(
        pd.MultiIndex.from_frame(met[["series", "product", "step"]])).to_numpy())
    if (met["series"] == "storage_mcm").any():
        st = met["series"] == "storage_mcm"
        met.loc[st, "mae_pct_capacity"] = 100 * met.loc[st, "mae"] / CAPACITY_MCM
    return met


# ---------------------------------------------------------------- figures + summary

def figures(pred, met):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    colors = {"naive": "#8c8c8c", "snaive_week": "#b07aa1", "ma7": "#f28e2b", "ma28": "#edc948",
              "ma91": "#ff9da7", "snaive_year_scaled": "#76b7b2", "trend7": "#9c755f",
              "climatology": "#59a14f", "gbm": "#2a6fb0"}

    fig, axes = plt.subplots(1, len(DAILY_TARGETS), figsize=(12, 4), sharey=True)
    for ax, col in zip(axes, DAILY_TARGETS):
        m = met[(met["series"] == col) & (met["product"] == "daily")]
        for model, g in m.groupby("model"):
            ax.plot(g["step"], g["wape_pct"], marker="o", ms=3, label=model, color=colors.get(model),
                    lw=2.2 if model == "gbm" else 1)
        ax.set_title(f"{LABELS[col]}: daily forecast error", loc="left", fontsize=10)
        ax.set_xlabel("days ahead")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("WAPE %")
    axes[-1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "backtest_daily_wape.png", dpi=110)
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
    for ax, h in zip(axes, [1, 7]):
        g = pred[(pred["series"] == "use_pwa_chonburi_m3") & (pred["product"] == "daily") & (pred["step"] == h)]
        g = g.sort_values("target_date")
        ax.fill_between(g["target_date"], g["gbm_p10"] / 1000, g["gbm_p90"] / 1000, color="#2a6fb0", alpha=0.2, label="GBM P10-P90")
        ax.plot(g["target_date"], g["actual"] / 1000, color="black", lw=0.8, label="actual")
        ax.plot(g["target_date"], g["gbm"] / 1000, color="#2a6fb0", lw=0.8, label="GBM")
        ax.plot(g["target_date"], g["snaive_week"] / 1000, color="#b07aa1", lw=0.6, alpha=0.8, label="same day last week")
        ax.set_title(f"PWA Chonburi, {h} day(s) ahead (1000 m3/day)", loc="left", fontsize=10)
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8, ncol=4)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "backtest_pwa_forecast.png", dpi=110)
    plt.close(fig)

    fig, axes = plt.subplots(len(STORAGE_H), 1, figsize=(13, 9), sharex=True)
    for ax, H in zip(axes, STORAGE_H):
        g = pred[(pred["product"] == "storage") & (pred["step"] == H)].sort_values("target_date")
        ax.fill_between(g["target_date"], g["gbm_p10"], g["gbm_p90"], color="#2a6fb0", alpha=0.2, label="GBM P10-P90")
        ax.plot(g["target_date"], g["actual"], color="black", lw=0.9, label="actual")
        ax.plot(g["target_date"], g["gbm"], color="#2a6fb0", lw=0.8, label="GBM")
        ax.plot(g["target_date"], g["climatology"], color="#59a14f", lw=0.8, label="climatology")
        ax.plot(g["target_date"], g["naive"], color="#8c8c8c", lw=0.6, label="no change")
        ax.set_title(f"Storage forecast {H} days ahead (MCM)", loc="left", fontsize=10)
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8, ncol=5)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "backtest_storage.png", dpi=110)
    plt.close(fig)


def best_table(met, product):
    m = met[met["product"] == product]
    rows = []
    for (series, step), g in m.groupby(["series", "step"]):
        g = g.set_index("model")
        best = g["mae"].idxmin()
        base = [x for x in g.index if x != "gbm"]
        best_base = g.loc[base, "mae"].idxmin()
        rows.append(dict(series=LABELS.get(series, series), step=step, naive_wape=g.loc["naive", "wape_pct"],
                         best_baseline=best_base, best_baseline_wape=g.loc[best_base, "wape_pct"],
                         gbm_wape=g.loc["gbm", "wape_pct"] if "gbm" in g.index else np.nan,
                         gbm_coverage=g.loc["gbm", "p10_p90_coverage_pct"] if "gbm" in g.index else np.nan,
                         gbm_mae=g.loc["gbm", "mae"], best_baseline_mae=g.loc[best_base, "mae"], winner=best))
    return pd.DataFrame(rows)


def md(t, fmt):
    head = "| " + " | ".join(t.columns) + " |"
    sep = "|" + "---|" * len(t.columns)
    body = ["| " + " | ".join(fmt(c, v) for c, v in zip(t.columns, row)) + " |" for row in t.itertuples(index=False)]
    return "\n".join([head, sep, *body])


def summary(met, pred):
    def f(c, v):
        if isinstance(v, float):
            return f"{v:.2f}" if c.endswith("mae") and abs(v) < 100 else f"{v:,.1f}" if abs(v) < 1000 else f"{v:,.0f}"
        return str(v)

    daily = best_table(met, "daily")
    window = best_table(met, "window")
    storage = best_table(met, "storage")
    storage["gbm_mae_pct_cap"] = 100 * storage["gbm_mae"] / CAPACITY_MCM
    span = lambda p: f"{pred.loc[pred['product'] == p, 'origin'].min().date()} to {pred.loc[pred['product'] == p, 'origin'].max().date()}"
    lines = [
        "# Bang Phra baseline forecast backtest",
        "",
        "Rolling-origin test: every forecast uses only data available on its origin day; the GBM is",
        "retrained on an expanding window at the start of each quarter (demand) or year (storage).",
        "WAPE = total absolute error / total actual. Coverage = share of actuals inside GBM P10-P90 (target 80%).",
        "",
        f"## Daily use, 1-7 days ahead (origins {span('daily')})",
        "",
        md(daily.drop(columns=["gbm_mae", "best_baseline_mae"]), f),
        "",
        f"## Total use over the next 7 / 28 days (origins {span('window')})",
        "",
        md(window.drop(columns=["gbm_mae", "best_baseline_mae"]), f),
        "",
        f"## Storage 7 / 30 / 90 days ahead (origins {span('storage')}); error in MCM",
        "",
        md(storage[["series", "step", "best_baseline", "best_baseline_mae", "gbm_mae", "gbm_mae_pct_cap",
                    "gbm_coverage", "winner"]], f),
        "",
        "Baselines: naive = last value (storage: no change); snaive_week = same weekday last week;",
        "ma7/ma28/ma91 = trailing means; snaive_year_scaled = same period last year x recent growth;",
        "trend7 = last 7-day storage trend extrapolated; climatology = typical change for that time of year.",
        "",
        "Full metrics: reports/backtest_metrics.csv. Predictions: reports/backtest_predictions.csv.",
    ]
    (REPORT_DIR / "backtest_summary.md").write_text("\n".join(lines), encoding="utf-8")
    return daily, window, storage


def main():
    d = load()
    parts = []
    for col in DAILY_TARGETS:
        print("daily", col)
        parts.append(daily_product(d, col))
    for col in WINDOW_TARGETS:
        print("window", col)
        parts.append(window_product(d, col))
    print("storage")
    parts.append(storage_product(d))

    keep = ["series", "product", "step", "origin", "target_date", "actual", *POINT_MODELS, "gbm_p10", "gbm_p90"]
    pred = pd.concat([p.reindex(columns=keep) for p in parts], ignore_index=True)
    met = score(pred)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = pred.copy()
    for c in ["origin", "target_date"]:
        out[c] = out[c].dt.strftime("%Y-%m-%d")
    out.to_csv(REPORT_DIR / "backtest_predictions.csv", index=False, float_format="%.4f")
    met.to_csv(REPORT_DIR / "backtest_metrics.csv", index=False, float_format="%.4f")
    figures(pred, met)
    daily, window, storage = summary(met, pred)
    pd.set_option("display.width", 200)
    print(daily.round(1).to_string())
    print(window.round(1).to_string())
    print(storage.round(2).to_string())


if __name__ == "__main__":
    main()
