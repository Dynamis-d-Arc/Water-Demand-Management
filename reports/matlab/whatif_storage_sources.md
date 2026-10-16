# Where could pumping savings come from? Storage what-if and cost per m³ by source

Rayong network model (`Demand-2023 v20RY to MTP new TM2P.inp`) without the placeholder nodes 71 and 678: 488,403 m³/day, flat demand, one weekday, all pumps available. **Assumed tariff** (replace with Eastwater's): 4.1839 THB/kWh peak 09:00-22:00, 2.6037 off-peak. Every plan below is checked in a 24 h EPANET run. Script: `matlab/whatif_storage_sources.m` (run time 34 min).

## Summary for executives

- **Bigger head tanks would not make time-of-use pumping pay.** Shifting pumping out of the 09:00-22:00 peak saves 0.2% with today's tanks, 0.4% at 2×, 0.3% at 5× and 0.9% at 10×, as a share of the daily pumping cost (EPANET-checked, against the lowest-energy plan at the same size; differences under about 0.5% are within the optimiser's tolerance; today's tanks hold 16,431 m³, 48 minutes of demand). No size tested reaches the 3-5% hoped for: the best, 10× (about 148,000 m³ more elevated storage), saves 0.9%, about 1.3 million THB/year at the assumed tariff, before the cost of building it.
- **Why: the pumps, not the tanks, limit the shift.** Moving pumping into the 11 off-peak hours means running more pumps at once, and more flow through the same discharge mains raises the head every pump works against (NPL3: 60 m with one pump, 86 m with six). The last pump at each station adds water at NPL2 0.30, NPL3 0.47, TM Pond 0.46 kWh/m³, against 0.245 on average in the lowest-energy plan, which uses up most of the 38% off-peak discount. Customer pressure also limits the drawdown: NPL3_HT must stay above about 35% full to keep every customer above its floor (55% with no TM Pond pump running).
- **What extra storage does buy is steadier pumping.** Against the lowest-energy plan with today's tanks, the 10× lowest-cost plan costs 3.4% less per day (about 5.1 million THB/year); only 0.9 points of that come from time-of-use. The rest is steadier pumping: bigger tanks let the stations run one efficient pump mix all day (0.2386 kWh/m³ at 10× against 0.2447 today).
- **Where the savings are instead:** pump into lower tanks. The lowest-energy plan for today's tanks keeps them only as full as the customer floors need (NPL2_HT 46-56%, NPL3_HT 49-70%) and uses 0.2447 kWh/m³, 7.5% less than the reference in `pump_plans.md` (0.2644, which starts and ends the day with both tanks 85% full). That needs no new assets but leaves less water in reserve, so it is an operating decision for Eastwater. Beyond that: favour the cheaper sources (next point), and cut the head the pumps work against at high flow or fit more efficient pumps, which needs pump tests and SCADA data.
- **Cheapest water per m³: NPL3 with 1 pump** at 0.219 kWh/m³ (0.57 THB/m³ off-peak, 0.92 at peak); **dearest: TM Pond with 2 pumps** at 0.348 kWh/m³ (0.91 / 1.46 THB/m³). kWh/m³ rises with the number of pumps running, because more flow through the same discharge main needs more head: NPL2 0.230-0.251 (3-6 pumps); NPL3 0.219-0.313 (1-6 pumps); TM Pond 0.273-0.348 (1-2 pumps). At full output NPL2 is the cheapest source and TM Pond the dearest. TM Pond draws from R10885 at 23.00 m, 20 m below the other stations' reservoirs, so it lifts further.
- **What would change these conclusions:** Eastwater's real tariff (a wider peak/off-peak gap or demand charges make shifting worth more), hourly demand from SCADA (the model's is flat), efficiency curves for the NPL3 and TM Pond pumps (75% assumed here), and Eastwater's minimum tank levels (the lower-tank saving depends on them). The cost of building extra storage is not included.

![Saving by storage size, stored water over the day, energy per m³ by source](whatif_storage_sources.png)

## (a) How much head-tank storage would make time-of-use pumping pay?

### Method

- **Storage sizes.** NPL2_HT and NPL3_HT together hold 16,431 m³ between their minimum and maximum levels today, 48 minutes of demand. Each size scales both tanks' volume (diameter × √k) and keeps their levels, so a given level gives customers the same pressure as today.
- **Plans.** For each size: the lowest-energy reference (ignores the tariff; what good operation achieves without time-of-use scheduling) and the lowest-cost plan under the assumed tariff. Both use a 10% tank reserve and the customer floors of `pump_plans.md` (10 m, or the model's own minimum where lower: Burapa, IEAT4/5/6).
- **Optimiser.** As `optimize_pumps.m`: a station-level MILP (`intlinprog`, 0.5% gap, 300 s limit) picks the pumps running at each station in each hour; every schedule is run through `validate_plan` (24 h EPANET); up to 6 rounds raise only the planning margins (tank floor, pressure margin, end level, pump-curve margin) when EPANET misses the fixed spec. A saving counts only when both plans pass.
- **What changed, and why.** Bigger tanks swing over a wide band of levels, and level matters in this network: on the snapshot grid (30-95% full), with 6 + 6 + 2 pumps running, the net inflows to NPL2_HT / NPL3_HT go from +2,600 / +5,875 m³/h with both tanks 30% full to +1,926 / +4,394 m³/h at 95% full, and the lowest customer pressure from 6.9 to 21.0 m. So the MILP uses tank inflows, pump power and customer pressures that depend on both tank levels (fitted on 16,464 EPANET snapshots; still additive station by station; fit within 127 / 133 m³/h for tank inflows, 18 kW for power, 0.43 m for pressures). It multiplies the pump choice by the start-of-hour level exactly, so it steps the tanks the way EPANET does with 1 h steps. Customer floors and the NPL2 pump-curve limit are constraints in every hour.
- **Repeatable day.** The optimiser chooses the level the day starts at, and the day must end at least as full. `optimize_pumps.m` starts at 85% at midnight, which leaves only 22:00-24:00 to refill after the peak and so caps what any tank size can shift (checked below at the largest size).
- **Pump-curve limit and solver details.** NPL2 pumps stay on their curve only with NPL2_HT full enough (2 pumps from 95%, 3 pumps from 80%, 4 pumps from 55%; 5 or 6 pumps at any level in the band); counts that need more than the 90% plan ceiling are never used. The MILP branches on "at least k pumps" choices per station and hour (the same bound as one choice per count, but it solved several times faster); each lowest-cost plan starts from the reference schedule, so it can only improve on it; plans keep 0.2 m above every customer floor to cover the fitted pressure error.

### Results

| storage | usable volume m³ | hours of demand | reference: EPANET check | reference THB/day | lowest cost: EPANET check | lowest cost THB/day | **time-of-use saving** | saving THB/day | MILP estimate | lowest cost vs today's reference | off-peak share of energy (ref / lowest cost) | kWh/m³ (ref / lowest cost) | tank levels, lowest cost (min-max) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1× | 16,431 | 0.8 | passes | 412,713 | passes | 411,982 | **0.2%** | 731 | 0.2% | 0.2% | 46% / 47% | 0.2447 / 0.2447 | NPL2_HT 45-71%, NPL3_HT 49-70% |
| 2× | 32,862 | 1.6 | passes | 408,171 | passes | 406,455 | **0.4%** | 1,716 | 0.4% | 1.5% | 46% / 47% | 0.2417 / 0.2418 | NPL2_HT 46-59%, NPL3_HT 51-66% |
| 5× | 82,156 | 4.0 | passes | 403,916 | passes | 402,635 | **0.3%** | 1,282 | 0.3% | 2.4% | 46% / 52% | 0.2388 / 0.2446 | NPL2_HT 32-61%, NPL3_HT 50-77% |
| 10× | 164,312 | 8.1 | passes | 402,458 | passes | 398,848 | **0.9%** | 3,610 | 0.9% | 3.4% | 46% / 52% | 0.2386 / 0.2433 | NPL2_HT 33-45%, NPL3_HT 51-67% |

Time-of-use saving = 1 - lowest-cost plan / reference at the same storage size, both from EPANET; "MILP estimate" is the optimiser's own figure before the EPANET check; "vs today's reference" compares with the lowest-energy plan for today's tanks, so it adds what steadier pumping with bigger tanks saves. Differences under about the MILP gap (0.5%, more where a solve stopped at the 300 s limit) are within the optimiser's tolerance. With today's tanks the solves stop at the 300 s limit with a 2-3% gap; that is a weak bound rather than a poor plan (in a development test a 20-minute solve improved the 1× reference by only 0.1%). Full KPIs: `whatif_storage_kpis.csv`; hourly schedules and EPANET tank levels: `whatif_storage_schedule.csv`.

**Start rule check (10× storage).** The same lowest-cost plan with `optimize_pumps.m`'s start rule (tanks 85% full at midnight, ending at least as full; check: passes) costs 439,433 THB/day, 9.2% dearer than the reference at this size, against 0.9% cheaper with a free start. Holding the tanks that full makes every pump lift against more head, which costs more than time-of-use pumping saves.

1× Reference (lowest energy): 1 round(s), MILP gap 2.44% - round 1: EPANET Pass.
1× Lowest cost (tariff-aware): 1 round(s), MILP gap 2.20% - round 1: EPANET Pass.
2× Reference (lowest energy): 1 round(s), MILP gap 1.83% - round 1: EPANET Pass.
2× Lowest cost (tariff-aware): 1 round(s), MILP gap 1.40% - round 1: EPANET Pass.
5× Reference (lowest energy): 1 round(s), MILP gap 0.31% - round 1: EPANET Pass.
5× Lowest cost (tariff-aware): 1 round(s), MILP gap 0.54% - round 1: EPANET Pass.
10× Reference (lowest energy): 1 round(s), MILP gap 0.50% - round 1: EPANET Pass.
10× Lowest cost (tariff-aware): 1 round(s), MILP gap 0.50% - round 1: EPANET Pass.
10× Lowest cost, starting 85% full at midnight: 1 round(s), MILP gap 0.46% - round 1: EPANET Pass.

Today's tanks: this reference uses 119,510 kWh/day (0.2447 kWh/m³), 7.5% less than the reference in `pump_plans.md` (129,140 kWh/day, 0.2644 kWh/m³), which plans on tank inflows measured near full and starts at 85%. The difference comes from where the tanks are held (see the summary).

## (b) Cost per m³ by source and pump combination

EPANET snapshots of every station combination with both head tanks 85% full (the pump plans' start level). kWh/m³ = station pump power / station flow; THB/m³ = kWh/m³ × tariff (energy only, assumed tariff).

**Pump efficiency used.** The model's [ENERGY] section gives every pump a global 75%; the .inp [CURVES] section has three efficiency curves. **NPL_2-Eff** matches the NPL2 pumps' head curve NPL_2 and is used for them (efficiency at each pump's flow). **DK_1-Eff** and **BPK_Eff** belong to the DK_1 and BPK head curves, which no pump at these stations uses, so they do not apply. NPL3 (head curve NPL3-115) and TM Pond (TM_Pond) have no efficiency curve: **75%** (model global) for both. Part (a) uses EPANET's 75% for every pump, like `pump_plans.md`.

| station | source (head) | feeds | pumps | flow m³/h | flow per pump CMD | pump head m | efficiency | kWh/m³ at 75% | **kWh/m³** | THB/m³ off-peak | THB/m³ peak | kWh/m³ at 50% / 90% full |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NPL2 | NPL_Res2 (43.41 m) | NPL2_HT | 3 | 4,878 | 39,022 | 62.7 | 74.3% (NPL_2-Eff) | 0.2277 | **0.2300** | 0.599 | 0.962 | - / 0.2314 |
| NPL2 | NPL_Res2 (43.41 m) | NPL2_HT | 4 | 6,337 | 38,021 | 66.6 | 77.0% (NPL_2-Eff) | 0.2419 | **0.2356** | 0.614 | 0.986 | - / 0.2368 |
| NPL2 | NPL_Res2 (43.41 m) | NPL2_HT | 5 | 7,680 | 36,864 | 71.0 | 79.7% (NPL_2-Eff) | 0.2577 | **0.2426** | 0.632 | 1.015 | 0.2336 / 0.2441 |
| NPL2 | NPL_Res2 (43.41 m) | NPL2_HT | 6 | 8,904 | 35,614 | 75.6 | 81.9% (NPL_2-Eff) | 0.2743 | **0.2511** | 0.654 | 1.051 | 0.2410 / 0.2527 |
| NPL3 | NPL_Res3 (43.41 m) | NPL3_HT | 1 | 2,594 | 62,247 | 60.3 | 75.0% (model) | 0.2190 | **0.2190** | 0.570 | 0.916 | 0.1901 / 0.2231 |
| NPL3 | NPL_Res3 (43.41 m) | NPL3_HT | 2 | 5,096 | 61,150 | 63.6 | 75.0% (model) | 0.2308 | **0.2308** | 0.601 | 0.966 | 0.2029 / 0.2348 |
| NPL3 | NPL_Res3 (43.41 m) | NPL3_HT | 3 | 7,441 | 59,524 | 68.3 | 75.0% (model) | 0.2479 | **0.2479** | 0.645 | 1.037 | 0.2213 / 0.2517 |
| NPL3 | NPL_Res3 (43.41 m) | NPL3_HT | 4 | 9,586 | 57,517 | 73.9 | 75.0% (model) | 0.2683 | **0.2683** | 0.699 | 1.123 | 0.2435 / 0.2719 |
| NPL3 | NPL_Res3 (43.41 m) | NPL3_HT | 5 | 11,513 | 55,262 | 80.0 | 75.0% (model) | 0.2905 | **0.2905** | 0.756 | 1.215 | 0.2675 / 0.2938 |
| NPL3 | NPL_Res3 (43.41 m) | NPL3_HT | 6 | 13,218 | 52,873 | 86.2 | 75.0% (model) | 0.3130 | **0.3130** | 0.815 | 1.310 | 0.2918 / 0.3161 |
| TM Pond | R10885 (23.00 m) | NPL2_HT + NPL3_HT | 1 | 2,955 | 70,931 | 75.2 | 75.0% (model) | 0.2730 | **0.2730** | 0.711 | 1.142 | 0.2511 / 0.2761 |
| TM Pond | R10885 (23.00 m) | NPL2_HT + NPL3_HT | 2 | 4,894 | 58,731 | 96.0 | 75.0% (model) | 0.3485 | **0.3485** | 0.907 | 1.458 | 0.3326 / 0.3508 |

Not valid with the tanks 85% full: NPL2 with 1 or 2 pumps and TM Pond with 3 to 6 pumps (EPANET: the pumps run beyond the end of their curve or cannot deliver the head). With the tanks half full, NPL2 needs at least 5 pumps running.

**Combinations** (104 valid with at least one pump; all in `whatif_combination_cost.csv`, with each station's flow, net tank inflows and the customer pressure margin). Cheapest and dearest per m³:

| NPL2 + NPL3 + TM Pond pumps | flow m³/h | kWh/m³ | THB/m³ off-peak | THB/m³ peak | net inflow NPL2_HT / NPL3_HT m³/h | can run all day |
|---|---|---|---|---|---|---|
| 0 + 1 + 0 | 2,594 | 0.2190 | 0.570 | 0.916 | -10165 / -7591 | no |
| 3 + 1 + 0 | 7,471 | 0.2262 | 0.589 | 0.946 | -5287 / -7591 | no |
| 3 + 0 + 0 | 4,878 | 0.2300 | 0.599 | 0.962 | -5287 / -10185 | no |
| 3 + 2 + 0 | 9,974 | 0.2304 | 0.600 | 0.964 | -5287 / -5089 | no |
| 0 + 2 + 0 | 5,096 | 0.2308 | 0.601 | 0.966 | -10165 / -5089 | no |
| 0 + 6 + 0 | 13,218 | 0.3130 | 0.815 | 1.310 | -10165 / +3033 | no |
| 0 + 6 + 2 | 18,113 | 0.3226 | 0.840 | 1.350 | -6883 / +4646 | no |
| 0 + 0 + 2 | 4,894 | 0.3485 | 0.907 | 1.458 | -6883 / -8573 | no |

"Can run all day": both tanks fill (net inflow ≥ 0) and every customer is above its floor, so the combination alone could meet today's 488,403 m³/day.
Cheapest such combination: 6 + 4 + 1 pumps, 0.2618 kWh/m³ (0.682 THB/m³ off-peak).

## Files

- `whatif_storage_kpis.csv`: one row per storage size and plan (EPANET KPIs, saving, MILP estimate, tank levels).
- `whatif_storage_schedule.csv`: pumps running per station and hour, tariff, EPANET tank levels at the start of each hour.
- `whatif_station_cost.csv`: per station and pump count, at 50% / 85% / 90% full.
- `whatif_combination_cost.csv`: every valid station combination at 85% full, cheapest first.
- `whatif_storage_sources.png`: the figure above.
