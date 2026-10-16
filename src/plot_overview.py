"""Plot the cleaned Bang Phra series with the values the cleaning removed.

Usage:  python src/plot_overview.py
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from config import CAPACITY_MCM, CLEAN_DIR, DEMAND_TARGETS, FIG_DIR

LABELS = {
    "use_total_m3": "Total use (all users)",
    "use_pwa_chonburi_m3": "PWA Chonburi",
    "use_thai_oil_m3": "Thai Oil",
    "use_egat_bangpakong_m3": "EGAT Bang Pakong",
}


def main():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    d = pd.read_csv(CLEAN_DIR / "bangphra_daily.csv", parse_dates=["date"])
    f = pd.read_csv(CLEAN_DIR / "bangphra_flags.csv", parse_dates=["date"])
    removed = f[f["flag"].isin(["outlier_hampel", "spike", "negative_flow", "zero_in_continuous_series"])]

    fig, axes = plt.subplots(len(DEMAND_TARGETS) + 1, 1, figsize=(13, 13), sharex=True)
    for ax, c in zip(axes, DEMAND_TARGETS):
        ax.plot(d["date"], d[c] / 1000, lw=0.5, color="#2a6fb0", label="kept")
        r = removed[(removed["column"] == c)]
        r = r[pd.to_numeric(r["raw_value"], errors="coerce").between(0, 2e6)]
        ax.scatter(r["date"], pd.to_numeric(r["raw_value"]) / 1000, s=6, color="#d1495b", label="removed", zorder=3)
        ax.set_ylabel("1000 m3/day")
        ax.set_title(LABELS[c], loc="left", fontsize=10)
        ax.grid(alpha=0.3)
    axes[0].legend(loc="upper left", fontsize=8)
    ax = axes[-1]
    ax.plot(d["date"], d["storage_mcm"], lw=0.8, color="#1b7f5b")
    ax.axhline(CAPACITY_MCM, color="grey", ls="--", lw=0.8)
    ax.axhline(0.3 * CAPACITY_MCM, color="#d1495b", ls=":", lw=0.8)
    ax.set_title("Storage (MCM); dashed = capacity, dotted = 30% critical level", loc="left", fontsize=10)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = FIG_DIR / "bangphra_overview.png"
    fig.savefig(out, dpi=110)
    print(out)


if __name__ == "__main__":
    main()
