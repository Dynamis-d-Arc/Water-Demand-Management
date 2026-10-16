# Data request: today's operation of the Rayong pump stations
## รายการข้อมูลที่ขอ: การเดินเครื่องสูบน้ำปัจจุบันของระบบระยอง

**Project:** AI for Demand & Supply Optimization, proof of concept (POC)
**For:** Eastwater operations, SCADA, energy/finance and customer metering teams
**Confidentiality / ความลับ:** covered by the NDA. Files stay on the project's computer and are not uploaded to any online service.

### Why we are asking / เหตุผลที่ขอข้อมูล

The POC has built pump schedules for the Rayong network (pump stations NPL2, NPL3 and TM Pond) and checked them in the EPANET model. What it cannot show yet is the saving against **today's operation**, which is what the 3-5% target is measured against. For that we need to know:

- how the pumps run today;
- what that costs in kWh and THB;
- how much water reaches customers.

The costs so far use an assumed tariff (4.1839 THB/kWh 09:00-22:00 on weekdays, 2.6037 THB/kWh otherwise, no demand charge, no Ft), so we also need the real one.

### Summary / สรุป

| # | Item | ข้อมูล | For the saving figure | Period | Resolution | Template |
|---|---|---|---|---|---|---|
| 1 | Today's pump operation | การเดินเครื่องสูบน้ำ | **required** | 1-3 months | hourly (finer is fine) | `pump_operation.csv` |
| 2 | Electricity bills and/or kWh per pump station | ใบแจ้งค่าไฟฟ้า / หน่วยไฟฟ้าของสถานีสูบน้ำ | **required**: bills or meter data, both is best | same months | bills monthly; meter data hourly or 15-min | `electricity_bills.csv`, `station_energy.csv` |
| 3 | Electricity tariff | อัตราค่าไฟฟ้า | **required** | in force over the period | - | `tariff.csv`, `holidays.csv` |
| 4 | Water delivered to each customer | ปริมาณน้ำที่จ่ายให้ลูกค้าแต่ละราย | **required** | same months | daily; hourly if logged | `customer_delivery.csv` |
| 5 | SCADA tank levels and key pressures | ระดับน้ำในถังพักน้ำและแรงดัน (SCADA) | checks it; **required for model calibration** | same months | hourly or finer | `scada_levels_pressures.csv` |
| 6 | Pump power and efficiency data | กำลังไฟฟ้าและประสิทธิภาพเครื่องสูบน้ำ | improves it | latest available | - | `pump_register.csv`, `pump_tests.csv` |
| 7 | Confirmations about the model | ข้อมูลที่ขอให้ยืนยัน | **Q1-Q3 required** | - | - | `confirmations.csv` |
| - | Your IDs for pumps, meters and customers | ตารางจับคู่รหัส | saves re-keying | - | - | `id_map.csv` |

All seven items are priority items in the POC report's data-gap list (Section 5). **The saving figure itself needs** items 1, 2 (bills or meter data), 3 and 4 for the same period, plus answers to Q1-Q3; items 5 and 6 make it firmer and are needed to calibrate the model.

**Period / ช่วงเวลา:**
- **For the saving figure:** the most recent 3 months of normal operation if possible, and at least 4 consecutive weeks.
- **Same period for every item,** including weekends and holidays.
- **Unusual events:** if something unusual happened (a pump out of service, a pipe repair, a shutdown), keep it in and tell us the dates.
- **Longer history is welcome** and loads the same way. The POC report asks for up to 24 months of pump logs and bills, and 3 years of daily customer volumes, for the forecasting and calibration work.

---

### 1. Today's pump operation / การเดินเครื่องสูบน้ำ (ข้อมูลรายชั่วโมง)

- **What:** for each of the 18 pumps, whether it ran in each hour, plus its flow and power if SCADA records them:
  - on/off status, or the share of the hour it ran (สถานะเปิด-ปิด หรือสัดส่วนเวลาที่เดินเครื่อง);
  - flow in m³/h (อัตราการไหล);
  - power in kW (กำลังไฟฟ้า).
  If you only have station totals, give the number of pumps running and the station flow for NPL2, NPL3 and TM Pond.
- **Why:** this *is* today's operation: how many pumps run, at which station and when. With item 2 it gives the energy each station really uses per m³ pumped. The plans are costed with that same figure, so the comparison is like-for-like. **Flows matter:** without them we have to assume the model's pump flows are right.
- **Period and resolution:** 1-3 months, the same months as item 2. Hourly; 5- or 15-minute snapshots are fine, we average them.
- **Preferred format:** `templates/pump_operation.csv`, with one row per pump per hour:
  - `timestamp`: start of the hour, Thai time;
  - `pump_id`;
  - `pumps_running`: 0-1, e.g. 0.5 = ran half the hour;
  - `flow_m3_h`, `power_kw`.

  A SCADA historian export in its own layout is also fine if you send its tag list (fill `id_map.csv`). If you only have start/stop event logs, send them as they are.

Pumps in the model (use these IDs, or map yours in `id_map.csv`):

| station สถานี | pumps เครื่องสูบ | draws from → delivers to | pump curve in the model |
|---|---|---|---|
| NPL2 | NPL2-01p ... NPL2-06p | NPL_Res2 (head 43.41 m) → head tank NPL2_HT | 0-1,642 m³/h at 138-61 m |
| NPL3 | NPL3-01p ... NPL3-06p | NPL_Res3 (head 43.41 m) → head tank NPL3_HT | 1,665 m³/h at 115 m |
| TM Pond | TM_Pond_01p ... TM_Pond_06p | R10885 (head 23 m) → network feeding both head tanks | 2,160 m³/h at 106 m; pumps 3-6 closed in the model |

### 2. Electricity bills and kWh per pump station / ใบแจ้งค่าไฟฟ้าและหน่วยไฟฟ้าของสถานีสูบน้ำ

- **What:**
  - **(a) Bills:** the PEA bill for every meter that supplies NPL2, NPL3 and TM Pond, for each month of the period, with every line:
    - kWh on-peak and off-peak (หน่วย On Peak / Off Peak);
    - maximum demand in kW (ความต้องการพลังไฟฟ้าสูงสุด);
    - energy charge, demand charge, Ft, service charge, power-factor charge (ค่าพลังงาน, ค่าความต้องการพลังไฟฟ้า, ค่า Ft, ค่าบริการ, ค่าปรับเพาเวอร์แฟกเตอร์);
    - VAT and the total.
  - **(b) Meter data, if you have it:** kWh per station per 15 minutes or per hour. This can be the PEA AMR load profile or Eastwater's own energy meters / SCADA kWh counters (หน่วยไฟฟ้ารายชั่วโมงหรือราย 15 นาที). Daily kWh per station is the minimum.
- **Why:**
  - The bills give the real cost, and we use them to check the tariff and the meter data.
  - Hourly kWh shows how much energy is bought on-peak and what sets the monthly demand charge.
- **Period and resolution:** the same 1-3 months. Bills monthly; meter data at 15 minutes or 1 hour.
- **Preferred format:**
  - `templates/electricity_bills.csv`: one row per bill;
  - `templates/station_energy.csv`: `timestamp`, `meter_id` (PEA customer number, CA), `station_id`, `kwh`, `interval_min`.

  Scans or PDFs of the bills are fine: we will type them in. Tell us which station(s) each meter supplies (join them with + if one meter supplies several, e.g. `NPL2+NPL3`).

### 3. Electricity tariff / อัตราค่าไฟฟ้า

- **What:** for each station meter, the rates in force over the period:
  - tariff category, e.g. PEA 4.2.2 TOU, 22-33 kV (ประเภทอัตรา);
  - energy rate per time-of-use period, in THB/kWh, with the hours of each period;
  - **demand charge** in THB/kW a month, and the hours it applies to (ค่าความต้องการพลังไฟฟ้า);
  - **Ft** in THB/kWh, for each Ft period (ค่าไฟฟ้าผันแปร Ft);
  - monthly service charge, and any special contract terms or discounts.

  Also give the list of weekday holidays billed at off-peak rates all day (วันหยุดที่คิดอัตรา Off Peak ทั้งวัน).
- **Why:** the saving is in baht. Today's operation and the plans have to be priced with the same, real tariff, and the demand charge rewards running fewer pumps at peak.
- **Preferred format:**
  - `templates/tariff.csv`: one row per rate component and time window, e.g. `ALL, 2026-01-01, , energy, weekday, 09:00, 22:00, 4.1839, THB/kWh, On Peak`;
  - `templates/holidays.csv`.

  The tariff schedule or contract as a PDF is also fine.

### 4. Water delivered to each customer / ปริมาณน้ำที่จ่ายให้ลูกค้าแต่ละราย

- **What:** the volume delivered to each customer connection in the model (the 28 nodes below), in m³ per day, or per hour if the meters log it (ปริมาณน้ำ ลบ.ม. รายวัน หรือรายชั่วโมง). If a customer has several meters, give each meter.
- **Why:**
  - It turns kWh and THB into **kWh per m³ and THB per m³ delivered**, the figures the plans are compared on.
  - Hourly data also gives the daily demand pattern, which the model lacks: it assumes the same demand every hour.
- **Period and resolution:** the same 1-3 months; daily at least, hourly preferred.
- **Preferred format:** `templates/customer_delivery.csv`:
  - `timestamp`: the date, or the start of the hour;
  - `node_id`: the model's ID, or your meter or account number once it is listed in `id_map.csv`;
  - `volume_m3`;
  - `interval_min`: 1440 for daily, 60 for hourly.

  Cumulative meter readings (`reading_m3`) are fine instead of volumes.

Customer nodes in the model (ID, demand in the model, ground elevation):

| node | m³/day | elev. m | node | m³/day | elev. m |
|---|---|---|---|---|---|
| MTP-IEAT3 | 122,000 | 34 | IEAT6 | 3,000 | 58.6 |
| 71 *(see Q1)* | 100,000 | 55 | IEAT5 | 2,700 | 58.6 |
| 678 *(see Q1)* | 100,000 | 43.7 | Burapa | 2,700 | 74.7 |
| EIE3 | 68,000 | 25 | Thaicoon | 2,400 | 63 |
| MTP-IEAT2 | 66,000 | 23.29 | PTT2 (model note: Prax Air) | 2,000 | 21.2 |
| RIL1996 (model note: New Connect) | 45,000 | 27.9 | ThanTaSaThan | 1,500 | 52 |
| EIE2 | 43,000 | 23.5 | TYS | 1,500 | 63 |
| Banchang-PWA | 40,000 | 51 | Indorama | 300 | 70 |
| AIE | 40,000 | 31.5 | PolyEaster | 271 | 60 |
| MTP-IEAT1 | 24,000 | 14 | PTT3 | 250 | 54.25 |
| PRY_ASS(SSP) | 9,600 | 40 | EIE1 | 200 | 25 |
| PTT1 | 5,800 | 21.2 | Linde(TIG) | 100 | 21.2 |
| HESIE4 | 5,000 | 56 | Ban-Kai-Collage | 80 | 70 |
| IEAT4 | 3,000 | 58.6 | PMSteel | 2 | 58 |

Total in the model: 688,403 m³/day.

### 5. SCADA tank levels and key pressures / ระดับน้ำในถังพักน้ำและแรงดันจาก SCADA

- **What:**
  - water level of head tanks **NPL2_HT** and **NPL3_HT** (ระดับน้ำในถังพักน้ำ);
  - source water level at each pump intake (ระดับน้ำต้นทางที่จุดรับน้ำ): the NPL2 and NPL3 sources and TM Pond;
  - pressure at key points (แรงดันน้ำ ณ จุดสำคัญ): IEAT4, IEAT5, IEAT6 and Burapa, where the model shows low pressure; station discharge pressures; any other points SCADA logs.
- **Why:**
  - It shows the limits today's operation keeps to: tank range, lowest customer pressure. The plans must keep to the same limits.
  - It shows whether the tanks end the day where they started.
  - It lets us calibrate the model.
- **Period and resolution:** the same 1-3 months, hourly or finer.
- **Preferred format:** `templates/scada_levels_pressures.csv`, one row per reading:
  - `timestamp`, `point_id`, `quantity` (level or pressure), `value`, `unit`;
  - tank levels in m above the tank floor (`m`) or water surface elevation (`m_msl`, ม.รทก.);
  - pressures in m, bar, kPa or kg/cm²: say which.

  Tanks in the model: floor at 81 m; NPL2_HT 2-21.85 m (diameter 21 m), NPL3_HT 2-25 m (diameter 23 m).

### 6. Pump power or efficiency data / กำลังไฟฟ้าและประสิทธิภาพของเครื่องสูบน้ำ

- **What:**
  - **(a) Pump register** (`templates/pump_register.csv`, the 18 pumps are pre-filled). For each pump:
    - its status today: duty, standby, out of service or removed (เครื่องหลัก/สำรอง/ชำรุด);
    - nameplate flow, head and motor kW (ค่าพิกัด);
    - pump and motor efficiency;
    - whether it has a variable-speed drive (VSD);
    - year installed and last overhaul.
  - **(b) Test points:** flow, head and input power at one or more operating points from a site test or a recent SCADA reading (`templates/pump_tests.csv`), or the manufacturer's pump curves (PDF).
- **Why:**
  - The model assumes 75% efficiency for every pump.
  - Real efficiency sets how much each pump-hour costs and which pumps a schedule should prefer.
  - Large differences between pumps are a saving in their own right.

### 7. Confirmations / ข้อมูลที่ขอให้ยืนยัน

Please answer in `templates/confirmations.csv` (pre-filled with the questions), or by email. Q1-Q3 decide which plans and demand figures are valid, so they come first.

| # | Question | In the model now |
|---|---|---|
| **Q1** | What are nodes **71** and **678**? Real customers, future demand or placeholders? If real: which customers, and what do they take per day today? (โหนด 71 และ 678 คืออะไร) | 100,000 m³/day each, 29% of the model's total. With them in, no pump schedule stops head tank NPL3_HT from draining. |
| **Q2** | Are **TM Pond pumps 3-6** standby, out of service or removed? How many TM Pond pumps can run at once? (เครื่องสูบ TM Pond 3-6 เป็นเครื่องสำรองหรือไม่) | Closed. The POC found that at most 2 TM Pond pumps can run (more cannot deliver the head). |
| **Q3** | **Source water levels** at the pump intakes: typical, lowest and highest, in m MSL (ระดับน้ำต้นทาง ม.รทก.) | NPL_Res2 and NPL_Res3 fixed at 43.41 m, R10885 (TM Pond) at 23 m. The suction pipework at NPL3 and TM Pond sits above these heads. |
| Q4 | Head tank operating range, and the levels at which operators start and stop pumps | 2-21.85 m (NPL2_HT), 2-25 m (NPL3_HT) |
| Q5 | Do the station meters also supply other loads (offices, treatment, lighting)? About how many kW? | Only pump energy is modelled |
| Q6 | Tariff category, voltage and any special contract for each station meter | The assumed tariff above |
| Q7 | Customers supplied by these stations that are not among the 28 nodes, or nodes no longer supplied | 28 nodes |

---

### How to prepare the files / วิธีเตรียมไฟล์

- **One file per item**, using the templates in `templates/`. Save as **CSV UTF-8** (Excel: *Save As → CSV UTF-8*). One Excel workbook with one sheet per item, each named like its template, also works.
- Several files per item are fine, e.g. one per month or per station. Name them like `pump_operation_NPL2_2026-03.csv`.
- **Times:**
  - Thai time (Asia/Bangkok, UTC+07:00), written `YYYY-MM-DD HH:MM`;
  - a timestamp is the **start** of its interval (`2026-03-02 09:00` = 09:00-10:00);
  - Christian-era years (2026, not 2569) if possible.
- **Numbers:** plain numbers without thousands separators, in the unit shown in the column name. **Leave a value blank if it is unknown; do not write 0.**
- **IDs:** use the model IDs above, or fill `id_map.csv` with your SCADA tags, meter numbers and customer accounts.
- The template's second row, starting with `#`, shows the unit and format of each column. You can leave it or delete it. `data_dictionary.csv` describes every column, in English with Thai labels.
- If a template does not fit what you have, send the data in its own format with a note. We will adapt the loader rather than ask you to re-key data.

**How to send:** see `README.md` in this folder. In short: send the files through the channel agreed under the NDA, not as plain email attachments. Every delivery gets a validation report back that lists anything missing or unclear.
