# US Layoffs Tracker (2023 – today)

How many people are being laid off in the United States, where, when, and how big are the layoffs?
This project collects layoff data from **official public sources**, checks them against each other
and against a widely cited private tracker, and summarizes them by **year, quarter, month, state, city and layoff size**.

**Tools:** Python (pandas, requests, matplotlib), BLS Public Data API, U.S. Department of Labor open data,
state WARN notices via Stanford Big Local News `warn-scraper`.

## Data sources

No single source tells the whole story, so each one checks the others.

| Source | Who publishes it | What it counts | Strength | Limitation |
|---|---|---|---|---|
| **JOLTS** layoffs & discharges | U.S. Bureau of Labor Statistics | Every employer-initiated separation, all business sizes | Official, complete national picture | Includes firings; state data are model estimates released once a year |
| **ETA-539** initial claims | U.S. Department of Labor | People filing for unemployment, weekly | Fast (about 1 week behind) | Not every laid-off worker files |
| **WARN** notices | State labor departments | Individual large layoffs: company, city, date, workers | Company and city detail | Large layoffs only; some states' data can't be collected |
| **BED** gross job losses | U.S. Bureau of Labor Statistics | Jobs lost at shrinking or closing businesses, by quarter | Covers every business size | About 7 months behind |
| **Challenger** job-cut announcements *(reference only)* | Challenger, Gray & Christmas (private research firm) | Job cuts companies **announce** | The tracker most often quoted in the news | Plans, not confirmed layoffs; entered by hand from monthly reports |

## Results

<!-- RESULTS:START -->
_Last updated November 02, 2026. Generated automatically by `make_charts.py`._

### Key numbers

| Measure | Value |
|---|---|
| US layoffs & discharges in 2025 (BLS) | **21.24M** |
| Change vs 2024 | **+6.1%** |
| 2026 so far (8 months), average per month | **1.69M** |
| Latest month (August 2026, preliminary) | **1.83M** |
| WARN notices since 2023 (29 states) | **10,072** notices, **887K** workers |

### Findings

- BLS counted **21.24M** layoffs and discharges in 2025, **+6.1%** compared with 2024 (20.01M).
- Through August 2026, 2026 averages **1.69M a month**, **-4.7%** versus the 2025 monthly average.
- States with the most layoffs and discharges in 2025: **CA** (2.4M), **TX** (1.7M), **NY** (1.5M).
- Notices of 1,000+ workers were **0.5%** of WARN notices but **12.7%** of the workers named in them.
- Largest single WARN notice since 2023: **Tend Exchange Subsidiary LLC and Delaware Tender Staffing
LLC** (nan, CA), **16,132** workers, May 2025.
- Trend match with BLS (rank correlation, 1 = same direction every month): unemployment claims **0.32**, WARN **-0.37**.

### Charts

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/charts/bls_monthly-dark.png">
  <img alt="Monthly US layoffs and discharges, BLS JOLTS" src="docs/charts/bls_monthly-light.png">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/charts/bls_yearly-dark.png">
  <img alt="Average monthly layoffs by year" src="docs/charts/bls_yearly-light.png">
</picture>

| Year | Months | Total | Average per month |
|---|---|---|---|
| 2023 | 12 | 19.85M | 1.65M |
| 2024 | 12 | 20.01M | 1.67M |
| 2025 | 12 | 21.24M | 1.77M |
| 2026 | 8 | 13.49M | 1.69M |

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/charts/sources_trend-dark.png">
  <img alt="Three sources indexed to 2023 = 100" src="docs/charts/sources_trend-light.png">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/charts/top_states-dark.png">
  <img alt="Top states by layoffs and discharges" src="docs/charts/top_states-light.png">
</picture>

<details><summary>All states table</summary>

| Rank | State | Layoffs & discharges |
|---|---|---|
| 1 | CA | 2.4M |
| 2 | TX | 1.7M |
| 3 | NY | 1.5M |
| 4 | FL | 1.4M |
| 5 | IL | 897K |
| 6 | OH | 819K |
| 7 | NJ | 723K |
| 8 | PA | 713K |
| 9 | MI | 667K |
| 10 | GA | 616K |
| 11 | NC | 581K |
| 12 | IN | 580K |
| 13 | VA | 557K |
| 14 | CO | 507K |
| 15 | TN | 501K |
| 16 | MA | 447K |
| 17 | WA | 401K |
| 18 | AZ | 388K |
| 19 | WI | 374K |
| 20 | SC | 326K |
| 21 | MN | 324K |
| 22 | MO | 317K |
| 23 | MD | 304K |
| 24 | KY | 279K |
| 25 | ID | 276K |
| 26 | LA | 268K |
| 27 | NV | 261K |
| 28 | CT | 252K |
| 29 | UT | 245K |
| 30 | AL | 240K |
| 31 | OR | 230K |
| 32 | OK | 219K |
| 33 | IA | 200K |
| 34 | KS | 191K |
| 35 | AR | 170K |
| 36 | MS | 151K |
| 37 | NE | 133K |
| 38 | NM | 113K |
| 39 | NH | 109K |
| 40 | ME | 96.0K |
| 41 | MT | 95.0K |
| 42 | RI | 93.0K |
| 43 | WV | 84.0K |
| 44 | DC | 74.0K |
| 45 | HI | 72.0K |
| 46 | ND | 68.0K |
| 47 | SD | 67.0K |
| 48 | DE | 64.0K |
| 49 | AK | 56.0K |
| 50 | VT | 46.0K |
| 51 | WY | 44.0K |

</details>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/charts/top_cities-dark.png">
  <img alt="Top cities by WARN workers" src="docs/charts/top_cities-light.png">
</picture>

| City | State | WARN notices | Workers |
|---|---|---|---|
| Chicago | IL | 23 | 16,639 |
| Various Locations In Washington | WA | 35 | 12,053 |
| Austin | TX | 60 | 11,174 |
| Nationwide | WA | 1 | 9,266 |
| Brewster | WA | 2 | 6,910 |
| Seattle | WA | 61 | 6,608 |
| Philadelphia | PA | 63 | 6,458 |
| Dallas | TX | 35 | 6,018 |
| Hillsboro | OR | 25 | 5,845 |
| Houston | TX | 55 | 5,650 |
| Portland | OR | 63 | 5,169 |
| San Antonio | TX | 47 | 5,154 |
| Redmond | WA | 19 | 4,642 |
| New York | NY | 58 | 4,249 |
| Fort Worth | TX | 31 | 4,165 |

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/charts/size_mix-dark.png">
  <img alt="Share of notices vs workers by layoff size" src="docs/charts/size_mix-light.png">
</picture>

| Layoff size | Notices | Share of notices | Workers | Share of workers |
|---|---|---|---|---|
| Small (<50) | 4,802 | 50.2% | 78,475 | 8.8% |
| Medium (50-249) | 4,183 | 43.7% | 453,899 | 51.2% |
| Large (250-999) | 535 | 5.6% | 242,218 | 27.3% |
| Mega (1000+) | 45 | 0.5% | 112,381 | 12.7% |

### How to read this

- **BLS JOLTS** counts every employer-initiated separation (layoffs *and* firings), all business sizes. State numbers are model-based estimates and are released once a year (each July).
- **DOL claims** count people filing for unemployment. Not every laid-off worker files, so it's a trend signal.
- **WARN notices** cover larger layoffs only (usually 50+ workers at employers with 100+ staff), from the 29 states whose data could be collected. Cities come from WARN only.
- Sept and Oct 2025 BLS data were affected by the federal government shutdown.

<!-- RESULTS:END -->

## How it works

1. **Collect.** Downloads WARN notices state by state, monthly JOLTS and quarterly BED data from the BLS API, and weekly unemployment claims from the Department of Labor.
2. **Clean.** Every state formats its WARN file differently, so the program finds the company, city, worker and date columns by name *and* by checking what's inside them. It removes duplicates, impossible dates and invalid values, and labels preliminary or shutdown-affected months.
3. **Cross-check.** Compares the sources month by month and state by state, and flags anything impossible (for example, more WARN layoffs than the official total).
4. **Report.** Saves an Excel workbook with every table, then `make_charts.py` draws the charts, finds the seasonal pattern, compares with Challenger's figures, and writes the Results section above.

A `warn_column_map` sheet shows exactly which columns were used for each state, and `source_status` shows which sources and states worked on each run.

## Project structure

```
us_layoff_tracker/
├── us_layoffs_tracker.py          # main program: collect, clean, cross-check, save report
├── make_charts.py                 # charts + Results section (runs automatically after the main program)
├── requirements.txt               # Python packages needed
├── reference/
│   └── challenger_job_cuts.csv    # Challenger figures, one row per period, with source link
├── docs/
│   ├── charts/                    # charts (light + dark versions), created automatically
│   └── RESULTS.md                 # results page, created automatically
├── layoffs_output/                # Excel report + CSVs (not uploaded to GitHub)
└── warn_data/                     # downloaded WARN files (not uploaded to GitHub)
```

## Setup

```bash
conda create -n layoffs python=3.11 -y
conda activate layoffs
pip install -r requirements.txt
conda env config vars set BLS_API_KEY="your_key" CONTACT_EMAIL="you@email.com"
conda deactivate && conda activate layoffs
```

Get a free BLS API key: https://data.bls.gov/registrationEngine/

## Run

```bash
python us_layoffs_tracker.py               # everything: all 50 states + DC, report, charts, README (first run: 30–90 minutes)
python us_layoffs_tracker.py --skip-warn   # same, but reuse downloaded WARN files (about 1–2 minutes)
python us_layoffs_tracker.py --states MI   # one state, for testing
python make_charts.py                      # only rebuild charts and Results from the saved report
```

Outputs:
- `layoffs_output/us_layoffs_report.xlsx`: every table (one sheet each), plus CSV copies
- `docs/charts/`: charts in light and dark versions
- `docs/RESULTS.md` and the Results section of this README, updated automatically

## Keeping it up to date

- **BLS, DOL and WARN data** refresh automatically every time you run the program.
- **Challenger figures** don't have a download, so add one line to `reference/challenger_job_cuts.csv` when each monthly report comes out (early each month):
  ```
  2026-10,month,NUMBER_FROM_REPORT,LINK_TO_REPORT
  ```
- **A state whose WARN data can't be downloaded:** save the state's official WARN list as `warn_data/manual/<state>.xlsx` (for example `mi.xlsx`). It's used automatically.

## Limitations

- WARN covers mostly large layoffs (generally 50+ workers at employers with 100+ staff). Small layoffs are counted only in the BLS totals.
- Since 2026, BLS publishes **state** JOLTS data once a year (each July), so the newest state months lag the national data.
- BLS revises up to five years of data each January, so numbers can change between runs.
- September and October 2025 BLS data were affected by the federal government shutdown.
- Some states' WARN files list only a notice date or only a layoff date, and some list a county instead of a city.
- Challenger's 2024 figures are available by quarter only, and its 2022–2023 totals come from news coverage of its reports.
- State websites change, so some states may fail on a given day. Check the `source_status` sheet.