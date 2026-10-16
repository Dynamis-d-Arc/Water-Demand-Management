"""Paths and the column map for the Bang Phra water-balance sheet (WB บางพระ)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEAN_DIR = ROOT / "data" / "clean"
REPORT_DIR = ROOT / "reports"
FIG_DIR = REPORT_DIR / "figures"

DEFAULT_XLSX = Path(r"C:\Users\Brandon\Downloads\water_daily_report_sample.xlsx")
DEFAULT_INP = ROOT.parent / "Demand-2023 v20RY to MTP new TM2P.inp"

SHEET = "WB บางพระ"
FIRST_DATA_ROW = 5          # 1-based Excel row of 1990-01-01
CAPACITY_MCM = 117.0        # storage capacity quoted on sheet "1.สรุปปริมาณน้ำ"

# blank: what an empty cell means. "zero" for intermittent flows (releases,
# diversions, occasional users); "missing" for series that are recorded every day.
# kind groups columns for the data dictionary and the balance check.
COLUMNS = [
    # col, name, unit, kind, blank, thai header (rows 2-4)
    ("A",  "date",                        "",       "index",     "missing", "วันที่"),
    ("B",  "level_m_msl",                 "m MSL",  "state",     "missing", "ระดับน้ำในอ่าง ม.(รทก.)"),
    ("C",  "storage_mcm",                 "MCM",    "state",     "missing", "ปริมาณน้ำในอ่าง (ล้าน ลบ.ม.)"),
    ("D",  "area_km2",                    "km2",    "state",     "missing", "พื้นที่ผิวน้ำในอ่าง (ตร.กม.)"),
    ("E",  "rain_mm",                     "mm",     "weather",   "zero",    "ฝนตกวัดได้ (มม.)"),
    ("F",  "rain_vol_m3",                 "m3",     "inflow",    "zero",    "ปริมาณฝนในอ่าง (ลบ.ม.)"),
    ("G",  "evap_seepage_m3",             "m3",     "loss",      "missing", "การระเหยและการรั่วซึม (ลบ.ม.)"),
    ("H",  "release_spillway_m3",         "m3",     "release",   "zero",    "ระบายน้ำออก: Spillway"),
    ("I",  "release_river_outlet_m3",     "m3",     "release",   "zero",    "ระบายน้ำออก: River Outlet"),
    ("J",  "release_canal_outlet_m3",     "m3",     "release",   "zero",    "ระบายน้ำออก: Canal Outlet"),
    ("K",  "release_agriculture_m3",      "m3",     "release",   "zero",    "ปริมาณน้ำเพื่อการเกษตร"),
    ("L",  "use_cassava_starch_m3",       "m3",     "use",       "zero",    "บ.แป้งมันสำประหลัง"),
    ("M",  "use_panya_resort_m3",         "m3",     "use",       "zero",    "บ.ปัญญารีสอร์ท"),
    ("N",  "use_siam_livestock_m3",       "m3",     "use",       "zero",    "บ.สยามปศุสัตว์"),
    ("O",  "use_pwa_chonburi_m3",         "m3",     "use",       "missing", "การประปาชลบุรี"),
    ("P",  "use_thai_oil_m3",             "m3",     "use",       "zero",    "บ.โรงกลั่นน้ำมันไทย"),
    ("Q",  "use_fisheries_research_m3",   "m3",     "use",       "zero",    "ศูนย์วิจัยและพัฒนาประมงน้ำจืด"),
    ("R",  "use_egat_bangpakong_m3",      "m3",     "use",       "zero",    "การไฟฟ้าบางปะกง"),
    ("S",  "use_eastwater_m3",            "m3",     "use",       "zero",    "EW"),
    ("T",  "use_bangphra_golf_m3",        "m3",     "use",       "zero",    "บ.บางพระกอล์ฟฯ"),
    ("U",  "use_private_1_m3",            "m3",     "use",       "zero",    "individual user (name in source header)"),
    ("V",  "use_bangkok_livestock_m3",    "m3",     "use",       "zero",    "บ.กรุงเทพค้าสัตว์"),
    ("W",  "use_private_2_m3",            "m3",     "use",       "zero",    "individual user (name in source header)"),
    ("X",  "use_total_m3",                "m3",     "use_total", "missing", "รวมน้ำเพื่ออุปโภคและอุตสาหกรรม"),
    ("Y",  "div_in_bangpakong_m3",        "m3",     "diversion", "zero",    "ผันน้ำเข้า: น้ำที่สูบจากแม่น้ำบางปะกง"),
    ("Z",  "div_in_nongkho_release_m3",   "m3",     "diversion", "zero",    "ผันน้ำเข้า: น้ำที่ระบายจากหนองค้อ"),
    ("AA", "div_in_nongkho_spillway_m3",  "m3",     "diversion", "zero",    "ผันน้ำเข้า: รับน้ำจาก Spillway หนองค้อ"),
    ("AB", "div_in_phra_ong_m3",          "m3",     "diversion", "zero",    "ผันน้ำเข้า: น้ำที่สูบจากพระองค์ฯ"),
    ("AC", "div_in_phan_thong_m3",        "m3",     "diversion", "zero",    "ผันน้ำเข้า: น้ำที่สูบจากพานทอง"),
    ("AD", "outflow_total_m3",            "m3",     "outflow",   "missing", "รวมปริมาณน้ำทั้งหมด (OUTFLOW)"),
    ("AE", "runoff_in_clipped_m3",        "m3",     "inflow",    "zero",    "INFLOW FROM RUNOFF (incl. rain on reservoir, clipped at 0)"),
    ("AF", "runoff_in_m3",                "m3",     "inflow",    "zero",    "INFLOW FROM RUNOFF (incl. rain on reservoir, balance residual)"),
]

# Water-year allocation plan (1 Nov 2024 - 31 Oct 2025) on sheet "3. รายงานอ่างฯบางพระ":
# dates in column P from row 5, daily plan ("แผน") per user in the columns below.
PLAN_SHEET = "3. รายงานอ่างฯบางพระ"
PLAN_FIRST_ROW = 5
PLAN_COLUMNS = {
    "P": "date",
    "R": "plan_pwa_chonburi_m3",
    "U": "plan_egat_bangpakong_m3",
    "X": "plan_thai_oil_m3",
    "AA": "plan_eastwater_m3",
    "AD": "plan_local_users_m3",
    "AG": "plan_evap_seepage_m3",
    "AJ": "plan_outflow_m3",
}

# Monthly pan-evaporation rates (mm/day) from the side table at AH1:AI12 of the sheet.
EVAP_MM_PER_DAY = [4.8, 5.1, 5.6, 5.8, 5.3, 5.2, 5.1, 5.0, 4.7, 4.5, 4.7, 5.0]

# Daily series that are forecast as demand. Eastwater (S) draws only in some
# periods, so it is kept in the data but not used as a point-forecast target.
DEMAND_TARGETS = ["use_total_m3", "use_pwa_chonburi_m3", "use_thai_oil_m3", "use_egat_bangpakong_m3"]
SUPPLY_TARGET = "storage_mcm"
