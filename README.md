# Water demand & supply POC: Bang Phra

Proof of concept for the Forecast → Optimize → EPANET check flow. It:

1. Cleans the Bang Phra reservoir daily water balance (sheet `WB บางพระ`, 1990-01-01 to 2025-03-28) and the water-year allocation plan.
2. Backtests baseline demand and storage forecasts against it, in Python and MATLAB.
3. Builds a storage risk outlook for Bang Phra (probability of falling below 30% of capacity).
4. Checks the Rayong EPANET model (`../Demand-2023 v20RY to MTP new TM2P.inp`) and grades any pump schedule Pass, Warning or Fail.
5. Prototypes day-ahead pump scheduling (Plans A/B/C), with every plan checked in EPANET.
6. Presents the results in an executive dashboard, [`dashboard/poc_dashboard.html`](dashboard/poc_dashboard.html).

Data cleaning and the dashboard build run in Python. Forecasting, optimization and EPANET checks run in MATLAB R2026b; the Python versions of the backtest and the EPANET check are kept for comparison.

## Executive dashboard

`dashboard/poc_dashboard.html` is a single file. To present it, open it in any browser; it works offline (the IBM Plex web fonts fall back to system fonts without internet). It contains:
- **Three key messages:** supply, demand and network.
- **Six headline numbers:** storage, shortage risk, forecast errors, the capacity gap and pumping energy.
- **Supply outlook:** switch between recent use and the allocation plan, and with or without diversions.
- **Supporting charts:** storage since 1990, demand growth, use against the allocation plan, and forecast accuracy.
- **Network:** customer pressures, the pump-plan comparison and pumps by hour.
- **Roadmap:** status against the proposal's POC and QW1–QW4 phases, plus the decisions and data needed.

Every chart has a hover readout and a **Show data** table. The **Theme** button switches between light and dark; light suits projectors.

Rebuild it after re-running any analysis script, so it shows the same numbers as the reports:

```bash
python src/build_dashboard.py     # -> dashboard/poc_dashboard.html (from dashboard/template.html)
```

The page embeds client data (reservoir volumes, network pressures). Share it under the same terms as the data.

## Run

```bash
python src/clean_bangphra.py      # ~10 s   -> data/clean/, reports/data_quality_bangphra.md
python src/plot_overview.py       # ~5 s    -> reports/figures/bangphra_overview.png
python src/backtest.py            # ~10 min -> reports/backtest_*.csv/.md, figures
python src/check_epanet.py        # ~5 s    -> reports/epanet_*.md/.csv
```

- **Default inputs:** `C:\Users\Brandon\Downloads\water_daily_report_sample.xlsx`, and the `.inp` one folder up. Pass a different path as the first argument to override either one.
- **Requirements:** pandas, numpy, scipy, scikit-learn, matplotlib, openpyxl, epyt.

## Outputs

| file | what |
|---|---|
| `data/clean/bangphra_daily.csv` | One row per day with all 31 sheet columns (English names, units in the name) plus `div_in_total_m3` and `inflow_recalc_m3`. Empty = missing or removed. |
| `data/clean/bangphra_daily.mat` | The same data as MATLAB struct `bangphra`, plus `datenum` and `date_iso`; units are in `bangphra_units`. |
| `data/clean/bangphra_flags.csv` | Every value changed or flagged by cleaning, with its raw value. |
| `data/clean/bangphra_data_dictionary.csv` | Each column's Excel column, Thai header, unit and coverage. |
| `data/clean/bangphra_level_storage_area.csv` | Level → storage / surface-area table built from 2020+ data. |
| `data/clean/bangphra_allocation_plan.csv` | Daily allocation plan per user for the water year 1 Nov 2024 – 31 Oct 2025, from sheet `3. รายงานอ่างฯบางพระ`. |
| `reports/data_quality_bangphra.md` | Consistency checks, flag counts, yearly summary. |
| `reports/backtest_summary.md` | Best baseline vs GBM for each series and horizon. |
| `reports/backtest_metrics.csv`, `backtest_predictions.csv` | Full metrics and every forecast made in the backtest. |
| `reports/epanet_check.md` | Whether the model runs, the system balance, tanks, pumps and pressure at each customer node. |

### MATLAB (R2026b)

```bash
matlab -batch "run('matlab/check_setup.m')"          # toolboxes, licences, data loads from CSV and .mat
matlab -batch "run('matlab/check_epanet.m')"         # runs the .inp from MATLAB, compares with Python
matlab -batch "run('matlab/backtest_forecast.m')"    # ~6 min -> reports/matlab/ (port of src/backtest.py)
matlab -batch "run('matlab/supply_outlook.m')"       # ~1 min -> reports/matlab/supply_outlook.* (storage risk, ESP)
matlab -batch "run('matlab/optimize_pumps.m')"       # ~25 min -> pump plans A/B/C, each checked in EPANET
```

Reusable functions in `matlab/`:
- `validate_plan.m`: runs any pump schedule and demand pattern through a 24 h EPANET simulation. It returns Pass, Warning or Fail with reasons, plus energy (kWh), cost (THB), kWh/m³, THB/m³, customer pressures and tank levels.
- `load_network.m`: opens the `.inp` from a temporary copy, so EPANET's files never land next to the original. By default it uses `EpytNetwork.m`, which runs EPANET through the Python `epyt` package with the same method names as the EPANET-MATLAB Toolkit. Pass `"toolkit"` as a second argument to use the toolkit instead.

`backtest_forecast.m` re-implements the Python backtest with the same:
- products and baselines;
- features and test periods;
- quarterly or yearly retraining.

The GBM is `fitrensemble` (LSBoost). There is one deliberate difference: `fitrensemble` has no quantile loss, so its P10/P90 range comes from the model's own errors in earlier test blocks (rolling conformal). [reports/matlab/backtest_comparison.md](reports/matlab/backtest_comparison.md) compares the two:
- **Baselines:** all 111 combinations match Python exactly.
- **GBM accuracy:** within about 0.1 WAPE points of Python for daily demand and storage at 30/90 days. It is 0.1–1.5 points worse on the 7/28-day totals, and 1.23 vs 1.09 MCM for storage at 7 days.
- **P10–P90 coverage:** the MATLAB ranges are far better calibrated: 78–82% for daily demand and storage, against Python's 51–83%.

- **Requirements:**
  - Statistics and Machine Learning, Optimization, Econometrics and Global Optimization toolboxes;
  - MATLAB's Python interface (`pyenv`) pointing at a Python with `epyt` installed, which is the default EPANET backend;
  - only for the `"toolkit"` backend: the EPANET-MATLAB Toolkit and the MathWorks MinGW-w64 compiler add-on.
- **Results:** the epyt backend and the toolkit give identical EPANET results: the same energy (191,207 kWh/day), tank levels, warnings and Pass/Warning/Fail grades. Both agree with the Python check to within 0.005 m at all 28 customer nodes.

```matlab
T = readtimetable("data/clean/bangphra_daily.csv");   % 'date' becomes the row times
S = load("data/clean/bangphra_daily.mat");
t = datetime(S.bangphra.datenum, "ConvertFrom", "datenum");
plot(t, S.bangphra.use_pwa_chonburi_m3)
```

## Cleaning rules

- **Placeholder rows:** the sheet is pre-filled with formula rows to 31 Dec 2025. Only days with a recorded water level are kept.
- **Negative flows:** these come from differencing meter readings when the next reading is missing (for example 28 Mar 2025, PWA = −12 million m³). They are removed, along with any total that includes them. The sheet's inflow columns (AE/AF) are computed from the outflow total, so they are removed on the same 37 days.
- **Blanks and `-`:** both count as 0 for flows that are not recorded every day, which matches the sheet's own SUM formulas. A blank on PWA or on total use counts as missing.
- **Outliers:**
  - *PWA and total use:* a rolling outlier filter (31-day median, more than 6 MADs and more than 30% away) removes errors.
  - *Thai Oil and EGAT:* these draw water in bursts and have real zero days, so only spikes above 4× the one-year 95th percentile are removed.
- **Sheet formulas re-checked:**
  - total use = sum of users: 100%;
  - outflow = evaporation + releases + use: 100%;
  - natural inflow (column AF) = next-day storage change + outflow − diversions: 99.5%.
- **Things to know about the data:**
  - Column AF includes rain falling on the reservoir.
  - Evaporation is surface area × a fixed monthly rate, not a measurement.
  - The level→storage table was revised in 2000. For 1990–99, storage reads 0.4–1.2 MCM higher at the same level.

## Findings so far

- **Daily demand:** simple baselines are hard to beat.
  - PWA Chonburi: 3.4% error (WAPE) 1 day ahead and 4.5% 7 days ahead, from yesterday's value or the 7-day mean.
  - Total use: 5.2–9.1%.
  - The first GBM only ties these. Most of the forecast error comes from step changes in allocation, such as PWA rising from about 155k to 205k m³/day in April 2022, which history alone cannot predict. The GBM needs known future events (contracts, allocation plans, new customers) as inputs to do better.
- **Thai Oil and EGAT:** these are only forecastable as weekly or 4-weekly totals (12–21% WAPE). Day-by-day values are effectively random.
- **Allocation plan vs actual** (1 Nov 2024 – 27 Mar 2025): actual use is 78% of the plan.
  - PWA Chonburi uses 99% of its allocation; EGAT 79% and Thai Oil 78%.
  - Eastwater uses only 36% of its allocation: 41k against 113k m³/day.
  - So a supply outlook built on "plan" demand is about 80k m³/day more pessimistic than reality.
- **Supply (storage):** the GBM beats every baseline at 30 and 90 days. Its error is 3.6 MCM at 30 days (3.1% of capacity) versus 5.1 for climatology, and 9.2 versus 12.3 MCM at 90 days.
- **Supply risk outlook** (`matlab/supply_outlook.m`, [report](reports/matlab/supply_outlook.md)). It simulates storage day by day for each of the 35 past years' inflows (ensemble streamflow prediction, ESP), with use, diversions and releases set by scenario.
  - **Accuracy:** in the 2019–2025 backtest it is the most accurate storage forecast so far: median error 1.12 / 3.49 / 8.15 MCM at 7 / 30 / 90 days, against the GBM's 1.23 / 3.60 / 9.29.
  - **Shortage warning:** "below 30% in 90 days" has a Brier skill of 0.62 over the base rate.
  - **Caveats:** its P10–P90 range is too narrow (63–65% coverage), and it runs about 4 MCM pessimistic at 90 days, likely because in practice diversions increase when storage is low.
  - **Outlook from 28 Mar 2025** (72.3 MCM, 62% full):
    - with recent use and typical diversions: no risk of falling below 30% within 180 days;
    - without diversions: a 43% chance;
    - at the allocation plan's use without diversions: 60%, with the 10%-risk date on 13 Jul 2025.
  - Diversions from Bang Pakong and Phra Ong are what keep Bang Phra safe.
- **EPANET model check:** the model runs 48 h with no EPANET warnings.
  - No demand patterns, controls or energy prices are defined, so every hour is identical, and 14 pumps run continuously.
  - Tank NPL3_HT drains from 24.8 to 16.5 m and NPL2_HT from 20.0 to 17.9 m; neither refills.
  - IEAT4/5/6 and Burapa (elevation 58–75 m) get only 6.6–9.8 m of pressure.
  - 27 pump-suction junctions at the NPL3 and TM Pond stations sit at −1.6 and −5.5 m. Their source reservoir heads (43.41 and 23 m) are below the suction pipe elevations, so check those heads or the pumps' required suction head (NPSH).
- **Plan checker** (`validate_plan.m`): the model's own operation grades **Warning**. It uses 191,207 kWh/day, 0.278 kWh/m³ and about 0.96 THB/m³ at the assumed tariff. Four customers are below 10 m, and both tanks end lower than they start, so the schedule can't repeat daily. Switching the TM Pond pumps off grades **Fail**: the network goes unbalanced, customers get negative pressure and both tanks empty within 3 hours.
- **Pump scheduling prototype** (`optimize_pumps.m`, [report](reports/matlab/pump_plans.md)).
  - **The network has little slack at the model's demand.** Customers are fed by gravity from two head tanks that hold about 16,400 m³ together, roughly 34 minutes of demand. At 688k m³/day, even every usable pump (6 NPL2 + 6 NPL3 + 2 TM Pond; TM Pond pumps 3–6 can never run) leaves NPL3_HT draining by about 775 m³/h, about 18,600 m³/day. So no schedule can repeat daily; either nodes `71`/`678` (100k m³/day each) are placeholders, or the NPL3 zone is short of capacity.
  - **Without those two nodes (488k m³/day), the lowest-energy schedule passes EPANET** at 0.264 kWh/m³ and 448,393 THB/day at the assumed tariff. The model's own operation uses 0.278 kWh/m³ at the full 688k demand, so the two aren't directly comparable.
  - **Time-of-use scheduling adds nothing.** In the final run, the one tariff-aware plan that passed (Plan B, 50% reserve) costs 0.2% *more* than the lowest-energy schedule. Across all runs, valid tariff-aware plans ranged from −0.4% to +0.6%. The tanks are too small to shift pumping out of peak hours; real savings would need upstream storage in the plan (raw-water ponds and reservoirs) or better pump efficiency.
  - **The EPANET check does its job.** Plan A looked 3.3% cheaper, but in EPANET NPL2_HT ended the day 8.3 m low and Burapa fell below its pressure target. Plan C also failed. Both are shown as rejected rather than as savings.
  - **How the optimizer works:**
    - Tank inflows are measured at two tank levels and averaged.
    - Plans keep the tanks between their reserve and 90% full.
    - The EPANET check judges each plan against its fixed reserve and pressure spec. Up to six optimise-and-check rounds raise the planning reserve when a plan misses.
    - The MILP stops at a 0.5% optimality gap. Some solves hit the 300-second safety limit, so exact figures can differ slightly between runs. The conclusions above held in every run.
    - A full run takes about 25 minutes.

## EPANET and Windows Smart App Control

Windows Smart App Control is **On** on this PC. Since the afternoon of 16 Oct 2026 (first blocked run 12:50) it blocks `epanet2_thunk_pcwin64.dll`, a small adapter that MATLAB's `loadlibrary` compiles with MinGW into `%TEMP%` each time the EPANET-MATLAB Toolkit loads (Code Integrity events 3033/3077).

The MATLAB scripts therefore run EPANET through the Python `epyt` package by default (`EpytNetwork.m`). `epyt` ships a prebuilt EPANET DLL that loads under the policy. No security setting was changed.

## Next steps

1. Add known future events to the demand model: monthly allocation plans and contract changes.
2. Add rainfall forecasts and storage-dependent diversions to the supply outlook, and calibrate its P10–P90 range.
3. Get customer meter and SCADA data for the 28 EPANET demand nodes. Add hourly demand patterns, the real tariff and pump availability. Model the raw-water storage upstream so scheduling has room to shift.
4. Confirm with the model owner what nodes `71`/`678` represent, whether TM Pond pumps 3–6 are standby, and the source reservoir heads.
