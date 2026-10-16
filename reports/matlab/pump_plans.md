# Pump schedule prototype (QW2) checked with EPANET (QW3)

Network `Demand-2023 v20RY to MTP new TM2P.inp`, one weekday, flat demand. Head tanks start at the model's levels capped at 85% of their range; plans keep them below 90%. 343 station combinations solved in EPANET; schedules chosen by `intlinprog` and checked in a 24 h EPANET run (`validate_plan`).

**Assumed tariff** (replace with Eastwater's): 4.1839 THB/kWh peak 09:00-22:00, 2.6037 off-peak. All pumps assumed available; model pump efficiency 75%. Customer floor = 10 m, or the model's own minimum where it is already lower (Burapa, IEAT4/5/6).

Model as supplied (14 pumps all day, from its own start levels): Warning, 191,207 kWh/day, 0.2778 kWh/m3, 0.9600 THB/m3. pressure below target at Burapa, IEAT4, IEAT5, IEAT6; tank NPL2_HT ends 2.0 m below its start level (plan cannot repeat daily); tank NPL3_HT ends 8.3 m below its start level (plan cannot repeat daily); 27 junction(s) without demand go below 0 m (pump suction pipework).

## Model demand: 688,403 m3/day

Start levels 18.87 / 21.55 m (85% / 85% of range). 105 of 343 station combinations are hydraulically valid; at most 2 TM Pond pumps can run (more gives EPANET 'pumps cannot deliver head'). Station-additive fit of the snapshots: power within 0.0 kW, tank flows within 0.2 m3/h (used by the MILP).
Most pumping that still meets the pressure floors (6 + 6 + 2 pumps) gives net tank flows of +296 / -775 m3/h (+7110 / -18591 m3/day).

| schedule | EPANET check | energy kWh/day | cost THB/day | kWh/m3 | THB/m3 | cost vs the model's operation (6 + 6 + 2 pumps all day) | lowest customer pressure m | tank reserve | pump starts | pumps on at peak (avg) |
|---|---|---|---|---|---|---|---|---|---|---|
| Model operation (6 + 6 + 2 pumps all day) | Warning | 190,842 | 659,874 | 0.2772 | 0.9586 | +0.0% | 6.62 | - | 0 | 14.0 |
| Reference (lowest energy, ignores tariff) | no feasible schedule | | | | | | | | | |
| Plan A lowest cost | no feasible schedule | | | | | | | | | |
| Plan C balanced | no feasible schedule | | | | | | | | | |
| Plan B lower risk | no feasible schedule | | | | | | | | | |

Model operation (6 + 6 + 2 pumps all day) - pressure below target at Burapa, IEAT4, IEAT5, IEAT6; tank NPL2_HT ends 0.9 m below its start level (plan cannot repeat daily); tank NPL3_HT ends 5.1 m below its start level (plan cannot repeat daily); 27 junction(s) without demand go below 0 m (pump suction pipework).
Reference (lowest energy, ignores tariff) - no schedule keeps the tanks within limits and ends the day as full as it started.
Plan A lowest cost - no schedule keeps the tanks within limits and ends the day as full as it started.
Plan C balanced - no schedule keeps the tanks within limits and ends the day as full as it started.
Plan B lower risk - no schedule keeps the tanks within limits and ends the day as full as it started.
Tank reserve is per tank (NPL2_HT / NPL3_HT). Figure: reports/matlab/pump_plans_model_demand.png.

## Without placeholder nodes 71 and 678: 488,403 m3/day

Start levels 18.87 / 21.55 m (85% / 85% of range). 105 of 343 station combinations are hydraulically valid; at most 2 TM Pond pumps can run (more gives EPANET 'pumps cannot deliver head'). Station-additive fit of the snapshots: power within 0.0 kW, tank flows within 0.1 m3/h (used by the MILP).
Most pumping that still meets the pressure floors (6 + 6 + 2 pumps) gives net tank flows of +2020 / +4646 m3/h (+48488 / +111496 m3/day).

| schedule | EPANET check | energy kWh/day | cost THB/day | kWh/m3 | THB/m3 | cost vs the reference | lowest customer pressure m | tank reserve | pump starts | pumps on at peak (avg) |
|---|---|---|---|---|---|---|---|---|---|---|
| Reference (lowest energy, ignores tariff) | Pass | 129,140 | 448,393 | 0.2644 | 0.9181 | +0.0% | 11.74 | 10% / 10% | 12 | 10.4 |
| Plan A lowest cost | Warning (not converged) | 126,097 | 433,506 | 0.2582 | 0.8876 | n/a (not valid) | 8.97 | 10% / 10% | 14 | 9.9 |
| Plan C balanced | Warning (not converged) | 130,061 | 447,507 | 0.2663 | 0.9163 | n/a (not valid) | 8.97 | 30% / 30% | 20 | 10.1 |
| Plan B lower risk | Pass | 130,858 | 449,391 | 0.2679 | 0.9201 | +0.2% | 13.73 | 50% / 50% | 23 | 10.2 |

Reference (lowest energy, ignores tariff) (3 round(s), station MILP, gap 0.37%) - tank NPL2_HT reaches its maximum level; 27 junction(s) without demand go below 0 m (pump suction pipework).
Plan A lowest cost (4 round(s), station MILP, gap 0.50%) - EPANET: pumps forced off: cannot deliver the head (e.g. against a full tank); pressure below target at Burapa; tank NPL2_HT ends 8.3 m below its start level (plan cannot repeat daily); tank NPL2_HT reaches its maximum level; tank NPL3_HT reaches its maximum level; 31 junction(s) without demand go below 0 m (pump suction pipework).
Plan C balanced (4 round(s), station MILP, gap 0.50%) - pressure below target at Burapa; tank NPL2_HT ends 2.9 m below its start level (plan cannot repeat daily); tank NPL2_HT reaches its maximum level; tank NPL3_HT reaches its maximum level; 28 junction(s) without demand go below 0 m (pump suction pipework).
Plan B lower risk (3 round(s), station MILP, gap 0.66%) - tank NPL2_HT reaches its maximum level; 27 junction(s) without demand go below 0 m (pump suction pipework).
Tank reserve is per tank (NPL2_HT / NPL3_HT). Figure: reports/matlab/pump_plans_no_placeholders.png.

Hourly schedules: reports/matlab/pump_plans_schedule.csv.
