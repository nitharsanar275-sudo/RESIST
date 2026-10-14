"""RESIST-X v3 extras: context strata, antibiotic-use link, isolate-level co-resistance/MDR,
retrospective backtest, privacy helpers and tamper-evident audit trail. No Streamlit imports."""
import hashlib, math, sqlite3
from itertools import combinations
import numpy as np
import pandas as pd
import engine as E

CTX = ["Hospital", "Ward", "Specimen", "Age_Group", "Sex", "Outcome"]
CLASS = {"Ciprofloxacin": "Fluoroquinolone", "Levofloxacin": "Fluoroquinolone", "Ceftriaxone": "Cephalosporin",
         "Cefotaxime": "Cephalosporin", "Ceftazidime": "Cephalosporin", "Cefepime": "Cephalosporin",
         "Meropenem": "Carbapenem", "Imipenem": "Carbapenem", "Ertapenem": "Carbapenem",
         "Gentamicin": "Aminoglycoside", "Amikacin": "Aminoglycoside",
         "Trimethoprim-sulfamethoxazole": "Folate-pathway inhibitor", "Co-trimoxazole": "Folate-pathway inhibitor",
         "Ampicillin": "Penicillin", "Piperacillin-tazobactam": "Penicillin+BLI", "Amoxicillin-clavulanate": "Penicillin+BLI",
         "Oxacillin": "Anti-staph penicillin", "Nitrofurantoin": "Nitrofuran", "Colistin": "Polymyxin",
         "Doxycycline": "Tetracycline", "Tigecycline": "Glycylcycline"}
_erfc = np.vectorize(math.erfc)


# ---------------- synthetic demo generators (ALL SYNTHETIC) ----------------
def make_demo_context(base, seed=7):
    """Split aggregate demo rows into Hospital x Ward x Age_Group cells + Specimen (synthetic)."""
    rng = np.random.default_rng(seed)
    H = ["City General", "District Hospital", "Teaching Hospital"]; hw = np.array([.4, .25, .35])
    W = {"ICU": (.15, 1.6), "General ward": (.55, 1.0), "OPD": (.30, .6)}
    A = {"<18": (.15, .8), "18-64": (.5, 1.0), "65+": (.35, 1.2)}
    w = np.einsum("i,j,k->ijk", hw, [v[0] for v in W.values()], [v[0] for v in A.values()]).ravel()
    m = np.einsum("i,j,k->ijk", np.ones(3), [v[1] for v in W.values()], [v[1] for v in A.values()]).ravel()
    cells = [(h, wd, ag) for h in H for wd in W for ag in A]
    spec = {"E. coli": ["Urine", "Blood"], "K. pneumoniae": ["Blood", "Respiratory"], "S. aureus": ["Skin/soft tissue", "Blood"]}
    out = []
    for r in base.itertuples():
        n = rng.multinomial(r.Tested, w / w.sum()); p = np.clip(r.Resistant / r.Tested * m, 0, 1)
        k = rng.binomial(n, p); sp = rng.choice(spec.get(r.Organism, ["Blood", "Urine"]), p=[.7, .3])
        for (h, wd, ag), ni, ki in zip(cells, n, k):
            if ni > 0:
                out.append([r.Month, r.Region, r.Organism, r.Antibiotic, int(ki), int(ni), r.Scenario, h, wd, sp, ag])
    return pd.DataFrame(out, columns=E.REQUIRED + ["Scenario", "Hospital", "Ward", "Specimen", "Age_Group"])


def make_demo_use(base, seed=5):
    """Synthetic antibiotic consumption (DDD/1000 patient-days) that LEADS resistance by one month."""
    rng = np.random.default_rng(seed); rows = []
    for (reg, abx), g in base.groupby(["Region", "Antibiotic"]):
        t = g.groupby("Month")[["Resistant", "Tested"]].sum(); p = (t.Resistant / t.Tested).values
        nxt = np.append(p[1:], p[-1])
        for mth, v in zip(t.index, nxt):
            rows.append([mth, reg, abx, round(25 + 140 * v + rng.normal(0, 4), 1)])
    return pd.DataFrame(rows, columns=["Month", "Region", "Antibiotic", "DDD_per_1000_patient_days"])


def make_demo_isolates(n=2500, seed=3):
    """Synthetic isolate-level wide table with a latent ESBL/carbapenemase driver -> realistic co-resistance."""
    rng = np.random.default_rng(seed); rows = []
    regs = ["North Zone", "East Zone", "South Zone", "West Zone"]
    for i in range(n):
        org = rng.choice(["E. coli", "K. pneumoniae"], p=[.6, .4]); mi = rng.integers(0, 18)
        d = pd.Timestamp("2025-01-01") + pd.DateOffset(months=int(mi), days=int(rng.integers(0, 27)))
        ec = org == "E. coli"; esbl = rng.random() < (0.22 if ec else 0.38) + 0.006 * mi
        carb = esbl and rng.random() < (0.04 if ec else 0.14)
        res = {"Ciprofloxacin": rng.random() < (.72 if esbl else .12), "Ceftriaxone": esbl or rng.random() < .03,
               "Gentamicin": rng.random() < (.5 if esbl else .06), "Trimethoprim-sulfamethoxazole": rng.random() < (.7 if esbl else .25),
               "Meropenem": carb or rng.random() < .005, "Nitrofurantoin": rng.random() < (.12 if ec else .35)}
        row = {"Isolate_ID": f"I{i:05d}", "Patient_Key": f"P{rng.integers(1, int(n * .85)):05d}", "Date": d.date(),
               "Region": rng.choice(regs), "Organism": org, "Specimen": rng.choice(["Urine", "Blood", "Respiratory"]),
               "Ward": rng.choice(["ICU", "General ward", "OPD"], p=[.2, .5, .3])}
        for k, v in res.items():
            row[k] = None if rng.random() < .03 else ("R" if v else "S")
        rows.append(row)
    return pd.DataFrame(rows)


def demo_events(base):
    """Ground-truth for the synthetic backtest: Scenario B rise begins at month index 14."""
    return pd.DataFrame([dict(Region="East Zone", Organism="K. pneumoniae", Antibiotic="Meropenem",
                              Event_Start=(pd.Timestamp("2025-01-01") + pd.DateOffset(months=14)).strftime("%Y-%m"))])


# ---------------- privacy ----------------
def suppress(df, k=5):
    """Small-cell suppression for exports: rows with Tested<k have counts blanked (national-style rule)."""
    d = df.copy(); m = d["Tested"] < k
    d["Resistant"] = d["Resistant"].astype(float).mask(m); d["Tested"] = d["Tested"].astype(float).mask(m)
    d["Suppressed_small_cell"] = m
    return d


# ---------------- contextual stratification ----------------
def strata_table(df, col):
    g = df.groupby(["Organism", "Antibiotic", col], as_index=False)[["Resistant", "Tested"]].sum()
    t = g.groupby(["Organism", "Antibiotic"])[["Resistant", "Tested"]].transform("sum")
    ro, no = (t.Resistant - g.Resistant).values.astype(float), (t.Tested - g.Tested).values.astype(float)
    g["Pct"] = g.Resistant / g.Tested * 100
    g["CI_low"], g["CI_high"] = E.wilson(g.Resistant, g.Tested)
    with np.errstate(divide="ignore", invalid="ignore"):
        g["Pct_rest"] = np.where(no > 0, ro / no * 100, np.nan)
        pool = (g.Resistant + ro) / (g.Tested + no)
        se = np.sqrt(pool * (1 - pool) * (1 / g.Tested + 1 / no))
        z = (g.Resistant / g.Tested - ro / no) / se
    g["Diff_pp"] = g.Pct - g.Pct_rest
    g["P_value"] = np.where(np.isfinite(z), _erfc(np.abs(np.nan_to_num(z)) / math.sqrt(2)), np.nan)
    g["FDR_q"] = E.bh_qvalues(g["P_value"].values)
    g["Low_n"] = g.Tested < 30
    return g.round(3).sort_values(["FDR_q", "P_value"]).reset_index(drop=True)


def strat_alerts(df, col, **kw):
    rows = []
    for (reg, org, abx, lv), g in df.groupby(["Region", "Organism", "Antibiotic", col]):
        res, _ = E.analyze_series(g, **kw)
        rows.append(dict(Region=reg, Organism=org, Antibiotic=abx, **{col: lv}, Status=res["status"],
                         Baseline_pct=res.get("p_base"), Recent_pct=res.get("p_recent"), Change_pp=res.get("change_pp"),
                         N_recent=res.get("n_recent"), Flags="; ".join(res["flags"])))
    t = pd.DataFrame(rows)
    o = {E.RED: 0, E.AMBER: 1, E.GREEN: 2}
    return t.sort_values("Status", key=lambda s: s.map(o)).round(2).reset_index(drop=True) if len(t) else t


# ---------------- antibiotic use vs resistance (ecological) ----------------
def check_use(use):
    use = use.copy(); use.columns = [str(c).strip() for c in use.columns]
    need = ["Month", "Region", "Antibiotic"]
    if any(c not in use for c in need) or len(use.columns) < 4:
        return None, "Use file needs columns: Month, Region, Antibiotic, <consumption value e.g. DDD_per_1000_patient_days>."
    val = [c for c in use.columns if c not in need][0]
    use = use.rename(columns={val: "DDD"}); use["Month"] = pd.to_datetime(use["Month"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    use["DDD"] = pd.to_numeric(use["DDD"], errors="coerce")
    return use.dropna(subset=["Month", "DDD"])[need + ["DDD"]], None


def use_vs_resistance(df, use, max_lag=3, perm=500, seed=0):
    """Spearman correlation of FIRST DIFFERENCES (removes shared trends) between use and resistance, lag 0..max_lag
    (use leading resistance). Permutation p-values; BH-FDR across all tests. Ecological - never causal."""
    rng = np.random.default_rng(seed); rows = []
    s = df.groupby(["Region", "Organism", "Antibiotic", "Month"], as_index=False)[["Resistant", "Tested"]].sum()
    s["Pct"] = s.Resistant / s.Tested * 100
    for (reg, org, abx), g in s.groupby(["Region", "Organism", "Antibiotic"]):
        u = use[(use.Region == reg) & (use.Antibiotic == abx)].set_index("Month")["DDD"]
        if u.empty:
            continue
        idx = pd.date_range(g.Month.min(), g.Month.max(), freq="MS")
        y = g.set_index("Month")["Pct"].reindex(idx); x0 = u.reindex(idx)
        for lag in range(max_lag + 1):
            d = pd.DataFrame({"y": y.diff(), "x": x0.shift(lag).diff()}).dropna()
            if len(d) < 8:
                continue
            rx, ry = d.x.rank().values, d.y.rank().values
            rho = np.corrcoef(rx, ry)[0, 1]
            if not np.isfinite(rho):
                continue
            null = np.array([np.corrcoef(rng.permutation(rx), ry)[0, 1] for _ in range(perm)])
            p = (np.sum(np.abs(null) >= abs(rho)) + 1) / (perm + 1)
            rows.append(dict(Region=reg, Organism=org, Antibiotic=abx, Lag_months=lag, N_months=len(d),
                             Spearman_rho=round(rho, 3), Perm_p=round(p, 4)))
    t = pd.DataFrame(rows)
    if len(t):
        t["FDR_q"] = E.bh_qvalues(t.Perm_p.values).round(4)
        t = t.sort_values("FDR_q").reset_index(drop=True)
    return t


# ---------------- isolate-level data: co-resistance, MDR ----------------
def validate_isolates(raw):
    """Wide table: Patient_Key (or an ID column that is hashed), Date, Organism, + one S/I/R column per antibiotic."""
    warns, df = [], raw.copy()
    df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
    low = {c.lower(): c for c in df.columns}
    pid = next((low[k] for k in ("patient_key", "patient_id", "patient", "uhid", "mrn") if k in low), None)
    if pid is None:
        return None, [], ["Need a patient identifier column (pseudonymous key preferred) for first-isolate de-duplication."], warns
    salt = hashlib.sha256(str(np.random.default_rng().random()).encode()).hexdigest()
    df["Patient_Key"] = df[pid].astype(str).map(lambda v: hashlib.sha256((salt + v).encode()).hexdigest()[:10])
    if pid != "Patient_Key":
        df = df.drop(columns=[pid]); warns.append(f"'{pid}' was irreversibly hashed (session salt) and removed.")
    df, pw, pe = E.pii_guard(df, skip=("Patient_Key",)); warns += pw
    if pe:
        return None, [], pe, warns
    ren = {c: {"date": "Date", "month": "Date", "organism": "Organism", "pathogen": "Organism", "region": "Region",
               "specimen": "Specimen", "ward": "Ward"}.get(c.lower(), c) for c in df.columns}
    df = df.rename(columns=ren)
    if "Date" not in df or "Organism" not in df:
        return None, [], ["Isolate file needs Date and Organism columns."], warns
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce"); df = df.dropna(subset=["Date"])
    ok = {"S", "I", "R", "SDD", "NS"}
    drugs = [c for c in df.columns if c not in ("Patient_Key", "Date", "Organism", "Region", "Specimen", "Ward", "Isolate_ID")
             and df[c].dropna().astype(str).str.upper().str.strip().isin(ok).mean() > .9 and df[c].notna().any()]
    if len(drugs) < 2:
        return None, [], ["Found fewer than 2 antibiotic columns with S/I/R values."], warns
    return df, drugs, [], warns


def first_isolates(iso, days=30):
    """Keep the first isolate per patient+organism; later ones within `days` of the last kept one are dropped."""
    iso = iso.sort_values("Date"); last, keep = {}, []
    for i, p, o, d in zip(iso.index, iso.Patient_Key, iso.Organism, iso.Date):
        k = (p, o)
        if k in last and (d - last[k]).days <= days:
            continue
        last[k] = d; keep.append(i)
    return iso.loc[keep]


def to_binary(iso, drugs, res_def="R only"):
    bad = {"R", "NS"} if res_def == "R only" else {"R", "I", "NS", "SDD"}
    out = iso.copy()
    for d in drugs:
        s = out[d].astype("string").str.upper().str.strip()
        out[d] = np.where(s.isin(["S", "I", "R", "SDD", "NS"]), s.isin(bad).astype(float), np.nan)
    return out


def coresistance(b, drugs, min_n=30):
    rows = []
    for a, c in combinations(drugs, 2):
        m = b[[a, c]].dropna(); n = len(m)
        if n < min_n:
            continue
        A, B = m[a].values, m[c].values; ab = int(((A == 1) & (B == 1)).sum()); a1, b1 = int(A.sum()), int(B.sum())
        pA, pB, pab = a1 / n, b1 / n, ab / n; exp = pA * pB; den = math.sqrt(pA * (1 - pA) * pB * (1 - pB))
        phi = (pab - exp) / den if den > 0 else np.nan
        orr = ((ab + .5) * (n - a1 - b1 + ab + .5)) / ((a1 - ab + .5) * (b1 - ab + .5))
        p = math.erfc(math.sqrt(n * phi * phi / 2)) if np.isfinite(phi) else np.nan
        rows.append(dict(Drug_A=a, Drug_B=c, N_both_tested=n, Pct_A=pA * 100, Pct_B=pB * 100, Pct_both=pab * 100,
                         Expected_if_independent=exp * 100, Lift=pab / exp if exp > 0 else np.nan, Phi=phi, Odds_ratio=orr, P_value=p))
    t = pd.DataFrame(rows)
    if len(t):
        t["FDR_q"] = E.bh_qvalues(t.P_value.values)
        t = t.sort_values("Phi", ascending=False)
    return t.round(4).reset_index(drop=True)


def mdr_flags(b, drugs):
    """Magiorakos 2012: MDR = non-susceptible to >=1 agent in >=3 classes (needs >=3 classes tested)."""
    cls = {}
    for d in drugs:
        cls.setdefault(CLASS.get(d, d), []).append(d)
    res = pd.DataFrame({c: b[v].max(axis=1, skipna=True) for c, v in cls.items()})
    tested = res.notna().sum(axis=1)
    mdr = (res.fillna(0).sum(axis=1) >= 3).astype(float).where(tested >= 3)
    return mdr, [d for d in drugs if d not in CLASS]


def mdr_trend(b, mdr):
    t = pd.DataFrame({"Month": b.Date.dt.to_period("M").dt.to_timestamp(), "MDR": mdr}).dropna()
    g = t.groupby("Month").agg(Resistant=("MDR", "sum"), Tested=("MDR", "size")).reset_index()
    g["Pct"] = g.Resistant / g.Tested * 100; g["CI_low"], g["CI_high"] = E.wilson(g.Resistant, g.Tested)
    return g


def frechet(df, region, org, months):
    """Aggregate-only data: bounds on P(resistant to both) from marginals. Assumes both drugs tested on the same isolates."""
    s = df[(df.Region == region) & (df.Organism == org) & df.Month.isin(months)].groupby("Antibiotic")[["Resistant", "Tested"]].sum()
    p = (s.Resistant / s.Tested).to_dict(); rows = []
    for a, c in combinations(sorted(p), 2):
        rows.append(dict(Drug_A=a, Drug_B=c, Pct_A=p[a] * 100, Pct_B=p[c] * 100, Min_both=max(0, p[a] + p[c] - 1) * 100,
                         If_independent=p[a] * p[c] * 100, Max_both=min(p[a], p[c]) * 100))
    return pd.DataFrame(rows).round(1)


# ---------------- backtest / external-validation harness ----------------
def backtest(df, events, recent=3, z_thr=2.33, min_pp=8.0, min_n=60, win=3):
    ev = {(r.Region, r.Organism, r.Antibiotic): pd.Timestamp(r.Event_Start) for r in events.itertuples()}
    months = sorted(df.Month.unique()); rows = []
    for key, g in df.groupby(["Region", "Organism", "Antibiotic"]):
        for t in months[recent + 2:]:
            sub = g[g.Month <= t]
            res, tb = E.analyze_series(sub, recent=recent, z_thr=z_thr, min_pp=min_pp, min_n=min_n)
            base_p = tb.Resistant.iloc[:-1].sum() / max(tb.Tested.iloc[:-1].sum(), 1) * 100
            naive = bool(len(tb) >= 4 and pd.notna(tb.Pct.iloc[-1]) and tb.Pct.iloc[-1] - base_p >= min_pp)
            rows.append(dict(Region=key[0], Organism=key[1], Antibiotic=key[2], Month=t, RESISTX=res["status"] == E.RED,
                             Abstain=res["status"] == E.AMBER, Naive=naive, Start=ev.get(key, pd.NaT)))
    d = pd.DataFrame(rows)
    if d.empty:
        return {}, d
    mo = lambda a, b: (a.year - b.year) * 12 + a.month - b.month
    d["Offset"] = [mo(m, s) if pd.notna(s) else np.nan for m, s in zip(d.Month, d.Start)]
    pre = d[d.Offset.isna() | (d.Offset < 0)]
    det = {}
    for rule in ("RESISTX", "Naive"):
        hits, delays = 0, []
        for key in ev:
            x = d[(d.Region == key[0]) & (d.Organism == key[1]) & (d.Antibiotic == key[2]) & d[rule] & d.Offset.between(0, win)]
            if len(x):
                hits += 1; delays.append(int(x.Offset.min()))
        det[rule] = dict(Events=len(ev), Detected=hits, Sensitivity_pct=round(100 * hits / len(ev), 1) if ev else np.nan,
                         Median_delay_months=float(np.median(delays)) if delays else np.nan,
                         False_alerts_per_100_series_months=round(100 * pre[rule].mean(), 2) if len(pre) else np.nan)
    det["RESISTX"]["Abstained_pct_of_series_months"] = round(100 * pre.Abstain.mean(), 1) if len(pre) else np.nan
    return det, d


# ---------------- tamper-evident audit trail + two-person sign-off ----------------
ROLES = ["Analyst", "Surveillance expert"]


def _db():
    E.init_db()
    c = sqlite3.connect(E.DB)
    c.execute("CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, series TEXT, decision TEXT,"
              " reviewer TEXT, role TEXT, note TEXT, prev_hash TEXT, hash TEXT)")
    return c


def _hash(prev, *f):
    return hashlib.sha256((prev + "|" + "|".join(map(str, f))).encode()).hexdigest()


def add_audit(series, decision, reviewer, role, note):
    if not reviewer.strip():
        raise ValueError("Reviewer name is required for the audit trail.")
    with _db() as c:
        r = c.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone(); prev = r[0] if r else "GENESIS"
        ts = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO audit(ts,series,decision,reviewer,role,note,prev_hash,hash) VALUES(?,?,?,?,?,?,?,?)",
                  (ts, series, decision, reviewer.strip(), role, note.strip(), prev, _hash(prev, ts, series, decision, reviewer.strip(), role, note.strip())))


def load_audit():
    with _db() as c:
        return pd.read_sql_query("SELECT * FROM audit ORDER BY id DESC", c)


def verify_audit():
    """-> (ok, first_bad_id). Any edit/deletion of past rows breaks the hash chain."""
    with _db() as c:
        rows = c.execute("SELECT id,ts,series,decision,reviewer,role,note,prev_hash,hash FROM audit ORDER BY id").fetchall()
    prev = "GENESIS"
    for i, ts, s, d, rv, ro, n, ph, h in rows:
        if ph != prev or h != _hash(prev, ts, s, d, rv, ro, n):
            return False, i
        prev = h
    return True, None


def review_state(audit, series):
    a = audit[audit.series == series].sort_values("id")
    if a.empty:
        return "Not reviewed"
    an, ex = a[a.role == "Analyst"], a[a.role == "Surveillance expert"]
    if ex.empty:
        return f"Awaiting expert sign-off (analyst: {an.iloc[-1].decision})" if len(an) else "Not reviewed"
    e = ex.iloc[-1]; an = an[an.reviewer != e.reviewer]
    if an.empty:
        return "Awaiting an independent second reviewer (expert and analyst must be different people)"
    if an.iloc[-1].decision == e.decision:
        return f"FINAL: {e.decision} (two-person sign-off)"
    return f"CONFLICT: analyst={an.iloc[-1].decision} vs expert={e.decision} - adjudication needed"
