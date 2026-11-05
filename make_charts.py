"""
make_charts.py - turns the report in layoffs_output/ into:
  * docs/charts/*.png   - 12 charts, each in a light and a dark version
  * docs/tables/*.csv   - full tables (companies, every day, every month)
  * docs/RESULTS.md     - key numbers, findings, charts and tables
  * README.md           - the same results block, between the RESULTS markers

It runs automatically at the end of us_layoffs_tracker.py, or on its own:
  python make_charts.py

Every number in the text is calculated from the data, so the README
updates itself each time the tracker runs.
"""

import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                      # draw to files, no window needed
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

DATA = Path("layoffs_output")
CHART_DIR = Path("docs/charts")
RESULTS_MD = Path("docs/RESULTS.md")
README = Path("README.md")
START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"
CHALLENGER = Path("reference/challenger_job_cuts.csv")   # hand-entered from Challenger's monthly reports
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TABLE_DIR = Path("docs/tables")        # CSV tables - GitHub shows these as searchable tables
# Sequential blue ramp (steps 100 -> 700) for the heat grid; dark mode flips the anchor
SEQ = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
       "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]

# ---------------------------------------------------------------------------
# Colors (validated: colorblind-safe in light and dark mode)
# ---------------------------------------------------------------------------
THEMES = {
    "light": {"surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
              "grid": "#e1e0d9", "axis": "#c3c2b7",
              "series": ["#2a78d6", "#eb6834", "#1baf7a"],
              "ramp": ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"],
              "ramp_text": ["#0b0b0b", "#ffffff", "#ffffff", "#ffffff"],
              "years": ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"], "seq": SEQ},
    "dark": {"surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781",
             "grid": "#2c2c2a", "axis": "#383835",
             "series": ["#3987e5", "#d95926", "#199e70"],
             "ramp": ["#cde2fb", "#86b6ef", "#3987e5", "#184f95"],
             "ramp_text": ["#0b0b0b", "#0b0b0b", "#ffffff", "#ffffff"],
             "years": ["#184f95", "#3987e5", "#86b6ef", "#cde2fb"], "seq": SEQ[::-1]},
}
W_PX, H_PX, DPI = 1000, 560, 100           # drawn at 1000x560, saved at 2x for sharp screens
LINE_W = 2 * 72 / DPI                      # 2px line in points
# Use the system sans font that exists on this computer (Mac: Helvetica Neue), quietly
from matplotlib import font_manager
_installed = {f.name for f in font_manager.fontManager.ttflist}
plt.rcParams["font.family"] = [f for f in ("Helvetica Neue", "Helvetica", "Arial", "Segoe UI")
                               if f in _installed] + ["DejaVu Sans"]


def compact(n, digits=1):
    """1234567 -> '1.2M', 85432 -> '85K'"""
    if pd.isna(n):
        return "n/a"
    n = float(n)
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= size:
            v = n / size
            return f"{v:.{digits}f}{suffix}" if v < 100 else f"{v:.0f}{suffix}"
    return f"{n:,.0f}"


def axis_fmt(v, _=None):
    """Axis ticks: 1.25M, 1M, 750K, 20K (no false rounding, no trailing .0)."""
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= size:
            return f"{v / size:.2f}".rstrip("0").rstrip(".") + suffix
    return f"{v:,.0f}"


def pct(a, b):
    return (a / b - 1) * 100 if b else np.nan


def read(name):
    p = DATA / f"{name}.csv"
    return pd.read_csv(p) if p.exists() and p.stat().st_size > 0 else pd.DataFrame()


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
def new_figure(t, title, subtitle, source):
    fig = plt.figure(figsize=(W_PX / DPI, H_PX / DPI), dpi=DPI, facecolor=t["surface"])
    fig.text(0.04, 0.94, title, fontsize=15, fontweight="bold", color=t["ink"], ha="left", va="top")
    fig.text(0.04, 0.875, subtitle, fontsize=10.5, color=t["ink2"], ha="left", va="top")
    fig.text(0.04, 0.03, source, fontsize=8.5, color=t["muted"], ha="left", va="bottom")
    return fig


def style_axes(ax, t, grid_axis="y"):
    ax.set_facecolor(t["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["axis"])
    ax.spines["bottom"].set_linewidth(1 * 72 / DPI)
    ax.tick_params(colors=t["muted"], labelsize=9, length=0, pad=6)
    ax.grid(axis=grid_axis, color=t["grid"], linewidth=1 * 72 / DPI)
    ax.set_axisbelow(True)


def px_to_data(ax, px_x=0, px_y=0):
    """Convert screen pixels to data units (to size bars and rounded corners exactly)."""
    bbox = ax.get_window_extent()
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    return px_x * (x1 - x0) / bbox.width, px_y * (y1 - y0) / bbox.height


def rounded_bar(ax, t, x, y, w, h, color, horizontal):
    """One-piece bar: 4px rounded data end, square corners at the baseline."""
    if (horizontal and w <= 0) or (not horizontal and h <= 0):
        return
    rx, ry = px_to_data(ax, 4, 4)
    ry = abs(ry)
    k = np.linspace(0, np.pi / 2, 12)
    if horizontal:                              # round the right end
        rx, ry = min(rx, w), min(ry, h / 2)
        top = [(x + w - rx + rx * np.sin(a), y + h - ry + ry * np.cos(a)) for a in k]
        bot = [(x + w - rx + rx * np.cos(a), y + ry - ry * np.sin(a)) for a in k]
        pts = [(x, y + h)] + top + bot + [(x, y)]
    else:                                       # round the top end
        rx, ry = min(rx, w / 2), min(ry, h)
        left = [(x + rx - rx * np.cos(a), y + h - ry + ry * np.sin(a)) for a in k]
        right = [(x + w - rx + rx * np.sin(a), y + h - ry + ry * np.cos(a)) for a in k]
        pts = [(x, y)] + left + right + [(x + w, y)]
    ax.add_patch(Polygon(pts, closed=True, linewidth=0, facecolor=color))


def save(fig, name, mode):
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(CHART_DIR / f"{name}-{mode}.png", dpi=DPI * 2, facecolor=fig.get_facecolor())
    plt.close(fig)


# ---------------------------------------------------------------------------
# The charts
# ---------------------------------------------------------------------------
def chart_bls_monthly(d, t, mode):
    """Change over time: official monthly layoffs, all sizes."""
    m = d["bls_month"]
    fig = new_figure(t, "US layoffs and discharges, every month",
                     f"All employers, all sizes. {m['date'].min():%b %Y} to {m['date'].max():%b %Y}"
                     f" (latest month is preliminary).",
                     "Source: U.S. Bureau of Labor Statistics, JOLTS (not seasonally adjusted).")
    ax = fig.add_axes([0.08, 0.14, 0.82, 0.66])
    style_axes(ax, t)
    ax.plot(m["date"], m["jolts_layoffs"], color=t["series"][0], linewidth=LINE_W,
            solid_joinstyle="round", solid_capstyle="round")
    last = m.iloc[-1]
    ax.scatter([last["date"]], [last["jolts_layoffs"]], s=64, color=t["series"][0],
               edgecolors=t["surface"], linewidths=2 * 72 / DPI, zorder=3)
    ax.annotate(compact(last["jolts_layoffs"], 2), (last["date"], last["jolts_layoffs"]),
                xytext=(8, 0), textcoords="offset points", va="center", fontsize=10,
                fontweight="bold", color=t["ink"])
    lo, hi = m["jolts_layoffs"].min(), m["jolts_layoffs"].max()
    pad = (hi - lo) * 0.25
    ax.set_ylim(max(lo - pad, 0), hi + pad)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(axis_fmt))
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.set_xlim(m["date"].min() - pd.Timedelta(days=10), m["date"].max() + pd.Timedelta(days=75))
    save(fig, "bls_monthly", mode)


def chart_bls_yearly(d, t, mode):
    """Magnitude by year: average per month, so a partial year compares fairly."""
    y = d["bls_year"]
    fig = new_figure(t, "Average layoffs per month, by year",
                     "Monthly average makes the partial current year comparable with full years.",
                     "Source: U.S. Bureau of Labor Statistics, JOLTS. Layoffs and discharges, all sizes.")
    ax = fig.add_axes([0.08, 0.14, 0.86, 0.66])
    style_axes(ax, t)
    n = len(y)
    ax.set_xlim(-0.6, n - 0.4)
    ax.set_ylim(0, y["avg"].max() * 1.18)
    bw, _ = px_to_data(ax, 24)                    # columns capped at 24px, never fill the slot
    for i, r in enumerate(y.itertuples()):
        rounded_bar(ax, t, i - bw / 2, 0, bw, r.avg, t["series"][0], horizontal=False)
        ax.annotate(compact(r.avg, 2), (i, r.avg), xytext=(0, 6), textcoords="offset points",
                    ha="center", fontsize=10, fontweight="bold", color=t["ink"])
    ax.set_xticks(range(n))
    ax.set_xticklabels(y["label"])
    ax.yaxis.set_major_formatter(plt.FuncFormatter(axis_fmt))
    save(fig, "bls_yearly", mode)


def chart_sources(d, t, mode):
    """Cross-check: three independent sources on one shared base (no second axis)."""
    s = d["sources"]
    names = ["BLS JOLTS layoffs (all US)", "DOL unemployment claims (all US)",
             f"WARN notices, workers ({d['warn_states']} states)"]
    cols = ["bls", "claims", "warn"]
    fig = new_figure(t, "Do the three sources move together?",
                     "Each source indexed to its own 2023 average = 100. 3-month rolling average.",
                     "Sources: BLS JOLTS; U.S. Dept. of Labor ETA-539 initial claims; state WARN notices.")
    ax = fig.add_axes([0.07, 0.14, 0.66, 0.6])
    style_axes(ax, t)
    ax.axhline(100, color=t["axis"], linewidth=1 * 72 / DPI, zorder=1)
    for i, (c, name) in enumerate(zip(cols, names)):
        sub = s[["date", c]].dropna()
        if sub.empty:
            continue
        ax.plot(sub["date"], sub[c], color=t["series"][i], linewidth=LINE_W,
                solid_joinstyle="round", solid_capstyle="round", label=name, zorder=2)
        last = sub.iloc[-1]
        ax.scatter([last["date"]], [last[c]], s=64, color=t["series"][i],
                   edgecolors=t["surface"], linewidths=2 * 72 / DPI, zorder=3)
    # end labels, nudged apart so they never collide
    ends = []
    for i, c in enumerate(cols):
        sub = s[["date", c]].dropna()
        if not sub.empty:
            ends.append([sub.iloc[-1][c], i, c, sub.iloc[-1]["date"]])
    ends.sort()
    lo, hi = ax.get_ylim()
    gap = (hi - lo) * 0.07
    for k in range(1, len(ends)):
        ends[k][0] = max(ends[k][0], ends[k - 1][0] + gap)
    for yv, i, c, dt in ends:
        short = ["BLS JOLTS", "DOL claims", "WARN"][i]
        ax.annotate(f"{short}  {s[c].dropna().iloc[-1]:.0f}", (dt, yv),
                    xytext=(14, 0), textcoords="offset points", va="center",
                    fontsize=9.5, color=t["ink"], annotation_clip=False)
    leg = ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=3, frameon=False,
                    fontsize=9, labelcolor=t["ink2"], handlelength=1.6, columnspacing=1.4)
    for h in leg.legend_handles:
        h.set_linewidth(3)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    save(fig, "sources_trend", mode)


def chart_hbars(t, mode, name, title, subtitle, source, labels, values, color):
    """Ranked horizontal bars, value at the tip."""
    fig = new_figure(t, title, subtitle, source)
    ax = fig.add_axes([0.25, 0.1, 0.68, 0.72])
    style_axes(ax, t, grid_axis="x")
    ax.spines["bottom"].set_visible(False)
    n = len(values)
    ax.set_ylim(n - 0.4, -0.6)
    ax.set_xlim(0, max(values) * 1.16)
    _, bh = px_to_data(ax, 0, 18)
    bh = abs(bh)
    for i, v in enumerate(values):
        rounded_bar(ax, t, 0, i - bh / 2, v, bh, color, horizontal=True)
        ax.annotate(compact(v), (v, i), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=9.5, color=t["ink"])
    ax.set_yticks(range(n))
    ax.set_yticklabels(labels, fontsize=9.5, color=t["ink2"])
    ax.xaxis.set_major_formatter(plt.FuncFormatter(axis_fmt))
    ax.tick_params(axis="x", labelsize=8.5)
    save(fig, name, mode)


def chart_size_mix(d, t, mode):
    """Part-to-whole: a few big notices hold a large share of workers."""
    mix = d["size_mix"]
    fig = new_figure(t, "How big are the layoffs? Notices vs. workers",
                     f"WARN notices since 2023, grouped by workers per notice ({d['warn_states']} states).",
                     "Source: state WARN notices. Size = workers named in one notice.")
    ax = fig.add_axes([0.2, 0.22, 0.74, 0.4])
    ax.set_facecolor(t["surface"])
    ax.axis("off")
    ax.set_xlim(0, 100)
    ax.set_ylim(1.5, -0.5)
    gap_x, _ = px_to_data(ax, 2)
    _, bh = px_to_data(ax, 0, 36)
    bh = abs(bh)
    rows = [("notices_pct", "Share of notices"), ("workers_pct", "Share of workers")]
    for r, (col, label) in enumerate(rows):
        left = 0
        ax.text(-2, r, label, ha="right", va="center", fontsize=10, color=t["ink2"])
        for k, seg in enumerate(mix.itertuples()):
            w = getattr(seg, col)
            if w <= 0:
                continue
            ax.add_patch(Rectangle((left, r - bh / 2), max(w - gap_x, 0), bh,
                                   linewidth=0, facecolor=t["ramp"][k]))
            if w >= 7:                                # only label segments wide enough
                ax.text(left + w / 2, r, f"{w:.0f}%", ha="center", va="center",
                        fontsize=10, fontweight="bold", color=t["ramp_text"][k])
            left += w
    handles = [Rectangle((0, 0), 1, 1, facecolor=t["ramp"][k]) for k in range(len(mix))]
    ax.legend(handles, list(mix["size_group"]), loc="lower left", bbox_to_anchor=(0, 1.08),
              ncol=4, frameon=False, fontsize=9.5, labelcolor=t["ink2"], handlelength=1.2)
    save(fig, "size_mix", mode)


def ink_on(hex_color):
    """Black or white text, whichever reads better on this fill."""
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lum = 0.2126 * r ** 2.2 + 0.7152 * g ** 2.2 + 0.0722 * b ** 2.2
    return "#0b0b0b" if lum > 0.3 else "#ffffff"


def chart_heatmap(d, t, mode):
    """Pattern: every month of every year in one grid. Darker = more layoffs (light mode)."""
    g = d["grid"]                                   # rows = years, columns = 1..12
    fig = new_figure(t, "Layoffs by month and year",
                     f"Each box is one month. {'Darker' if mode == 'light' else 'Brighter'} = more layoffs "
                     "and discharges. Not seasonally adjusted, so yearly patterns show.",
                     "Source: U.S. Bureau of Labor Statistics, JOLTS. Values in millions. Blank = not published yet.")
    ax = fig.add_axes([0.08, 0.12, 0.88, 0.62])
    ax.set_facecolor(t["surface"])
    ax.axis("off")
    years = list(g.index)
    ax.set_xlim(-0.5, 11.5)
    ax.set_ylim(len(years) - 0.5, -1.0)
    lo, hi = np.nanmin(g.values), np.nanmax(g.values)
    gap_x, gap_y = px_to_data(ax, 2, 2)
    gap_y = abs(gap_y)
    for r, yr in enumerate(years):
        ax.text(-0.62, r, str(yr), ha="right", va="center", fontsize=10.5, color=t["ink2"])
        for c in range(12):
            v = g.loc[yr, c + 1]
            if pd.isna(v):
                continue
            k = int(round((v - lo) / (hi - lo) * (len(t["seq"]) - 1))) if hi > lo else 6
            fill = t["seq"][k]
            ax.add_patch(Rectangle((c - 0.5 + gap_x / 2, r - 0.5 + gap_y / 2), 1 - gap_x, 1 - gap_y,
                                   linewidth=0, facecolor=fill))
            ax.text(c, r, f"{v / 1e6:.2f}", ha="center", va="center", fontsize=9.5, color=ink_on(fill))
    for c, m in enumerate(MONTHS):
        ax.text(c, -0.75, m, ha="center", va="center", fontsize=9.5, color=t["muted"])
    save(fig, "month_year_heatmap", mode)


def chart_seasonal(d, t, mode):
    """Same month, different years: one line per year, Jan -> Dec."""
    g = d["grid"]
    fig = new_figure(t, "Same month, different years",
                     "Monthly layoffs and discharges, one line per year. Newest year is the strongest line.",
                     "Source: U.S. Bureau of Labor Statistics, JOLTS (not seasonally adjusted).")
    ax = fig.add_axes([0.08, 0.14, 0.8, 0.6])
    style_axes(ax, t)
    years = list(g.index)[-4:]                      # up to 4 years keeps the lines readable
    colors = t["years"][-len(years):]
    vals = g.loc[years].values
    lo, hi = np.nanmin(vals), np.nanmax(vals)
    pad = (hi - lo) * 0.2
    ax.set_ylim(max(lo - pad, 0), hi + pad)
    ends = []
    for yr, col in zip(years, colors):
        row = g.loc[yr].dropna()
        ax.plot(row.index, row.values, color=col, linewidth=LINE_W, solid_joinstyle="round",
                solid_capstyle="round", label=str(yr), zorder=2)
        ax.scatter([row.index[-1]], [row.values[-1]], s=64, color=col, edgecolors=t["surface"],
                   linewidths=2 * 72 / DPI, zorder=3)
        ends.append([row.values[-1], row.index[-1], yr])
    # end labels: lines ending in the same month are nudged apart so labels never overlap
    gap = (hi - lo + 2 * pad) * 0.06
    for x_end in set(e[1] for e in ends):
        group = sorted([e for e in ends if e[1] == x_end])
        for k in range(1, len(group)):
            group[k][0] = max(group[k][0], group[k - 1][0] + gap)
    for yv, x_end, yr in ends:
        ax.annotate(str(yr), (x_end, yv), xytext=(10, 0), textcoords="offset points",
                    va="center", fontsize=9.5, color=t["ink"], annotation_clip=False)
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels(MONTHS)
    ax.set_xlim(0.6, 12.6)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(axis_fmt))
    leg = ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=len(years), frameon=False,
                    fontsize=9.5, labelcolor=t["ink2"], handlelength=1.6)
    for h in leg.legend_handles:
        h.set_linewidth(3)
    save(fig, "same_month_by_year", mode)


# ---------------------------------------------------------------------------
# Company names and calendar details (WARN only - the one source with exact dates and names)
# ---------------------------------------------------------------------------
LEGAL_WORDS = {"inc", "incorporated", "llc", "l", "c", "corp", "corporation", "co", "company", "ltd",
               "limited", "lp", "llp", "plc", "the", "dba", "na", "pllc", "pc"}


def company_key(name):
    """'Amazon.com Services, LLC' and 'AMAZON.COM SERVICES LLC' -> 'amazon services' (same company)."""
    s = str(name).lower()
    s = re.sub(r"\(.*?\)", " ", s)              # drop text in brackets
    s = s.replace("&", " and ").replace(".com", " ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    words = [w for w in s.split() if w not in LEGAL_WORDS]
    return " ".join(words)


def tidy_name(name):
    """SHOUTING NAMES -> Title Case; normal names stay as written."""
    name = re.sub(r"\s+", " ", str(name)).strip(" ,")
    return name.title() if name.isupper() else name


def precise_dates(df, col):
    """Keep only states whose dates are real days. A state that only records the month shows up
    as almost every date being the 1st - those would create fake 'day 1' spikes, so they're left out."""
    x = df.dropna(subset=[col])
    if x.empty:
        return x, []
    share_day1 = x.groupby("state")[col].apply(lambda s: (s.dt.day == 1).mean())
    rough = sorted(share_day1[share_day1 > 0.6].index)
    return x[~x["state"].isin(rough)], rough


def chart_weekday(d, t, mode):
    """Grouped bars: share of notices FILED vs layoffs STARTING on each weekday (same unit: %)."""
    wk = d["weekday"]
    fig = new_figure(t, "Which day of the week?",
                     "Share of WARN notices by weekday: the day the notice was filed vs. the day the layoff takes effect.",
                     f"Source: state WARN notices since 2023 ({d['warn_states']} states). Past dates only.")
    ax = fig.add_axes([0.08, 0.13, 0.88, 0.62])
    style_axes(ax, t)
    ax.set_xlim(-0.6, 6.6)
    ax.set_ylim(0, max(wk["filed_pct"].max(), wk["effective_pct"].max()) * 1.2)
    bw, _ = px_to_data(ax, 22)
    gap, _ = px_to_data(ax, 2)
    series = [("filed_pct", "Notice filed"), ("effective_pct", "Layoff takes effect")]
    for k, (col, label) in enumerate(series):
        peak = int(np.argmax(wk[col].values))           # label only each color's highest bar
        for i, v in enumerate(wk[col]):
            x = i - bw - gap / 2 if k == 0 else i + gap / 2
            rounded_bar(ax, t, x, 0, bw, v, t["series"][k], horizontal=False)
            if i == peak:
                ax.annotate(f"{v:.0f}%", (x + bw / 2, v), xytext=(0, 4), textcoords="offset points",
                            ha="center", fontsize=9, fontweight="bold", color=t["ink"])
    handles = [Rectangle((0, 0), 1, 1, facecolor=t["series"][k]) for k in range(2)]
    ax.legend(handles, [s[1] for s in series], loc="lower left", bbox_to_anchor=(0, 1.02), ncol=2,
              frameon=False, fontsize=9.5, labelcolor=t["ink2"], handlelength=1.2)
    ax.set_xticks(range(7))
    ax.set_xticklabels(WEEKDAYS)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    save(fig, "weekday_pattern", mode)


def chart_day_of_month(d, t, mode):
    """Which date in the month do layoffs take effect? (effective dates already passed)."""
    dm = d["day_of_month"]
    fig = new_figure(t, "Which date in the month do layoffs take effect?",
                     "Share of WARN layoffs by day of the month they start (effective date, past dates only).",
                     "Source: state WARN notices since 2023. States that record only the month are left out.")
    ax = fig.add_axes([0.08, 0.13, 0.88, 0.64])
    style_axes(ax, t)
    ax.set_xlim(0.3, 31.7)
    ax.set_ylim(0, dm.max() * 1.2)
    bw, _ = px_to_data(ax, 16)
    top3 = set(dm.sort_values(ascending=False).head(3).index)
    for day, v in dm.items():
        rounded_bar(ax, t, day - bw / 2, 0, bw, v, t["series"][0], horizontal=False)
        if day in top3:
            ax.annotate(f"{v:.0f}%", (day, v), xytext=(0, 4), textcoords="offset points",
                        ha="center", fontsize=9, fontweight="bold", color=t["ink"])
    ax.set_xticks([1, 5, 10, 15, 20, 25, 31])
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    save(fig, "day_of_month_pattern", mode)


def chart_recent_daily(d, t, mode):
    """Date-wise: workers in WARN notices, every day of the last 90 days."""
    r = d["recent_daily"]
    fig = new_figure(t, "Layoffs day by day, last 90 days",
                     f"Workers named in WARN notices filed each day, {r['date'].min():%b %d} to {r['date'].max():%b %d, %Y}.",
                     f"Source: state WARN notices ({d['warn_states']} states). Days with no notices show as gaps.")
    ax = fig.add_axes([0.08, 0.13, 0.88, 0.64])
    style_axes(ax, t)
    ax.set_xlim(r["date"].min() - pd.Timedelta(days=1), r["date"].max() + pd.Timedelta(days=1))
    ax.set_ylim(0, r["workers"].max() * 1.18)
    bw, _ = px_to_data(ax, 6)
    for dt, v in zip(r["date"], r["workers"]):
        x = mdates.date2num(dt)
        rounded_bar(ax, t, x - bw / 2, 0, bw, v, t["series"][0], horizontal=False)
    peak = r.loc[r["workers"].idxmax()]
    ax.annotate(f"{compact(peak['workers'])} on {peak['date']:%b %d}", (mdates.date2num(peak["date"]), peak["workers"]),
                xytext=(0, 6), textcoords="offset points", ha="center", fontsize=9.5,
                fontweight="bold", color=t["ink"])
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0, interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(axis_fmt))
    save(fig, "recent_daily", mode)


def prepare_warn_details(d):
    """Company totals, calendar patterns, daily and monthly tables from WARN notices."""
    w = d["warn_all"].copy()
    if w.empty:
        return
    w["company"] = w["company"].astype(str)
    w = w[~w["company"].str.strip().str.lower().isin({"", "nan", "none"})]
    w["key"] = w["company"].map(company_key)
    w = w[w["key"] != ""]
    # One display name per company: its most common spelling
    names = (w.groupby(["key", "company"]).size().reset_index(name="n")
             .sort_values("n", ascending=False).drop_duplicates("key").set_index("key")["company"].map(tidy_name))
    w["company_clean"] = w["key"].map(names)
    w["date"] = pd.to_datetime(w["date"])
    for c in ("notice_date", "layoff_date"):
        w[c] = pd.to_datetime(w[c], errors="coerce") if c in w else pd.NaT
    d["warn_named"] = w

    # Top companies since 2023 (all states added together)
    comp = (w.groupby("company_clean").agg(workers=("workers", "sum"), notices=("key", "count"),
                                           states=("state", lambda s: ", ".join(sorted(set(s)))),
                                           first=("date", "min"), last=("date", "max"))
            .reset_index().sort_values("workers", ascending=False))
    d["companies"] = comp

    # Weekday: notice FILED (notice dates) vs layoff TAKES EFFECT (effective dates already passed)
    today = pd.Timestamp.today().normalize()
    filed, rough_f = precise_dates(w, "notice_date")
    eff, rough_e = precise_dates(w[w["layoff_date"] <= today], "layoff_date")
    wk = pd.DataFrame({"weekday": WEEKDAYS})
    wk["filed"] = filed["notice_date"].dt.dayofweek.value_counts().reindex(range(7), fill_value=0).values
    wk["effective"] = eff["layoff_date"].dt.dayofweek.value_counts().reindex(range(7), fill_value=0).values
    wk["filed_pct"] = wk["filed"] / max(wk["filed"].sum(), 1) * 100
    wk["effective_pct"] = wk["effective"] / max(wk["effective"].sum(), 1) * 100
    d["weekday"] = wk
    d["day_of_month"] = (eff["layoff_date"].dt.day.value_counts(normalize=True).reindex(range(1, 32), fill_value=0) * 100)
    d["rough_states"] = sorted(set(rough_f) | set(rough_e))
    d["n_filed"], d["n_effective"] = int(wk["filed"].sum()), int(wk["effective"].sum())

    # Date-wise table: every day with notices
    def top_names(g, n=3):
        t3 = g.groupby("company_clean")["workers"].sum().sort_values(ascending=False).head(n)
        return "; ".join(f"{name} ({int(v):,})" for name, v in t3.items())
    daily = (w.groupby(w["date"].dt.normalize())
             .apply(lambda g: pd.Series({"notices": len(g), "workers": int(g["workers"].sum()),
                                         "states": ", ".join(sorted(set(g["state"]))),
                                         "top_companies": top_names(g)}), include_groups=False)
             .reset_index().rename(columns={"index": "date"}))
    daily.columns = ["date", "notices", "workers", "states", "top_companies"]
    daily = daily.sort_values("date", ascending=False)
    daily["weekday"] = daily["date"].dt.day_name()
    d["daily"] = daily
    last = w["date"].max().normalize()
    span = pd.DataFrame({"date": pd.date_range(last - pd.Timedelta(days=89), last)})
    d["recent_daily"] = span.merge(daily[["date", "workers"]], on="date", how="left").fillna({"workers": 0})

    # Month-by-year table with company names
    w["ym"] = w["date"].dt.to_period("M")
    monthly = (w.groupby("ym")
               .apply(lambda g: pd.Series({"notices": len(g), "workers": int(g["workers"].sum()),
                                           "companies": g["key"].nunique(),
                                           "top_companies": top_names(g)}), include_groups=False)
               .reset_index().sort_values("ym", ascending=False))
    monthly["year"] = monthly["ym"].dt.year
    monthly["month"] = monthly["ym"].dt.strftime("%B")
    d["monthly_companies"] = monthly
    d["month_year_workers"] = (w.assign(y=w["date"].dt.year, m=w["date"].dt.month)
                               .pivot_table(index="y", columns="m", values="workers", aggfunc="sum")
                               .reindex(columns=range(1, 13)))
    d["recent_notices"] = (w.sort_values(["date", "workers"], ascending=[False, False])
                           [["date", "company_clean", "city", "state", "workers"]].head(25))


def save_tables(d):
    """Full tables as CSV in docs/tables/ - GitHub displays them as searchable tables."""
    if "companies" not in d:
        return
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    c = d["companies"].copy()
    c["first"], c["last"] = c["first"].dt.date, c["last"].dt.date
    c.rename(columns={"company_clean": "company", "first": "first_notice", "last": "latest_notice"}) \
        .to_csv(TABLE_DIR / "top_companies.csv", index=False)
    dd = d["daily"].copy()
    dd["date"] = dd["date"].dt.date
    dd[["date", "weekday", "notices", "workers", "states", "top_companies"]].to_csv(TABLE_DIR / "daily_notices.csv", index=False)
    m = d["monthly_companies"]
    m[["year", "month", "notices", "workers", "companies", "top_companies"]] \
        .rename(columns={"companies": "different_companies"}).to_csv(TABLE_DIR / "monthly_notices_companies.csv", index=False)
    grid = d["month_year_workers"].copy()
    grid.columns = MONTHS
    grid.index.name = "year"
    grid.fillna(0).astype(int).to_csv(TABLE_DIR / "month_by_year_workers.csv")


# ---------------------------------------------------------------------------
# Prepare the numbers
# ---------------------------------------------------------------------------
def prepare():
    d = {}
    bm = read("bls_us_monthly")
    bm = bm.dropna(subset=["jolts_layoffs"]) if not bm.empty else bm
    if bm.empty:
        raise SystemExit("No BLS national data in layoffs_output/ - run us_layoffs_tracker.py first.")
    bm["date"] = pd.to_datetime(bm["month"])
    bm = bm.sort_values("date")
    d["bls_month"] = bm

    by = bm.assign(year=bm["date"].dt.year).groupby("year").agg(
        total=("jolts_layoffs", "sum"), months=("jolts_layoffs", "count"),
        last=("date", "max")).reset_index()
    by["avg"] = by["total"] / by["months"]
    by["label"] = [str(r.year) if r.months == 12 else f"{r.year}\n(Jan–{r.last:%b})" for r in by.itertuples()]
    d["bls_year"] = by

    # Month x year grid + typical pattern (full years only, so every month counts equally)
    grid = bm.assign(year=bm["date"].dt.year, m=bm["date"].dt.month).pivot_table(
        index="year", columns="m", values="jolts_layoffs", aggfunc="sum").reindex(columns=range(1, 13))
    d["grid"] = grid
    full_years = grid.dropna()
    if len(full_years):
        share = full_years.div(full_years.mean(axis=1), axis=0)      # each month vs its year's average
        typical = share.mean().sort_values(ascending=False)
        d["peak_months"] = [(MONTHS[m - 1], (v - 1) * 100) for m, v in typical.head(2).items()]
        d["low_months"] = [(MONTHS[m - 1], (v - 1) * 100) for m, v in typical.tail(2).items()]
    d["peak_by_year"] = {yr: (MONTHS[int(row.idxmax()) - 1], row.max()) for yr, row in grid.iterrows()
                         if row.notna().any()}

    # State ranking: latest year with all 12 months
    st = read("bls_state_monthly")
    if not st.empty:
        st = st.dropna(subset=["jolts_layoffs"])
        st["year"] = pd.to_datetime(st["month"]).dt.year
        full = st.groupby(["state", "year"]).agg(total=("jolts_layoffs", "sum"),
                                                 months=("jolts_layoffs", "count")).reset_index()
        full = full[full["months"] == 12]
        d["state_year"] = int(full["year"].max()) if not full.empty else None
        d["states"] = (full[full["year"] == d["state_year"]].sort_values("total", ascending=False)
                       if d["state_year"] else pd.DataFrame())
    else:
        d["state_year"], d["states"] = None, pd.DataFrame()

    # WARN
    warn = read("warn_clean")
    today_month = pd.Timestamp.today().to_period("M")
    if not warn.empty:
        warn["date"] = pd.to_datetime(warn["date"])
        warn = warn[warn["date"].dt.to_period("M") < today_month]   # drop the unfinished month
    d["warn"] = warn
    d["warn_all"] = read("warn_clean")                              # includes the current month
    d["warn_states"] = warn["state"].nunique() if not warn.empty else 0

    # City ranking (WARN). Skip empty or catch-all locations.
    if not warn.empty:
        bad = {"", "unknown", "nan", "none", "statewide", "various", "multiple", "n/a"}
        c = warn[~warn["city"].astype(str).str.strip().str.lower().isin(bad)]
        d["cities"] = (c.groupby(["state", "city"], as_index=False)
                       .agg(workers=("workers", "sum"), notices=("company", "count"))
                       .sort_values("workers", ascending=False))
        top = warn.sort_values("workers", ascending=False).head(10)
        d["top_events"] = top[["date", "company", "city", "state", "workers"]]
        sz = warn.dropna(subset=["size_group"])
        sz = sz[sz["workers"] > 0]
        order = ["Small (<50)", "Medium (50-249)", "Large (250-999)", "Mega (1000+)"]
        mix = sz.groupby("size_group").agg(notices=("company", "count"), workers=("workers", "sum"))
        mix = mix.reindex(order).fillna(0).reset_index()
        mix["notices_pct"] = mix["notices"] / mix["notices"].sum() * 100
        mix["workers_pct"] = mix["workers"] / mix["workers"].sum() * 100
        d["size_mix"] = mix
    else:
        d["cities"], d["top_events"], d["size_mix"] = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # Three sources, monthly, indexed to 2023 average = 100, 3-month rolling average
    s = bm.set_index("month")[["jolts_layoffs"]].rename(columns={"jolts_layoffs": "bls"})
    ui = read("ui_claims_monthly")
    if not ui.empty:
        ui = ui.groupby("month").agg(claims=("initial_claims", "sum"), weeks=("weeks", "max"))
        ui["claims"] = ui["claims"] / ui["weeks"]                 # per week: fair for 4- vs 5-week months
        ui = ui[ui.index.map(lambda m: pd.Period(m, "M") < today_month)]
        s = s.join(ui[["claims"]], how="outer")
    if not warn.empty:
        wm = warn.groupby(warn["date"].dt.to_period("M").astype(str))["workers"].sum().rename("warn")
        s = s.join(wm, how="outer")
    s = s.sort_index()
    s = s[s.index >= "2023-01"]
    for c in s.columns:
        base = s.loc[s.index.str.startswith("2023"), c].mean()
        s[c] = s[c] / base * 100 if base else np.nan
        s[c] = s[c].rolling(3, min_periods=3).mean()
    s = s.reset_index().rename(columns={"index": "month"})
    s["date"] = pd.to_datetime(s["month"])
    for c in ("claims", "warn"):
        if c not in s:
            s[c] = np.nan
    d["sources"] = s

    # Comparison with other trackers, by year
    comp = by[["year", "total", "months", "last"]].rename(columns={"total": "bls", "months": "bls_months"})
    if CHALLENGER.exists():
        ch = pd.read_csv(CHALLENGER, dtype={"period": str})
        yearly = ch[ch["level"] == "year"].assign(year=lambda x: x["period"].astype(int))
        monthly = ch[ch["level"] == "month"].assign(year=lambda x: x["period"].str[:4].astype(int))
        rows = []
        for yr in sorted(set(yearly["year"]) | set(monthly["year"])):
            y_row = yearly[yearly["year"] == yr]
            m_rows = monthly[monthly["year"] == yr]
            if len(y_row):
                rows.append((yr, int(y_row["announced_job_cuts"].iloc[0]), 12))
            elif len(m_rows):
                rows.append((yr, int(m_rows["announced_job_cuts"].sum()), len(m_rows)))
        comp = comp.merge(pd.DataFrame(rows, columns=["year", "challenger", "ch_months"]), on="year", how="left")
    uiy = read("ui_claims_monthly")
    if not uiy.empty:
        uiy["year"] = uiy["month"].str[:4].astype(int)
        uiy = uiy.groupby("year").agg(claims=("initial_claims", "sum"),
                                      claims_last=("month", "max")).reset_index()
        comp = comp.merge(uiy, on="year", how="left")
    if not warn.empty:
        wy = warn.groupby(warn["date"].dt.year).agg(warn=("workers", "sum"),
                                                     warn_last=("date", "max")).reset_index()
        wy = wy.rename(columns={"date": "year"})
        comp = comp.merge(wy, on="year", how="left")
    d["compare"] = comp

    def trend_match(a, b):
        x = s[[a, b]].dropna()
        return round(x[a].rank().corr(x[b].rank()), 2) if len(x) >= 6 else np.nan
    d["match_claims"] = trend_match("bls", "claims")
    d["match_warn"] = trend_match("bls", "warn")
    prepare_warn_details(d)
    return d


# ---------------------------------------------------------------------------
# Results text (every number comes from the data)
# ---------------------------------------------------------------------------
def picture(name, alt):
    return (f'<picture>\n  <source media="(prefers-color-scheme: dark)" srcset="{{p}}docs/charts/{name}-dark.png">\n'
            f'  <img alt="{alt}" src="{{p}}docs/charts/{name}-light.png">\n</picture>')


def results_markdown(d, prefix):
    by, bm = d["bls_year"], d["bls_month"]
    full = by[by["months"] == 12]
    lines = [f"_Last updated {pd.Timestamp.today():%B %d, %Y}. Generated automatically by `make_charts.py`._", ""]
    fresh = [f"BLS JOLTS through **{bm.iloc[-1]['date']:%B %Y}**"]
    if not d["warn_all"].empty:
        fresh.append(f"WARN notices through **{pd.to_datetime(d['warn_all']['date']).max():%B %d, %Y}**")
    uw = read("ui_claims_monthly")
    if not uw.empty:
        fresh.append(f"unemployment claims through **{pd.Period(uw['month'].max(), 'M').strftime('%B %Y')}**")
    lines += ["**Data current as of:** " + " · ".join(fresh), ""]

    # Key numbers
    lines += ["### Key numbers", "", "| Measure | Value |", "|---|---|"]
    if len(full):
        ly = full.iloc[-1]
        lines.append(f"| US layoffs & discharges in {ly.year} (BLS) | **{compact(ly.total, 2)}** |")
        if len(full) > 1:
            py = full.iloc[-2]
            lines.append(f"| Change vs {py.year} | **{pct(ly.total, py.total):+.1f}%** |")
    cur = by.iloc[-1]
    if cur.months < 12:
        lines.append(f"| {cur.year} so far ({cur.months} months), average per month | **{compact(cur.avg, 2)}** |")
    lines.append(f"| Latest month ({bm.iloc[-1]['date']:%B %Y}, preliminary) | **{compact(bm.iloc[-1]['jolts_layoffs'], 2)}** |")
    if not d["warn"].empty:
        lines.append(f"| WARN notices since 2023 ({d['warn_states']} states) | **{len(d['warn']):,}** notices, "
                     f"**{compact(d['warn']['workers'].sum())}** workers |")
    lines.append("")

    # Findings
    f = []
    if len(full) > 1:
        a, b = full.iloc[-1], full.iloc[-2]
        f.append(f"BLS counted **{compact(a.total, 2)}** layoffs and discharges in {a.year}, "
                 f"**{pct(a.total, b.total):+.1f}%** compared with {b.year} ({compact(b.total, 2)}).")
    if cur.months < 12 and len(full):
        f.append(f"Through {cur['last']:%B %Y}, {cur.year} averages **{compact(cur.avg, 2)} a month**, "
                 f"**{pct(cur.avg, full.iloc[-1].avg):+.1f}%** versus the {full.iloc[-1].year} monthly average.")
    if d.get("peak_months"):
        pk, lw = d["peak_months"], d["low_months"]
        f.append(f"Seasonal pattern (full years): **{pk[0][0]}** and **{pk[1][0]}** are usually the highest months "
                 f"({pk[0][1]:+.0f}% and {pk[1][1]:+.0f}% vs. the yearly average); **{lw[-1][0]}** and **{lw[0][0]}** "
                 f"are usually the lowest.")
    if d.get("peak_by_year"):
        f.append("Highest month each year: " + ", ".join(
            f"{yr} **{m}** ({compact(v, 2)})" for yr, (m, v) in d["peak_by_year"].items()) + ".")
    if not d["states"].empty:
        top3 = d["states"].head(3)
        f.append(f"States with the most layoffs and discharges in {d['state_year']}: "
                 + ", ".join(f"**{r.state}** ({compact(r.total)})" for r in top3.itertuples()) + ".")
    if not d["size_mix"].empty:
        mega = d["size_mix"].iloc[-1]
        f.append(f"Notices of 1,000+ workers were **{mega.notices_pct:.1f}%** of WARN notices but "
                 f"**{mega.workers_pct:.1f}%** of the workers named in them.")
    if not d["top_events"].empty:
        e = d["top_events"].iloc[0]
        f.append(f"Largest single WARN notice since 2023: **{e.company}** ({e.city}, {e.state}), "
                 f"**{int(e.workers):,}** workers, {pd.Timestamp(e.date):%B %Y}.")
    if "companies" in d and len(d["companies"]):
        c0 = d["companies"].iloc[0]
        f.append(f"Company with the most workers in WARN notices since 2023: **{c0.company_clean}**, "
                 f"**{int(c0.workers):,}** workers across {int(c0.notices)} notices ({c0.states}).")
        wk = d["weekday"]
        top_f = wk.loc[wk["filed_pct"].idxmax()]
        top_e = wk.loc[wk["effective_pct"].idxmax()]
        weekend = wk.loc[wk["weekday"].isin(["Sat", "Sun"]), "filed_pct"].sum()
        f.append(f"Notices are filed most often on **{top_f.weekday}** ({top_f.filed_pct:.0f}%); only "
                 f"{weekend:.0f}% on weekends. Layoffs most often take effect on **{top_e.weekday}** "
                 f"({top_e.effective_pct:.0f}%).")
        dm = d["day_of_month"].sort_values(ascending=False)
        f.append(f"Most common start dates in the month: **day {dm.index[0]}** ({dm.iloc[0]:.0f}% of layoffs), "
                 f"then day {dm.index[1]} ({dm.iloc[1]:.0f}%) and day {dm.index[2]} ({dm.iloc[2]:.0f}%).")
        bd = d["daily"].sort_values("workers", ascending=False).iloc[0]
        f.append(f"Busiest single day: **{bd.date:%B %d, %Y}** ({bd.weekday}), {int(bd.notices)} notices "
                 f"covering **{int(bd.workers):,}** workers.")
    if pd.notna(d["match_claims"]) or pd.notna(d["match_warn"]):
        f.append(f"Trend match with BLS (rank correlation, 1 = same direction every month): "
                 f"unemployment claims **{d['match_claims']}**, WARN **{d['match_warn']}**.")
    lines += ["### Findings", ""] + [f"- {x}" for x in f] + [""]

    # Charts + table views
    def pic(name, alt):
        return picture(name, alt).replace("{p}", prefix)
    lines += ["### Charts", "", pic("bls_monthly", "Monthly US layoffs and discharges, BLS JOLTS"), "",
              pic("bls_yearly", "Average monthly layoffs by year"), "",
              "| Year | Months | Total | Average per month |", "|---|---|---|---|"]
    lines += [f"| {r.year} | {r.months} | {compact(r.total, 2)} | {compact(r.avg, 2)} |" for r in by.itertuples()]
    lines += ["", "#### Monthly pattern", "", pic("month_year_heatmap", "Layoffs by month and year heat grid"), "",
              pic("same_month_by_year", "Same month compared across years"), ""]
    lines += ["#### Do the sources agree?", "", pic("sources_trend", "Three sources indexed to 2023 = 100"), ""]
    cp = d.get("compare")
    if cp is not None and "challenger" in cp:
        def cell(v, months, full=12):
            if pd.isna(v):
                return "–"
            return compact(v, 2) + ("" if months == full else f" ({int(months)} mo)")
        lines += ["#### Compared with other trackers", "",
                  "| Year | BLS JOLTS layoffs & discharges | DOL initial unemployment claims | "
                  "Challenger announced job cuts | WARN workers (" + str(d["warn_states"]) + " states) |",
                  "|---|---|---|---|---|"]
        for r in cp.itertuples():
            claims_m = int(str(r.claims_last)[5:7]) if "claims" in cp and pd.notna(getattr(r, "claims", np.nan)) else 12
            warn_m = pd.Timestamp(r.warn_last).month if "warn" in cp and pd.notna(getattr(r, "warn", np.nan)) else 12
            cur_year = r.year == pd.Timestamp.today().year
            lines.append(f"| {r.year} | {cell(r.bls, r.bls_months)} | "
                         f"{cell(getattr(r, 'claims', np.nan), claims_m if cur_year else 12)} | "
                         f"{cell(r.challenger, r.ch_months)} | "
                         f"{cell(getattr(r, 'warn', np.nan), warn_m if cur_year else 12)} |")
        lines += ["", "_(n mo) = months available so far. Challenger, Gray & Christmas figures are entered from their "
                  "monthly reports (see `reference/challenger_job_cuts.csv` for each source link)._", "",
                  "**Why the numbers differ:** BLS counts every layoff *and* firing, at every employer. "
                  "DOL claims count people who **applied** for unemployment benefits. Challenger counts job cuts "
                  "**announced** by companies (plans, which may happen later or not at all). WARN counts large "
                  "layoffs that legally required advance notice. They measure different things, so the levels differ; "
                  "what matters is whether they **rise and fall together**.", ""]
    if not d["states"].empty:
        lines += [pic("top_states", "Top states by layoffs and discharges"), "",
                  "<details><summary>All states table</summary>", "", "| Rank | State | Layoffs & discharges |", "|---|---|---|"]
        lines += [f"| {i} | {r.state} | {compact(r.total)} |" for i, r in enumerate(d["states"].itertuples(), 1)]
        lines += ["", "</details>", ""]
    if not d["cities"].empty:
        lines += [pic("top_cities", "Top cities by WARN workers"), "",
                  "| City | State | WARN notices | Workers |", "|---|---|---|---|"]
        lines += [f"| {r.city} | {r.state} | {r.notices:,} | {int(r.workers):,} |"
                  for r in d["cities"].head(15).itertuples()]
        lines.append("")
    if not d["size_mix"].empty:
        lines += [pic("size_mix", "Share of notices vs workers by layoff size"), "",
                  "| Layoff size | Notices | Share of notices | Workers | Share of workers |", "|---|---|---|---|---|"]
        lines += [f"| {r.size_group} | {int(r.notices):,} | {r.notices_pct:.1f}% | {int(r.workers):,} | {r.workers_pct:.1f}% |"
                  for r in d["size_mix"].itertuples()]
        lines.append("")
    if "companies" in d and len(d["companies"]):
        lines += ["### Companies, dates and calendar patterns", "",
                  f"_From WARN notices only ({d['warn_states']} states): the one source with exact dates and company names._", "",
                  "#### Companies with the most layoffs", "", pic("top_companies", "Top companies by workers in WARN notices"), "",
                  "| Rank | Company | Workers | Notices | States | Latest notice |", "|---|---|---|---|---|---|"]
        lines += [f"| {i} | {r.company_clean} | {int(r.workers):,} | {int(r.notices)} | {r.states} | {r.last:%b %d, %Y} |"
                  for i, r in enumerate(d["companies"].head(15).itertuples(), 1)]
        lines += ["", f"Full list: [docs/tables/top_companies.csv]({prefix}docs/tables/top_companies.csv)", "",
                  "#### Day by day", "", pic("recent_daily", "Workers in WARN notices each day, last 90 days"), "",
                  "**Latest notices**", "", "| Date | Company | City | State | Workers |", "|---|---|---|---|---|"]
        lines += [f"| {r.date:%b %d, %Y} | {r.company_clean} | {r.city} | {r.state} | {int(r.workers):,} |"
                  for r in d["recent_notices"].head(15).itertuples()]
        lines += ["", f"Every day since 2023: [docs/tables/daily_notices.csv]({prefix}docs/tables/daily_notices.csv)", "",
                  "#### Day of the week and date in the month", "",
                  pic("weekday_pattern", "Share of notices by weekday filed and effective"), "",
                  pic("day_of_month_pattern", "Share of layoffs by day of the month they take effect"), "",
                  "| Weekday | Notices filed | Share | Layoffs taking effect | Share |", "|---|---|---|---|---|"]
        lines += [f"| {r.weekday} | {int(r.filed):,} | {r.filed_pct:.1f}% | {int(r.effective):,} | {r.effective_pct:.1f}% |"
                  for r in d["weekday"].itertuples()]
        note = (f" States recording only the month were left out of these two charts: {', '.join(d['rough_states'])}."
                if d["rough_states"] else "")
        lines += ["", f"_Based on {d['n_filed']:,} notices with a filing date and {d['n_effective']:,} layoffs that "
                  f"have already taken effect.{note}_", "",
                  "#### Month by month, with company names", "",
                  "| Month | Notices | Workers | Different companies | Biggest companies that month (workers) |",
                  "|---|---|---|---|---|"]
        lines += [f"| {r.month} {r.year} | {int(r.notices):,} | {int(r.workers):,} | {int(r.companies):,} | {r.top_companies} |"
                  for r in d["monthly_companies"].head(12).itertuples()]
        g = d["month_year_workers"]
        lines += ["", f"All months: [docs/tables/monthly_notices_companies.csv]({prefix}docs/tables/monthly_notices_companies.csv)", "",
                  "<details><summary>Workers in WARN notices, month × year</summary>", "",
                  "| Year | " + " | ".join(MONTHS) + " | Total |", "|---" * 14 + "|"]
        for yr, row in g.iterrows():
            cells = [f"{int(v):,}" if pd.notna(v) else "–" for v in row.values]
            lines.append(f"| {yr} | " + " | ".join(cells) + f" | {int(row.sum()):,} |")
        lines += ["", "</details>", ""]
    lines += ["### How to read this", "",
              "- **BLS JOLTS** counts every employer-initiated separation (layoffs *and* firings), all business sizes. "
              "State numbers are model-based estimates and are released once a year (each July).",
              "- **DOL claims** count people filing for unemployment. Not every laid-off worker files, so it's a trend signal.",
              "- **WARN notices** cover larger layoffs only (usually 50+ workers at employers with 100+ staff), "
              f"from the {d['warn_states']} states whose data could be collected. Cities come from WARN only.",
              "- Sept and Oct 2025 BLS data were affected by the federal government shutdown.",
              "- **Company names** are grouped by removing legal endings (Inc, LLC, Corp), so the same company in different "
              "states adds up. Different divisions with different names (for example a subsidiary) still count separately.",
              "- **Dates:** a WARN notice is usually filed about 60 days before the layoff takes effect, so the "
              "\"filed\" and \"takes effect\" patterns differ on purpose.", ""]
    return "\n".join(lines)


def build():
    d = prepare()
    for mode, t in THEMES.items():
        chart_bls_monthly(d, t, mode)
        chart_bls_yearly(d, t, mode)
        chart_sources(d, t, mode)
        chart_heatmap(d, t, mode)
        chart_seasonal(d, t, mode)
        if not d["states"].empty:
            top = d["states"].head(15)
            chart_hbars(t, mode, "top_states", f"States with the most layoffs and discharges, {d['state_year']}",
                        "Top 15 states. All employers, all sizes.",
                        "Source: U.S. Bureau of Labor Statistics, state JOLTS estimates (annual release).",
                        list(top["state"]), list(top["total"]), t["series"][0])
        if not d["cities"].empty:
            top = d["cities"].head(15)
            chart_hbars(t, mode, "top_cities", "Cities with the most workers in WARN layoff notices",
                        f"Since Jan 2023. Top 15 locations in the {d['warn_states']} states with WARN data.",
                        "Source: state WARN notices. Some states list a county instead of a city.",
                        [f"{c}, {s}" for c, s in zip(top["city"], top["state"])], list(top["workers"]),
                        t["series"][0])
        if not d["size_mix"].empty:
            chart_size_mix(d, t, mode)
        if "companies" in d and len(d["companies"]):
            top = d["companies"].head(15)
            chart_hbars(t, mode, "top_companies", "Companies with the most workers in WARN layoff notices",
                        f"Since Jan 2023, all notices added up. Top 15 in the {d['warn_states']} states with WARN data.",
                        "Source: state WARN notices. Company names grouped by removing legal endings (Inc, LLC, Corp).",
                        [n if len(n) <= 34 else n[:32] + "…" for n in top["company_clean"]], list(top["workers"]),
                        t["series"][0])
            chart_recent_daily(d, t, mode)
            chart_weekday(d, t, mode)
            chart_day_of_month(d, t, mode)

    save_tables(d)
    RESULTS_MD.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_MD.write_text("# Results\n\n" + results_markdown(d, prefix="../"))
    block = results_markdown(d, prefix="")
    if README.exists():
        text = README.read_text()
        if START in text and END in text:
            head, rest = text.split(START, 1)
            _, tail = rest.split(END, 1)
            README.write_text(head + START + "\n" + block + "\n" + END + tail)
            print("Updated README.md results section")
        else:
            print(f"README.md has no {START} / {END} markers - results written to {RESULTS_MD} only")
    print(f"Saved charts to {CHART_DIR.resolve()} and results to {RESULTS_MD}")


if __name__ == "__main__":
    build()