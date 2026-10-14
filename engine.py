"""RESIST-X engine: data loading, validation, statistics and alert logic.
No Streamlit imports here, so it can be tested on its own."""
import math, re
import numpy as np
import pandas as pd

REQUIRED = ["Month", "Region", "Organism", "Antibiotic", "Resistant", "Tested"]
ALIASES = {
    "month": "Month", "date": "Month", "period": "Month", "year_month": "Month",
    "region": "Region", "country": "Region", "state": "Region",
    "organism": "Organism", "pathogen": "Organism", "bacteria": "Organism",
    "antibiotic": "Antibiotic", "drug": "Antibiotic", "antimicrobial": "Antibiotic",
    "resistant": "Resistant", "n_resistant": "Resistant", "resistant_count": "Resistant",
    "tested": "Tested", "n_tested": "Tested", "samples": "Tested", "total_tested": "Tested",
    "resistance_pct": "ResistancePct", "resistance_percent": "ResistancePct",
    "resistance (%)": "ResistancePct", "scenario": "Scenario",
}

ALIASES.update({"hospital": "Hospital", "facility": "Hospital", "ward": "Ward", "unit": "Ward",
    "specimen": "Specimen", "specimen_type": "Specimen", "sample_type": "Specimen", "age_group": "Age_Group",
    "agegroup": "Age_Group", "age_band": "Age_Group", "sex": "Sex", "gender": "Sex", "outcome": "Outcome"})
OPT = ["Scenario", "Hospital", "Ward", "Specimen", "Age_Group", "Sex", "Outcome"]

PII_COLS = re.compile(r"(^|_)(name|phone|mobile|contact|mrn|uhid|aadhaar|aadhar|dob|birth|address|email|ssn|passport)(_|$)", re.I)
PII_CELL = [re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), re.compile(r"(?<!\d)(?:\+?91[- ]?)?[6-9]\d{9}(?!\d)"),
            re.compile(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)")]


def pii_guard(df, skip=()):
    """Drop identifier-like columns; block upload if e-mail/phone/Aadhaar-like values remain. -> (df, warns, errs)"""
    warns, errs = [], []
    drop = [c for c in df.columns if PII_COLS.search(str(c).strip().replace(" ", "_"))]
    if drop:
        df = df.drop(columns=drop)
        warns.append("Dropped column(s) that look like personal identifiers: " + ", ".join(map(str, drop)))
    for c in [c for c in df.columns if c not in skip]:
        if not pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_datetime64_any_dtype(df[c]):
            s = df[c].dropna().astype(str).head(3000)
            if any(s.str.contains(p).any() for p in PII_CELL):
                errs.append(f"Column '{c}' contains e-mail/phone/Aadhaar-like values. Remove personal data and re-upload.")
    return df, warns, errs


DEFAULTS = dict(recent=3, z_thr=2.33, min_pp=8.0, min_n=60)

RED, AMBER, GREEN = "Review alert", "Insufficient evidence", "No alert"


# ---------- demo data (SYNTHETIC) ----------
def make_demo(seed=42):
    rng = np.random.default_rng(seed)
    months = pd.date_range("2025-01-01", periods=18, freq="MS")
    rows = []

    def add(scn, region, org, abx, probs, ns, drop=()):
        for i, m in enumerate(months):
            if i in drop:
                continue
            n = int(ns[i] if hasattr(ns, "__len__") else ns)
            r = int(rng.binomial(n, min(max(probs[i], 0.0), 1.0)))
            rows.append([m, region, org, abx, r, n, scn])

    # Scenario A: stable
    add("A - Stable", "North Zone", "E. coli", "Ciprofloxacin",
        [0.14 + 0.005 * math.sin(i) for i in range(18)], rng.integers(110, 140, 18))
    # Scenario B: unusual increase in last 4 months
    pb = [0.08] * 14 + [0.13, 0.20, 0.27, 0.33]
    add("B - Unusual increase", "East Zone", "K. pneumoniae", "Meropenem", pb, rng.integers(90, 120, 18))
    # Scenario C: very low counts + missing months
    add("C - Insufficient evidence", "West Zone", "S. aureus", "Oxacillin",
        [0.20] * 14 + [0.10, 0.40, 0.30, 0.45], rng.integers(4, 14, 18), drop=(5, 9, 16))
    # Context series (stable, for region comparison)
    for reg, base in [("North Zone", 0.10), ("East Zone", 0.12), ("South Zone", 0.11), ("West Zone", 0.13)]:
        add("Context", reg, "E. coli", "Ceftriaxone", [base] * 18, rng.integers(100, 130, 18))
    add("Context", "South Zone", "K. pneumoniae", "Meropenem", [0.09] * 18, rng.integers(90, 120, 18))
    df = pd.DataFrame(rows, columns=REQUIRED + ["Scenario"])
    return df


# ---------- loading & validation ----------
def validate_upload(raw: pd.DataFrame):
    """Return (clean_df or None, list_of_errors, list_of_warnings)."""
    errors, warns = [], []
    df = raw.copy()
    df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
    df = df.rename(columns={c: ALIASES.get(c.lower(), c) for c in df.columns})
    if "Resistant" not in df and "ResistancePct" in df and "Tested" in df:
        pct = pd.to_numeric(df["ResistancePct"], errors="coerce")
        df["Resistant"] = (pct / 100 * pd.to_numeric(df["Tested"], errors="coerce")).round()
        warns.append("'Resistant' was derived from Resistance % x Tested (rounded).")
    df, pw, pe = pii_guard(df)
    warns += pw
    if pe:
        return None, pe, warns
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        errors.append(f"Missing required column(s): {', '.join(missing)}. "
                      f"Needed: {', '.join(REQUIRED)}.")
        return None, errors, warns
    if df.empty:
        return None, ["The file has no rows."], warns
    n0 = len(df)
    df["Month"] = pd.to_datetime(df["Month"], errors="coerce")
    for c in ("Resistant", "Tested"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("Region", "Organism", "Antibiotic"):
        df[c] = df[c].astype("string").str.strip()
    bad_date = int(df["Month"].isna().sum())
    if bad_date:
        warns.append(f"{bad_date} row(s) dropped: unreadable date in 'Month'.")
    df = df.dropna(subset=["Month"])
    miss_cnt = int(df[["Resistant", "Tested", "Region", "Organism", "Antibiotic"]].isna().any(axis=1).sum())
    if miss_cnt:
        warns.append(f"{miss_cnt} row(s) dropped: missing counts or labels.")
    df = df.dropna(subset=["Resistant", "Tested", "Region", "Organism", "Antibiotic"])
    bad = int(((df["Tested"] <= 0) | (df["Resistant"] < 0) | (df["Resistant"] > df["Tested"])).sum())
    if bad:
        warns.append(f"{bad} row(s) dropped: Tested<=0 or Resistant outside 0..Tested.")
        df = df[(df["Tested"] > 0) & (df["Resistant"] >= 0) & (df["Resistant"] <= df["Tested"])]
    if df.empty:
        return None, errors + [f"No valid rows left out of {n0}."], warns
    df["Month"] = df["Month"].dt.to_period("M").dt.to_timestamp()
    df["Resistant"] = df["Resistant"].astype(int)
    df["Tested"] = df["Tested"].astype(int)
    opt = [c for c in OPT if c in df]
    df = df[REQUIRED + opt].copy()
    for c in opt:
        df[c] = df[c].astype("string").str.strip().fillna("Unknown")
    # merge duplicate rows of same series-month
    keys = ["Month", "Region", "Organism", "Antibiotic"] + opt
    dup = int(df.duplicated(keys).sum())
    if dup:
        warns.append(f"{dup} duplicate series-month row(s) were summed.")
        df = df.groupby(keys, as_index=False)[["Resistant", "Tested"]].sum()
    return df.reset_index(drop=True), errors, warns


# ---------- statistics ----------
def wilson(r, n, z=1.96):
    r = np.asarray(r, float); n = np.asarray(n, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        p = r / n
        d = 1 + z * z / n
        c = (p + z * z / (2 * n)) / d
        h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h) * 100, (c + h) * 100


def norm_sf(z):
    return 0.5 * math.erfc(z / math.sqrt(2))


def is_yearly(months):
    """True when every period is 1 January (annual data such as ATLAS/EARS-Net): windows then count years."""
    m = pd.to_datetime(pd.Series(months)).dropna()
    return len(m) > 1 and bool((m.dt.month == 1).all())


def series_table(df):
    """Monthly table for ONE series with full month range (missing months kept as NaN)."""
    g = df.groupby("Month", as_index=False)[["Resistant", "Tested"]].sum()
    full = pd.date_range(g["Month"].min(), g["Month"].max(), freq=("YS" if is_yearly(g["Month"]) else "MS"))
    g = g.set_index("Month").reindex(full).rename_axis("Month").reset_index()
    g["Pct"] = g["Resistant"] / g["Tested"] * 100
    lo, hi = wilson(g["Resistant"].fillna(0), g["Tested"].fillna(0))
    g["CI_low"] = np.where(g["Tested"] > 0, lo, np.nan)
    g["CI_high"] = np.where(g["Tested"] > 0, hi, np.nan)
    return g


def analyze_series(df, recent=3, z_thr=2.33, min_pp=8.0, min_n=60):
    """Compare the last `recent` calendar months with the earlier baseline."""
    g = series_table(df)
    out = dict(months=len(g), recent_window=recent, status=GREEN, flags=[])
    if len(g) < recent + 3:
        out.update(status=AMBER, flags=["Fewer than 3 baseline months - history too short."],
                   explanation="Not enough history to define a baseline. Cannot interpret the trend.")
        return out, g
    rec, base = g.iloc[-recent:], g.iloc[:-recent]
    nr, rr = rec["Tested"].sum(), rec["Resistant"].sum()
    nb, rb = base["Tested"].sum(), base["Resistant"].sum()
    miss_rec = int(rec["Tested"].isna().sum()); miss_base = int(base["Tested"].isna().sum())
    out.update(n_recent=int(nr), n_base=int(nb), missing_recent=miss_rec, missing_base=miss_base)
    if miss_rec or miss_base:
        out["flags"].append(f"Missing months: {miss_base} in baseline, {miss_rec} in recent window.")
    if nr == 0 or nb == 0:
        out.update(status=AMBER, explanation="No samples in the recent window or baseline.")
        out["flags"].append("No data in a comparison window.")
        return out, g
    pr, pb = rr / nr, rb / nb
    pool = (rr + rb) / (nr + nb)
    se = math.sqrt(pool * (1 - pool) * (1 / nr + 1 / nb)) if 0 < pool < 1 else float("nan")
    z = (pr - pb) / se if se and not math.isnan(se) else 0.0
    pval = norm_sf(z)
    lo, hi = wilson([rr], [nr])
    out.update(p_recent=pr * 100, p_base=pb * 100, change_pp=(pr - pb) * 100, z=z, p_value=pval,
               ci_low=float(lo[0]), ci_high=float(hi[0]))
    low_n = nr < min_n or nb < min_n or (rec["Tested"].fillna(0) < 10).any()
    if nr < min_n:
        out["flags"].append(f"Low sample count in recent window ({int(nr)} < {min_n}).")
    if nb < min_n:
        out["flags"].append(f"Low sample count in baseline ({int(nb)} < {min_n}).")
    if (rec["Tested"].fillna(0) < 10).any() and nr >= min_n:
        out["flags"].append("Some recent months have fewer than 10 samples.")
    changed = z >= z_thr and (pr - pb) * 100 >= min_pp
    if low_n or miss_rec >= max(1, recent // 2 + 1):
        out["status"] = AMBER
        extra = " The apparent change cannot be interpreted confidently." if (pr - pb) * 100 >= min_pp else ""
        out["explanation"] = (f"Evidence is insufficient: only {int(nr)} recent and {int(nb)} baseline samples "
                              f"(minimum {min_n}), or too many missing months.{extra} "
                              "Collect more data before drawing conclusions.")
    elif changed:
        out["status"] = RED
        out["explanation"] = (
            f"Resistance in the last {recent} months is {pr*100:.1f}% (95% CI {lo[0]:.1f}-{hi[0]:.1f}%, "
            f"n={int(nr)}) versus a baseline of {pb*100:.1f}% (n={int(nb)}). "
            f"That is +{(pr-pb)*100:.1f} percentage points; one-sided z={z:.2f} (p={pval:.4f}), above the "
            f"threshold z>={z_thr} and the minimum rise of {min_pp} points. "
            "Flagged for HUMAN REVIEW only - this does not confirm an outbreak.")
    else:
        out["explanation"] = (f"Recent resistance {pr*100:.1f}% vs baseline {pb*100:.1f}% "
                              f"({(pr-pb)*100:+.1f} points, z={z:.2f}). No configured alert. "
                              "This does not prove the situation is safe.")
    return out, g


def analyze_all(df, **kw):
    rows = []
    for (reg, org, abx), g in df.groupby(["Region", "Organism", "Antibiotic"]):
        res, _ = analyze_series(g, **kw)
        rows.append(dict(
            Region=reg, Organism=org, Antibiotic=abx, Status=res["status"],
            Baseline_pct=res.get("p_base"), Recent_pct=res.get("p_recent"),
            Change_pp=res.get("change_pp"), Z=res.get("z"), P_value=res.get("p_value"),
            N_recent=res.get("n_recent"), N_baseline=res.get("n_base"),
            Data_flags="; ".join(res["flags"]), Explanation=res["explanation"]))
    t = pd.DataFrame(rows)
    if not t.empty:
        order = {RED: 0, AMBER: 1, GREEN: 2}
        t = t.sort_values(["Status", "Z"], key=lambda s: s.map(order) if s.name == "Status" else -s.fillna(-99)
                          ).reset_index(drop=True)
    return t.round(3)


# ================= v2 additions =================
import sqlite3, os, html as _html
from pathlib import Path

DB = Path(__file__).resolve().parent / "data" / "reviews.db"


def bh_qvalues(p):
    """Benjamini-Hochberg adjusted p-values (FDR). NaN stays NaN."""
    p = np.asarray(p, float); q = np.full_like(p, np.nan)
    ok = ~np.isnan(p); pv = p[ok]; m = len(pv)
    if m == 0:
        return q
    o = np.argsort(pv); r = pv[o] * m / (np.arange(m) + 1)
    r = np.minimum.accumulate(r[::-1])[::-1]
    out = np.empty(m); out[o] = np.minimum(r, 1.0); q[ok] = out
    return q


_analyze_all_v1 = analyze_all


def analyze_all(df, fdr_alpha=0.05, **kw):
    t = _analyze_all_v1(df, **kw)
    if t.empty:
        return t
    t["FDR_q"] = np.round(bh_qvalues(t["P_value"].values), 4)
    for i, r in t.iterrows():
        if r["Status"] == RED and r["FDR_q"] > fdr_alpha:
            t.at[i, "Data_flags"] = (r["Data_flags"] + "; " if r["Data_flags"] else "") + \
                f"Not significant after FDR correction across {len(t)} series (q={r['FDR_q']})."
    return t


def cusum(tbl, k=0.5, h=4.0):
    """One-sided CUSUM on standardized monthly proportions; baseline = first 60% of months."""
    t = tbl.dropna(subset=["Tested"]).copy()
    if len(t) < 5:
        t["CUSUM"] = np.nan; t["Alarm"] = False; return t
    nb = max(3, int(len(t) * 0.6))
    p0 = t["Resistant"].iloc[:nb].sum() / t["Tested"].iloc[:nb].sum()
    p0 = min(max(p0, 0.01), 0.99)
    z = (t["Resistant"] / t["Tested"] - p0) / np.sqrt(p0 * (1 - p0) / t["Tested"])
    s, out = 0.0, []
    for v in z:
        s = max(0.0, s + v - k); out.append(s)
    t["CUSUM"] = out; t["Alarm"] = t["CUSUM"] > h
    return t


def data_quality(df):
    rows = []
    for (reg, org, abx), g in df.groupby(["Region", "Organism", "Antibiotic"]):
        full = pd.date_range(df["Month"].min(), df["Month"].max(), freq=("YS" if is_yearly(df["Month"]) else "MS"))
        got = g.groupby("Month")["Tested"].sum()
        comp = len(got) / len(full)
        adeq = float((got >= 30).mean())
        rows.append(dict(Region=reg, Organism=org, Antibiotic=abx, Completeness_pct=round(comp * 100, 1),
                         Months_adequate_n30_pct=round(adeq * 100, 1),
                         Median_monthly_samples=int(got.median()),
                         Quality_score=round(100 * (0.6 * comp + 0.4 * adeq), 1)))
    return pd.DataFrame(rows).sort_values("Quality_score").reset_index(drop=True)


def sim_rates(n=100, base=0.10, delta=0.15, z_thr=2.33, min_pp=8.0, min_n=60, sims=2000,
              seed=1, months=18, recent=3):
    """Monte-Carlo check of the alert rule. Ramp of +delta over the last 4 months (delta=0 -> false alarms)."""
    rng = np.random.default_rng(seed)
    p = np.full(months, base); p[-4:] += delta * np.array([.25, .5, .75, 1.0])
    p = np.clip(p, 0, 1)
    r = rng.binomial(n, p, size=(sims, months))
    rr, rb = r[:, -recent:].sum(1), r[:, :-recent].sum(1)
    nr, nb = recent * n, (months - recent) * n
    pr, pb = rr / nr, rb / nb
    pool = (rr + rb) / (nr + nb)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (pr - pb) / np.sqrt(pool * (1 - pool) * (1 / nr + 1 / nb))
    z = np.nan_to_num(z)
    low = (nr < min_n) or (nb < min_n) or (n < 10)
    red = (z >= z_thr) & ((pr - pb) * 100 >= min_pp)
    naive = (r[:, -1] / n - r[:, :-1].mean(1) / n) * 100 >= min_pp
    return dict(proposed=0.0 if low else float(red.mean()), naive=float(naive.mean()),
                insufficient=1.0 if low else 0.0)


def validation_grid(z_thr=2.33, min_pp=8.0, min_n=60):
    rows = []
    for n in (20, 50, 100, 200):
        for d in (0.0, 0.05, 0.10, 0.15, 0.20):
            s = sim_rates(n=n, delta=d, z_thr=z_thr, min_pp=min_pp, min_n=min_n, sims=1500)
            rows.append(dict(Monthly_samples=n, True_rise_pp=int(d * 100),
                             RESISTX_alert_pct=round(s["proposed"] * 100, 1),
                             Naive_rule_alert_pct=round(s["naive"] * 100, 1),
                             Insufficient_evidence=bool(s["insufficient"])))
    return pd.DataFrame(rows)


def explain_ta(res):
    st_ = res["status"]
    if "p_recent" not in res:
        return "Pothumana data illai - trend-a confident-a solla mudiyadhu."
    pr, pb, ch = res["p_recent"], res["p_base"], res["change_pp"]
    if st_ == RED:
        return (f"Kadaisi {res['recent_window']} maadhathula resistance {pr:.1f}% (munnadi {pb:.1f}%). "
                f"Idhu {ch:+.1f} point mela poiduchu, statistics padi ithu thaniya nadakka vaaipu kammi. "
                "Idhu outbreak-nu confirm pannala - manidha review kandippa venum.")
    if st_ == AMBER:
        return ("Sample ennikkai kammi allathu maadhangal missing. Athanaala trend-a nambikkaiyaa "
                "solla mudiyadhu. Innum data vaangi paarunga.")
    return f"Resistance {pr:.1f}% (baseline {pb:.1f}%). Ippodhaikku alert illai, aana idhu 'safe'-nu artham illai."


def init_db():
    DB.parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB) as c:
        c.execute("CREATE TABLE IF NOT EXISTS reviews(ts TEXT, series TEXT, status TEXT, reviewer TEXT, note TEXT)")


def save_review(series, status, reviewer, note):
    init_db()
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO reviews VALUES(datetime('now','localtime'),?,?,?,?)",
                  (series, status, reviewer.strip() or "anonymous", note.strip()))


def load_reviews():
    init_db()
    with sqlite3.connect(DB) as c:
        return pd.read_sql_query("SELECT * FROM reviews ORDER BY ts DESC", c)


def build_report(series, label_text, res, fig_html, review_df=None, prov="", state=""):
    e = _html.escape
    rv = ""
    if review_df is not None and len(review_df):
        rv = "<h3>Human review log</h3>" + review_df.to_html(index=False, escape=True)
    return f"""<html><head><meta charset="utf-8"><title>RESIST-X alert brief</title>
<style>body{{font-family:Segoe UI,Arial;max-width:900px;margin:30px auto;color:#14213d}}
.b{{padding:8px 14px;background:#fff3cd;border:1px solid #e0b100;border-radius:8px}}
.x{{padding:12px;border-left:6px solid #d33;background:#f6f8fb;margin:12px 0}}</style></head><body>
<h1>RESIST-X Alert Brief</h1><p class="b"><b>{e(label_text)}</b></p>
<p><small>{e(prov)}</small></p><h2>{e(series)}</h2><p><b>Review state:</b> {e(state or "not reviewed")}</p><div class="x"><b>Status: {e(res['status'])}</b><br>{e(res['explanation'])}</div>
{fig_html}<p><b>Data flags:</b> {e('; '.join(res['flags']) or 'none')}</p>{rv}
<hr><p><i>Prototype screening output for human review only. Not an outbreak confirmation, diagnosis or
treatment recommendation. Statistical alerts are not validated for operational use.</i></p></body></html>"""
