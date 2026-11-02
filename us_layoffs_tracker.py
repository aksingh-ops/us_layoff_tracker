"""
US Layoffs Tracker (2023 -> today)
==================================
Pulls layoff data from three trusted, public sources and cross-checks them:

  1. WARN notices (state labor departments, collected by Stanford's Big Local News
     `warn-scraper`)  -> company, city, state, date, number of workers.  Event-level.
  2. BLS JOLTS "Layoffs and Discharges" (U.S. Bureau of Labor Statistics)
     -> official monthly estimate of ALL layoffs, big and small, national + every state.
  3. DOL ETA-539 weekly initial unemployment claims (U.S. Department of Labor)
     -> how many people filed for unemployment each week, by state.

Outputs:
  - layoffs_output/us_layoffs_report.xlsx : every table (one sheet each) + CSV copies
  - docs/charts/*.png, docs/RESULTS.md and the README "Results" section (via make_charts.py)

Setup:
  pip install -r requirements.txt
  Free BLS API key: https://data.bls.gov/registrationEngine/  (saved as BLS_API_KEY)

Run:
  python us_layoffs_tracker.py                 # all states
  python us_layoffs_tracker.py --skip-warn     # reuse WARN files already downloaded (fast)
  python us_layoffs_tracker.py --states MI,CA  # only some states (for testing)
  python us_layoffs_tracker.py --refresh       # re-download WARN files even if downloaded today
"""

import argparse
import io
import json
import os
import re
import subprocess
import warnings
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests

# ----------------------------------------------------------------------------
# STEP 0. Settings
# ----------------------------------------------------------------------------
START_DATE = pd.Timestamp("2023-01-01")
END_YEAR = date.today().year
OUT_DIR = Path("layoffs_output")
WARN_DIR = Path("warn_data")
BLS_KEY = os.getenv("BLS_API_KEY")
HEADERS = {"User-Agent": f"layoffs-research ({os.getenv('CONTACT_EMAIL', 'contact@example.com')})"}

# State postal code -> FIPS code (BLS uses FIPS codes inside its series IDs)
STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09",
    "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17",
    "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24",
    "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30", "NE": "31",
    "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56",
}

# Layoff size buckets (number of workers in one notice)
SIZE_BINS = [0, 49, 249, 999, np.inf]
SIZE_LABELS = ["Small (<50)", "Medium (50-249)", "Large (250-999)", "Mega (1000+)"]

status_log = []  # every success/failure goes here -> source_status.csv


def log(source, item, ok, note=""):
    status_log.append({"source": source, "item": item, "ok": ok, "note": note})
    print(f"[{'OK ' if ok else 'ERR'}] {source:6} {item:6} {note}")


# ----------------------------------------------------------------------------
# STEP 1. Download WARN notices state by state
# ----------------------------------------------------------------------------
def download_warn(states, refresh=False):
    WARN_DIR.mkdir(exist_ok=True)
    for st in states:
        f = WARN_DIR / f"{st.lower()}.csv"
        if not refresh and f.exists() and f.stat().st_size > 0 and \
                (pd.Timestamp.now().timestamp() - f.stat().st_mtime) < 20 * 3600:
            log("WARN", st, True, "using today's file (already downloaded)")
            continue
        try:
            subprocess.run(
                ["warn-scraper", st, "--data-dir", str(WARN_DIR)],
                check=True, capture_output=True, text=True, timeout=1200,
            )
            log("WARN", st, True, "downloaded")
        except FileNotFoundError:
            raise SystemExit("warn-scraper is not installed. Run: pip install warn-scraper")
        except Exception as e:  # some state websites break or are not supported
            msg = getattr(e, "stderr", "") or str(e)
            log("WARN", st, False, msg.strip().splitlines()[-1][:150] if msg else "failed")


# ----------------------------------------------------------------------------
# STEP 2. Clean WARN files (every state uses different column names)
# ----------------------------------------------------------------------------
# Words we look for in column names. The code also checks what is INSIDE each
# column (dates? numbers? text?), so a column called "Notice Type" is never
# mistaken for a date, and files with odd or missing headers still work.
HINTS = {
    "company": ["company", "employer", "business", "organization", "name"],
    "city": ["city", "location", "county", "region", "site", "address"],
    "workers": ["expected layoff", "revised layoff", "affected", "employees", "workers", "emp",
                "number", "jobs", "layoff", "total", "headcount", "count", "laid off", "#"],
    "notice": ["notice date", "date of notice", "date of warn notice", "initial report date",
               "notification date", "initial date reported", "received", "warn date",
               "date filed", "date posted", "month posted", "posted", "notice", "date received"],
    "layoff": ["effective", "layoff date", "separation", "closing", "start", "date"],
}
AVOID = {
    "company": ["contact", "date", "phone", "email"],
    "city": ["zip", "state", "date"],
    "workers": ["date", "phone", "zip", "naics", "code", "type", "address", "id", "approximate", "full-time"],
    "notice": ["type"],
    "layoff": ["type"],
}


def to_number(series):
    """'1,250 (approx.)' -> 1250"""
    return pd.to_numeric(
        series.astype(str).str.replace(",", "").str.extract(r"(\d+)")[0], errors="coerce"
    )


def to_date(series):
    """Turn many date styles (10/29/2026, 2026-10-29, Oct 29 2026) into real dates."""
    s = series.astype(str).str.strip()
    # Pull the first date out of messy text, e.g. "03/04/2025 (updated 04/01/2025)"
    # or a range like "10/15/2025 - 11/30/2025" -> "03/04/2025" / "10/15/2025"
    first = s.str.extract(r"(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{1,2}-\d{1,2}(?:[T ][\d:\.]+(?:Z|[+-]\d{2}:?\d{2})?)?"
                          r"|[A-Za-z]{3,9}\.? \d{1,2},? \d{4})", expand=False)
    s = first.fillna(s)
    # Only text that looks like a date (has / or - or a month name) - stops '27' becoming a date
    looks = s.str.contains(r"[/\-]|[A-Za-z]{3}", regex=True) & (s.str.len() >= 6)
    s = s.where(looks)
    try:
        # utc=True handles files that mix time zones (e.g. "...-05:00" and "...Z")
        out = pd.to_datetime(s, errors="coerce", format="mixed", utc=True).dt.tz_localize(None)
    except Exception:
        # Last resort: parse one cell at a time so one strange cell can't stop everything
        out = s.apply(lambda v: pd.to_datetime(v, errors="coerce", utc=True))
        out = pd.to_datetime(out, errors="coerce", utc=True).dt.tz_localize(None)
    # Throw away impossible dates (typos like 0001-01-01 or 2205) and use one standard
    # date format for every state, so dates from different columns can be combined.
    out = out.dt.normalize()                      # keep the day, drop the clock time
    out = out.where((out.dt.year >= 1990) & (out.dt.year <= 2100))
    return out.astype("datetime64[ns]")


def share_filled(values):
    """Fraction of non-empty cells that converted successfully."""
    return values.notna().mean() if len(values) else 0.0


def profile(raw):
    """For each column: how many cells look like dates, numbers, digits-in-text."""
    prof = {}
    for c in raw.columns:
        s = raw[c].dropna().astype(str).str.strip()
        s = s[s != ""].head(400)
        prof[c] = {
            "date": share_filled(to_date(s)) if len(s) else 0.0,
            "num": share_filled(to_number(s)) if len(s) else 0.0,
            "pure_num": s.str.fullmatch(r"[\d,\.\s]+").mean() if len(s) else 0.0,
            "has_digit": s.str.contains(r"\d").mean() if len(s) else 0.0,
            "unique": s.nunique() / len(s) if len(s) else 0.0,
            "median": to_number(s).median() if len(s) else np.nan,
        }
    return prof


def by_name(cols, kind, ok):
    """First column whose NAME matches a hint AND whose CONTENT passes the check."""
    for kw in HINTS[kind]:
        for c in cols:
            name = str(c).lower().strip()
            starts_word = re.search(r"(^|[^a-z])" + re.escape(kw), name)
            if starts_word and not any(a in name for a in AVOID[kind]) and ok(c):
                return c
    return None


def map_columns(raw):
    cols = list(raw.columns)
    p = profile(raw)
    # A column whose NAME already says what it is only needs a light content check;
    # a column chosen by CONTENT alone must pass a stricter check.
    named_date = lambda c: p[c]["date"] >= 0.3
    strict_date = lambda c: p[c]["date"] >= 0.6
    named_workers = lambda c: (p[c]["num"] >= 0.3 and p[c]["date"] < 0.3
                               and (pd.isna(p[c]["median"]) or p[c]["median"] < 10000))
    strict_workers = lambda c: (p[c]["num"] >= 0.6 and p[c]["date"] < 0.3 and p[c]["pure_num"] >= 0.6
                                and (pd.isna(p[c]["median"]) or p[c]["median"] < 10000))
    is_text = lambda c: p[c]["date"] < 0.3 and p[c]["pure_num"] < 0.3

    notice = by_name(cols, "notice", named_date)
    layoff = by_name([c for c in cols if c != notice], "layoff", named_date)
    workers = by_name(cols, "workers", named_workers)
    company = by_name(cols, "company", is_text)
    city = by_name(cols, "city", is_text)

    # Content-based backups (e.g. a file with no header row). Prefer columns named "...date..."
    date_cols = sorted([c for c in cols if strict_date(c)],
                       key=lambda c: (0 if re.search(r"(^|[^a-z])date", str(c).lower()) else 1, cols.index(c)))
    if not notice and not layoff and date_cols:
        notice = date_cols[0]
        layoff = date_cols[1] if len(date_cols) > 1 else None
    if not workers:
        nums = [c for c in cols if c not in date_cols and strict_workers(c)]
        workers = nums[-1] if nums else None   # NAICS codes are big (>10000) so they're skipped
    if not company:
        texts = [c for c in cols if is_text(c) and p[c]["unique"] > 0.3]
        company = min(texts, key=lambda c: p[c]["has_digit"]) if texts else None  # addresses have digits
    return company, city, workers, notice, layoff


def read_state_file(path):
    read = (lambda **kw: pd.read_excel(path, dtype=str, **kw)) if path.suffix in (".xlsx", ".xls") \
        else (lambda **kw: pd.read_csv(path, dtype=str, on_bad_lines="skip", **kw))
    raw = read()
    # If rows have MORE values than the header has names (e.g. Wisconsin merged two headers),
    # pandas silently turns the first column into row labels and every header slides one
    # column over. Re-read so columns line up from the left again.
    if path.suffix == ".csv" and not isinstance(raw.index, pd.RangeIndex):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = read(index_col=False)
    # Some states' files have no header row: the "column names" are really data
    looks_like_data = sum(bool(re.fullmatch(r"[\d/\-\.,\s]+", str(c).strip())) for c in raw.columns)
    if looks_like_data >= 2:
        raw = read(header=None)
        raw.columns = [f"col_{i}" for i in range(raw.shape[1])]
    raw.columns = [str(c).strip() for c in raw.columns]
    return raw


MANUAL_DIR = WARN_DIR / "manual"   # put hand-downloaded state files here, e.g. warn_data/manual/mi.xlsx


def find_state_file(st):
    """Use a hand-downloaded file first (if you added one), otherwise the scraper's file."""
    for ext in ("csv", "xlsx", "xls"):
        p = MANUAL_DIR / f"{st.lower()}.{ext}"
        if p.exists():
            return p, "manual"
    p = WARN_DIR / f"{st.lower()}.csv"
    return (p if p.exists() else None), "scraper"


COLUMN_MAP = []   # one row per state: which columns were used -> sheet "warn_column_map"


def clean_warn(states):
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    for st in states:
        path, origin = find_state_file(st)
        if path is None:
            continue
        try:
            raw = read_state_file(path)
        except pd.errors.EmptyDataError:
            log("WARN", st, False, "downloaded file is empty")
            continue
        except Exception as e:
            log("WARN", st, False, f"could not read file: {e}"[:150])
            continue

        company, city, workers, notice_date, layoff_date = map_columns(raw)
        COLUMN_MAP.append({"state": st, "source": origin, "file": path.name, "rows": len(raw),
                           "company_col": company, "city_col": city, "workers_col": workers,
                           "notice_date_col": notice_date, "layoff_date_col": layoff_date,
                           "all_columns": " | ".join(map(str, raw.columns))})
        if not (company and (notice_date or layoff_date)):
            log("WARN", st, False,
                f"could not map columns (company={company}, workers={workers}, "
                f"date={notice_date or layoff_date}); columns: {list(raw.columns)[:10]}"[:300])
            continue

        df = pd.DataFrame({
            "state": st,
            "company": raw[company].astype(str).str.strip(),
            "city": raw[city].astype(str).str.strip().str.title() if city else "Unknown",
            "workers": to_number(raw[workers]) if workers else np.nan,
            "notice_date": to_date(raw[notice_date]) if notice_date else pd.NaT,
            "layoff_date": to_date(raw[layoff_date]) if layoff_date else pd.NaT,
        })
        # Use the notice date first (when the public learned about it); fall back to layoff date
        df["date"] = df["notice_date"].fillna(df["layoff_date"])
        all_rows = len(df)
        latest = df["date"].max()
        df = df[df["date"].notna() & (df["date"] >= START_DATE) & (df["date"] <= pd.Timestamp.today())]
        latest_txt = latest.date() if pd.notna(latest) else "none"
        note = (f"{len(df):,} notices since 2023 (of {all_rows:,} rows; date column "
                f"'{notice_date or layoff_date}'; latest {latest_txt}; source: {origin} file)")
        if not workers:
            note += " - NOTE: no usable worker-count column, notices counted but workers = 0"
        stale = pd.isna(latest) or latest < pd.Timestamp.today() - pd.DateOffset(months=6)
        if stale:
            note += " - WARNING: newest notice is over 6 months old, state file may be outdated"
        w = df["workers"]
        avg_w = round(w.mean(), 1) if w.notna().any() else np.nan
        max_w = w.max() if w.notna().any() else np.nan
        odd = (pd.notna(max_w) and max_w > 20000) or (pd.notna(avg_w) and avg_w > 1000)
        COLUMN_MAP[-1].update({
            "date_type": "notice date" if notice_date else "layoff/effective date",
            "notices_since_2023": len(df), "workers_since_2023": int(w.fillna(0).sum()),
            "avg_workers_per_notice": avg_w, "max_workers_one_notice": max_w,
            "latest_notice": latest_txt, "looks_outdated": bool(stale),
            "check": "CHECK: unusually large worker numbers - wrong column?" if odd else "ok"})
        if odd:
            note += f" - CHECK: avg {avg_w} / max {max_w} workers per notice looks too large"
        frames.append(df)
        log("WARN", st, len(df) > 0, note)

    if not frames:
        return pd.DataFrame()

    warn = pd.concat(frames, ignore_index=True)
    warn["workers"] = warn["workers"].fillna(0).astype(int)

    # Remove duplicate notices (same company, state, date, workers)
    warn["company_key"] = warn["company"].str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
    before = len(warn)
    warn = warn.drop_duplicates(["state", "company_key", "date", "workers"]).drop(columns="company_key")
    print(f"Removed {before - len(warn):,} duplicate WARN rows")

    warn["year"] = warn["date"].dt.year
    warn["quarter"] = warn["date"].dt.to_period("Q").astype(str)
    warn["month"] = warn["date"].dt.to_period("M").astype(str)
    warn["size_group"] = pd.cut(warn["workers"], SIZE_BINS, labels=SIZE_LABELS)
    return warn


# ----------------------------------------------------------------------------
# STEP 3. Official BLS data (JOLTS monthly + BED quarterly)
# ----------------------------------------------------------------------------
# Facts from BLS documentation that shape this code:
#  - JOLTS series IDs are 21 characters: JT + S/U + industry(6) + state(2) + area(5)
#    + size class(2) + data element(2, "LD" = layoffs & discharges) + rate/level(1, "L").
#  - Levels are in THOUSANDS. Unavailable values come back as "-" (not a number).
#  - "Layoffs and discharges" = ALL employer-initiated separations, including firings.
#  - National JOLTS is monthly (~5 weeks late). Since 2026, STATE JOLTS is released
#    ONCE A YEAR (each July, covering the prior calendar year's months).
#  - State JOLTS numbers are model-based estimates, not direct counts.
#  - The Oct-Nov 2025 government shutdown disrupted collection: Sep-2025 used partial
#    data and Oct-2025 was collected late, so those months are flagged.
#  - BED (Business Employment Dynamics) counts gross job losses from unemployment-
#    insurance records (all business sizes), quarterly, about 7 months late.
SHUTDOWN_MONTHS = {"2025-09", "2025-10"}
BLS_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"


def clean_bls_value(v):
    """Return a real number, or NaN for '-', '(NA)', blanks, negatives or sentinel codes."""
    try:
        x = float(str(v).replace(",", ""))
    except ValueError:
        return np.nan
    return x if 0 <= x < 1e8 else np.nan   # catches ACS-style codes like -666666666


BLS_CACHE_DIR = Path("bls_cache")


def bls_request(series_ids, label):
    """Ask the BLS API for many series, in batches. Returns {series_id: [data points]}.
    Answers are saved in bls_cache/. A run on the same day reuses them (BLS allows only
    25 requests/day without a key, 500 with a key), and if BLS refuses or is down,
    the newest saved answer is used instead so the report never silently loses data."""
    BLS_CACHE_DIR.mkdir(exist_ok=True)
    today_file = BLS_CACHE_DIR / f"{label.lower()}_{date.today():%Y-%m-%d}.json"
    if today_file.exists():
        saved = json.loads(today_file.read_text())
        if set(series_ids) <= set(saved.get("requested", [])):
            cached = saved["data"]
            log(label, "cache", True, f"using today's saved BLS answer ({len(cached)} series)")
            return {k: cached[k] for k in series_ids if k in cached}

    batch = 50 if BLS_KEY else 25
    out, failed = {}, False
    for i in range(0, len(series_ids), batch):
        payload = {"seriesid": series_ids[i:i + batch],
                   "startyear": str(START_DATE.year), "endyear": str(END_YEAR)}
        if BLS_KEY:
            payload["registrationkey"] = BLS_KEY
        try:
            res = requests.post(BLS_API, json=payload, headers=HEADERS, timeout=120).json()
        except Exception as e:
            log(label, f"batch{i // batch}", False, str(e)[:150])
            failed = True
            continue
        msgs = " | ".join(m for m in res.get("message", []) if m)
        if res.get("status") != "REQUEST_SUCCEEDED":
            hint = " -> add a free BLS API key (see README)" if "threshold" in msgs else ""
            log(label, f"batch{i // batch}", False, (msgs[:180] or "request failed") + hint)
            failed = True
            continue
        got = 0
        for s in res["Results"]["series"]:
            if s.get("data"):
                out[s["seriesID"]] = s["data"]
                got += 1
        log(label, f"batch{i // batch}", True,
            f"{got}/{len(payload['seriesid'])} series returned data" + (f" ({msgs[:120]})" if msgs else ""))

    if not failed and out:
        today_file.write_text(json.dumps({"requested": series_ids, "data": out}))
        return out
    # Something failed: fill the gaps from the newest saved answer, and say so
    older = sorted(BLS_CACHE_DIR.glob(f"{label.lower()}_*.json"))
    if older:
        cached = json.loads(older[-1].read_text()).get("data", {})
        filled = [k for k in series_ids if k not in out and k in cached]
        for k in filled:
            out[k] = cached[k]
        if filled:
            log(label, "cache", True, f"filled {len(filled)} series from saved file {older[-1].name}")
    return out


def jolts_series_id(fips="00"):
    # JT + U(not seasonally adjusted, so months can be added up) + 000000(total nonfarm)
    # + state + 00000(area) + 00(all sizes) + LD(layoffs & discharges) + L(level)
    return f"JTU000000{fips}0000000LDL"


def fetch_jolts(states):
    ids = {jolts_series_id(): "US"}
    ids.update({jolts_series_id(STATE_FIPS[s]): s for s in states})
    data = bls_request(list(ids), "JOLTS")
    rows = []
    for sid, points in data.items():
        for d in points:
            if not d["period"].startswith("M") or d["period"] == "M13":   # M13 = annual average
                continue
            month = f"{d['year']}-{d['period'][1:]}"
            val = clean_bls_value(d["value"])
            notes = [f.get("text", "") for f in d.get("footnotes", []) if f and f.get("text")]
            prelim = any(f.get("code") == "P" for f in d.get("footnotes", []) if f)
            quality = "preliminary" if prelim else "final"
            if month in SHUTDOWN_MONTHS:
                quality += "; 2025 shutdown-affected month"
            if pd.isna(val):
                quality += "; value not available"
            rows.append({"state": ids[sid], "month": month,
                         "jolts_layoffs": val * 1000 if pd.notna(val) else np.nan,  # thousands -> people
                         "quality": quality, "bls_footnotes": "; ".join(notes)})
    df = pd.DataFrame(rows, columns=["state", "month", "jolts_layoffs", "quality", "bls_footnotes"])
    if not df.empty:
        st_df = df[df["state"] != "US"].dropna(subset=["jolts_layoffs"])
        us_df = df[df["state"] == "US"].dropna(subset=["jolts_layoffs"])
        log("JOLTS", "latest", True,
            f"national through {us_df['month'].max() if len(us_df) else 'n/a'}; "
            f"states through {st_df['month'].max() if len(st_df) else 'n/a'} (state data is released yearly)")
    return df


def bed_series_id(area="0000000000"):
    # BD + S(seasonally adjusted) + area(10) + 000000(total private) + 1(establishment)
    # + 1(employment) + 00(all sizes) + 04(gross job losses) + L(level) + Q(quarterly) + 5(private)
    return "BDS" + area + "000000" + "1" + "1" + "00" + "04" + "L" + "Q" + "5"


def fetch_bed(states):
    """Quarterly gross job losses (all business sizes). National ID is verified;
    state IDs follow BLS's area-code pattern and are reported as missing if BLS rejects them."""
    ids = {bed_series_id(): "US"}
    ids.update({bed_series_id(f"00000{STATE_FIPS[s]}000"): s for s in states})
    data = bls_request(list(ids), "BED")
    rows = []
    for sid, points in data.items():
        for d in points:
            if not d["period"].startswith("Q"):
                continue
            val = clean_bls_value(d["value"])
            rows.append({"state": ids[sid], "quarter": f"{d['year']}Q{d['period'][-1]}",
                         "bed_gross_job_losses": val * 1000 if pd.notna(val) else np.nan})
    df = pd.DataFrame(rows, columns=["state", "quarter", "bed_gross_job_losses"])
    states_found = sorted(set(df["state"]) - {"US"})
    log("BED", "coverage", not df.empty,
        f"national {'ok' if 'US' in set(df['state']) else 'missing'}; {len(states_found)} states returned data")
    return df


# ----------------------------------------------------------------------------
# STEP 4. DOL weekly initial unemployment claims by state (ETA-539)
# ----------------------------------------------------------------------------
# ETA-539 layout (DOL handbook 402): c1 = week number, c2 = reflected week ending,
# c3 = IC (state initial claims), c8 = continued weeks claimed, ...
# DOL's own edit rules say c3 can never be negative or empty, so anything else is bad data.
def fetch_ui_claims(states):
    url = "https://oui.doleta.gov/unemploy/csv/ar539.csv"
    try:
        r = requests.get(url, headers=HEADERS, timeout=180)
        r.raise_for_status()
        ui = pd.read_csv(io.StringIO(r.text), dtype=str)
        ui.columns = [c.strip().lower() for c in ui.columns]
        ui["week_end"] = pd.to_datetime(ui["rptdate"], errors="coerce", format="mixed")
        ui = ui[(ui["week_end"] >= START_DATE) & (ui["st"].str.strip().isin(states))].copy()
        ui["st"] = ui["st"].str.strip()
        ui["initial_claims"] = ui["c3"].apply(clean_bls_value)
        bad = int(ui["initial_claims"].isna().sum())
        ui["month"] = ui["week_end"].dt.to_period("M").astype(str)
        monthly = ui.groupby(["st", "month"], as_index=False).agg(
            initial_claims=("initial_claims", "sum"), weeks=("initial_claims", "count"))
        log("UI", "all", True, f"latest week {ui['week_end'].max().date()}; {bad} invalid values removed")
        return monthly.rename(columns={"st": "state"})
    except Exception as e:
        log("UI", "all", False, str(e)[:150])
        return pd.DataFrame(columns=["state", "month", "initial_claims", "weeks"])


# ----------------------------------------------------------------------------
# STEP 5. Summaries: year / quarter / month, state, city, size
# ----------------------------------------------------------------------------
def summarize(warn):
    agg = {"notices": ("company", "count"), "workers": ("workers", "sum")}
    t = {}
    t["warn_clean"] = warn.sort_values("date")
    t["us_by_year"] = warn.groupby("year").agg(**agg).reset_index()
    t["us_by_quarter"] = warn.groupby("quarter").agg(**agg).reset_index()
    t["us_by_month"] = warn.groupby("month").agg(**agg).reset_index()
    for x in ("us_by_year", "us_by_quarter", "us_by_month"):
        t[x]["change_vs_prev_%"] = (t[x]["workers"].pct_change() * 100).round(1)
    t["state_by_year"] = warn.groupby(["state", "year"]).agg(**agg).reset_index()
    t["state_by_quarter"] = warn.groupby(["state", "quarter"]).agg(**agg).reset_index()
    t["state_by_month"] = warn.groupby(["state", "month"]).agg(**agg).reset_index()
    t["city_by_year"] = (warn.groupby(["state", "city", "year"]).agg(**agg).reset_index()
                         .sort_values("workers", ascending=False))
    t["city_by_quarter"] = warn.groupby(["state", "city", "quarter"]).agg(**agg).reset_index()
    t["size_by_year"] = warn.groupby(["year", "size_group"], observed=False).agg(**agg).reset_index()
    t["top_100_events"] = warn.nlargest(100, "workers")[["date", "state", "city", "company", "workers"]]
    return t


# ----------------------------------------------------------------------------
# STEP 6. Cross-verification between the three sources
# ----------------------------------------------------------------------------
def cross_verify(warn, jolts, ui, bed, states):
    checks = {}
    warn_m = warn.groupby(["state", "month"], as_index=False)["workers"].sum().rename(columns={"workers": "warn_workers"})
    st_jolts = jolts[jolts["state"] != "US"]
    latest_state_month = st_jolts.dropna(subset=["jolts_layoffs"])["month"].max() if len(st_jolts) else None
    cm = (st_jolts.merge(warn_m, on=["state", "month"], how="outer")
          .merge(ui, on=["state", "month"], how="outer")
          .sort_values(["state", "month"]))
    cm = cm[cm["month"] >= START_DATE.strftime("%Y-%m")]
    cm["warn_share_of_jolts_%"] = (cm["warn_workers"] / cm["jolts_layoffs"] * 100).round(1)

    def flag(r):
        if pd.isna(r["jolts_layoffs"]):
            if latest_state_month and r["month"] > latest_state_month:
                return "No BLS state number yet (state JOLTS is released once a year, each July)"
            return "BLS value not available"
        if pd.notna(r["warn_workers"]) and r["warn_workers"] > r["jolts_layoffs"]:
            return "CHECK: WARN > BLS total (duplicate notices or notice/layoff timing)"
        if pd.isna(r["warn_workers"]):
            return "No WARN data for this state/month"
        if isinstance(r.get("quality"), str) and "shutdown" in r["quality"]:
            return "Consistent (BLS month affected by 2025 shutdown - lower confidence)"
        return "Consistent"
    cm["verification"] = cm.apply(flag, axis=1)
    checks["crosscheck_state_month"] = cm

    # Per state: does WARN move up/down together with BLS and UI claims? (correlation)
    rows = []
    for st, g in cm.groupby("state"):
        g = g.dropna(subset=["warn_workers"])
        def corr(a, b):
            gg = g.dropna(subset=[a, b])
            # Spearman "trend match" = correlation of the ranks (no extra tools needed)
            return round(gg[a].rank().corr(gg[b].rank()), 2) if len(gg) >= 6 else np.nan
        both = g.dropna(subset=["jolts_layoffs"])
        rows.append({
            "state": st,
            "months_with_warn": len(g),
            "months_with_warn_and_bls": len(both),
            "warn_total": g["warn_workers"].sum(),
            "bls_jolts_total_same_months": both["jolts_layoffs"].sum(),
            "ui_claims_total": g["initial_claims"].sum(),
            "warn_as_%_of_bls": round(both["warn_workers"].sum() / both["jolts_layoffs"].sum() * 100, 2)
            if both["jolts_layoffs"].sum() else np.nan,
            "trend_match_warn_vs_bls": corr("warn_workers", "jolts_layoffs"),
            "trend_match_warn_vs_ui": corr("warn_workers", "initial_claims"),
            "months_flagged": (g["verification"].str.startswith("CHECK")).sum(),
        })
    checks["crosscheck_state_summary"] = pd.DataFrame(rows)

    # Quarterly check against BED (gross job losses from UI records, all business sizes)
    if not bed.empty:
        warn_q = warn.groupby(["state", "quarter"], as_index=False)["workers"].sum() \
            .rename(columns={"workers": "warn_workers"})
        us_q = warn.groupby("quarter", as_index=False)["workers"].sum().rename(columns={"workers": "warn_workers"})
        us_q["state"] = "US"
        bq = bed.merge(pd.concat([warn_q, us_q]), on=["state", "quarter"], how="left")
        bq["warn_as_%_of_bed"] = (bq["warn_workers"] / bq["bed_gross_job_losses"] * 100).round(2)
        bq["verification"] = np.where(bq["warn_workers"] > bq["bed_gross_job_losses"],
                                      "CHECK: WARN > all job losses", "Consistent")
        checks["crosscheck_bed_quarterly"] = bq.sort_values(["state", "quarter"])

    # Internal check: do the state BLS numbers add up close to the national BLS number?
    if len(states) == len(STATE_FIPS) and not jolts.empty:
        nat = jolts[jolts["state"] == "US"][["month", "jolts_layoffs"]].rename(columns={"jolts_layoffs": "bls_national"})
        sm = st_jolts.groupby("month", as_index=False).agg(bls_sum_of_states=("jolts_layoffs", "sum"),
                                                          states_reporting=("jolts_layoffs", "count"))
        nc = nat.merge(sm[sm["states_reporting"] == len(STATE_FIPS)], on="month")
        nc["gap_%"] = ((nc["bls_sum_of_states"] / nc["bls_national"] - 1) * 100).round(1)
        nc["verification"] = np.where(nc["gap_%"].abs() <= 10, "Consistent", "CHECK: >10% gap")
        checks["crosscheck_national"] = nc

    # National official picture by month / quarter / year (BLS = big + small layoffs)
    us = jolts[jolts["state"] == "US"].dropna(subset=["jolts_layoffs"]).copy()
    if not us.empty:
        us["date"] = pd.to_datetime(us["month"])
        us["year"], us["quarter"] = us["date"].dt.year, us["date"].dt.to_period("Q").astype(str)
        checks["bls_us_monthly"] = us[["month", "jolts_layoffs", "quality"]]
        checks["bls_us_quarterly"] = us.groupby("quarter", as_index=False).agg(
            jolts_layoffs=("jolts_layoffs", "sum"), months=("month", "count"))
        checks["bls_us_yearly"] = us.groupby("year", as_index=False).agg(
            jolts_layoffs=("jolts_layoffs", "sum"), months=("month", "count"))
    checks["bls_state_monthly"] = st_jolts
    checks["bed_quarterly"] = bed
    checks["ui_claims_monthly"] = ui
    return checks


# ----------------------------------------------------------------------------
# STEP 7. Save everything
# ----------------------------------------------------------------------------
def save(tables):
    OUT_DIR.mkdir(exist_ok=True)
    tables["source_status"] = pd.DataFrame(status_log)
    tables["warn_column_map"] = pd.DataFrame(COLUMN_MAP)
    with pd.ExcelWriter(OUT_DIR / "us_layoffs_report.xlsx", engine="openpyxl") as xl:
        for name, df in tables.items():
            df = df.copy()
            for c in df.columns:
                if df[c].dtype == object or pd.api.types.is_string_dtype(df[c]):
                    df[c] = df[c].map(lambda v: v[:32000] if isinstance(v, str) else v)
            df.to_excel(xl, sheet_name=name[:31], index=False)
            df.to_csv(OUT_DIR / f"{name}.csv", index=False)
    print(f"\nSaved {len(tables)} tables to {OUT_DIR.resolve()}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--states", default="ALL", help="Comma list like MI,CA,TX or ALL")
    p.add_argument("--skip-warn", action="store_true", help="Reuse WARN files already downloaded")
    p.add_argument("--refresh", action="store_true", help="Re-download WARN files even if downloaded today")
    a = p.parse_args()
    states = list(STATE_FIPS) if a.states.upper() == "ALL" else [s.strip().upper() for s in a.states.split(",")]

    if not a.skip_warn:
        download_warn(states, refresh=a.refresh)
    warn = clean_warn(states)
    if warn.empty:
        raise SystemExit("No WARN data loaded. Check source_status / internet connection.")

    have = sorted(warn["state"].unique())
    missing = [s for s in states if s not in have]
    print(f"\nWARN company-level data: {len(have)} states -> {', '.join(have)}")
    print(f"No WARN data (covered only by BLS + DOL totals): {len(missing)} -> {', '.join(missing)}\n")

    jolts = fetch_jolts(states)
    bed = fetch_bed(states)
    ui = fetch_ui_claims(states)

    tables = summarize(warn)
    tables.update(cross_verify(warn, jolts, ui, bed, states))
    save(tables)

    print("\n=== Quick view: WARN workers by year ===")
    print(tables["us_by_year"].to_string(index=False))
    if "bls_us_yearly" in tables:
        print("\n=== Official BLS JOLTS layoffs & discharges by year (all sizes; 'months' < 12 = partial year) ===")
        print(tables["bls_us_yearly"].to_string(index=False))

    # Charts + results section for the README (see make_charts.py)
    try:
        import make_charts
        make_charts.build()
    except Exception as e:
        print(f"\nCharts were not updated: {e}")


if __name__ == "__main__":
    main()