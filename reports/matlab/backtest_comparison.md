# MATLAB vs Python forecast backtest

MATLAB 2026b, run time 368 s. Same data, test periods (demand from 2022-01-01, storage from 2019-01-01), baselines, features and retraining schedule as `src/backtest.py`.
The GBM is `fitrensemble` (LSBoost, 300 trees, rate 0.05, 31 leaves, min leaf 40) in MATLAB and `HistGradientBoostingRegressor` with the same settings in Python.
P10-P90: Python fits quantile-loss models; MATLAB uses residual quantiles from earlier out-of-sample blocks.

## Baselines reproduce Python

111 baseline rows compared (series x horizon x model). Largest WAPE difference 0.0000 points; largest difference in number of scored forecasts 0.

## Daily use, 1-7 days ahead (WAPE %)

| series | step | best baseline | baseline | Python GBM | MATLAB GBM | Python P10-P90 cover | MATLAB P10-P90 cover | best overall (MATLAB) |
|---|---|---|---|---|---|---|---|---|
| PWA Chonburi | 1 | naive | 3.4 | 3.6 | 3.6 | 83% | 82% | naive |
| PWA Chonburi | 2 | ma7 | 3.7 | 3.9 | 3.8 | 80% | 81% | ma7 |
| PWA Chonburi | 3 | ma7 | 3.9 | 4.1 | 4.1 | 78% | 81% | ma7 |
| PWA Chonburi | 4 | ma7 | 4.1 | 4.2 | 4.2 | 77% | 80% | ma7 |
| PWA Chonburi | 5 | ma7 | 4.3 | 4.4 | 4.4 | 77% | 79% | ma7 |
| PWA Chonburi | 6 | ma7 | 4.4 | 4.5 | 4.5 | 76% | 80% | ma7 |
| PWA Chonburi | 7 | ma7 | 4.5 | 4.6 | 4.6 | 75% | 79% | ma7 |
| Total use | 1 | naive | 5.2 | 6.0 | 5.9 | 78% | 81% | naive |
| Total use | 2 | naive | 6.3 | 6.7 | 6.6 | 74% | 82% | naive |
| Total use | 3 | naive | 7.0 | 7.3 | 7.2 | 74% | 80% | naive |
| Total use | 4 | naive | 7.6 | 7.8 | 7.8 | 73% | 79% | naive |
| Total use | 5 | naive | 8.2 | 8.2 | 8.2 | 74% | 79% | naive |
| Total use | 6 | ma7 | 8.6 | 8.6 | 8.5 | 72% | 79% | gbm |
| Total use | 7 | ma7 | 8.9 | 8.8 | 8.8 | 71% | 78% | gbm |

## Total use over the next 7 / 28 days (WAPE %)

| series | step | best baseline | baseline | Python GBM | MATLAB GBM | Python P10-P90 cover | MATLAB P10-P90 cover | best overall (MATLAB) |
|---|---|---|---|---|---|---|---|---|
| EGAT Bang Pakong | 7 | ma28 | 20.9 | 25.3 | 26.3 | 73% | 85% | ma28 |
| EGAT Bang Pakong | 28 | ma28 | 17.5 | 20.0 | 21.5 | 56% | 80% | ma28 |
| PWA Chonburi | 7 | naive | 3.1 | 3.8 | 3.9 | 73% | 77% | naive |
| PWA Chonburi | 28 | ma28 | 3.7 | 4.2 | 4.3 | 60% | 80% | ma28 |
| Thai Oil | 7 | ma91 | 16.2 | 18.8 | 19.1 | 81% | 87% | ma91 |
| Thai Oil | 28 | ma91 | 11.6 | 16.7 | 17.8 | 75% | 86% | ma91 |
| Total use | 7 | naive | 6.3 | 7.4 | 7.3 | 71% | 76% | naive |
| Total use | 28 | ma28 | 8.5 | 9.1 | 9.2 | 56% | 68% | ma28 |

## Storage 7 / 30 / 90 days ahead (MAE, MCM)

| series | step | best baseline | baseline | Python GBM | MATLAB GBM | Python P10-P90 cover | MATLAB P10-P90 cover | best overall (MATLAB) |
|---|---|---|---|---|---|---|---|---|
| Storage | 7 | trend7 | 1.05 | 1.09 | 1.23 | 72% | 81% | trend7 |
| Storage | 30 | climatology | 5.08 | 3.58 | 3.60 | 54% | 81% | gbm |
| Storage | 90 | climatology | 12.32 | 9.17 | 9.29 | 51% | 78% | gbm |

Full MATLAB metrics: reports/matlab/backtest_metrics_matlab.csv. Predictions: reports/matlab/backtest_predictions_matlab.csv.
