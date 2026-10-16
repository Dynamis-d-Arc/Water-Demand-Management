# Bang Phra baseline forecast backtest

Rolling-origin test: every forecast uses only data available on its origin day; the GBM is
retrained on an expanding window at the start of each quarter (demand) or year (storage).
WAPE = total absolute error / total actual. Coverage = share of actuals inside GBM P10-P90 (target 80%).

## Daily use, 1-7 days ahead (origins 2022-01-01 to 2025-03-27)

| series | step | naive_wape | best_baseline | best_baseline_wape | gbm_wape | gbm_coverage | winner |
|---|---|---|---|---|---|---|---|
| PWA Chonburi | 1 | 3.4 | naive | 3.4 | 3.6 | 83.1 | naive |
| PWA Chonburi | 2 | 3.9 | ma7 | 3.7 | 3.9 | 79.7 | ma7 |
| PWA Chonburi | 3 | 4.3 | ma7 | 3.9 | 4.1 | 77.9 | ma7 |
| PWA Chonburi | 4 | 4.5 | ma7 | 4.1 | 4.2 | 76.7 | ma7 |
| PWA Chonburi | 5 | 4.7 | ma7 | 4.3 | 4.4 | 76.6 | ma7 |
| PWA Chonburi | 6 | 4.8 | ma7 | 4.4 | 4.5 | 76.1 | ma7 |
| PWA Chonburi | 7 | 4.9 | ma7 | 4.5 | 4.6 | 74.6 | ma7 |
| Total use | 1 | 5.2 | naive | 5.2 | 6.0 | 78.2 | naive |
| Total use | 2 | 6.3 | naive | 6.3 | 6.7 | 74.5 | naive |
| Total use | 3 | 7.0 | naive | 7.0 | 7.3 | 74.2 | naive |
| Total use | 4 | 7.6 | naive | 7.6 | 7.8 | 73.4 | naive |
| Total use | 5 | 8.2 | naive | 8.2 | 8.2 | 73.8 | naive |
| Total use | 6 | 8.7 | ma7 | 8.6 | 8.6 | 71.9 | gbm |
| Total use | 7 | 9.1 | ma7 | 8.9 | 8.8 | 71.0 | gbm |

## Total use over the next 7 / 28 days (origins 2022-01-01 to 2025-03-27)

| series | step | naive_wape | best_baseline | best_baseline_wape | gbm_wape | gbm_coverage | winner |
|---|---|---|---|---|---|---|---|
| EGAT Bang Pakong | 7 | 23.1 | ma28 | 20.9 | 25.3 | 72.8 | ma28 |
| EGAT Bang Pakong | 28 | 17.5 | naive | 17.5 | 20.0 | 56.1 | naive |
| PWA Chonburi | 7 | 3.1 | naive | 3.1 | 3.8 | 73.2 | naive |
| PWA Chonburi | 28 | 3.7 | naive | 3.7 | 4.2 | 59.9 | naive |
| Thai Oil | 7 | 17.9 | ma91 | 16.2 | 18.8 | 81.1 | ma91 |
| Thai Oil | 28 | 13.4 | ma91 | 11.6 | 16.7 | 74.9 | ma91 |
| Total use | 7 | 6.3 | naive | 6.3 | 7.4 | 71.4 | naive |
| Total use | 28 | 8.5 | naive | 8.5 | 9.1 | 55.6 | naive |

## Storage 7 / 30 / 90 days ahead (origins 2019-01-01 to 2025-03-28); error in MCM

| series | step | best_baseline | best_baseline_mae | gbm_mae | gbm_mae_pct_cap | gbm_coverage | winner |
|---|---|---|---|---|---|---|---|
| Storage | 7 | trend7 | 1.05 | 1.09 | 0.9 | 71.7 | trend7 |
| Storage | 30 | climatology | 5.08 | 3.58 | 3.1 | 53.8 | gbm |
| Storage | 90 | climatology | 12.32 | 9.17 | 7.8 | 50.9 | gbm |

Baselines: naive = last value (storage: no change); snaive_week = same weekday last week;
ma7/ma28/ma91 = trailing means; snaive_year_scaled = same period last year x recent growth;
trend7 = last 7-day storage trend extrapolated; climatology = typical change for that time of year.

Full metrics: reports/backtest_metrics.csv. Predictions: reports/backtest_predictions.csv.