# Bang Phra supply risk outlook (ESP)

Storage is simulated once for every past year's natural inflow from the start date, with use, diversions and releases set by scenario (see `matlab/supply_outlook.m`). The spread across years is the inflow uncertainty; operating decisions are not forecast.

## Backtest (origins 2019-01-01 to 2025-03-21, recent use + typical diversions)

| days ahead | ESP P50 MAE (MCM) | GBM MAE | climatology MAE | ESP P10-P90 cover | GBM P10-P90 cover | ESP bias (MCM) |
|---|---|---|---|---|---|---|
| 7 | 1.12 | 1.23 | 1.43 | 64% | 81% | -0.49 |
| 30 | 3.49 | 3.60 | 5.08 | 65% | 81% | -1.82 |
| 90 | 8.15 | 9.29 | 12.32 | 63% | 78% | -4.27 |

Shortage warning, storage below 30% of capacity (35.1 MCM) at the horizon:

| days ahead | days observed below 30% | mean forecast probability | Brier score | Brier skill vs base rate |
|---|---|---|---|---|
| 7 | 212 of 2272 | 0.09 | 0.002 | 0.99 |
| 30 | 212 of 2249 | 0.11 | 0.009 | 0.93 |
| 90 | 212 of 2189 | 0.15 | 0.048 | 0.62 |

Base rate = share of days below 30% in 1990-2018 (29%). Skill > 0 beats always forecasting that rate.

## Outlook from 2025-03-28 (storage 72.3 MCM, 62% full) for 180 days

Recent use = 243049 m3/day (28-day mean). Plan use = sheet 3 total for each day (249000-358210 m3/day). 35 inflow years (1990-2024).

| scenario | P50 at 30 d | P50 at 90 d | P10 at 90 d | P50 at 180 d | P(<30%) by 90 d | P(<30%) by 180 d | 10%-risk day below 30% |
|---|---|---|---|---|---|---|---|
| Recent use, typical diversions | 64.3 | 56.4 | 50.0 | 83.0 | 0% | 0% | not within 180 d |
| Recent use, no diversions | 64.0 | 52.8 | 46.5 | 40.6 | 0% | 43% | 2025-08-06 |
| Allocation plan, typical diversions | 62.0 | 50.5 | 44.1 | 76.7 | 0% | 6% | not within 180 d |
| Allocation plan, no diversions | 61.7 | 46.9 | 40.6 | 34.4 | 3% | 60% | 2025-07-13 |

10%-risk day = first day the P10 path drops below 30% of capacity. Figure: reports/matlab/supply_outlook_fan.png.

Assumptions: evaporation = surface area x the sheet's monthly pan rate; diversions and outlet releases are averages, not responses to storage (in practice pumping in increases when storage is low); inflow years are treated as equally likely (no seasonal rainfall forecast yet).
