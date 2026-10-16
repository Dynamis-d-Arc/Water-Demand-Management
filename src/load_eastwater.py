"""Load Eastwater's operational data, check it and map it to the Rayong EPANET model.

Usage:  python src/load_eastwater.py [inbox_folder] [--sample] [--inp path/to/model.inp]
        python src/load_eastwater.py --write-templates

Reads every .csv/.xlsx file in the inbox (default data/eastwater/raw/). Each file (or Excel sheet) is matched to a
dataset by its columns, with the file name as tie-break, so pump_operation_NPL2_2026-03.csv and a SCADA export
with the template's columns both work; several files per dataset are stacked. Lines whose first cell starts with #
are notes and are skipped. If the inbox is empty, or with --sample, the synthetic set in data_request/samples/ is
loaded instead and every output is prefixed SAMPLE_.

Writes to data/eastwater/ (prefix SAMPLE_ for the sample set):
  pump_operation_hourly.csv     pumps running, flow and power per pump (or per station) and hour
  station_energy.csv            metered kWh per meter and interval, as received
  electricity_bills.csv         one row per bill
  tariff.csv, holidays.csv      tariff components by meter, dates, day type and time window; off-peak holidays
  customer_delivery_daily.csv   m3 per customer node and day (customer_delivery_hourly.csv if hourly data came in)
  scada_hourly.csv              tank levels (m above the floor), reservoir heads and pressures (m), hourly means
  pump_register.csv, pump_tests.csv, confirmations.csv, id_map.csv
  flags.csv                     every value removed or flagged, with file, line and reason
  validation_report.md          what came in, coverage, and what to fix
  manifest.json                 inputs with SHA-256, outputs and periods; src/baseline_vs_today.py reads this
--write-templates rebuilds data_request/templates/ and data_request/data_dictionary.csv from SCHEMA and the model.
"""
import argparse
import datetime as dt
import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from config import DEFAULT_INP, ROOT

EW_DIR = ROOT / "data" / "eastwater"
RAW_DIR = EW_DIR / "raw"
REQUEST_DIR = ROOT / "data_request"
TEMPLATE_DIR = REQUEST_DIR / "templates"
SAMPLE_DIR = REQUEST_DIR / "samples"
BKK = dt.timezone(dt.timedelta(hours=7))          # Asia/Bangkok is UTC+07:00 all year (no daylight saving)
TS_FMT, DATE_FMT = "%Y-%m-%d %H:%M", "%Y-%m-%d"
TS_HINT = "YYYY-MM-DD HH:MM Thai time (Asia/Bangkok UTC+07:00)"
SAMPLE_NOTE = ("SAMPLE DATA: synthetic, generated to test the loaders. It is not Eastwater data, and its numbers "
               "say nothing about Eastwater's operation.")
MISSING = {"", "-", "na", "n/a", "nan", "null", "none", "#n/a"}
PRESSURE_TO_M = {"m": 1.0, "bar": 10.1972, "kpa": 0.101972, "kg/cm2": 10.0, "psi": 0.703070}
FLOW_TO_M3H = {"CMD": 1 / 24, "CMH": 1.0, "MLD": 1000 / 24, "LPS": 3.6}


@dataclass(frozen=True)
class Col:
    name: str
    kind: str                 # timestamp, date, time, number, id, choice or text
    unit: str = ""
    required: bool = False    # a row without it is removed
    desc: str = ""
    th: str = ""
    example: str = ""
    choices: tuple = ()


@dataclass(frozen=True)
class Dataset:
    file: str                 # template file name
    title: str
    th: str
    signature: tuple          # columns that identify a file as this dataset
    hint: tuple               # file-name fragments, used as tie-break
    priority: str             # needed for the saving figure, or helpful
    cols: tuple


SCHEMA = {
    "id_map": Dataset(
        "id_map.csv", "ID map", "ตารางจับคู่รหัส", ("epanet_id", "client_tag"), ("id_map", "mapping"), "helpful", (
            Col("epanet_id", "id", required=True, desc="ID in the EPANET model (pre-filled)",
                th="รหัสในแบบจำลอง EPANET", example="NPL2-01p"),
            Col("element_type", "choice", desc="What the ID is (pre-filled)", th="ประเภท", example="pump",
                choices=("pump", "station", "tank", "reservoir", "customer", "junction")),
            Col("client_tag", "text", desc="Eastwater's ID for the same thing: SCADA tag, meter number or customer "
                "account. One tag per row; copy the row if there are more", example="NPL2.P01.RUN",
                th="รหัสที่ใช้ในระบบของ Eastwater (SCADA tag / เลขมาตร / เลขบัญชีลูกค้า)"),
            Col("client_name", "text", desc="Eastwater's name for it, e.g. the customer's company name",
                th="ชื่อที่ใช้ใน Eastwater", example="บริษัท ตัวอย่าง จำกัด"),
            Col("model_description", "text", desc="What the model says about it (pre-filled, for reference)",
                th="ข้อมูลในแบบจำลอง", example="lifts NPL_Res2 to NPL2_HT"),
            Col("notes", "text", desc="Anything we should know", th="หมายเหตุ"),
        )),
    "pump_operation": Dataset(
        "pump_operation.csv", "Pump operation", "การเดินเครื่องสูบน้ำ", ("timestamp", "pump_id"),
        ("pump_operation", "pump_status", "pump_log", "pump_run"), "needed", (
            Col("timestamp", "timestamp", "Asia/Bangkok", True, "Start of the interval",
                "วันเวลาเริ่มช่วง (เวลาประเทศไทย)", "2026-03-02 09:00"),
            Col("pump_id", "id", "", True, "EPANET pump ID (NPL2-01p ... TM_Pond_06p), or the station (NPL2, NPL3, "
                "TM_Pond) if only station totals exist. A tag listed in id_map also works",
                "รหัสเครื่องสูบน้ำหรือสถานีสูบน้ำ", "NPL2-01p"),
            Col("pumps_running", "number", "0-1 per pump; 0-6 per station", False, "Average number of pumps running "
                "in the interval: 0 to 1 for one pump (1 = ran all interval, 0.5 = half), 0 to 6 for a station. Blank "
                "if you give flow only", "จำนวนเครื่องที่เดิน (0-1 ต่อเครื่อง)", "1"),
            Col("flow_m3_h", "number", "m3/h", False, "Average flow in the interval", "อัตราการไหลเฉลี่ย (ลบ.ม./ชม.)",
                "1450"),
            Col("power_kw", "number", "kW", False, "Average electrical input power in the interval",
                "กำลังไฟฟ้าเฉลี่ย (กิโลวัตต์)", "430"),
            Col("speed_pct", "number", "%", False, "Speed of a variable-speed pump (100 = full speed)",
                "ความเร็วรอบ (%)", "100"),
            Col("interval_min", "number", "min", False, "Length of the interval: 5, 10, 15, 30 or 60 (60 if blank)",
                "ช่วงเวลาของข้อมูล (นาที)", "60"),
        )),
    "station_energy": Dataset(
        "station_energy.csv", "Station electricity (metered)", "พลังงานไฟฟ้าของสถานีสูบน้ำ",
        ("timestamp", "meter_id", "kwh"), ("station_energy", "energy", "kwh", "meter"), "needed (this or the bills)", (
            Col("timestamp", "timestamp", "Asia/Bangkok", True, "Start of the interval (the date, for daily data)",
                "วันเวลาเริ่มช่วง (เวลาประเทศไทย)", "2026-03-02 09:00"),
            Col("meter_id", "text", "", True, "Electricity meter: PEA customer number (CA) or Eastwater's meter name",
                "หมายเลขผู้ใช้ไฟฟ้า (CA) หรือชื่อมาตรไฟฟ้า", "020001234567"),
            Col("station_id", "id", "", True, "Pump station(s) on this meter: NPL2, NPL3 or TM_Pond; join with + if "
                "one meter supplies several (NPL2+NPL3)", "สถานีสูบน้ำที่ใช้มาตรนี้", "NPL2"),
            Col("kwh", "number", "kWh", True, "Energy in the interval", "พลังงานไฟฟ้าในช่วงเวลา (kWh)", "2690"),
            Col("interval_min", "number", "min", True, "15, 30, 60, or 1440 for daily totals",
                "ช่วงเวลาของข้อมูล (นาที)", "60"),
            Col("kw_max", "number", "kW", False, "Highest 15-minute demand in the interval, if the meter records it",
                "ความต้องการพลังไฟฟ้าสูงสุด 15 นาที (kW)", "2750"),
        )),
    "electricity_bills": Dataset(
        "electricity_bills.csv", "Electricity bills", "ใบแจ้งค่าไฟฟ้า", ("meter_id", "period_start", "period_end"),
        ("bill",), "needed (these or station meter data)", (
            Col("meter_id", "text", "", True, "PEA customer number (CA) or meter name, as in station_energy",
                "หมายเลขผู้ใช้ไฟฟ้า (CA)", "020001234567"),
            Col("station_id", "id", "", True, "Pump station(s) on this meter (NPL2, NPL3, TM_Pond; join with +)",
                "สถานีสูบน้ำ", "NPL2"),
            Col("period_start", "date", "YYYY-MM-DD", True, "First day the bill covers", "วันเริ่มรอบบิล",
                "2026-03-01"),
            Col("period_end", "date", "YYYY-MM-DD", True, "Last day the bill covers", "วันสิ้นสุดรอบบิล",
                "2026-03-31"),
            Col("tariff_code", "text", "", False, "Tariff on the bill, e.g. PEA 4.2.2 TOU 22-33 kV",
                "ประเภทอัตราค่าไฟฟ้า", "4.2.2 TOU"),
            Col("kwh_on_peak", "number", "kWh", False, "On-peak energy", "หน่วยไฟฟ้าช่วง On Peak (kWh)", "1200000"),
            Col("kwh_off_peak", "number", "kWh", False, "Off-peak energy", "หน่วยไฟฟ้าช่วง Off Peak (kWh)",
                "1350000"),
            Col("kwh_total", "number", "kWh", True, "Total energy", "หน่วยไฟฟ้ารวม (kWh)", "2550000"),
            Col("kw_max_on_peak", "number", "kW", False, "Maximum demand in on-peak hours (the billed demand)",
                "ความต้องการพลังไฟฟ้าสูงสุดช่วง On Peak (kW)", "3900"),
            Col("kw_max_partial_peak", "number", "kW", False, "Maximum demand in partial-peak hours (TOD tariff)",
                "ความต้องการพลังไฟฟ้าสูงสุดช่วง Partial Peak (kW)", ""),
            Col("kw_max_off_peak", "number", "kW", False, "Maximum demand in off-peak hours",
                "ความต้องการพลังไฟฟ้าสูงสุดช่วง Off Peak (kW)", "4100"),
            Col("energy_charge_thb", "number", "THB", False, "Energy charge", "ค่าพลังงานไฟฟ้า (บาท)", "8535000"),
            Col("demand_charge_thb", "number", "THB", False, "Demand charge", "ค่าความต้องการพลังไฟฟ้า (บาท)",
                "518400"),
            Col("ft_charge_thb", "number", "THB", False, "Ft charge", "ค่า Ft (บาท)", "510000"),
            Col("ft_thb_per_kwh", "number", "THB/kWh", False, "Ft rate on the bill", "อัตรา Ft (บาท/หน่วย)", "0.20"),
            Col("service_charge_thb", "number", "THB", False, "Monthly service charge", "ค่าบริการรายเดือน (บาท)",
                "312.24"),
            Col("pf_charge_thb", "number", "THB", False, "Power-factor (kVAR) charge", "ค่าปรับเพาเวอร์แฟกเตอร์ (บาท)",
                "0"),
            Col("other_charge_thb", "number", "THB", False, "Any other charge or credit", "ค่าใช้จ่ายอื่น (บาท)", "0"),
            Col("total_ex_vat_thb", "number", "THB", False, "Total before VAT", "รวมเงินก่อนภาษีมูลค่าเพิ่ม (บาท)",
                "9563712.24"),
            Col("vat_thb", "number", "THB", False, "VAT", "ภาษีมูลค่าเพิ่ม (บาท)", "669459.86"),
            Col("total_thb", "number", "THB", False, "Total including VAT", "รวมเงินทั้งสิ้น (บาท)", "10233172.10"),
        )),
    "tariff": Dataset(
        "tariff.csv", "Electricity tariff", "อัตราค่าไฟฟ้า", ("component", "rate", "unit"), ("tariff",), "needed", (
            Col("meter_id", "text", "", True, "Meter the row applies to, or ALL", "มาตรที่ใช้อัตรานี้ หรือ ALL", "ALL"),
            Col("valid_from", "date", "YYYY-MM-DD", True, "First day the rate applies", "ใช้ตั้งแต่วันที่",
                "2026-01-01"),
            Col("valid_to", "date", "YYYY-MM-DD", False, "Last day the rate applies; blank = still valid",
                "ใช้ถึงวันที่ (ว่าง = ยังใช้อยู่)", ""),
            Col("component", "choice", "", True, "energy = THB/kWh by time of day; demand = THB/kW a month on the "
                "highest 15-minute demand in the window; ft = THB/kWh; service = THB/month; vat = %",
                "ประเภทค่าไฟฟ้า", "energy", ("energy", "demand", "ft", "service", "vat")),
            Col("day_type", "choice", "", False, "For energy and demand rows: weekday (Mon-Fri except the dates in "
                "holidays.csv), weekend, holiday or all", "ประเภทวัน (วันทำงาน / เสาร์-อาทิตย์ / วันหยุด)", "weekday",
                ("weekday", "weekend", "holiday", "all")),
            Col("start_time", "time", "HH:MM", False, "Start of the window (energy and demand rows)", "เวลาเริ่ม",
                "09:00"),
            Col("end_time", "time", "HH:MM", False, "End of the window; 24:00 = midnight; a window may run past "
                "midnight (22:00 to 09:00)", "เวลาสิ้นสุด", "22:00"),
            Col("rate", "number", "see unit", True, "The rate", "อัตรา", "4.1839"),
            Col("unit", "choice", "", True, "THB/kWh (energy, ft), THB/kW (demand), THB/month (service), % (vat)",
                "หน่วย", "THB/kWh", ("THB/kWh", "THB/kW", "THB/month", "%")),
            Col("period_name", "text", "", False, "Name of the period, e.g. On Peak", "ชื่อช่วงเวลา เช่น On Peak",
                "On Peak"),
            Col("notes", "text", "", False, "Tariff code, source document", "หมายเหตุ", "PEA 4.2.2 TOU"),
        )),
    "holidays": Dataset(
        "holidays.csv", "Off-peak holidays", "วันหยุดที่คิดอัตรา Off Peak ทั้งวัน", ("date",), ("holiday",),
        "needed with the tariff", (
            Col("date", "date", "YYYY-MM-DD", True, "A weekday billed at off-peak rates all day", "วันที่",
                "2026-05-01"),
            Col("name", "text", "", False, "Name of the holiday", "ชื่อวันหยุด", "วันแรงงานแห่งชาติ"),
        )),
    "customer_delivery": Dataset(
        "customer_delivery.csv", "Water delivered to customers", "ปริมาณน้ำที่จ่ายให้ลูกค้า", ("timestamp", "node_id"),
        ("customer_delivery", "delivery", "customer"), "needed", (
            Col("timestamp", "timestamp", "Asia/Bangkok", True, "The date for daily data; start of the hour for "
                "hourly data", "วันที่ (รายวัน) หรือวันเวลาเริ่มชั่วโมง (รายชั่วโมง)", "2026-03-02"),
            Col("node_id", "id", "", True, "EPANET customer node (one of the 28 in id_map), or the customer's meter "
                "or account number once it is listed in id_map", "รหัสจุดจ่ายน้ำในแบบจำลอง หรือเลขมาตรของลูกค้า",
                "MTP-IEAT3"),
            Col("volume_m3", "number", "m3", False, "Volume delivered in the interval", "ปริมาณน้ำที่จ่าย (ลบ.ม.)",
                "118500"),
            Col("reading_m3", "number", "m3", False, "Cumulative meter reading at the timestamp, if you have "
                "readings instead of volumes", "เลขอ่านมาตรสะสม (ลบ.ม.)", ""),
            Col("interval_min", "number", "min", True, "1440 for daily data, 60 for hourly",
                "ช่วงเวลาของข้อมูล (นาที): 60 หรือ 1440", "1440"),
            Col("meter_id", "text", "", False, "Customer meter, if a node has several meters", "หมายเลขมาตรน้ำ", ""),
            Col("customer_name", "text", "", False, "Customer name", "ชื่อลูกค้า", ""),
            Col("quality", "choice", "", False, "measured, or estimated (filled in or billed estimate)",
                "วัดจริง หรือ ประมาณการ", "measured", ("measured", "estimated")),
        )),
    "scada": Dataset(
        "scada_levels_pressures.csv", "SCADA levels and pressures", "ระดับน้ำและแรงดันจาก SCADA",
        ("timestamp", "point_id", "value"), ("scada", "level", "pressure"), "needed for model calibration", (
            Col("timestamp", "timestamp", "Asia/Bangkok", True, "Time of the reading (or start of the interval)",
                "วันเวลา (เวลาประเทศไทย)", "2026-03-02 09:00"),
            Col("point_id", "id", "", True, "EPANET node: NPL2_HT or NPL3_HT (head tanks), NPL_Res2, NPL_Res3 or "
                "R10885 (pump sources), or a junction ID for a pressure point",
                "รหัสจุดวัด (ถังพักน้ำ แหล่งน้ำ หรือจุดวัดแรงดัน)", "NPL2_HT"),
            Col("quantity", "choice", "", True, "level (tank or source water level) or pressure",
                "ชนิดค่าที่วัด: ระดับน้ำ หรือ แรงดัน", "level", ("level", "pressure")),
            Col("value", "number", "see unit", True, "The reading", "ค่าที่วัดได้", "18.4"),
            Col("unit", "choice", "", True, "level: m (above the tank floor) or m_msl (water surface elevation); "
                "pressure: m, bar, kPa, kg/cm2 or psi", "หน่วย", "m", ("m", "m_msl", "bar", "kPa", "kg/cm2", "psi")),
        )),
    "pump_register": Dataset(
        "pump_register.csv", "Pump register", "ทะเบียนเครื่องสูบน้ำ", ("pump_id", "status"), ("register",),
        "improves the result", (
            Col("pump_id", "id", "", True, "EPANET pump ID (pre-filled)", "รหัสเครื่องสูบน้ำ", "TM_Pond_03p"),
            Col("station_id", "id", "", False, "Pump station (pre-filled)", "สถานีสูบน้ำ", "TM_Pond"),
            Col("status", "choice", "", False, "Today's role: duty, standby, out_of_service or removed",
                "สถานะ: เครื่องหลัก / เครื่องสำรอง / ชำรุด / ถอดออก", "standby",
                ("duty", "standby", "out_of_service", "removed")),
            Col("rated_flow_m3_h", "number", "m3/h", False, "Nameplate flow", "อัตราการไหลตามพิกัด (ลบ.ม./ชม.)",
                "2160"),
            Col("rated_head_m", "number", "m", False, "Nameplate head", "เฮดตามพิกัด (ม.)", "106"),
            Col("rated_power_kw", "number", "kW", False, "Motor rating", "กำลังมอเตอร์ตามพิกัด (kW)", "900"),
            Col("pump_efficiency_pct", "number", "%", False, "Best efficiency from the pump curve",
                "ประสิทธิภาพเครื่องสูบตามพิกัด (%)", "82"),
            Col("motor_efficiency_pct", "number", "%", False, "Motor efficiency", "ประสิทธิภาพมอเตอร์ (%)", "95"),
            Col("vsd", "choice", "", False, "Variable-speed drive fitted: yes or no",
                "มีอุปกรณ์ปรับความเร็วรอบ (VSD) หรือไม่", "no", ("yes", "no")),
            Col("year_installed", "number", "year", False, "Year installed (Christian era)", "ปีที่ติดตั้ง (ค.ศ.)",
                "2008"),
            Col("last_overhaul", "date", "YYYY-MM-DD", False, "Last major overhaul", "วันที่ซ่อมบำรุงใหญ่ครั้งล่าสุด",
                "2024-11-15"),
            Col("model_curve", "text", "", False, "Pump curve in the model (pre-filled, do not edit)",
                "กราฟเครื่องสูบในแบบจำลอง (ไม่ต้องแก้ไข)", ""),
            Col("model_status", "text", "", False, "Status in the model (pre-filled, do not edit)",
                "สถานะในแบบจำลอง (ไม่ต้องแก้ไข)", ""),
            Col("notes", "text", "", False, "Anything we should know", "หมายเหตุ", ""),
        )),
    "pump_tests": Dataset(
        "pump_tests.csv", "Pump tests and efficiency", "ผลทดสอบประสิทธิภาพเครื่องสูบน้ำ",
        ("pump_id", "test_date", "flow_m3_h", "head_m", "power_kw"), ("pump_test", "efficiency"),
        "improves the result", (
            Col("pump_id", "id", "", True, "EPANET pump ID", "รหัสเครื่องสูบน้ำ", "NPL3-02p"),
            Col("test_date", "date", "YYYY-MM-DD", True, "Date of the test or reading", "วันที่ทดสอบ", "2025-11-20"),
            Col("flow_m3_h", "number", "m3/h", True, "Flow", "อัตราการไหล (ลบ.ม./ชม.)", "1650"),
            Col("head_m", "number", "m", True, "Total head: discharge minus suction pressure, in m", "เฮดรวม (ม.)",
                "112"),
            Col("power_kw", "number", "kW", True, "Electrical input power", "กำลังไฟฟ้าขาเข้า (kW)", "730"),
            Col("efficiency_pct", "number", "%", False, "Wire-to-water efficiency, if you calculated it",
                "ประสิทธิภาพรวม (%)", "69"),
            Col("speed_pct", "number", "%", False, "Speed (100 = full speed)", "ความเร็วรอบ (%)", "100"),
            Col("source", "text", "", False, "site test, manufacturer curve or SCADA reading", "ที่มาของข้อมูล",
                "site test"),
        )),
    "confirmations": Dataset(
        "confirmations.csv", "Confirmations", "ข้อมูลที่ขอให้ยืนยัน", ("question_id", "answer"), ("confirmation",),
        "needed", (
            Col("question_id", "text", "", True, "Question number (pre-filled)", "รหัสคำถาม", "Q1"),
            Col("topic", "text", "", False, "Topic (pre-filled)", "หัวข้อ", ""),
            Col("topic_th", "text", "", False, "Topic in Thai (pre-filled)", "หัวข้อ (ภาษาไทย)", ""),
            Col("question", "text", "", False, "The question (pre-filled)", "คำถาม", ""),
            Col("model_value", "text", "", False, "What the model has now (pre-filled)", "ค่าในแบบจำลอง", ""),
            Col("answer", "text", "", False, "Your answer", "คำตอบ", ""),
            Col("answered_by", "text", "", False, "Name and role", "ผู้ตอบ", ""),
            Col("answer_date", "date", "YYYY-MM-DD", False, "Date of the answer", "วันที่ตอบ", ""),
        )),
}
NEEDED = ["pump_operation", "customer_delivery"]          # plus station energy or bills, and the tariff
ALIASES = {
    "timestamp": ("datetime", "date_time", "time_stamp", "date", "time"),
    "pump_id": ("pump", "pump_tag", "pump_name"),
    "pumps_running": ("running", "run_status", "on_off", "pumps_on"),
    "flow_m3_h": ("flow", "flow_m3h", "flow_cmh"),
    "power_kw": ("power", "kw"),
    "kwh": ("energy_kwh", "kwh_total"),
    "volume_m3": ("volume", "volume_m", "delivered_m3"),
    "node_id": ("node", "customer_node"),
    "point_id": ("point", "tag"),
    "station_id": ("station",),
    "meter_id": ("meter", "ca", "ca_number", "meter_no"),
    "interval_min": ("interval", "interval_minutes"),
}


# ------------------------------------------------------------------ the model

def read_model(inp=DEFAULT_INP):
    """Pumps (with station, curve and what they connect), tanks, reservoirs and customer nodes, from the .inp."""
    rows, sec = {}, None
    for line in Path(inp).read_text(encoding="utf-8", errors="replace").splitlines():
        body, _, note = line.partition(";")
        body = body.strip()
        if body.startswith("["):
            sec = body.upper()
            rows.setdefault(sec, [])
        elif body and sec:
            rows[sec].append((body.split(), note.strip()))

    def get(s):
        return rows.get(s, [])

    units = next((f[1].upper() for f, _ in get("[OPTIONS]") if f[0].lower() == "units" and len(f) > 1), "CMD")
    to_m3h = FLOW_TO_M3H.get(units, 1 / 24)
    eff = next((float(f[2]) for f, _ in get("[ENERGY]") if len(f) > 2 and f[0].lower() == "global"
                and f[1].lower() == "efficiency"), 75.0)
    junc = pd.DataFrame([dict(id=f[0], elevation_m=float(f[1]), base_demand_m3_day=float(f[2]) * to_m3h * 24
                              if len(f) > 2 else 0.0, note=n) for f, n in get("[JUNCTIONS]")]).set_index("id")
    tanks = pd.DataFrame([dict(id=f[0], elevation_m=float(f[1]), init_level_m=float(f[2]), min_level_m=float(f[3]),
                               max_level_m=float(f[4]), diameter_m=float(f[5]))
                          for f, _ in get("[TANKS]")]).set_index("id")
    resv = pd.DataFrame([dict(id=f[0], head_m=float(f[1])) for f, _ in get("[RESERVOIRS]")]).set_index("id")
    status = {f[0]: f[1].capitalize() for f, _ in get("[STATUS]") if len(f) > 1}
    curves = {}
    for f, _ in get("[CURVES]"):
        curves.setdefault(f[0], []).append((float(f[1]) * to_m3h, float(f[2])))

    # Connectivity without pumps, to say which source and tank each pump links
    adj = {}
    closed = {k for k, v in status.items() if v == "Closed"}
    for f, _ in get("[PIPES]") + get("[VALVES]"):
        if f[0] in closed or (len(f) > 7 and f[7].lower() == "closed"):
            continue
        adj.setdefault(f[1], []).append(f[2])
        adj.setdefault(f[2], []).append(f[1])
    ends = set(tanks.index) | set(resv.index)

    def reach(start):
        seen, todo, found = {start}, [start], set()
        while todo:
            n = todo.pop()
            if n in ends:
                found.add(n)
                continue
            for m in adj.get(n, ()):
                if m not in seen:
                    seen.add(m)
                    todo.append(m)
        return " + ".join(sorted(found))

    pumps = []
    for f, _ in get("[PUMPS]"):
        kw = dict(zip([k.upper() for k in f[3::2]], f[4::2]))
        curve = kw.get("HEAD", "")
        pts = curves.get(curve, [])
        if len(pts) == 1:
            q, h = pts[0]
            text, qmax = f"{curve}: {q:,.0f} m3/h at {h:g} m (single point)", 2 * q
        elif pts:
            text = (f"{curve}: {len(pts)} points, {pts[0][0]:,.0f}-{pts[-1][0]:,.0f} m3/h, "
                    f"{pts[0][1]:g}-{pts[-1][1]:g} m")
            qmax = pts[-1][0]
        else:
            text, qmax = f"POWER {kw.get('POWER', '?')} kW" if "POWER" in kw else "", np.nan
        pumps.append(dict(id=f[0], station_id=station_of(f[0]), curve=curve, curve_text=text, max_flow_m3_h=qmax,
                          model_status=status.get(f[0], "Open"), source=reach(f[1]), delivers_to=reach(f[2])))
    pumps = pd.DataFrame(pumps).set_index("id").sort_index()
    order = list(dict.fromkeys(station_of(f[0]) for f, _ in get("[PUMPS]")))
    stations = pd.DataFrame({"n_pumps": pumps.groupby("station_id").size()}).loc[order]
    stations["pumps"] = [", ".join(pumps.index[pumps.station_id == s]) for s in stations.index]
    cust = junc[junc["base_demand_m3_day"] > 0].copy()
    return dict(inp=Path(inp), units=units, pump_efficiency_pct=eff, pumps=pumps, stations=stations, tanks=tanks,
                reservoirs=resv, customers=cust, junctions=junc,
                elements=dict(pump=list(pumps.index), station=list(stations.index), tank=list(tanks.index),
                              reservoir=list(resv.index), customer=list(cust.index), junction=list(junc.index)))


def station_of(pump_id):
    """Station ID from a pump ID: NPL2-01p -> NPL2, TM_Pond_03p -> TM_Pond."""
    return re.sub(r"[-_ ]?\d+p?$", "", pump_id)


def id_key(s):
    """Loose key for matching IDs: case, separators and leading zeros ignored, a pump's trailing 'p' dropped."""
    tokens = re.findall(r"[A-Za-z]+|\d+", str(s))
    if len(tokens) >= 2 and tokens[-1].lower() == "p" and tokens[-2].isdigit():
        tokens = tokens[:-1]
    return "".join((t.lstrip("0") or "0") if t.isdigit() else t.upper() for t in tokens)


class Ids:
    """Maps received IDs to EPANET IDs: the exact ID, then a tag from the client's id_map, then a loose match."""

    def __init__(self, model):
        self.kinds = {}
        for kind, ids in model["elements"].items():
            for i in ids:
                self.kinds.setdefault(i, set()).add(kind)
        self.upper = {}
        self.loose = {}
        for i in self.kinds:
            self.upper.setdefault(i.upper(), set()).add(i)
            self.loose.setdefault(id_key(i), set()).add(i)
        self.client = {}

    def one(self, value, kinds):
        """(EPANET ID or None, how it was matched)."""
        v = str(value).strip()

        def pick(cands):
            c = [i for i in cands if self.kinds[i] & set(kinds)]
            return c[0] if len(c) == 1 else None

        if v in self.kinds and self.kinds[v] & set(kinds):
            return v, "exact"
        if (hit := pick(self.upper.get(v.upper(), ()))) is not None:
            return hit, "case"
        hit = self.client.get(v.lower())
        if hit is not None and self.kinds.get(hit, set()) & set(kinds):
            return hit, "id_map"
        if (hit := pick(self.loose.get(id_key(v), ()))) is not None:
            return hit, "loose"
        return None, "unmapped"

    def map(self, values, kinds):
        uniq = {v: self.one(v, kinds) for v in pd.unique(values.dropna())}
        ids = values.map(lambda v: uniq.get(v, (None, ""))[0])
        how = values.map(lambda v: uniq.get(v, (None, "missing"))[1])
        return ids, how


# ------------------------------------------------------------------ reading files

def read_tables(path):
    """(label, table of text, file line of each row, has a SAMPLE note) for a .csv or for each sheet of an .xlsx."""
    out = []
    if path.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        for sheet, raw in pd.read_excel(path, sheet_name=None, header=None, dtype=str).items():
            raw = raw.fillna("")
            first = raw.iloc[:, 0].astype(str).str.lstrip()
            note = first.str.startswith("#")
            sample = raw[note].apply(lambda r: "SAMPLE" in " ".join(r), axis=1).any()
            raw = raw[~note & (raw != "").any(axis=1)]
            if len(raw) < 1:
                continue
            t = raw.iloc[1:].copy()
            t.columns = [str(c) for c in raw.iloc[0]]
            out.append((f"{path.name}[{sheet}]", t.reset_index(drop=True), list(raw.index[1:] + 1), sample))
        return out
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp874"):          # cp874 = Thai Windows, what Excel writes for "CSV" on a Thai PC
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("latin-1")
    kept, sample = [], False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            sample |= "SAMPLE" in line
        elif line.strip().strip(",;\t"):
            kept.append((n, line))
    if not kept:
        return out
    head = kept[0][1]
    sep = max([",", ";", "\t"], key=head.count)
    t = pd.read_csv(io.StringIO("\n".join(line for _, line in kept)), sep=sep, dtype=str, keep_default_na=False,
                    skipinitialspace=True)
    lines = [n for n, _ in kept[1:]]
    out.append((path.name, t, lines if len(lines) == len(t) else list(range(2, len(t) + 2)), sample))
    return out


def norm_col(c):
    c = str(c).replace("³", "3").replace("²", "2").strip().lower()
    return re.sub(r"[^0-9a-z]+", "_", c).strip("_")


def canon_columns(columns, key):
    """Template column names for a dataset, from what the file calls them."""
    names = [c.name for c in SCHEMA[key].cols]
    cols = [norm_col(c) for c in columns]
    out = []
    for c in cols:
        if c not in names:
            c = next((k for k, al in ALIASES.items() if c in al and k in names and k not in cols), c)
        out.append(c)
    return out


def detect(label, columns):
    """The dataset a table belongs to: all its signature columns present; ties go to the file name, then to the
    dataset with more of its columns present."""
    best, best_score = None, None
    name = label.lower()
    for key, ds in SCHEMA.items():
        cols = canon_columns(columns, key)
        if not set(ds.signature) <= set(cols):
            continue
        score = (any(h in name for h in ds.hint), len(ds.signature), len(set(cols) & {c.name for c in ds.cols}))
        if best_score is None or score > best_score:
            best, best_score = key, score
    if best is None:
        guess = next((k for k, ds in SCHEMA.items() if any(h in name for h in ds.hint)), None)
        return None, guess
    return best, None


# ------------------------------------------------------------------ parsing values

ISO_RE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?\s*(?:Z|[+-]\d{2}:?\d{2})?$")
TZ_RE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")
DMY_RE = re.compile(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$")


def parse_times(s):
    """Thai wall-clock times (tz-naive) from ISO text with or without a UTC offset, day/month/year text (the Thai
    convention; Buddhist-era years are converted) or Excel serial numbers. Returns the times and counts of what was
    converted."""
    s = s.fillna("").astype(str).str.strip()
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    counts = {}
    iso = s.str.match(ISO_RE)
    year = pd.to_numeric(s.str[:4].where(iso), errors="coerce")
    be = iso & (year > 2400)
    if be.any():
        s = s.copy()
        s[be] = (year[be] - 543).astype(int).astype(str) + s[be].str[4:]
        counts["Buddhist-era years converted to AD"] = int(be.sum())
    tz = iso & s.str.contains(TZ_RE)
    if tz.any():
        t = pd.to_datetime(s[tz], format="ISO8601", utc=True, errors="coerce")
        out.loc[t.index] = t.dt.tz_convert(BKK).dt.tz_localize(None).astype("datetime64[ns]").values
        off = s[tz].str.extract(r"(Z|[+-]\d{2}:?\d{2})$")[0].str.replace(":", "")
        if (off != "+0700").any():
            counts["times with another UTC offset converted to Thai time"] = int((off != "+0700").sum())
    plain = iso & ~tz
    if plain.any():
        t = pd.to_datetime(s[plain], format="ISO8601", errors="coerce")
        out.loc[t.index] = t.astype("datetime64[ns]").values
    m = s[~iso].str.extract(DMY_RE)
    m = m[m[0].notna()].astype(float)
    if len(m):
        yr = m[2].where(m[2] < 2400, m[2] - 543)
        if (m[2] > 2400).any():
            counts["Buddhist-era years converted to AD"] = counts.get("Buddhist-era years converted to AD", 0) + int(
                (m[2] > 2400).sum())
        parts = pd.DataFrame({"year": yr, "month": m[1], "day": m[0], "hour": m[3].fillna(0), "minute": m[4].fillna(0),
                              "second": m[5].fillna(0)})
        out.loc[m.index] = pd.to_datetime(parts, errors="coerce").astype("datetime64[ns]").values
        counts["dates read as day/month/year"] = len(m)
    num = pd.to_numeric(s.where(~iso & ~s.index.isin(m.index)), errors="coerce")
    serial = num.between(20000, 80000)
    if serial.any():
        t = pd.to_datetime(num[serial], unit="D", origin="1899-12-30").dt.round("s")
        out.loc[t.index] = t.astype("datetime64[ns]").values
        counts["Excel serial dates converted"] = int(serial.sum())
    return out, counts


def to_number(s):
    """Numbers from text; thousands separators and spaces are ignored."""
    t = s.fillna("").astype(str).str.strip().str.replace(",", "", regex=False).str.replace(" ", "", regex=False)
    return pd.to_numeric(t, errors="coerce")


def hhmm(s):
    """Minutes after midnight from HH:MM (24:00 allowed) or an Excel time fraction."""
    s = s.fillna("").astype(str).str.strip()
    m = s.str.extract(r"^(\d{1,2}):(\d{2})(?::\d{2})?$").astype(float)
    mins = m[0] * 60 + m[1]
    frac = pd.to_numeric(s, errors="coerce")
    mins = mins.where(mins.notna(), (frac * 1440).round().where(frac.between(0, 1)))
    return mins.where(mins.between(0, 1440))


def window_mask(start, end):
    """Minutes of the day inside [start, end); windows may wrap past midnight; start == end means all day."""
    minute = np.arange(1440)
    if start == end:
        return np.ones(1440, bool)
    if start < end:
        return (minute >= start) & (minute < end)
    return (minute >= start) | (minute < end)


# ------------------------------------------------------------------ tariff

class Tariff:
    """Electricity prices by meter, date and hour, from tariff rows (component, day type, time window, rate)."""

    def __init__(self, rows, holidays=(), name="Eastwater tariff"):
        r = rows.copy()
        for c in ("valid_from", "valid_to"):
            r[c] = pd.to_datetime(r[c], errors="coerce")
        r["start_min"] = hhmm(r["start_time"]) if "start_time" in r else np.nan
        r["end_min"] = hhmm(r["end_time"]) if "end_time" in r else np.nan
        r["meter_id"] = r["meter_id"].fillna("ALL").astype(str)
        self.rows = r.reset_index(drop=True)
        self.holidays = {pd.Timestamp(d).date() for d in holidays}
        self.name = name
        self._cache = {}

    def day_type(self, date):
        if date in self.holidays:
            return "holiday"
        return "weekend" if date.weekday() >= 5 else "weekday"

    def _rows(self, meter, component, date):
        r, day = self.rows, pd.Timestamp(date)
        r = r[(r["component"] == component) & (r["valid_from"] <= day)
              & (r["valid_to"].isna() | (r["valid_to"] >= day))]
        own = r[r["meter_id"] == str(meter)]
        return own if len(own) else r[r["meter_id"].str.upper() == "ALL"]

    def _windows(self, meter, component, date):
        """Rows for the day's type; holidays without rows of their own are priced like weekends."""
        r = self._rows(meter, component, date)
        dtype = self.day_type(date)
        if dtype == "holiday" and not (r["day_type"] == "holiday").any():
            dtype = "weekend"
        return r[r["day_type"].isin([dtype, "all"])]

    def minute_rates(self, meter, component, date):
        """Rate for each minute of the day (NaN where no window applies) and how many windows cover each minute."""
        r = self._windows(meter, component, date)
        total, count = np.zeros(1440), np.zeros(1440, int)
        for s, e, v in zip(r["start_min"], r["end_min"], r["rate"]):
            mask = window_mask(0 if pd.isna(s) else int(s), 1440 if pd.isna(e) else int(e))
            total[mask] += v
            count[mask] += 1
        return np.where(count > 0, total / np.maximum(count, 1), np.nan), count

    def energy(self, meter, date):
        """THB/kWh for each hour (hourly mean of the minute rates; NaN if part of the hour has no rate)."""
        key = ("energy", meter, date)
        if key not in self._cache:
            self._cache[key] = self.minute_rates(meter, "energy", date)[0].reshape(24, 60).mean(axis=1)
        return self._cache[key]

    def ft(self, meter, date):
        return float(self._rows(meter, "ft", date)["rate"].sum())

    def service(self, meter, date):
        return float(self._rows(meter, "service", date)["rate"].sum())

    def vat(self, date):
        r = self._rows("ALL", "vat", date)
        return float(r["rate"].iloc[0]) if len(r) else np.nan

    def demand(self, meter, date):
        """[(window name, THB/kW, 24 booleans: hour at least half inside the window)] for the day."""
        key = ("demand", meter, date)
        if key not in self._cache:
            r = self._windows(meter, "demand", date)
            out = []
            for row in r.itertuples():
                s = 0 if pd.isna(row.start_min) else int(row.start_min)
                e = 1440 if pd.isna(row.end_min) else int(row.end_min)
                name = (row.period_name if isinstance(getattr(row, "period_name", None), str) and row.period_name
                        else f"{s // 60:02d}:{s % 60:02d}-{e // 60:02d}:{e % 60:02d}")
                out.append((name, float(row.rate), window_mask(s, e).reshape(24, 60).mean(axis=1) >= 0.5))
            self._cache[key] = out
        return self._cache[key]


# ------------------------------------------------------------------ the run

class Run:
    """Flags, notes and statistics collected while loading, for flags.csv and the validation report."""

    def __init__(self, model):
        self.model = model
        self.ids = Ids(model)
        self.flags = []
        self.raw = {}
        self.notes = {k: [] for k in SCHEMA}
        self.stats = {k: dict(files=[], rows_in=0, rows_kept=0, period="", coverage="") for k in SCHEMA}
        self.matches = []
        self.unread = []

    def flag(self, key, idx, column, issue, action):
        """One flag per row in idx; issue may be a string or a Series of per-row text."""
        raw = self.raw[key]
        for i in idx:
            r = raw.loc[i]
            self.flags.append(dict(dataset=key, file=r["_file"], line=r["_row"], column=column,
                                   value=r[column] if column in raw else "",
                                   issue=issue if isinstance(issue, str) else issue.loc[i], action=action))

    def note(self, key, text):
        self.notes[key].append(text)

    def map_col(self, key, d, column, kinds):
        """EPANET IDs for a column; rows that cannot be mapped are flagged (and should be dropped by the caller)."""
        ids, how = self.ids.map(d[column], kinds)
        for (v, h, e), n in pd.DataFrame({"v": d[column], "h": how, "e": ids}).value_counts(dropna=False).items():
            if h not in ("exact", "missing"):
                self.matches.append(dict(dataset=key, column=column, received=v, epanet_id=e if h != "unmapped" else "",
                                         how=h, rows=int(n)))
        bad = ids.isna() & d[column].notna()
        self.flag(key, d.index[bad], column, f"not a {' or '.join(kinds)} ID in the model or id_map", "row removed")
        return ids


def prepare(run, key, parts):
    """Stack one dataset's tables with template column names and typed values; flag unreadable values and drop rows
    missing a required one."""
    spec = SCHEMA[key]
    frames = []
    for label, t, lines, _ in parts:
        t = t.copy()
        t.columns = canon_columns(t.columns, key)
        t = t.loc[:, ~t.columns.duplicated()]
        extra = [c for c in t.columns if c not in {c.name for c in spec.cols}]
        if extra:
            run.note(key, f"`{label}`: columns not in the template, ignored: {', '.join(extra)}")
        t["_file"], t["_row"] = label, lines
        frames.append(t)
    d = pd.concat(frames, ignore_index=True).fillna("")
    for c in spec.cols:
        if c.name not in d:
            d[c.name] = ""
    run.raw[key] = d.copy()
    run.stats[key]["rows_in"] = len(d)
    out = d[["_file", "_row"]].copy()
    for c in spec.cols:
        raw = d[c.name].astype(str).str.strip()
        blank = raw.str.lower().isin(MISSING)
        if c.kind in ("timestamp", "date"):
            v, counts = parse_times(raw.where(~blank, ""))
            for what, n in counts.items():
                run.note(key, f"{c.name}: {n:,} {what}")
            if c.kind == "date":
                v = v.dt.normalize()
        elif c.kind == "number":
            v = to_number(raw.where(~blank, ""))
        elif c.kind == "time":
            v = raw.where(~blank)
            bad_t = ~blank & hhmm(raw).isna()
            run.flag(key, d.index[bad_t], c.name, "not a time HH:MM", "value removed")
            v = v.where(~bad_t)
        elif c.kind == "choice":
            lookup = {x.lower(): x for x in c.choices}
            v = raw.str.lower().map(lookup)
        else:
            v = raw.where(~blank)
        bad = ~blank & v.isna()
        if c.kind != "time":
            what = {"timestamp": "unreadable date/time", "date": "unreadable date", "number": "not a number",
                    "choice": f"not one of {', '.join(c.choices)}"}.get(c.kind)
            if what:
                run.flag(key, d.index[bad], c.name, what, "row removed" if c.required else "value removed")
        out[c.name] = v
    req = [c.name for c in spec.cols if c.required]
    missing = out[req].isna()
    for c in req:
        only_blank = missing[c] & d[c].astype(str).str.strip().str.lower().isin(MISSING)
        run.flag(key, d.index[only_blank], c, f"{c} is blank", "row removed")
    return out[~missing.any(axis=1)].copy()


def coverage(times, step, start, end):
    """Share of the expected intervals present between start and end, and the longest run of missing ones."""
    grid = pd.date_range(start, end, freq=step)
    if len(grid) == 0:
        return np.nan, 0
    present = grid.isin(pd.DatetimeIndex(times.unique()))
    gap = pd.Series(~present)
    runs = gap.groupby((gap != gap.shift()).cumsum()).sum()
    return present.mean(), int(runs.max()) if len(runs) else 0


def drop_duplicates(run, key, d, keys, values):
    """Keep the first of rows with the same key; flag the rest, as conflicting if any value differs."""
    dup = d.duplicated(keys, keep="first")
    if dup.any():
        first = d[~dup].set_index(keys)[values]
        later = d[dup].set_index(keys)[values]
        conflict = ~((first.reindex(later.index).fillna(-1e30).values == later.fillna(-1e30).values).all(axis=1))
        issue = pd.Series(np.where(conflict, "duplicate with different values (first kept)", "exact duplicate"),
                          index=d.index[dup])
        run.flag(key, d.index[dup], keys[-1], issue, "row removed")
        run.note(key, f"{int(dup.sum()):,} duplicate rows removed ({int(conflict.sum()):,} with different values)")
    return d[~dup]


def period_text(t):
    t = pd.to_datetime(t).dropna()
    return f"{t.min():%Y-%m-%d} to {t.max():%Y-%m-%d}" if len(t) else ""


# ------------------------------------------------------------------ datasets

def load_id_map(run, d):
    key = "id_map"
    d = d[d["client_tag"].notna()].copy()
    if d.empty:
        return d
    all_kinds = tuple(run.model["elements"])
    d["epanet_id"] = run.map_col(key, d, "epanet_id", all_kinds)
    d = d.dropna(subset=["epanet_id"])
    tag = d["client_tag"].str.strip().str.lower()
    clash = tag.map(d.groupby(tag)["epanet_id"].nunique()) > 1
    run.flag(key, d.index[clash], "client_tag", "same tag given for different EPANET IDs", "row removed")
    d = d[~clash]
    for t, e in zip(d["client_tag"], d["epanet_id"]):
        run.ids.client[t.strip().lower()] = e
    run.stats[key]["coverage"] = f"{d['epanet_id'].nunique()} model IDs, {len(d)} tags"
    return d.drop_duplicates(["client_tag", "epanet_id"])


def load_pump_operation(run, d):
    key, m = "pump_operation", run.model
    d["pump_id"] = run.map_col(key, d, "pump_id", ("pump", "station"))
    d = d.dropna(subset=["pump_id"]).copy()
    is_pump = d["pump_id"].isin(m["pumps"].index)
    d["level"] = np.where(is_pump, "pump", "station")
    d["station_id"] = d["pump_id"].map(m["pumps"]["station_id"]).fillna(d["pump_id"])
    d["interval_min"] = d["interval_min"].fillna(60)
    bad = ~d["interval_min"].isin([1, 5, 10, 15, 20, 30, 60])
    run.flag(key, d.index[bad], "interval_min", "interval must be 1-60 minutes and divide the hour", "row removed")
    d = d[~bad]
    neither = d["pumps_running"].isna() & d["flow_m3_h"].isna()
    run.flag(key, d.index[neither], "pumps_running", "neither pumps_running nor flow_m3_h given", "row removed")
    d = d[~neither].copy()
    is_pump = d["level"] == "pump"

    for c, lo in (("flow_m3_h", "flow"), ("power_kw", "power"), ("speed_pct", "speed")):
        neg = d[c] < 0
        run.flag(key, d.index[neg], c, f"negative {lo}", "value removed")
        d.loc[neg, c] = np.nan
    # A single pump with flow but no status: running when the flow is above 10% of its usual running flow
    infer = is_pump & d["pumps_running"].isna() & d["flow_m3_h"].notna()
    if infer.any():
        typical = d[d["flow_m3_h"] > 0].groupby("pump_id")["flow_m3_h"].median()
        thr = d.loc[infer, "pump_id"].map(0.1 * typical).fillna(np.inf)
        d.loc[infer, "pumps_running"] = (d.loc[infer, "flow_m3_h"] > thr).astype(float)
        run.note(key, f"pumps_running inferred from flow on {int(infer.sum()):,} rows (on = flow above 10% of the "
                      "pump's usual running flow)")
    st_rows = d["level"] == "station"
    if st_rows.any() and d.loc[st_rows, "pumps_running"].isna().any():
        n = int(d.loc[st_rows, "pumps_running"].isna().sum())
        run.note(key, f"{n:,} station rows have flow but no pump count; they give flow only")
    cap = np.where(is_pump, 1.0, d["station_id"].map(m["stations"]["n_pumps"]).astype(float))
    over = (d["pumps_running"] > cap + 1e-9) | (d["pumps_running"] < 0)
    run.flag(key, d.index[over], "pumps_running", pd.Series(
        [f"pumps_running {v:g} outside 0-{c:g}" for v, c in zip(d.loc[over, "pumps_running"], cap[over.values])],
        index=d.index[over]), "value removed")
    d.loc[over, "pumps_running"] = np.nan
    qmax = np.where(is_pump, d["pump_id"].map(m["pumps"]["max_flow_m3_h"]),
                    d["station_id"].map(m["pumps"].groupby("station_id")["max_flow_m3_h"].sum()))
    high = d["flow_m3_h"] > 1.5 * qmax
    run.flag(key, d.index[high], "flow_m3_h", "flow above 1.5x the largest flow on the model's pump curve", "kept")
    high_p = d["power_kw"] > 3000 * cap
    run.flag(key, d.index[high_p], "power_kw", "power above 3,000 kW per pump", "kept")
    run_q = d[is_pump & (d["pumps_running"] >= 0.99) & (d["flow_m3_h"] > 0)].groupby("pump_id")["flow_m3_h"].median()
    off_flow = is_pump & (d["pumps_running"] == 0) & (d["flow_m3_h"] > 0.05 * d["pump_id"].map(run_q).fillna(np.inf))
    run.flag(key, d.index[off_flow], "flow_m3_h", "flow while the pump is recorded off", "kept")
    on_noflow = is_pump & (d["pumps_running"] > 0) & (d["flow_m3_h"] == 0)
    run.flag(key, d.index[on_noflow], "flow_m3_h", "pump recorded running with zero flow", "kept")

    d = drop_duplicates(run, key, d, ["pump_id", "timestamp"], ["pumps_running", "flow_m3_h", "power_kw"])
    mis = (d["timestamp"].dt.minute % d["interval_min"].astype(int) != 0) | (d["timestamp"].dt.second != 0)
    if mis.any():
        run.note(key, f"{int(mis.sum()):,} timestamps not on an interval boundary; moved to the start of the interval")
        d.loc[mis, "timestamp"] = d.loc[mis, "timestamp"].dt.floor("min") - pd.to_timedelta(
            d.loc[mis, "timestamp"].dt.minute % d.loc[mis, "interval_min"].astype(int), unit="min")
    d["hour"] = d["timestamp"].dt.floor("h")
    h = (d.groupby(["pump_id", "hour"])
          .agg(station_id=("station_id", "first"), level=("level", "first"), pumps_running=("pumps_running", "mean"),
               flow_m3_h=("flow_m3_h", "mean"), power_kw=("power_kw", "mean"), speed_pct=("speed_pct", "mean"),
               minutes=("interval_min", "sum"))
          .reset_index().rename(columns={"hour": "timestamp"}))
    h["coverage"] = (h.pop("minutes") / 60).clip(upper=1).round(3)
    if (d["interval_min"] < 60).any():
        run.note(key, f"sub-hourly readings averaged to hours ({int((h['coverage'] < 1).sum()):,} hours only "
                      "partly covered)")

    start, end = h["timestamp"].min(), h["timestamp"].max()
    cov = {p: coverage(g["timestamp"], "h", start, end) for p, g in h.groupby("pump_id")}
    pumps_seen = [p for p in m["pumps"].index if p in cov]
    unseen = [p for p in m["pumps"].index if p not in cov and m["pumps"].loc[p, "station_id"] not in set(h["pump_id"])]
    if unseen:
        run.note(key, f"no data for {', '.join(unseen)}")
    n_hours = len(pd.date_range(start, end, freq="h"))
    low = {p: c for p, c in cov.items() if c[0] < 1}
    for p, (share, gap) in sorted(low.items()):
        run.note(key, f"{p}: {round((1 - share) * n_hours)} of {n_hours} hours missing, longest gap {gap} h")
    run.stats[key]["gaps"] = len(low)
    stations = sorted(set(h.loc[h["level"] == "station", "pump_id"]))
    both = [s for s in stations if s in set(h.loc[h["level"] == "pump", "station_id"])]
    if both:
        run.note(key, f"{', '.join(both)}: per-pump and station rows both given; per-pump rows are used")
    missing = sum(round((1 - c[0]) * n_hours) for c in cov.values())
    run.stats[key].update(period=period_text(h["timestamp"]), coverage=(
        f"{len(pumps_seen)}/{len(m['pumps'])} pumps" + (f" + stations {', '.join(stations)}" if stations else "")
        + f", {n_hours} h, {missing} pump-hours missing"))
    return h[["timestamp", "station_id", "pump_id", "level", "pumps_running", "flow_m3_h", "power_kw", "speed_pct",
              "coverage"]].sort_values(["timestamp", "pump_id"])


def map_stations(run, key, d):
    """Station IDs for a column that may join several stations with +, in the model's station order."""
    order = list(run.model["stations"].index)
    parts = d["station_id"].fillna("").str.split("+")
    flat = pd.Series([p.strip() for ps in parts for p in ps if p.strip()])
    ids, how = run.ids.map(flat, ("station",))
    lookup = dict(zip(flat, ids))
    for v, h, e in set(zip(flat, how, ids)):
        if h not in ("exact",):
            run.matches.append(dict(dataset=key, column="station_id", received=v, epanet_id=e or "", how=h,
                                    rows=int((flat == v).sum())))

    def one(ps):
        got = [lookup.get(p.strip()) for p in ps if p.strip()]
        if not got or any(g is None for g in got):
            return None
        return "+".join(sorted(set(got), key=order.index))

    out = parts.map(one)
    bad = out.isna()
    run.flag(key, d.index[bad], "station_id", "not a station in the model (NPL2, NPL3, TM_Pond)", "row removed")
    return out


def load_station_energy(run, d):
    key, m = "station_energy", run.model
    d["station_id"] = map_stations(run, key, d)
    d = d.dropna(subset=["station_id"]).copy()
    bad = ~d["interval_min"].isin([5, 10, 15, 30, 60, 1440])
    run.flag(key, d.index[bad], "interval_min", "interval must be 5, 10, 15, 30, 60 or 1440 minutes", "row removed")
    d = d[~bad].copy()
    neg = d["kwh"] < 0
    run.flag(key, d.index[neg], "kwh", "negative energy", "row removed")
    d = d[~neg].copy()
    n_pumps = d["station_id"].map(lambda s: sum(m["stations"].loc[x, "n_pumps"] for x in s.split("+")))
    kw = d["kwh"] / (d["interval_min"] / 60)
    high = kw > 2000 * n_pumps
    run.flag(key, d.index[high], "kwh", "average power above 2,000 kW per installed pump", "kept")
    many = d.groupby("meter_id")["station_id"].transform("nunique") > 1
    run.flag(key, d.index[many], "station_id", "meter listed with different stations; first used", "kept")
    d["station_id"] = d.groupby("meter_id")["station_id"].transform("first")
    d = drop_duplicates(run, key, d, ["meter_id", "timestamp"], ["kwh"])
    daily = d["interval_min"] == 1440
    mis = (daily & (d["timestamp"] != d["timestamp"].dt.normalize())) | (
        ~daily & (d["timestamp"].dt.minute % d["interval_min"].where(~daily, 1).astype(int) != 0))
    if mis.any():
        run.note(key, f"{int(mis.sum()):,} timestamps not on an interval boundary (daily rows should be dates)")
    cov = []
    for meter, g in d.groupby("meter_id"):
        step = f"{int(g['interval_min'].min())}min"
        share, gap = coverage(g["timestamp"], step, g["timestamp"].min(), g["timestamp"].max())
        res = "daily" if g["interval_min"].min() == 1440 else f"{int(g['interval_min'].min())}-min"
        cov.append(f"{meter} ({g['station_id'].iloc[0]}): {res}, {share:.1%}")
        if share < 1:
            n = len(pd.date_range(g["timestamp"].min(), g["timestamp"].max(), freq=step))
            run.note(key, f"meter {meter}: {round((1 - share) * n)} of {n} intervals missing, longest gap {gap}")
            run.stats[key]["gaps"] = run.stats[key].get("gaps", 0) + 1
    uncovered = [s for s in m["stations"].index if not any(s in x.split("+") for x in d["station_id"].unique())]
    if uncovered:
        run.note(key, f"no meter data for station(s) {', '.join(uncovered)}")
        run.stats[key]["gaps"] = run.stats[key].get("gaps", 0) + len(uncovered)
    run.stats[key].update(period=period_text(d["timestamp"]), coverage="; ".join(cov))
    return d[["timestamp", "meter_id", "station_id", "interval_min", "kwh", "kw_max"]].sort_values(
        ["meter_id", "timestamp"])


def load_bills(run, d):
    key = "electricity_bills"
    d["station_id"] = map_stations(run, key, d)
    d = d.dropna(subset=["station_id"]).copy()
    back = d["period_end"] < d["period_start"]
    run.flag(key, d.index[back], "period_end", "period ends before it starts", "row removed")
    d = d[~back].copy()
    nums = [c.name for c in SCHEMA[key].cols if c.kind == "number"]
    for c in nums:
        if c.endswith("_charge_thb"):        # credits may be negative
            continue
        neg = d[c] < 0
        run.flag(key, d.index[neg], c, "negative value", "value removed")
        d.loc[neg, c] = np.nan

    def off(a, b, tol_rel, tol_abs=1.0):
        return (a - b).abs() > np.maximum(tol_rel * b.abs(), tol_abs)

    parts = d[["kwh_on_peak", "kwh_off_peak"]]
    have = parts.notna().all(axis=1)
    bad = have & off(parts.sum(axis=1), d["kwh_total"], 0.005)
    run.flag(key, d.index[bad], "kwh_total", "on-peak + off-peak kWh differs from kwh_total by > 0.5%", "kept")
    charges = d[["energy_charge_thb", "demand_charge_thb", "ft_charge_thb", "service_charge_thb", "pf_charge_thb",
                 "other_charge_thb"]]
    have = charges[["energy_charge_thb"]].notna().all(axis=1) & d["total_ex_vat_thb"].notna()
    bad = have & off(charges.sum(axis=1, min_count=1), d["total_ex_vat_thb"], 0.01)
    run.flag(key, d.index[bad], "total_ex_vat_thb", "charges do not add up to total_ex_vat_thb (> 1%)", "kept")
    have = d[["total_ex_vat_thb", "vat_thb", "total_thb"]].notna().all(axis=1)
    bad = have & off(d["total_ex_vat_thb"] + d["vat_thb"], d["total_thb"], 0.0, 2.0)
    run.flag(key, d.index[bad], "total_thb", "total_ex_vat_thb + vat_thb differs from total_thb", "kept")
    price = d["total_ex_vat_thb"] / d["kwh_total"]
    odd = price.notna() & ~price.between(1, 10)
    run.flag(key, d.index[odd], "total_ex_vat_thb", "average price outside 1-10 THB/kWh", "kept")
    d = d.sort_values(["meter_id", "period_start"])
    overlap = d["period_start"] <= d.groupby("meter_id")["period_end"].shift()
    run.flag(key, d.index[overlap], "period_start", "bill period overlaps the previous bill of this meter", "kept")
    d = drop_duplicates(run, key, d, ["meter_id", "period_start"], ["kwh_total", "total_ex_vat_thb"])
    run.stats[key].update(period=f"{d['period_start'].min():%Y-%m-%d} to {d['period_end'].max():%Y-%m-%d}" if len(d)
                          else "", coverage=f"{d['meter_id'].nunique()} meters, {len(d)} bills")
    cols = ["meter_id", "station_id", "period_start", "period_end"] + [c.name for c in SCHEMA[key].cols][4:]
    return d[cols]


UNIT_OF = {"energy": "THB/kWh", "ft": "THB/kWh", "demand": "THB/kW", "service": "THB/month", "vat": "%"}
RATE_RANGE = {"energy": (0.3, 15), "ft": (-2, 3), "demand": (0, 1500), "service": (0, 100000), "vat": (0, 30)}


def load_tariff(run, d):
    key = "tariff"
    d = d.copy()
    wrong = d["unit"] != d["component"].map(UNIT_OF)
    run.flag(key, d.index[wrong], "unit", d.loc[wrong, "component"].map(lambda c: f"{c} rates must be in {UNIT_OF[c]}"),
             "row removed")
    d = d[~wrong].copy()
    timed = d["component"].isin(["energy", "demand"])
    no_win = timed & (d["day_type"].isna() | d["start_time"].isna() | d["end_time"].isna())
    run.flag(key, d.index[no_win], "day_type", "energy and demand rows need day_type, start_time and end_time",
             "row removed")
    d = d[~no_win].copy()
    lo = d["component"].map(lambda c: RATE_RANGE[c][0])
    hi = d["component"].map(lambda c: RATE_RANGE[c][1])
    odd = ~d["rate"].between(lo, hi)
    run.flag(key, d.index[odd], "rate", "rate outside the usual range for this component", "kept")
    late = d["valid_to"].notna() & (d["valid_to"] < d["valid_from"])
    run.flag(key, d.index[late], "valid_to", "valid_to before valid_from", "row removed")
    d = d[~late].copy()
    d["day_type"] = d["day_type"].fillna("all")
    # Every minute of a weekday, a weekend day and a holiday needs exactly one energy rate
    t = Tariff(d)
    problems = set()
    for meter in d["meter_id"].unique():
        for start in sorted(d.loc[d["component"] == "energy", "valid_from"].unique()):
            first = pd.Timestamp(start).date()
            days = {}
            for k in range(7):
                day = first + dt.timedelta(days=k)
                days.setdefault("weekend" if day.weekday() >= 5 else "weekday", day)
            days["holiday"] = days["weekday"]
            for dtype, day in days.items():
                t.holidays = {day} if dtype == "holiday" else set()
                _, count = t.minute_rates(meter, "energy", day)
                if (count == 0).any():
                    problems.add(f"meter {meter}: energy rates leave {int((count == 0).sum())} minutes of a "
                                 f"{dtype} from {first} without a rate")
                if (count > 1).any():
                    problems.add(f"meter {meter}: energy windows overlap on {int((count > 1).sum())} minutes of a "
                                 f"{dtype} from {first}")
    for p in sorted(problems):
        run.note(key, p)
    run.stats[key]["gaps"] = len(problems)
    comps = d.groupby("component").size()
    run.stats[key].update(period=period_text(pd.concat([d["valid_from"], d["valid_to"]])),
                          coverage=", ".join(f"{c} {n}" for c, n in comps.items()))
    return d[[c.name for c in SCHEMA[key].cols]]


def load_holidays(run, d):
    d = d.drop_duplicates("date").sort_values("date")
    run.stats["holidays"].update(period=period_text(d["date"]), coverage=f"{len(d)} dates")
    return d[["date", "name"]]


def load_customer_delivery(run, d):
    key, m = "customer_delivery", run.model
    d["node_id"] = run.map_col(key, d, "node_id", ("customer",))
    d = d.dropna(subset=["node_id"]).copy()
    d["meter_id"] = d["meter_id"].fillna("")
    bad = ~d["interval_min"].isin([60, 1440])
    run.flag(key, d.index[bad], "interval_min", "interval must be 60 (hourly) or 1440 (daily)", "row removed")
    d = d[~bad].copy()
    daily = d["interval_min"] == 1440
    mis = daily & (d["timestamp"] != d["timestamp"].dt.normalize())
    if mis.any():
        run.note(key, f"{int(mis.sum()):,} daily rows had a time of day; read as that date")
        d.loc[mis, "timestamp"] = d.loc[mis, "timestamp"].dt.normalize()
    mis = ~daily & (d["timestamp"] != d["timestamp"].dt.floor("h"))
    if mis.any():
        run.note(key, f"{int(mis.sum()):,} hourly rows not on the hour; moved to the start of the hour")
        d.loc[mis, "timestamp"] = d.loc[mis, "timestamp"].dt.floor("h")
    d = drop_duplicates(run, key, d, ["node_id", "meter_id", "interval_min", "timestamp"], ["volume_m3", "reading_m3"])

    # Meter readings -> volume of the interval that starts at each reading
    rd = d["volume_m3"].isna() & d["reading_m3"].notna()
    if rd.any():
        r = d[rd].sort_values("timestamp")
        g = r.groupby(["node_id", "meter_id", "interval_min"])
        nxt, nxt_t = g["reading_m3"].shift(-1), g["timestamp"].shift(-1)
        step = pd.to_timedelta(r["interval_min"], unit="min")
        vol = (nxt - r["reading_m3"]).where(nxt_t - r["timestamp"] == step)
        back = vol < 0
        run.flag(key, r.index[back], "reading_m3", "meter reading went down (reset or rollover)", "value removed")
        d.loc[r.index, "volume_m3"] = vol.where(~back)
        run.note(key, f"volumes taken from meter readings on {int(vol.notna().sum()):,} rows")
    neg = d["volume_m3"] < 0
    run.flag(key, d.index[neg], "volume_m3", "negative volume", "value removed")
    d.loc[neg, "volume_m3"] = np.nan
    base = d["node_id"].map(m["customers"]["base_demand_m3_day"])
    per_day = d["volume_m3"] * 1440 / d["interval_min"]
    high = (base >= 100) & (per_day > 3 * base)
    run.flag(key, d.index[high], "volume_m3", "more than 3x the model's base demand for this node", "kept")
    d = d.dropna(subset=["volume_m3"])
    d["estimated"] = d["quality"].eq("estimated")

    hourly = d[d["interval_min"] == 60].copy()
    hourly["date"] = hourly["timestamp"].dt.normalize()
    from_h = (hourly.groupby(["node_id", "meter_id", "date"])
                    .agg(volume_m3=("volume_m3", "sum"), hours=("timestamp", "nunique"), estimated=("estimated", "any"))
                    .reset_index())
    part = from_h["hours"] < 24
    if part.any():
        run.note(key, f"{int(part.sum()):,} node-days of hourly data have fewer than 24 hours; not used as daily "
                      "totals")
    from_h = from_h[~part].assign(source="hourly")
    dd = d[d["interval_min"] == 1440].rename(columns={"timestamp": "date"}).assign(source="daily")
    both = dd.merge(from_h, on=["node_id", "meter_id", "date"], suffixes=("", "_h"))
    diff = (both["volume_m3"] - both["volume_m3_h"]).abs() > 0.02 * both["volume_m3"]
    if diff.any():
        run.note(key, f"{int(diff.sum()):,} node-days where hourly data differ from the daily total by > 2% "
                      "(daily total used)")
    from_h = from_h.merge(dd[["node_id", "meter_id", "date"]], how="left", indicator=True)
    from_h = from_h[from_h.pop("_merge") == "left_only"]
    day = pd.concat([dd[["node_id", "meter_id", "date", "volume_m3", "estimated", "source"]],
                     from_h[["node_id", "meter_id", "date", "volume_m3", "estimated", "source"]]])
    day["estimated_m3"] = day["volume_m3"].where(day["estimated"], 0.0)
    out = (day.groupby(["date", "node_id"])
              .agg(volume_m3=("volume_m3", "sum"), meters=("meter_id", "nunique"), estimated_m3=("estimated_m3", "sum"),
                   source=("source", lambda s: "+".join(sorted(set(s)))))
              .reset_index())
    hourly_out = (hourly.groupby(["timestamp", "node_id"]).agg(volume_m3=("volume_m3", "sum"),
                                                               meters=("meter_id", "nunique")).reset_index())

    days = pd.date_range(out["date"].min(), out["date"].max(), freq="D") if len(out) else []
    have = out.groupby("node_id")["date"].nunique()
    nodes = list(m["customers"].index)
    none = [n for n in nodes if n not in have.index]
    if none:
        share = m["customers"].loc[none, "base_demand_m3_day"].sum() / m["customers"]["base_demand_m3_day"].sum()
        run.note(key, f"no data for {len(none)} of {len(nodes)} customer nodes: {', '.join(none)} "
                      f"({share:.0%} of the model's base demand)")
    for n, k in have.items():
        if len(days) and k < len(days):
            run.note(key, f"{n}: {k} of {len(days)} days")
    run.stats[key]["gaps"] = len(none) + int((have < len(days)).sum())
    if len(hourly_out):
        run.note(key, f"hourly data for {hourly_out['node_id'].nunique()} nodes "
                      f"({period_text(hourly_out['timestamp'])})")
    run.stats[key].update(period=period_text(out["date"]), coverage=(
        f"{len(have)}/{len(nodes)} nodes, {have.sum() / max(len(days) * len(have), 1):.1%} of node-days"))
    return out, hourly_out


def load_scada(run, d):
    key, m = "scada", run.model
    d["point_id"] = run.map_col(key, d, "point_id", ("tank", "reservoir", "junction"))
    d = d.dropna(subset=["point_id"]).copy()
    kind = d["point_id"].map(lambda p: "tank" if p in m["tanks"].index else
                             "reservoir" if p in m["reservoirs"].index else "junction")
    ok = ((d["quantity"] == "level") & kind.isin(["tank", "reservoir"]) & d["unit"].isin(["m", "m_msl"])) | (
        (d["quantity"] == "pressure") & (kind == "junction") & d["unit"].str.lower().isin(PRESSURE_TO_M))
    run.flag(key, d.index[~ok], "unit", "quantity/unit does not fit the point (level: tanks and sources in m or "
             "m_msl; pressure: junctions in m, bar, kPa, kg/cm2 or psi)", "row removed")
    d, kind = d[ok].copy(), kind[ok]
    tank_msl = (kind == "tank") & (d["unit"] == "m_msl")
    d.loc[tank_msl, "value"] -= d.loc[tank_msl, "point_id"].map(m["tanks"]["elevation_m"])
    res_depth = (kind == "reservoir") & (d["unit"] == "m")
    if res_depth.any():
        run.note(key, f"{int(res_depth.sum()):,} source levels given in m, not m_msl; kept as given (the model "
                      "compares heads in m above sea level)")
    pres = d["quantity"] == "pressure"
    d.loc[pres, "value"] *= d.loc[pres, "unit"].str.lower().map(PRESSURE_TO_M)
    conv = pres & (d["unit"] != "m")
    if conv.any() or tank_msl.any():
        units = ", ".join(sorted(d.loc[conv, "unit"].unique()))
        run.note(key, f"converted to m: {int(conv.sum()):,} pressures ({units})"
                      f", {int(tank_msl.sum()):,} tank levels from m_msl to m above the tank floor")
    d["unit_out"] = np.select([kind == "tank", (kind == "reservoir") & (d["unit"] == "m_msl"), kind == "reservoir"],
                              ["m above tank floor", "m head (MSL)", "m as given"], "m pressure head")
    tmax = d["point_id"].map(m["tanks"]["max_level_m"])
    tmin = d["point_id"].map(m["tanks"]["min_level_m"])
    bad = ((kind == "tank") & ((d["value"] < -0.5) | (d["value"] > tmax + 1))) | (
        (kind == "junction") & ~d["value"].between(-20, 250)) | ((kind == "reservoir") & ~d["value"].between(-10, 300))
    run.flag(key, d.index[bad], "value", pd.Series(
        [f"{v:.2f} m is impossible for {p}" for v, p in zip(d.loc[bad, "value"], d.loc[bad, "point_id"])],
        index=d.index[bad]), "value removed")
    d = d[~bad]
    kind = kind[~bad]
    low = (kind == "tank") & (d["value"] < tmin[~bad])
    run.flag(key, d.index[low], "value", "tank below the model's minimum level", "kept")
    neg = (kind == "junction") & (d["value"] < 0)
    run.flag(key, d.index[neg], "value", "negative pressure", "kept")
    d = drop_duplicates(run, key, d, ["point_id", "quantity", "timestamp"], ["value"])
    d["hour"] = d["timestamp"].dt.floor("h")
    h = (d.groupby(["point_id", "quantity", "hour"])
          .agg(value_m=("value", "mean"), min_m=("value", "min"), max_m=("value", "max"), readings=("value", "size"),
               unit=("unit_out", "first"))
          .reset_index().rename(columns={"hour": "timestamp"}))
    res = h[h["point_id"].isin(m["reservoirs"].index) & (h["unit"] == "m head (MSL)")]
    for p, g in res.groupby("point_id"):
        model_head = m["reservoirs"].loc[p, "head_m"]
        run.note(key, f"{p}: measured head {g['value_m'].min():.2f}-{g['value_m'].max():.2f} m (median "
                      f"{g['value_m'].median():.2f}); the model fixes it at {model_head:g} m")
    cov = []
    for (p, q), g in h.groupby(["point_id", "quantity"]):
        daily = g["timestamp"].diff().median() >= pd.Timedelta(hours=20)
        share, gap = coverage(g["timestamp"], "D" if daily else "h", g["timestamp"].min(), g["timestamp"].max())
        cov.append(f"{p} {q} {'daily' if daily else 'hourly'} {share:.0%}")
        if share < 1 and p in m["tanks"].index:
            run.note(key, f"{p}: {share:.1%} of hours present, longest gap {gap} h")
            run.stats[key]["gaps"] = run.stats[key].get("gaps", 0) + 1
    run.stats[key].update(period=period_text(h["timestamp"]), coverage=f"{h['point_id'].nunique()} points: "
                          + ", ".join(cov[:8]) + (" ..." if len(cov) > 8 else ""))
    return h[["timestamp", "point_id", "quantity", "value_m", "min_m", "max_m", "readings", "unit"]]


def load_pump_register(run, d):
    key, m = "pump_register", run.model
    d["pump_id"] = run.map_col(key, d, "pump_id", ("pump",))
    d = d.dropna(subset=["pump_id"]).copy()
    d["station_id"] = d["pump_id"].map(m["pumps"]["station_id"])
    for c in ("rated_flow_m3_h", "rated_head_m", "rated_power_kw"):
        bad = d[c] <= 0
        run.flag(key, d.index[bad], c, "must be positive", "value removed")
        d.loc[bad, c] = np.nan
    for c in ("pump_efficiency_pct", "motor_efficiency_pct"):
        bad = ~d[c].between(10, 100) & d[c].notna()
        run.flag(key, d.index[bad], c, "efficiency must be 10-100%", "value removed")
        d.loc[bad, c] = np.nan
    d = drop_duplicates(run, key, d, ["pump_id"], ["rated_power_kw"])
    st = d["status"].value_counts()
    run.stats[key].update(coverage=f"{len(d)}/{len(m['pumps'])} pumps; " + (
        ", ".join(f"{k} {v}" for k, v in st.items()) if len(st) else "no status given"))
    blank = d["status"].isna().sum()
    if blank:
        run.note(key, f"{blank} pumps without a status")
    return d[[c.name for c in SCHEMA[key].cols]]


def load_pump_tests(run, d):
    key = "pump_tests"
    d["pump_id"] = run.map_col(key, d, "pump_id", ("pump",))
    d = d.dropna(subset=["pump_id"]).copy()
    bad = (d[["flow_m3_h", "head_m", "power_kw"]] <= 0).any(axis=1)
    run.flag(key, d.index[bad], "flow_m3_h", "flow, head and power must be positive", "row removed")
    d = d[~bad].copy()
    d["wire_to_water_pct"] = (9.80665 * d["flow_m3_h"] / 3600 * d["head_m"] / d["power_kw"] * 100).round(1)
    odd = ~d["wire_to_water_pct"].between(20, 95)
    run.flag(key, d.index[odd], "power_kw", "flow x head / power gives an efficiency outside 20-95%", "kept")
    given = d["efficiency_pct"].notna() & ((d["efficiency_pct"] - d["wire_to_water_pct"]).abs() > 5)
    run.flag(key, d.index[given], "efficiency_pct", "differs from flow x head / power by more than 5 points", "kept")
    run.stats[key].update(period=period_text(d["test_date"]),
                          coverage=f"{d['pump_id'].nunique()} pumps, {len(d)} test points")
    return d[[c.name for c in SCHEMA[key].cols] + ["wire_to_water_pct"]]


def load_confirmations(run, d):
    key = "confirmations"
    answered = d["answer"].notna()
    run.stats[key].update(coverage=f"{int(answered.sum())} of {len(d)} answered", gaps=int((~answered).sum()))
    for q in d.loc[~answered, "question_id"]:
        run.note(key, f"{q} not answered yet")
    return d


LOADERS = {"id_map": load_id_map, "pump_operation": load_pump_operation, "station_energy": load_station_energy,
           "electricity_bills": load_bills, "tariff": load_tariff, "holidays": load_holidays,
           "customer_delivery": load_customer_delivery, "scada": load_scada, "pump_register": load_pump_register,
           "pump_tests": load_pump_tests, "confirmations": load_confirmations}
OUTPUTS = {"id_map": "id_map.csv", "pump_operation": "pump_operation_hourly.csv",
           "station_energy": "station_energy.csv", "electricity_bills": "electricity_bills.csv",
           "tariff": "tariff.csv", "holidays": "holidays.csv",
           "customer_delivery": ("customer_delivery_daily.csv", "customer_delivery_hourly.csv"),
           "scada": "scada_hourly.csv", "pump_register": "pump_register.csv", "pump_tests": "pump_tests.csv",
           "confirmations": "confirmations.csv"}


# ------------------------------------------------------------------ output

def write_csv(df, path):
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            fmt = DATE_FMT if (out[c].dropna() == out[c].dropna().dt.normalize()).all() and c != "timestamp" else TS_FMT
            out[c] = out[c].dt.strftime(fmt)
    out.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.6g")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(p):
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def status_of(run, key):
    st = run.stats[key]
    if not st["files"]:
        return "missing"
    flagged = any(f["dataset"] == key for f in run.flags)
    return "check" if flagged or st.get("gaps") else "ok"


def readiness(run, outputs):
    have = {k for k, v in outputs.items() if v}
    missing = [SCHEMA[k].title.lower() for k in NEEDED if k not in have]
    if not ({"station_energy", "electricity_bills"} & have):
        missing.append("station electricity (meter data or bills)")
    notes = []
    if "tariff" not in have:
        notes.append("no tariff yet, so costs use the POC's assumed tariff")
    return missing, notes


def write_report(run, outputs, prefix, inbox, n_files, path):
    m = run.model
    L = ["# Eastwater data: validation report", ""]
    if prefix:
        L += [f"> **{SAMPLE_NOTE}**", ""]
    L += [f"Loaded {dt.datetime.now():%Y-%m-%d %H:%M} from `{rel(inbox)}` ({n_files} files). Model "
          f"`{m['inp'].name}`: {len(m['pumps'])} pumps at {len(m['stations'])} stations "
          f"({', '.join(m['stations'].index)}), {len(m['tanks'])} head tanks, {len(m['customers'])} customer nodes. "
          "All times are Thai time (Asia/Bangkok, UTC+07:00).", ""]
    missing, notes = readiness(run, outputs)
    L += ["**Ready to compute the saving vs today's operation:** "
          + ("yes" if not missing else "no, still needed: " + ", ".join(missing))
          + ("" if not notes else f" ({'; '.join(notes)})") + ".", ""]
    L += ["## Summary", "", "| dataset | files | rows read | rows kept | period | coverage | flags | status |",
          "|---|---|---|---|---|---|---|---|"]
    for key, ds in SCHEMA.items():
        st = run.stats[key]
        nflag = sum(1 for f in run.flags if f["dataset"] == key)
        L.append(f"| {ds.title} | {len(st['files'])} | {st['rows_in']:,} | {st['rows_kept']:,} | {st['period']} | "
                 f"{st['coverage']} | {nflag:,} | {status_of(run, key)} |")
    L += ["", "Status: **ok** = loaded cleanly; **check** = loaded, but rows were removed or data are missing (see "
          "below); **missing** = not received. *Rows kept* counts clean output rows (hourly or daily), so it can "
          "differ from rows read.", ""]
    fl = pd.DataFrame(run.flags, columns=["dataset", "file", "line", "column", "value", "issue", "action"])
    L += ["## To fix or confirm", ""]
    if fl.empty and not run.unread:
        L.append("Nothing: every row passed the checks.")
    for f in run.unread:
        L.append(f"- {f}")
    if not fl.empty:
        g = (fl.groupby(["dataset", "column", "issue", "action"], sort=False)
               .agg(n=("line", "size"), file=("file", "first"), line=("line", "first"), value=("value", "first"))
               .reset_index().sort_values("n", ascending=False))
        for r in g.head(25).itertuples():
            ex = f"`{r.file}` line {r.line}" + (f" (`{r.value}`)" if str(r.value) != "" else "")
            L.append(f"- {SCHEMA[r.dataset].title}, `{r.column}`: {r.issue} - {r.n:,} row(s), {r.action}; "
                     f"first at {ex}")
        if len(g) > 25:
            L.append(f"- ... {len(g) - 25} more kinds of issue in `flags.csv`")
    L += ["", f"Every flagged row is listed in `{prefix}flags.csv` with its file and line.", ""]
    L += ["## Notes by dataset", ""]
    for key, ds in SCHEMA.items():
        if run.notes[key]:
            L += [f"**{ds.title}**", ""] + [f"- {n}" for n in run.notes[key][:15]]
            if len(run.notes[key]) > 15:
                L.append(f"- ... {len(run.notes[key]) - 15} more")
            L.append("")
    mt = pd.DataFrame(run.matches)
    if not mt.empty:
        mt = mt.groupby(["dataset", "column", "received", "epanet_id", "how"], dropna=False)["rows"].sum().reset_index()
        how = {"case": "same ID, different capitals", "id_map": "client tag in id_map",
               "loose": "same ID, different separators or zeros", "unmapped": "**not found: rows removed**"}
        L += ["## IDs not matched exactly", "", "| dataset | received | mapped to | how | rows |",
              "|---|---|---|---|---|"]
        L += [f"| {SCHEMA[r.dataset].title} | `{r.received}` | {r.epanet_id or '-'} | {how.get(r.how, r.how)} | "
              f"{r.rows:,} |" for r in mt.sort_values(["how", "dataset"]).itertuples()]
        L.append("")
    L += ["## Outputs", "", *[f"- `{rel(p)}`" for p in sorted({p for v in outputs.values() for p in v})], ""]
    path.write_text("\n".join(L), encoding="utf-8")


def load(inbox, prefix, inp=DEFAULT_INP):
    model = read_model(inp)
    run = Run(model)
    files = sorted(p for p in Path(inbox).glob("*") if p.suffix.lower() in (".csv", ".xlsx", ".xlsm", ".xls")
                   and not p.name.startswith("~$"))
    tables, inputs = {k: [] for k in SCHEMA}, []
    samples = []
    for f in files:
        for label, t, lines, sample in read_tables(f):
            samples.append(sample or "sample" in f.name.lower())
            key, guess = detect(label, t.columns)
            if key is None:
                if guess:
                    need = [c for c in SCHEMA[guess].signature if c not in canon_columns(t.columns, guess)]
                    run.unread.append(f"`{label}` looks like {SCHEMA[guess].title.lower()} but lacks column(s) "
                                      f"{', '.join(need)}; not loaded")
                else:
                    run.unread.append(f"`{label}`: columns {', '.join(map(str, t.columns[:8]))} match no template; "
                                      "not loaded")
                continue
            tables[key].append((label, t, lines, sample))
            run.stats[key]["files"].append(label)
            inputs.append(dict(file=rel(f), table=label, dataset=key, rows=len(t), sha256=sha256(f),
                               sample=bool(sample or "sample" in f.name.lower())))
    if any(samples) and not all(samples):
        raise SystemExit(f"{inbox} mixes SAMPLE files with real ones; keep the sample set out of the inbox.")
    is_sample = bool(samples) and all(samples)
    if is_sample and not prefix:
        prefix = "SAMPLE_"

    EW_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {k: [] for k in SCHEMA}
    data = {}
    for key in SCHEMA:                      # id_map first, so later datasets can use client tags
        if not tables[key]:
            continue
        d = prepare(run, key, tables[key])
        res = LOADERS[key](run, d)
        res = res if isinstance(res, tuple) else (res,)
        names = OUTPUTS[key] if isinstance(OUTPUTS[key], tuple) else (OUTPUTS[key],)
        run.stats[key]["rows_kept"] = len(res[0])
        for df, name in zip(res, names):
            if len(df):
                path = EW_DIR / f"{prefix}{name}"
                write_csv(df, path)
                outputs[key].append(path)
        data[key] = res[0]

    fl = pd.DataFrame(run.flags, columns=["dataset", "file", "line", "column", "value", "issue", "action"])
    flags_path = EW_DIR / f"{prefix}flags.csv"
    fl.to_csv(flags_path, index=False, encoding="utf-8-sig")
    report_path = EW_DIR / f"{prefix}validation_report.md"
    write_report(run, outputs, prefix, inbox, len(files), report_path)

    manifest_path = EW_DIR / f"{prefix}manifest.json"
    old = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    new_outputs = {k: [p.name for p in v] for k, v in outputs.items() if v}
    keep = {p for v in new_outputs.values() for p in v} | {flags_path.name, report_path.name, manifest_path.name}
    for name in {p for v in old.get("outputs", {}).values() for p in v} - keep:
        (EW_DIR / name).unlink(missing_ok=True)       # an output of the last run that this run did not produce
    missing, notes = readiness(run, outputs)
    manifest = dict(created=dt.datetime.now().isoformat(timespec="seconds"), sample=is_sample,
                    note=SAMPLE_NOTE if is_sample else "Eastwater data - confidential (NDA)", inbox=rel(inbox),
                    model=dict(file=rel(model["inp"]), sha256=sha256(model["inp"])),
                    timezone="Asia/Bangkok (UTC+07:00)",
                    inputs=inputs, outputs=new_outputs, flags=flags_path.name, report=report_path.name,
                    periods={k: run.stats[k]["period"] for k in SCHEMA if run.stats[k]["period"]},
                    ready_for_saving=not missing, still_needed=missing)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return run, outputs, report_path


# ------------------------------------------------------------------ templates

QUESTIONS = [
    ("Q1", "Nodes 71 and 678", "โหนด 71 และ 678 คืออะไร",
     "Nodes 71 and 678 each take 100,000 m3/day in the model (together 29% of its 688,403 m3/day). Are they real "
     "customers, future demand or placeholders? If real: which customers, and what do they take per day today?",
     "71: 100,000 m3/day at elevation 55 m; 678: 100,000 m3/day at elevation 43.7 m"),
    ("Q2", "TM Pond pumps 3-6", "เครื่องสูบ TM Pond หมายเลข 3-6 เป็นเครื่องสำรองหรือไม่",
     "TM Pond pumps 3-6 (TM_Pond_03p to TM_Pond_06p) are closed in the model. Are they standby, out of service or "
     "removed? How many TM Pond pumps can run at the same time?",
     "TM_Pond_03p-06p Closed; the POC found that at most 2 TM Pond pumps can run (more cannot deliver the head)"),
    ("Q3", "Source water levels", "ระดับน้ำต้นทางที่จุดรับน้ำของสถานีสูบ (ม.รทก.)",
     "The model fixes the source water level (head) at the pump intakes. What are the typical, lowest and highest "
     "levels in m above mean sea level? At NPL3 and TM Pond the model's suction pipework sits above these heads, "
     "so it shows negative pressure there.",
     "NPL_Res2 (NPL2 intake) 43.41 m; NPL_Res3 (NPL3 intake) 43.41 m; R10885 (TM Pond intake) 23 m"),
    ("Q4", "Head tank operating range", "ช่วงระดับน้ำใช้งานของถังพักน้ำ และเกณฑ์เปิด-ปิดเครื่องสูบ",
     "What lowest and highest levels do operators keep in the head tanks, and which levels make them start or stop "
     "pumps?", "NPL2_HT 2-21.85 m and NPL3_HT 2-25 m above the tank floor (floor at 81 m)"),
    ("Q5", "Other loads on station meters", "มาตรไฟฟ้าของสถานีจ่ายไฟให้โหลดอื่นด้วยหรือไม่",
     "Do the station electricity meters also supply other loads (offices, treatment, lighting, other pumps)? About "
     "how many kW?", "The model only counts pump energy"),
    ("Q6", "Tariff per meter", "ประเภทอัตราค่าไฟฟ้าของแต่ละมาตร",
     "For each station meter: utility, tariff category (e.g. PEA 4.2.2 TOU), supply voltage, and any special "
     "contract.", "The POC assumes 4.1839 THB/kWh 09:00-22:00 weekdays and 2.6037 THB/kWh otherwise"),
    ("Q7", "Customers not in the model", "ลูกค้าที่ไม่มีในแบบจำลอง",
     "Do these three stations supply customers that are not among the model's 28 nodes, or does the model have "
     "nodes that are no longer supplied?", "28 customer nodes, 688,403 m3/day in total"),
]


def prefill(key, model):
    """Pre-filled rows for the templates that list model IDs or questions."""
    m = model
    if key == "id_map":
        rows = []
        for s, r in m["stations"].iterrows():
            rows.append(dict(epanet_id=s, element_type="station", model_description=f"{r.n_pumps} pumps: {r.pumps}"))
        for p, r in m["pumps"].iterrows():
            rows.append(dict(epanet_id=p, element_type="pump", model_description=(
                f"{r.station_id} pump; from {r.source} to {r.delivers_to}; curve {r.curve_text}; "
                f"{'closed' if r.model_status == 'Closed' else 'open'} in the model")))
        for t, r in m["tanks"].iterrows():
            rows.append(dict(epanet_id=t, element_type="tank", model_description=(
                f"head tank; floor at {r.elevation_m:g} m; level {r.min_level_m:g}-{r.max_level_m:g} m; "
                f"diameter {r.diameter_m:g} m")))
        for v, r in m["reservoirs"].iterrows():
            feeds = ", ".join(sorted(set(m["pumps"].loc[m["pumps"]["source"] == v, "station_id"])))
            rows.append(dict(epanet_id=v, element_type="reservoir",
                             model_description=f"pump source for {feeds or '-'}; fixed head {r.head_m:g} m"))
        for c, r in m["customers"].sort_values("base_demand_m3_day", ascending=False).iterrows():
            rows.append(dict(epanet_id=c, element_type="customer", model_description=(
                f"customer node; {r.base_demand_m3_day:,.0f} m3/day in the model; elevation {r.elevation_m:g} m"
                + (f"; model note: {r.note}" if r.note else ""))))
        return pd.DataFrame(rows)
    if key == "pump_register":
        p = m["pumps"].reset_index().rename(columns={"id": "pump_id"})
        p["station_id"] = p["station_id"]
        p["model_curve"] = p["curve_text"]
        return p[["pump_id", "station_id", "model_curve", "model_status"]]
    if key == "confirmations":
        return pd.DataFrame(QUESTIONS, columns=["question_id", "topic", "topic_th", "question", "model_value"])
    return None


def unit_hint(c):
    """Second template row: unit or format of each column, with an example."""
    if c.kind == "timestamp":
        return TS_HINT
    if c.kind == "date":
        return "YYYY-MM-DD"
    if c.kind == "time":
        return "HH:MM (24:00 = midnight)"
    if c.kind == "choice":
        return " / ".join(c.choices)
    ex = f" (e.g. {c.example})" if c.example else ""
    if c.kind == "id":
        return "EPANET ID" + ex
    if c.kind == "number":
        return (c.unit or "number") + ex
    return ("e.g. " + c.example) if c.example else "text"


def write_templates(model):
    import csv
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for key, ds in SCHEMA.items():
        cols = [c.name for c in ds.cols]
        hints = [unit_hint(c) for c in ds.cols]
        hints[0] = "#" + hints[0]
        with open(TEMPLATE_DIR / ds.file, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerow(hints)
            pre = prefill(key, model)
            if pre is not None:
                for r in pre.reindex(columns=cols).fillna("").itertuples(index=False):
                    w.writerow(list(r))
        for c in ds.cols:
            rows.append(dict(dataset=key, dataset_title=ds.title, dataset_th=ds.th, template=f"templates/{ds.file}",
                             priority=ds.priority, column=c.name, required="yes" if c.required else "no",
                             type=c.kind, unit_or_format=unit_hint(c), description=c.desc, label_th=c.th,
                             example=c.example))
    pd.DataFrame(rows).to_csv(REQUEST_DIR / "data_dictionary.csv", index=False, encoding="utf-8-sig")
    print(f"templates -> {rel(TEMPLATE_DIR)} ({len(SCHEMA)} files); dictionary -> "
          f"{rel(REQUEST_DIR / 'data_dictionary.csv')} ({len(rows)} columns)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inbox", nargs="?", default=None, help="folder with Eastwater's files (default data/eastwater/raw)")
    ap.add_argument("--sample", action="store_true", help="load the synthetic sample set")
    ap.add_argument("--inp", default=DEFAULT_INP, help="EPANET model")
    ap.add_argument("--write-templates", action="store_true", help="rebuild the templates and the data dictionary")
    a = ap.parse_args()
    if a.write_templates:
        write_templates(read_model(a.inp))
        return
    inbox = Path(a.inbox) if a.inbox else RAW_DIR
    has_files = inbox.is_dir() and any(p.suffix.lower() in (".csv", ".xlsx", ".xlsm", ".xls") for p in inbox.iterdir())
    prefix = ""
    if a.sample or (a.inbox is None and not has_files):
        if not a.sample:
            print(f"No files in {rel(inbox)}; loading the SAMPLE set instead.")
        inbox, prefix = SAMPLE_DIR, "SAMPLE_"
    run, outputs, report = load(inbox, prefix, a.inp)
    print(f"{'SAMPLE: ' if prefix else ''}loaded {sum(len(s['files']) for s in run.stats.values())} tables from "
          f"{rel(inbox)}; {len(run.flags):,} flags")
    for key, ds in SCHEMA.items():
        st = run.stats[key]
        if st["files"]:
            print(f"  {ds.title:32s} {st['rows_in']:>8,} rows in  {st['rows_kept']:>8,} kept  {st['period']}")
    missing, _ = readiness(run, outputs)
    print(f"ready for the saving calculation: {'yes' if not missing else 'no - needs ' + ', '.join(missing)}")
    print(f"report -> {rel(report)}")


if __name__ == "__main__":
    main()
