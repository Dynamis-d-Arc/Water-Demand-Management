# Eastwater data request pack

This folder asks Eastwater for the operational data the POC still needs, and holds what the loaders need to read that data without manual work. When the files arrive, two commands produce the **saving vs today's operation**:
- `src/load_eastwater.py` checks the data and maps it to the Rayong EPANET model;
- `src/baseline_vs_today.py` computes today's baseline and compares it with the pump plans.

| file | what |
|---|---|
| [`request_checklist.md`](request_checklist.md) | The request to send: each item, why we need it, period, resolution and format, with Thai labels. |
| [`data_dictionary.csv`](data_dictionary.csv) | Every column of every template: type, unit or format, required or not, description, Thai label and an example. Opens in Excel with Thai text intact. |
| `templates/` | One CSV per dataset, with the exact column names. The second row (starting with `#`) gives each column's unit or format. `id_map`, `pump_register` and `confirmations` come pre-filled with the model's 18 pumps, 3 stations, 2 head tanks, 3 sources, 28 customer nodes and the questions. |
| `samples/` | A small **synthetic SAMPLE set** in the template formats, and the script that makes it. It is for testing only and is never Eastwater data. |

## For Eastwater: how to send the data

1. Fill the templates in `templates/`, one file per dataset; several files per dataset are fine (e.g. one per month or station). Save as **CSV UTF-8**. An Excel workbook with one sheet per dataset, each named like its template, also works.
2. Follow the rules at the end of `request_checklist.md`:
   - times in Thai time (`YYYY-MM-DD HH:MM`, start of the interval);
   - units as in the column names;
   - blank for unknown, never 0;
   - the model's IDs, or your own tags listed in `id_map.csv`.
3. If your data does not fit a template, send it in its own format with a short note. Bills and contracts can be PDFs.
4. **Send the files through the secure channel agreed under the NDA**, such as Eastwater's file-sharing service or an encrypted archive with the password sent separately. Do not send them as plain email attachments.

Each delivery gets the validation report back, listing what is missing or needs a fix, row by row.

## For the project team: loading the data

The client data is under NDA. Keep it on this computer, in `data/eastwater/`, and do not copy it into other tools or online services.

1. Save the files as received in **`data/eastwater/raw/`**: CSV or XLSX, any file names.
   - The loader recognises each table by its columns, using the file name only to break ties.
   - Keep the SAMPLE files out of this folder. The loader refuses an inbox that mixes SAMPLE and real files.
2. Load and check:
   ```bash
   python src/load_eastwater.py
   ```
   Read `data/eastwater/validation_report.md`. Fix or ask about what it lists, add files, and re-run; each run rebuilds the outputs from all the files in `raw/`.
3. Compute the baseline and the saving:
   ```bash
   python src/baseline_vs_today.py
   ```
   The result is in `reports/baseline_vs_today.md`.

Run both from `water_poc`. They need pandas and numpy (and openpyxl for Excel files), and take about 5 seconds each.

Other commands:

```bash
python src/load_eastwater.py --sample           # load the SAMPLE set even if real files are in raw/
python src/baseline_vs_today.py --sample        # report on the SAMPLE set
python src/load_eastwater.py path/to/folder     # load from another folder
python src/load_eastwater.py --write-templates  # rebuild templates/ and data_dictionary.csv from the schema and the .inp
python data_request/samples/make_samples.py     # rebuild the SAMPLE set
```

When `data/eastwater/raw/` is empty, both scripts run on the SAMPLE set instead. Their outputs are then named `SAMPLE_*` (data) and `*_SAMPLE.*` (reports), and carry a SAMPLE banner.

The schema at the top of `src/load_eastwater.py` defines the columns, units and checks. The templates and the data dictionary are generated from it, so to change a column, edit the schema and run `--write-templates`. The IDs come from the `[PUMPS]`, `[TANKS]`, `[RESERVOIRS]` and `[JUNCTIONS]` sections of the `.inp`, which is read on every run.

## What the loader checks

| check | what happens |
|---|---|
| **Columns** | Each table is matched to a dataset by its columns. Common variants are accepted, e.g. `Flow (m3/h)` for `flow_m3_h` or `date` for `timestamp`. Missing required columns, or files that match no template, are listed in the report. |
| **Timezone and dates** | Timestamps are read as Thai time. Times with a UTC offset (`2026-03-01T02:00Z`) are converted to Thai time. Day/month/year dates, Buddhist-era years (2569 → 2026) and Excel serial dates are converted and counted. Unreadable dates are removed and flagged. |
| **Units** | Pressures in bar, kPa, kg/cm² or psi are converted to m. Tank levels given as water surface elevation (`m_msl`) become m above the tank floor, using the model's floor elevation (81 m). Tariff units must match their component (THB/kWh, THB/kW, THB/month, %). |
| **Gaps** | Missing hours are counted per pump, meter and tank, and missing days per customer node, with the longest gap. In the baseline, pump-status gaps of up to 2 h take the pump's last state; longer gaps are left out of the per-pump-hour and per-m³ figures. |
| **Duplicates** | The first row with the same ID and time is kept. The others are flagged, separately when their values differ. |
| **Out-of-range values** | Removed and flagged: negative flows, volumes or kWh; a pump running more than 100% of an hour; a tank level outside the tank; pressures below -20 m or above 250 m. Kept but flagged: flows above 1.5x the model's pump curve; more than 3x a customer's model demand; flow while a pump is recorded off; bill lines that do not add up; a tariff that leaves minutes of a day without a rate. |
| **IDs** | Matched to the model by the exact ID, then by your tags in `id_map.csv`, then by the same ID with different separators or leading zeros (`NPL3-1` = `NPL3-01p`). Unknown IDs are removed and listed. Model elements with no data are listed too, e.g. nodes 71 and 678. |

## Outputs

`data/eastwater/` (client data, under the NDA):

| file | what |
|---|---|
| `validation_report.md` | What came in, coverage per dataset, every kind of problem with its first file and line, and the IDs that were not matched exactly. Starts with whether the saving can be computed yet. |
| `flags.csv` | Every removed or flagged value: dataset, file, line, column, value, issue, action. |
| `pump_operation_hourly.csv` | Pumps running (0-1 per pump, or a count per station), flow and power per pump and hour. Sub-hourly data is averaged, and `coverage` is the share of the hour that had data. |
| `station_energy.csv`, `electricity_bills.csv` | Metered kWh per meter at the interval received; one row per bill. |
| `tariff.csv`, `holidays.csv` | Rate components per meter, dates, day type and time window; off-peak holidays. |
| `customer_delivery_daily.csv` (`_hourly.csv`) | m³ per customer node and day (and hour). Hourly data fills days that have no daily total. |
| `scada_hourly.csv` | Hourly mean, minimum and maximum, all in m: tank level above the floor, source head above sea level, or pressure. |
| `pump_register.csv`, `pump_tests.csv`, `confirmations.csv`, `id_map.csv` | As received, with IDs checked. Pump tests also get the wire-to-water efficiency, flow x head / power. |
| `manifest.json` | Every input file with its SHA-256, the outputs of the run, the periods, and whether the saving can be computed. `baseline_vs_today.py` reads only what this lists. |

`reports/`:

| file | what |
|---|---|
| `baseline_vs_today.md` | Headline saving, today's baseline, the plans compared like-for-like, where the saving comes from, and checks. |
| `baseline_vs_today_kpis.csv` | One row for today (all days, and weekdays) and one per plan, with every KPI, for the dashboard or other tools. |
| `baseline_vs_today_daily.csv` | One row per day: delivered m³, kWh and pump-hours per meter and station, cost, demand charge, kWh/m³, THB/m³, and whether the day is complete. |

## How the saving is calculated

**Today's baseline.** Days count only when every meter has 24 hours of energy, every hour has a price, and every regularly reporting customer node has a volume.

- **Energy per hour** comes from the best source available for each meter:
  - meter data at hourly or finer resolution;
  - daily meter totals, shared over the day's pump-hours;
  - bills, with the on-peak and off-peak kWh each shared over the pump-hours in that period;
  - pump power from SCADA;
  - pump ratings x hours run, as a last-resort estimate.
- **Costs** use Eastwater's tariff hour by hour: time-of-use energy plus Ft. The demand charge is the highest hourly kW in its window each month, spread over the month's days. VAT and the fixed service charge are left out.
- **Results:**
  - kWh/day;
  - kWh/m³ and THB/m³ delivered;
  - share of energy bought on-peak;
  - peak demand per meter and month, when the tariff has a demand charge.

  Bills are reconciled against the meter data.

**Plans vs today, like-for-like.** The plans in `reports/matlab/pump_plans_kpis.csv` come from the EPANET model, which assumes a 75% pump efficiency and the POC's assumed tariff. Their modelled kWh/m³ would mostly measure that assumption, not the schedule. So each plan's hourly pump counts (`pump_plans_schedule.csv`) are re-costed with **today's measured performance**:

- **With pump or station flows:**
  - each station's kWh per m³ pumped is measured, net of the load with no pumps running;
  - each plan's pumped volume per station is its pumps running x the model's flow per pump, scaled to the plan's delivered volume and today's pumped-to-delivered ratio;
  - so a model whose pumps move more water than the real ones does not inflate the saving.
- **Without flows:** each station's flow is taken as the model's flow x one factor that makes today's pumping match today's delivered volume.
- **Without model flows either:** the plans are costed per pump-hour.

Plans are run on the same weekdays as today, at the same tariff. **Saving = 1 - plan THB/m³ / today's THB/m³**, split into:

- fewer kWh per m³ (station mix, fewer pump-hours);
- cheaper hours (time-of-use);
- a lower peak demand.

Only plans graded **Pass** by EPANET get a saving, as in `pump_plans.md`.

**Before quoting the figure.** The plans were optimised for a flat demand (488,403 m³/day without nodes 71 and 678) and the assumed tariff, so this comparison is indicative. For a firm figure:

1. Get answers to Q1-Q3.
2. Re-run `matlab/optimize_pumps.m` with Eastwater's hourly demand pattern, the real tariff (including the demand charge) and the real pump availability.
3. Re-run `baseline_vs_today.py`.

The report repeats these caveats.

## The SAMPLE set

`samples/SAMPLE_*.csv` is **invented** data for March 2026, made by `samples/make_samples.py`:
- a rule-based operator runs the model's pumps against a made-up demand;
- pump flows are set about 7% below the model's, with made-up pump powers;
- the energy rates are the POC's assumed tariff, and the demand charge and Ft are illustrative.

Every file name starts with `SAMPLE_`, every file's first line says SAMPLE, and the reports made from it carry a SAMPLE banner. **Never present any number from it as Eastwater's.**

It has errors planted on purpose, and the validation report finds all of them:
- a 6-hour gap for one pump, and a pump running "2" hours in an hour;
- exact and conflicting duplicates;
- NPL3 pumps written `NPL3-1` (loose match), and TM Pond pumps, a customer and a tank given by client tags (id_map);
- a negative kWh and a negative volume, each making one day incomplete;
- a customer node that is not in the model, and no data for nodes 71 and 678;
- hourly volumes with day/month/Buddhist-era dates;
- pressures in bar and kg/cm², timestamps in UTC, and a tank level in m MSL;
- an impossible tank level of 35 m;
- no meter data for TM Pond, which has a bill only.

Whatever saving the scripts report on the SAMPLE set only shows that the calculation runs; it says nothing about Eastwater.
