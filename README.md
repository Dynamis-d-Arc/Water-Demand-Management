# Water demand & supply POC: Bang Phra

The first POC step for the Forecast → Optimize → EPANET check flow. This step:

1. Cleans the Bang Phra reservoir daily water balance (sheet `WB บางพระ`, 1990-01-01 to 2025-03-28).
2. Backtests baseline demand and storage forecasts against it.
3. Checks that the Rayong EPANET model (`../Demand-2023 v20RY to MTP new TM2P.inp`) runs.

Everything runs in Python. The cleaned data is also saved in a form MATLAB can read.

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
| `reports/data_quality_bangphra.md` | Consistency checks, flag counts, yearly summary. |
| `reports/backtest_summary.md` | Best baseline vs GBM for each series and horizon. |
| `reports/backtest_metrics.csv`, `backtest_predictions.csv` | Full metrics and every forecast made in the backtest. |
| `reports/epanet_check.md` | Whether the model runs, the system balance, tanks, pumps and pressure at each customer node. |

### MATLAB (R2026b)

```bash
matlab -batch "run('matlab/check_setup.m')"          # toolboxes, licences, data loads from CSV and .mat
matlab -batch "run('matlab/check_epanet.m')"         # runs the .inp with the EPANET-MATLAB Toolkit, compares with Python
matlab -batch "run('matlab/backtest_forecast.m')"    # ~6 min -> reports/matlab/ (port of src/backtest.py)
```

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
  - the EPANET-MATLAB Toolkit;
  - the MathWorks MinGW-w64 compiler add-on, which the toolkit needs to load EPANET.
- **Results:** the MATLAB and Python runs agree to within 0.005 m pressure at all 28 customer nodes.

```matlab
T = readtimetable("data/clean/bangphra_daily.csv");   % 'date' becomes the row times
S = load("data/clean/bangphra_daily.mat");
t = datetime(S.bangphra.datenum, "ConvertFrom", "datenum");
plot(t, S.bangphra.use_pwa_chonburi_m3)
```

## Cleaning rules

- **Placeholder rows:** the sheet is pre-filled with formula rows to 31 Dec 2025. Only days with a recorded water level are kept.
- **Negative flows:** these come from differencing meter readings when the next reading is missing (for example 28 Mar 2025, PWA = −12 million m³). They are removed, along with any total that includes them.
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
- **Supply (storage):** the GBM beats every baseline at 30 and 90 days. Its error is 3.6 MCM at 30 days (3.1% of capacity) versus 5.1 for climatology, and 9.2 versus 12.3 MCM at 90 days. Its P10–P90 range is too narrow, though (51–54% coverage instead of 80%). The next gain is adding rainfall forecasts and planned diversions as inputs.
- **EPANET:** the model runs 48 h with no EPANET warnings, and supply matches the 688k m³/day of demand.
  - No demand patterns, controls or energy prices are defined, so every hour is identical.
  - 14 pumps run continuously.
  - Tank NPL3_HT drains from 24.8 to 16.5 m and NPL2_HT from 20.0 to 17.9 m; neither refills.
  - IEAT4/5/6 and Burapa (elevation 58–75 m) get only 6.6–9.8 m of pressure.
  - 27 pump-suction junctions at the NPL3 and TM Pond stations sit at −1.6 and −5.5 m. Their source reservoir heads (43.41 and 23 m) are below the suction pipe elevations, so check those heads or the pumps' required suction head (NPSH).

## Next steps

1. Add known future events to the demand model: monthly allocation plans (sheet 3 has dry-season plans per user) and contract changes.
2. Feed rainfall forecasts and planned diversions into the storage model, and calibrate its P10–P90 range.
3. Get customer meter and SCADA (control-system) data for the 28 EPANET demand nodes, then add hourly demand patterns, a time-of-use tariff and pump controls to the model.
