# Bang Phra data quality

Source sheet `WB บางพระ`; 13149 dated rows, kept 1990-01-01 to 2025-03-28 (12871 days). Dropped 278 pre-filled formula rows after the last recorded level.

## Consistency checks

- Total use equals the sum of the user columns: 100.0% of days
- Total outflow equals evaporation + releases + total use: 100.0% of days
- Rain volume equals rain (mm) x surface area: 96.6% of rainy days
- Evaporation equals surface area x the sheet's monthly pan rate: 89.1% of days (evaporation is computed, not measured)
- Natural inflow recomputed as next-day storage change + outflow - diversions matches column AF within 1,000 m3: 99.5% of days (AF includes rain falling on the reservoir)

## Flags

| column | flag | days |
|---|---|---|
| level_m_msl | level_jump | 18 |
| outflow_total_m3 | component_invalid | 35 |
| outflow_total_m3 | negative_flow | 2 |
| use_eastwater_m3 | dash_as_zero | 4 |
| use_eastwater_m3 | negative_flow | 2 |
| use_egat_bangpakong_m3 | dash_as_zero | 20 |
| use_egat_bangpakong_m3 | negative_flow | 6 |
| use_egat_bangpakong_m3 | spike | 10 |
| use_fisheries_research_m3 | dash_as_zero | 32 |
| use_pwa_chonburi_m3 | negative_flow | 1 |
| use_pwa_chonburi_m3 | outlier_hampel | 255 |
| use_pwa_chonburi_m3 | zero_in_continuous_series | 13 |
| use_thai_oil_m3 | dash_as_zero | 56 |
| use_thai_oil_m3 | negative_flow | 2 |
| use_thai_oil_m3 | spike | 4 |
| use_total_m3 | component_invalid | 35 |
| use_total_m3 | negative_flow | 2 |
| use_total_m3 | outlier_hampel | 158 |
| use_total_m3 | zero_in_continuous_series | 1 |

## Storage vs the 2020+ level-storage table (median residual, MCM)

A non-zero residual means the level->storage table used that year differs from the current one.

| year | residual |
|---|---|
| 1990 | 0.48 |
| 1991 | 0.48 |
| 1992 | 0.44 |
| 1993 | 0.4 |
| 1994 | 0.42 |
| 1995 | 0.53 |
| 1996 | 0.61 |
| 1997 | 1.15 |
| 1998 | 0.54 |
| 1999 | 0.46 |
| 2000 | -0.0 |
| 2001 | -0.0 |
| 2002 | -0.0 |
| 2003 | -0.0 |
| 2004 | -0.0 |
| 2005 | -0.0 |
| 2006 | -0.0 |
| 2007 | -0.0 |
| 2008 | -0.0 |
| 2009 | -0.0 |
| 2010 | -0.0 |
| 2011 | -0.0 |
| 2012 | -0.0 |
| 2013 | -0.0 |
| 2014 | -0.0 |
| 2015 | -0.0 |
| 2016 | -0.0 |
| 2017 | -0.0 |
| 2018 | -0.0 |
| 2019 | 0.0 |
| 2020 | 0.0 |
| 2021 | 0.0 |
| 2022 | 0.0 |
| 2023 | 0.0 |
| 2024 | 0.0 |
| 2025 | 0.0 |

## Yearly summary (m3/day means; *_nan = days missing after cleaning)

| year | days | total_mean | pwa_chonburi_mean | thai_oil_mean | egat_bangpakong_mean | total_nan | pwa_chonburi_nan | thai_oil_nan | egat_bangpakong_nan | storage_min_mcm | storage_max_mcm | div_in_mcm |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1990 | 365 | 72,500 | 60,361 | 5,230 | 3,411 | 6 | 6 | 0 | 0 | 31.9 | 57.1 | 0.0 |
| 1991 | 365 | 63,959 | 53,458 | 4,887 | 3,210 | 5 | 7 | 0 | 0 | 25.1 | 46.3 | 0.0 |
| 1992 | 366 | 63,227 | 53,305 | 5,313 | 3,574 | 6 | 8 | 0 | 0 | 11.6 | 48.1 | 0.0 |
| 1993 | 365 | 70,338 | 63,626 | 3,121 | 3,120 | 6 | 6 | 0 | 0 | 23.9 | 44.0 | 0.0 |
| 1994 | 365 | 71,828 | 67,211 | 1,408 | 3,122 | 2 | 2 | 0 | 0 | 21.8 | 39.0 | 0.0 |
| 1995 | 365 | 80,342 | 74,006 | 2,335 | 3,854 | 7 | 7 | 0 | 0 | 17.3 | 116 | 0.0 |
| 1996 | 366 | 79,022 | 69,770 | 5,166 | 3,525 | 4 | 12 | 0 | 0 | 83.5 | 114 | 0.0 |
| 1997 | 365 | 84,962 | 74,042 | 6,564 | 4,193 | 3 | 2 | 0 | 0 | 65.0 | 108 | 0.0 |
| 1998 | 365 | 84,012 | 72,617 | 6,906 | 4,264 | 18 | 24 | 0 | 0 | 45.8 | 67.7 | 0.0 |
| 1999 | 365 | 89,145 | 76,481 | 7,662 | 3,752 | 22 | 43 | 0 | 0 | 38.1 | 64.2 | 0.0 |
| 2000 | 366 | 98,733 | 86,441 | 8,100 | 3,502 | 15 | 30 | 0 | 0 | 44.3 | 58.9 | 0.0 |
| 2001 | 365 | 86,503 | 78,051 | 5,913 | 2,598 | 22 | 32 | 0 | 0 | 20.8 | 46.6 | 0.0 |
| 2002 | 365 | 63,091 | 57,847 | 2,924 | 2,312 | 8 | 7 | 1 | 0 | 15.6 | 28.5 | 0.0 |
| 2003 | 365 | 59,990 | 56,082 | 1,929 | 1,982 | 1 | 1 | 0 | 0 | 14.0 | 61.5 | 0.0 |
| 2004 | 366 | 69,980 | 64,815 | 2,233 | 2,916 | 6 | 5 | 1 | 0 | 41.0 | 59.6 | 0.0 |
| 2005 | 365 | 105,569 | 79,175 | 4,423 | 2,276 | 5 | 5 | 0 | 0 | 11.6 | 44.5 | 0.0 |
| 2006 | 365 | 89,116 | 79,328 | 4,938 | 2,380 | 1 | 2 | 0 | 0 | 33.0 | 70.4 | 0.4 |
| 2007 | 365 | 75,258 | 69,972 | 3,008 | 2,301 | 3 | 6 | 0 | 0 | 50.7 | 66.5 | 9.5 |
| 2008 | 366 | 88,108 | 67,813 | 2,521 | 2,373 | 2 | 3 | 0 | 0 | 32.6 | 56.6 | 10.3 |
| 2009 | 365 | 107,696 | 73,184 | 2,349 | 2,472 | 4 | 9 | 0 | 0 | 37.0 | 70.4 | 13.6 |
| 2010 | 365 | 108,385 | 71,638 | 2,337 | 2,633 | 5 | 6 | 1 | 0 | 44.4 | 95.6 | 13.4 |
| 2011 | 365 | 104,577 | 65,583 | 2,293 | 2,402 | 3 | 0 | 0 | 7 | 62.9 | 114 | 1.0 |
| 2012 | 366 | 114,590 | 73,328 | 3,846 | 2,642 | 6 | 16 | 0 | 1 | 62.2 | 95.3 | 24.2 |
| 2013 | 365 | 125,314 | 79,760 | 4,890 | 2,873 | 3 | 6 | 0 | 0 | 43.5 | 86.1 | 10.3 |
| 2014 | 365 | 163,269 | 95,836 | 7,484 | 2,808 | 2 | 16 | 0 | 2 | 26.9 | 79.0 | 11.8 |
| 2015 | 365 | 182,011 | 125,268 | 6,917 | 2,749 | 3 | 8 | 1 | 0 | 13.4 | 59.6 | 39.6 |
| 2016 | 366 | 148,542 | 131,011 | 6,538 | 3,007 | 6 | 5 | 0 | 1 | 15.0 | 98.5 | 72.6 |
| 2017 | 365 | 232,017 | 193,183 | 10,478 | 2,491 | 8 | 7 | 0 | 2 | 66.8 | 113 | 18.9 |
| 2018 | 365 | 248,183 | 214,105 | 9,976 | 2,652 | 2 | 4 | 0 | 2 | 58.9 | 101 | 46.8 |
| 2019 | 365 | 191,878 | 159,595 | 8,156 | 3,644 | 7 | 7 | 0 | 0 | 39.6 | 83.1 | 63.3 |
| 2020 | 366 | 206,471 | 159,379 | 6,366 | 2,923 | 2 | 2 | 0 | 0 | 15.5 | 83.3 | 59.4 |
| 2021 | 365 | 200,662 | 141,697 | 9,560 | 3,214 | 2 | 3 | 1 | 0 | 35.6 | 117 | 61.6 |
| 2022 | 365 | 256,109 | 195,756 | 9,650 | 3,441 | 0 | 0 | 0 | 0 | 76.3 | 119 | 39.4 |
| 2023 | 365 | 324,576 | 198,876 | 13,894 | 2,785 | 0 | 0 | 0 | 0 | 44.0 | 108 | 94.1 |
| 2024 | 366 | 286,406 | 212,875 | 14,068 | 2,667 | 0 | 0 | 0 | 0 | 39.8 | 108 | 102 |
| 2025 | 87 | 268,132 | 219,034 | 14,265 | 4,639 | 1 | 1 | 1 | 1 | 72.3 | 96.6 | 0.0 |

Storage capacity used for % full: 117.0 MCM.