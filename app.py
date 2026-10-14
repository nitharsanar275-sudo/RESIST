import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import engine as E
import extras as X

st.set_page_config(page_title="RESIST-X | AMR Early-Warning", page_icon="🧬", layout="wide")

CSS = """
<style>
.stApp{background:radial-gradient(1200px 600px at 10% -10%,#12315a 0%,#0a0f1c 55%);color:#e6eefb}
[data-testid="stSidebar"]{background:#0d1626;border-right:1px solid #1f3355}
#MainMenu,footer{visibility:hidden}
.hero{padding:18px 24px;border-radius:16px;background:linear-gradient(120deg,#0e2a4d,#123f6b 60%,#0f6b6b);
 border:1px solid #2a5a8f;margin-bottom:14px}
.hero h1{margin:0;font-size:2.1rem;letter-spacing:1px;color:#fff}
.hero p{margin:4px 0 0;color:#b9d3f2}
.badge{display:inline-block;padding:4px 12px;border-radius:99px;font-weight:700;font-size:.8rem;margin-top:8px}
.b-syn{background:#4a3a00;color:#ffd24a;border:1px solid #ffd24a}
.b-real{background:#07381f;color:#4be38a;border:1px solid #4be38a}
.b-unk{background:#3a1f4a;color:#d9a8ff;border:1px solid #d9a8ff}
.card{background:#101b30;border:1px solid #23406b;border-radius:14px;padding:14px 18px}
.card .v{font-size:1.9rem;font-weight:800;color:#fff}.card .l{color:#8fb0da;font-size:.85rem}
.alert{border-left:6px solid;border-radius:10px;padding:12px 16px;margin:8px 0;background:#101b30}
.a-red{border-color:#ff4d6d}.a-amb{border-color:#ffb020}.a-grn{border-color:#2fd47a}
.small{color:#8fb0da;font-size:.82rem}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

COL = {E.RED: "#ff4d6d", E.AMBER: "#ffb020", E.GREEN: "#2fd47a"}
ICON = {E.RED: "🔴", E.AMBER: "🟡", E.GREEN: "🟢"}
CLS = {E.RED: "a-red", E.AMBER: "a-amb", E.GREEN: "a-grn"}


def show_chart(fig):
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(16,27,48,.6)",
                      margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", y=-0.2))
    try:
        st.plotly_chart(fig, width="stretch")
    except TypeError:
        st.plotly_chart(fig, use_container_width=True)


def show_df(df):
    try:
        st.dataframe(df, width="stretch", hide_index=True)
    except TypeError:
        st.dataframe(df, use_container_width=True, hide_index=True)


def csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8")


@st.cache_data
def demo():
    return X.make_demo_context(E.make_demo())


@st.cache_data
def demo_iso():
    return X.make_demo_isolates()


@st.cache_data
def demo_use():
    return X.make_demo_use(E.make_demo())


@st.cache_data
def run_backtest(d, ev, recent, z, pp, mn):
    return X.backtest(d, ev, recent=recent, z_thr=z, min_pp=pp, min_n=mn)


@st.cache_data
def run_use(d, u):
    return X.use_vs_resistance(d, u)


# ---------------- sidebar: data source ----------------
st.sidebar.markdown("## 🧬 RESIST-X")
source = st.sidebar.radio("Data source", ["Upload CSV", "Synthetic demo"])
data, label = None, "syn"
iso_df, drugs, use_df, events = None, [], None, None
if source == "Synthetic demo":
    data = demo()
    scn = st.sidebar.selectbox("Demo scenario", ["All series", "A - Stable", "B - Unusual increase",
                                                 "C - Insufficient evidence"])
    if scn != "All series":
        data = data[data["Scenario"] == scn]
    iso_df, drugs, _, _ = X.validate_isolates(demo_iso())
    use_df, _ = X.check_use(demo_use())
    events = X.demo_events(None)
else:
    up = st.sidebar.file_uploader("CSV file", type=["csv"])
    st.sidebar.caption("Required columns: " + ", ".join(E.REQUIRED))
    st.sidebar.download_button("⬇ Sample template", csv_bytes(demo()[E.REQUIRED + ["Hospital", "Ward", "Specimen", "Age_Group"]].head(12)),
                               "resist_x_template.csv", "text/csv")
    kind = st.sidebar.selectbox("This file is", ["Unverified (label me)", "Real surveillance data",
                                                 "Synthetic / test data"])
    label = {"Unverified (label me)": "unk", "Real surveillance data": "real", "Synthetic / test data": "syn"}[kind]
    if up is not None:
        try:
            raw = pd.read_csv(up, encoding="utf-8-sig", sep=None, engine="python")
            clean, errs, warns = E.validate_upload(raw)
            for w in warns:
                st.sidebar.warning(w)
            for er in errs:
                st.sidebar.error(er)
            data = clean
        except Exception as ex:
            st.sidebar.error(f"Could not read file: {ex}")
    with st.sidebar.expander("➕ Optional files (richer analysis)"):
        st.caption("Isolate-level (wide, one S/I/R column per antibiotic), antibiotic use (Month,Region,Antibiotic,DDD) "
                   "and labelled events (Region,Organism,Antibiotic,Event_Start).")
        fi, fu, fe = st.file_uploader("Isolate-level CSV", type=["csv"]), st.file_uploader("Antibiotic-use CSV", type=["csv"]), \
            st.file_uploader("Events CSV", type=["csv"])
        try:
            if fi is not None:
                iso_df, drugs, ie, iw = X.validate_isolates(pd.read_csv(fi, encoding="utf-8-sig"))
                [st.warning(w) for w in iw]; [st.error(e) for e in ie]
            if fu is not None:
                use_df, ue = X.check_use(pd.read_csv(fu, encoding="utf-8-sig"))
                if ue: st.error(ue)
            if fe is not None:
                events = pd.read_csv(fe)
        except Exception as ex:
            st.error(f"Could not read optional file: {ex}")
    if data is None:
        st.info("""### Real data steps
1. Register & download ATLAS: https://amr.vivli.org/ (free, needs approval)
2. In CMD: `python convert_atlas.py atlas.csv --country India --out data`
3. Sidebar: **Upload CSV** > `data/atlas_aggregate.csv`; set *This file is* = **Real surveillance data**
4. Sidebar > Optional files: Isolate-level CSV > `data/atlas_isolates.csv`
5. Your own hospital/lab data: columns Month, Region, Organism, Antibiotic, Resistant, Tested (counts only, no patient names)""")

# ---------------- header ----------------
BADGE = {"syn": ("b-syn", "⚠ SYNTHETIC DEMO DATA - NOT REAL OBSERVATIONS"),
         "real": ("b-real", "✔ USER-DECLARED REAL SURVEILLANCE DATA"),
         "unk": ("b-unk", "? DATA ORIGIN UNVERIFIED")}
bc, bt = BADGE[label]
st.markdown(f"""<div class="hero"><h1>🧬 RESIST-X</h1>
<p>Antimicrobial Resistance Early-Warning &amp; Surveillance - flags trends for <b>human review</b>,
accounting for sample size, uncertainty and missing data.</p><span class="badge {bc}">{bt}</span></div>""",
            unsafe_allow_html=True)

if data is None or data.empty:
    st.stop()

# ---------------- filters ----------------
st.sidebar.markdown("### Filters")
regs = sorted(data["Region"].unique())
orgs = sorted(data["Organism"].unique())
abxs = sorted(data["Antibiotic"].unique())
f_reg = st.sidebar.multiselect("Region", regs, default=regs)
f_org = st.sidebar.multiselect("Organism", orgs, default=orgs)
f_abx = st.sidebar.multiselect("Antibiotic", abxs, default=abxs)
f_ctx = {}
for c_ in X.CTX:
    if c_ in data.columns:
        lv = sorted(data[c_].dropna().unique())
        f_ctx[c_] = st.sidebar.multiselect(c_.replace("_", " "), lv, default=lv)
dmin, dmax = data["Month"].min().date(), data["Month"].max().date()
if dmin < dmax:
    d1, d2 = st.sidebar.slider("Date range", dmin, dmax, (dmin, dmax), format="MMM YYYY")
else:
    d1, d2 = dmin, dmax
with st.sidebar.expander("⚙ Alert settings"):
    recent = st.slider("Recent window (months)", 2, 6, E.DEFAULTS["recent"])
    z_thr = st.slider("Z threshold", 1.5, 4.0, E.DEFAULTS["z_thr"], 0.01)
    min_pp = st.slider("Min. rise (% points)", 2.0, 20.0, E.DEFAULTS["min_pp"], 0.5)
    min_n = st.slider("Min. samples per window", 10, 300, E.DEFAULTS["min_n"], 5)

with st.sidebar.expander("🔒 Privacy & provenance"):
    sup_on = st.checkbox("Suppress small cells in downloads", value=(label != "syn"))
    sup_k = st.number_input("Suppress cells with fewer than k tests", 1, 30, 5)
    std = st.selectbox("Lab standard", ["Not stated", "CLSI", "EUCAST", "Mixed / other"])
    ver = st.text_input("Standard version/year", "")
    src = st.text_input("Data source / lab / download date", "")
PROV = f"Data: {label.upper()} | Standard: {std} {ver} | Source: {src or 'not stated'} | Small-cell suppression k={sup_k if sup_on else 'off'}"
df = data[data["Region"].isin(f_reg) & data["Organism"].isin(f_org) & data["Antibiotic"].isin(f_abx)
          & (data["Month"].dt.date >= d1) & (data["Month"].dt.date <= d2)]
for c_, sel_ in f_ctx.items():
    df = df[df[c_].isin(sel_)]
if df.empty:
    st.warning("No data matches the current filters. Widen the filters in the sidebar.")
    st.stop()

alerts = E.analyze_all(df, recent=recent, z_thr=z_thr, min_pp=min_pp, min_n=min_n)

# ---------------- summary cards ----------------
tot_t, tot_r = int(df["Tested"].sum()), int(df["Resistant"].sum())
n_red = int((alerts["Status"] == E.RED).sum())
n_amb = int((alerts["Status"] == E.AMBER).sum())
cards = [("Series monitored", len(alerts)), ("Samples tested", f"{tot_t:,}"),
         ("Overall resistance", f"{tot_r / tot_t * 100:.1f}%"),
         ("🔴 Review alerts", n_red), ("🟡 Low evidence", n_amb)]
for c, (l, v) in zip(st.columns(5), cards):
    c.markdown(f'<div class="card"><div class="l">{l}</div><div class="v">{v}</div></div>', unsafe_allow_html=True)
st.write("")

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10 = st.tabs([
    "🚨 Alerts", "📈 Trends", "🗺 Region compare", "🗃 Data & downloads", "ℹ Method",
    "🧪 Validation", "🧬 Co-resistance & quality", "📝 Review & report", "🏥 Context & antibiotic use", "🛡 Governance"])

# ---------------- alerts ----------------
with tab1:
    st.markdown("#### Early-warning review queue")
    st.caption("Flags are for investigation by a human. They do not confirm outbreaks or recommend treatment.")
    for _, r in alerts.iterrows():
        flag = f'<br><span class="small">⚠ {r["Data_flags"]}</span>' if r["Data_flags"] else ""
        st.markdown(
            f'<div class="alert {CLS[r["Status"]]}"><b>{ICON[r["Status"]]} {r["Status"]}</b> - '
            f'{r["Organism"]} / {r["Antibiotic"]} / {r["Region"]}<br>'
            f'<span class="small">{r["Explanation"]}</span>{flag}</div>', unsafe_allow_html=True)
    st.markdown("##### Inspect the data behind an alert")
    keys = [(r["Region"], r["Organism"], r["Antibiotic"]) for _, r in alerts.iterrows()]
    pick = st.selectbox("Series", keys, format_func=lambda k: " | ".join(k))
    reg, org, abx = pick
    sub = df[(df.Region == reg) & (df.Organism == org) & (df.Antibiotic == abx)]
    res, tbl = E.analyze_series(sub, recent=recent, z_thr=z_thr, min_pp=min_pp, min_n=min_n)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=tbl["Month"], y=tbl["CI_high"], line=dict(width=0), hoverinfo="skip",
                             showlegend=False))
    fig.add_trace(go.Scatter(x=tbl["Month"], y=tbl["CI_low"], fill="tonexty", fillcolor="rgba(80,160,255,.2)",
                             line=dict(width=0), name="95% CI (Wilson)", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=tbl["Month"], y=tbl["Pct"], mode="lines+markers", name="Resistance %",
                             line=dict(color=COL[res["status"]], width=3), connectgaps=False,
                             customdata=tbl[["Resistant", "Tested"]].fillna(0).values,
                             hovertemplate="%{x|%b %Y}<br>%{y:.1f}% (%{customdata[0]:.0f}/%{customdata[1]:.0f})"
                                           "<extra></extra>"))
    if "p_base" in res and len(tbl) > recent:
        fig.add_hline(y=res["p_base"], line_dash="dot", line_color="#9fb8d9",
                      annotation_text=f"baseline {res['p_base']:.1f}%")
        fig.add_vrect(x0=tbl["Month"].iloc[-recent], x1=tbl["Month"].iloc[-1], fillcolor="#ffffff",
                      opacity=0.07, line_width=0, annotation_text="recent window",
                      annotation_position="top left")
    fig.update_layout(title=f"{org} / {abx} - {reg}", yaxis_title="Resistance (%)", xaxis_title="Month")
    show_chart(fig)
    alert_fig, alert_res, alert_pick = fig, res, pick
    st.markdown(f'<div class="alert {CLS[res["status"]]}"><b>{ICON[res["status"]]} {res["status"]}</b><br>'
                f'<span class="small">{res["explanation"]}</span></div>', unsafe_allow_html=True)
    st.info("🇮🇳 தமிழ் / Tanglish: " + E.explain_ta(res))
    cu = E.cusum(tbl)
    if cu["CUSUM"].notna().any():
        fc = go.Figure(go.Scatter(x=cu["Month"], y=cu["CUSUM"], mode="lines+markers", line=dict(color="#c084fc")))
        fc.add_hline(y=4.0, line_dash="dash", line_color="#ff4d6d", annotation_text="CUSUM alarm limit")
        fc.update_layout(title="CUSUM control chart (second, independent method)", yaxis_title="CUSUM")
        show_chart(fc)
        if bool(cu["Alarm"].any()):
            st.caption("CUSUM crossed its limit in: " + ", ".join(cu.loc[cu["Alarm"], "Month"].dt.strftime("%b %Y")))
    show_df(tbl.round(2).assign(Month=tbl["Month"].dt.strftime("%Y-%m")))

# ---------------- trends ----------------
with tab2:
    st.markdown("#### Resistance trends")
    d2_ = df.assign(Series=df["Region"] + " | " + df["Organism"] + " | " + df["Antibiotic"])
    g = d2_.groupby(["Series", "Month"], as_index=False)[["Resistant", "Tested"]].sum()
    g["Pct"] = g["Resistant"] / g["Tested"] * 100
    allser = sorted(g["Series"].unique())
    sel = st.multiselect("Series to plot", allser, default=allser)
    fig = go.Figure()
    for s in sel:
        x = g[g["Series"] == s]
        fig.add_trace(go.Scatter(x=x["Month"], y=x["Pct"], mode="lines+markers", name=s,
                                 customdata=x[["Resistant", "Tested"]].values,
                                 hovertemplate="%{x|%b %Y}<br>%{y:.1f}% (%{customdata[0]}/%{customdata[1]})"
                                               "<extra></extra>"))
    fig.update_layout(title="Monthly resistance % (hover for counts)", yaxis_title="Resistance (%)")
    show_chart(fig)
    vol = d2_.groupby("Month", as_index=False)["Tested"].sum()
    fb = go.Figure(go.Bar(x=vol["Month"], y=vol["Tested"], marker_color="#3b82f6"))
    fb.update_layout(title="Samples tested per month (sample-size context)", yaxis_title="Samples")
    show_chart(fb)

# ---------------- region compare ----------------
with tab3:
    st.markdown("#### Compare regions")
    pairs = sorted(set(zip(df["Organism"], df["Antibiotic"])))
    o, a = st.selectbox("Organism | Antibiotic", pairs, format_func=lambda k: " | ".join(k))
    s = df[(df["Organism"] == o) & (df["Antibiotic"] == a)]
    cmp_ = s.groupby("Region", as_index=False)[["Resistant", "Tested"]].sum()
    lo, hi = E.wilson(cmp_["Resistant"], cmp_["Tested"])
    cmp_["Pct"] = cmp_["Resistant"] / cmp_["Tested"] * 100
    fig = go.Figure(go.Bar(x=cmp_["Region"], y=cmp_["Pct"], marker_color="#38bdf8",
                           error_y=dict(type="data", symmetric=False, array=(hi - cmp_["Pct"]).values,
                                        arrayminus=(cmp_["Pct"] - lo).values),
                           text=[f"n={n:,}" for n in cmp_["Tested"]], textposition="outside"))
    fig.update_layout(title=f"{o} / {a}: resistance by region (95% CI, filtered period)",
                      yaxis_title="Resistance (%)")
    show_chart(fig)
    s2 = s.groupby(["Region", "Month"], as_index=False)[["Resistant", "Tested"]].sum()
    s2["Pct"] = s2["Resistant"] / s2["Tested"] * 100
    piv = s2.pivot(index="Region", columns="Month", values="Pct")
    hm = go.Figure(go.Heatmap(z=piv.values, x=[m.strftime("%b %y") for m in piv.columns], y=list(piv.index),
                              colorscale="YlOrRd", colorbar=dict(title="%"), hoverongaps=False))
    hm.update_layout(title="Region x month heatmap (blank = no data)")
    show_chart(hm)

# ---------------- data ----------------
with tab4:
    st.markdown("#### Data quality")
    q1, q2, q3 = st.columns(3)
    q1.metric("Rows", len(df))
    q2.metric("Rows with <10 samples", int((df["Tested"] < 10).sum()))
    q3.metric("Series with missing months", int(alerts["Data_flags"].str.contains("Missing").sum()))
    st.markdown("#### Raw data preview")
    show_df(df.assign(Month=df["Month"].dt.strftime("%Y-%m")).head(500))
    cA, cB = st.columns(2)
    cA.download_button("⬇ Download filtered data (CSV)", csv_bytes(X.suppress(df, sup_k) if sup_on else df), "resist_x_filtered_data.csv", "text/csv")
    cB.download_button("⬇ Download alerts (CSV)", csv_bytes(alerts), "resist_x_alerts.csv", "text/csv")
    st.markdown("#### Alert table")
    show_df(alerts.drop(columns=["Explanation"]))

# ---------------- method ----------------
with tab5:
    st.markdown("""
#### How RESIST-X works
1. Counts are summed per **Region × Organism × Antibiotic × Month**; resistance % = Resistant / Tested.
2. Each month gets a **Wilson 95% confidence interval**, so small samples show wide uncertainty.
3. The **recent window** (default last 3 months) is compared with the earlier **baseline** using a one-sided
   two-proportion z-test. A *Review alert* needs **both** z ≥ threshold **and** a minimum rise in % points.
4. If sample counts are below the minimum, or months are missing, the result is **Insufficient evidence**
   instead of an alert.
5. Every alert shows its numbers and reason. All thresholds are adjustable in the sidebar.

#### Limitations
- Prototype; **not validated** for outbreak prediction, diagnosis or treatment advice.
- Multiple-comparison control (Benjamini-Hochberg) is applied; some false alarms are still expected.
- Demo data is **synthetic**; real data needs a clear source, definitions and lab-method notes (see Governance tab).
- Do not upload patient-identifying data (names, phone numbers, MRNs). Only aggregated counts are needed.
""")


# ---------------- extra method/sources ----------------
with tab5:
    st.markdown("""
#### Extra safeguards
- **FDR correction (Benjamini-Hochberg):** with many series tested at once, alerts that do not survive
  correction are flagged in the alert card and the `FDR_q` column.
- **CUSUM** is shown as an independent second method on each series.

#### Data sources to check for real data (verify access yourself; not all offer CSV download)
- WHO AMR dashboard: https://data.who.int/dashboards/amr
- ICMR reports: https://www.icmr.gov.in/reports?q=AMR
- ICMR AMRSN dataset page: https://nhrdr.icmr.org.in/datasets/icmr-antimicrobial-resistance-surveillance-network-dataset

When you import real data, record the source, download date, definitions (e.g. S/I/R standard) and limitations.
""")

# ---------------- validation ----------------
with tab6:
    st.markdown("#### Does the detector actually work? (Monte-Carlo simulation, synthetic)")
    st.caption("We inject a known rise into simulated series and count how often each rule raises an alert. "
               "0 pp rise = false-alarm rate. Naive rule = 'latest month exceeds baseline mean by the min. rise'.")
    c1, c2, c3 = st.columns(3)
    sn = c1.select_slider("Samples per month", [10, 20, 50, 100, 200, 400], 100)
    sb = c2.slider("Baseline resistance (%)", 2, 50, 10)
    sd = c3.slider("True rise (% points)", 0, 30, 15)
    r0 = E.sim_rates(n=sn, base=sb / 100, delta=sd / 100, z_thr=z_thr, min_pp=min_pp, min_n=min_n)
    r00 = E.sim_rates(n=sn, base=sb / 100, delta=0.0, z_thr=z_thr, min_pp=min_pp, min_n=min_n)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("RESIST-X detection", f"{r0['proposed']*100:.1f}%")
    m2.metric("RESIST-X false alarms", f"{r00['proposed']*100:.1f}%")
    m3.metric("Naive detection", f"{r0['naive']*100:.1f}%")
    m4.metric("Naive false alarms", f"{r00['naive']*100:.1f}%")
    if r0["insufficient"]:
        st.warning("With these settings the sample size is below the minimum, so RESIST-X abstains "
                   "(Insufficient evidence) rather than alerting.")
    grid = E.validation_grid(z_thr, min_pp, min_n)
    fg = go.Figure()
    for n_, gg in grid.groupby("Monthly_samples"):
        fg.add_trace(go.Scatter(x=gg["True_rise_pp"], y=gg["RESISTX_alert_pct"], mode="lines+markers",
                                name=f"RESIST-X n={n_}"))
    fg.update_layout(title="Alert rate vs true rise (higher on right, ~0 at left is good)",
                     xaxis_title="True rise (% points)", yaxis_title="Alert rate (%)")
    show_chart(fg)
    show_df(grid)

# ---------------- co-resistance & quality ----------------
with tab7:
    st.markdown("#### Organism x antibiotic resistance (latest window)")
    lastm = sorted(df["Month"].unique())[-recent:]
    L = df[df["Month"].isin(lastm)].groupby(["Organism", "Antibiotic"], as_index=False)[["Resistant", "Tested"]].sum()
    L["Pct"] = L["Resistant"] / L["Tested"] * 100
    pv = L.pivot(index="Organism", columns="Antibiotic", values="Pct")
    hm2 = go.Figure(go.Heatmap(z=pv.values, x=list(pv.columns), y=list(pv.index), colorscale="YlOrRd",
                               colorbar=dict(title="%"), hoverongaps=False))
    hm2.update_layout(title="Resistance % (blank = combination not tested)")
    show_chart(hm2)
    multi = alerts[alerts["Status"] == E.RED].groupby(["Region", "Organism"]).size()
    multi = multi[multi >= 2]
    if len(multi):
        st.error("Multi-drug signal: " + "; ".join(f"{r} / {o} has {n} alerting antibiotics" for (r, o), n in multi.items()))
    else:
        st.caption("No region-organism pair currently has alerts on 2+ antibiotics.")
    st.markdown("#### Data-quality score per series")
    st.caption("Score = 60% month completeness + 40% share of months with at least 30 samples.")
    show_df(E.data_quality(df))

# ---------------- validation: backtest ----------------
with tab6:
    st.markdown("---\n#### Retrospective backtest (external-validation harness)")
    st.caption("Replays the alert rule month by month on data and compares it with labelled events "
               "(Region, Organism, Antibiotic, Event_Start). Use it on YOUR hospital data before any operational use.")
    if events is None or len(events) == 0:
        st.info("Upload a labelled-events CSV in the sidebar (Optional files) to run external validation.")
    else:
        det, _bt = run_backtest(df, events, recent, z_thr, min_pp, min_n)
        if det:
            st.dataframe(pd.DataFrame(det).T)
            st.caption("Sensitivity = labelled events caught within 3 months of onset. False alerts = alerts raised "
                       "before onset / in series with no event. 'Abstained' = Insufficient evidence instead of guessing.")

# ---------------- co-resistance: isolate-level ----------------
with tab7:
    st.markdown("---\n#### Patient-level co-resistance & MDR (isolate-level data)")
    if iso_df is None:
        st.info("Upload an isolate-level CSV (sidebar > Optional files) to get true co-resistance. "
                "Until then only aggregate bounds are possible (below).")
    else:
        i1, i2, i3 = st.columns(3)
        io = i1.selectbox("Organism", sorted(iso_df["Organism"].unique()))
        rd = i2.radio("Resistant means", ["R only", "I + R (non-susceptible)"], horizontal=True)
        dd = i3.number_input("First-isolate window (days)", 0, 365, 30)
        sub = iso_df[iso_df["Organism"] == io]
        fi_ = X.first_isolates(sub, dd) if dd else sub
        bi = X.to_binary(fi_, drugs, rd)
        st.caption(f"{len(sub):,} isolates -> {len(fi_):,} after first-isolate de-duplication per patient.")
        co = X.coresistance(bi, drugs)
        if len(co):
            M = pd.DataFrame(index=drugs, columns=drugs, dtype=float)
            for r_ in co.itertuples():
                M.loc[r_.Drug_A, r_.Drug_B] = M.loc[r_.Drug_B, r_.Drug_A] = r_.Phi
            show_chart(go.Figure(go.Heatmap(z=M.values, x=drugs, y=drugs, colorscale="RdBu_r", zmid=0, zmin=-1, zmax=1,
                                            colorbar=dict(title="phi"))).update_layout(title=f"Co-resistance (phi) - {io}"))
            show_df(co)
        else:
            st.warning("Too few isolates tested for any drug pair (need 30+).")
        mdr, unm = X.mdr_flags(bi, drugs)
        if unm:
            st.caption("Drugs without a class mapping were treated as their own class: " + ", ".join(unm))
        mt = X.mdr_trend(bi, mdr)
        if len(mt):
            fm = go.Figure([go.Scatter(x=mt.Month, y=mt.CI_high, line=dict(width=0), showlegend=False, hoverinfo="skip"),
                            go.Scatter(x=mt.Month, y=mt.CI_low, fill="tonexty", fillcolor="rgba(192,132,252,.2)", line=dict(width=0), name="95% CI"),
                            go.Scatter(x=mt.Month, y=mt.Pct, mode="lines+markers", name="MDR %", line=dict(color="#c084fc"))])
            fm.update_layout(title="MDR (>=3 antibiotic classes) % of first isolates", yaxis_title="%")
            show_chart(fm)
    with st.expander("Aggregate-only bounds (no isolate data needed)"):
        st.caption("From marginal resistance rates only, the share resistant to BOTH drugs must lie between the bounds. "
                   "A wide gap = aggregate counts cannot tell you about co-resistance.")
        fr = X.frechet(df, st.selectbox("Region", sorted(df.Region.unique()), key="fr_r"),
                       st.selectbox("Organism", sorted(df.Organism.unique()), key="fr_o"), lastm)
        show_df(fr) if len(fr) else st.caption("Need 2+ antibiotics for this region/organism.")

# ---------------- review & report (audit trail) ----------------
with tab8:
    st.markdown("#### Human review - tamper-evident audit trail with two-person sign-off")
    key = " | ".join(alert_pick)
    st.write(f"Series under review: **{key}** (change it on the Alerts tab)")
    rc1, rc2, rc3 = st.columns(3)
    stt = rc1.selectbox("Decision", ["Under review", "Dismissed - no action", "Needs more data", "Escalated to officer"])
    role = rc2.selectbox("Role", X.ROLES)
    who = rc3.text_input("Reviewer name (required, no patient data)")
    note = st.text_area("Note")
    if st.button("💾 Save review"):
        try:
            X.add_audit(key, stt, who, role, note); st.success("Saved to hash-chained log.")
        except ValueError as ex:
            st.error(str(ex))
    au = X.load_audit()
    state = X.review_state(au, key)
    st.info("Status: " + state)
    show_df(au.drop(columns=["prev_hash"]) if len(au) else au)
    if len(au):
        st.download_button("⬇ Download audit log (CSV)", csv_bytes(au), "resist_x_audit.csv", "text/csv")
    st.markdown("#### Alert brief")
    lbl = {"syn": "SYNTHETIC DEMO DATA - not real observations", "real": "User-declared real surveillance data",
           "unk": "Data origin unverified"}[label]
    page = E.build_report(key, lbl, alert_res, alert_fig.to_html(full_html=False, include_plotlyjs=True),
                          au[au["series"] == key][["ts", "decision", "reviewer", "role", "note"]] if len(au) else None, PROV, state)
    st.download_button("⬇ Download alert brief (HTML - open & print to PDF)", page.encode("utf-8"),
                       "resist_x_alert_brief.html", "text/html")

# ---------------- context & antibiotic use ----------------
with tab9:
    st.markdown("#### Contextual strata (hospital, ward, specimen, age group, sex, outcome)")
    cc = [c for c in X.CTX if c in df.columns]
    if not cc:
        st.info("No context columns in this file. Optional columns: " + ", ".join(X.CTX))
    else:
        col = st.selectbox("Stratify by", cc)
        stt_ = X.strata_table(df, col)
        pr = sorted(set(zip(stt_.Organism, stt_.Antibiotic)))
        po, pa = st.selectbox("Organism | Antibiotic ", pr, format_func=lambda k: " | ".join(k), key="st_pair")
        x = stt_[(stt_.Organism == po) & (stt_.Antibiotic == pa)]
        show_chart(go.Figure(go.Bar(x=x[col], y=x.Pct, marker_color="#38bdf8", text=[f"n={int(n):,}" for n in x.Tested],
                   error_y=dict(type="data", symmetric=False, array=(x.CI_high - x.Pct).values, arrayminus=(x.Pct - x.CI_low).values)))
                   .update_layout(title=f"{po} / {pa} by {col} (95% CI)", yaxis_title="Resistance (%)"))
        st.caption("Each level is tested against all other levels (two-proportion z, BH-FDR across all rows). "
                   "Adjusting for case-mix needs patient-level data.")
        show_df(stt_)
        with st.expander("Early-warning alerts within each stratum"):
            show_df(X.strat_alerts(df, col, recent=recent, z_thr=z_thr, min_pp=min_pp, min_n=min_n))
    st.markdown("#### Antibiotic use vs resistance (ecological, first-differenced, lagged)")
    if use_df is None:
        st.info("Upload an antibiotic-use CSV (Month, Region, Antibiotic, DDD) to explore this.")
    else:
        ur = run_use(df, use_df)
        if len(ur):
            show_df(ur)
        else:
            st.warning("No overlapping Region/Antibiotic/month data with at least 8 months.")
        st.caption("Association only - not causation. Controlled for shared trends by differencing; confounding by case-mix, "
                   "infection control and testing practice is still possible.")

# ---------------- governance ----------------
with tab10:
    ok, bad = X.verify_audit()
    st.markdown("#### Governance status")
    g1, g2, g3 = st.columns(3)
    g1.metric("Audit chain", "Intact ✔" if ok else f"TAMPERED at #{bad}")
    g2.metric("PII guard on upload", "Active")
    g3.metric("Small-cell suppression", f"k={sup_k}" if sup_on else "Off")
    st.markdown(f"**Provenance recorded in reports:** {PROV}")
    if label == "real" and std == "Not stated":
        st.warning("Real data declared but lab standard (CLSI/EUCAST + version) not stated. Different breakpoints are not comparable.")
    st.markdown("""
#### What the software enforces
- **Privacy:** identifier-like columns (name, phone, MRN, DOB, address...) are dropped; e-mail/phone/Aadhaar-like values block the upload;
  patient IDs in isolate files are irreversibly hashed with a session salt; downloads can suppress small cells.
- **Lab standards:** standard/version/source are recorded in every brief; isolate analysis offers R-only vs I+R definitions and
  first-isolate de-duplication per patient.
- **Expert review:** a final decision needs two different people - an analyst and a surveillance expert - and every entry is hash-chained.
- **Validation:** Monte-Carlo simulation plus a backtest harness that scores sensitivity, delay, false alerts and abstentions on labelled events.

#### What software cannot replace (do before operational use)
1. Run the backtest on your own labelled historical events (prospective/external validation, ethics approval).
2. Pass the institutional data-protection review (DPDP Act 2023 in India / local law); host on an access-controlled server with HTTPS and login.
3. Align with national lab standards and external quality assurance (e.g. NABL, ICMR AMRSN protocols, WHO GLASS).
4. Have a surveillance epidemiologist approve thresholds and the escalation pathway.

#### Real-data sources (verify access yourself)
- WHO AMR dashboard: https://data.who.int/dashboards/amr
- ICMR reports: https://www.icmr.gov.in/reports?q=AMR
- ICMR AMRSN dataset page: https://nhrdr.icmr.org.in/datasets/icmr-antimicrobial-resistance-surveillance-network-dataset
""")
