"""Convert a Pfizer ATLAS download (Vivli / Synapse syn17009517) to RESIST-X files.
Usage: python convert_atlas.py atlas.csv --country India [--top-drugs 12] [--min-tested 30] [--out data]
Outputs: <out>/atlas_aggregate.csv (annual, upload as 'Upload CSV' > Real surveillance data)
         <out>/atlas_isolates.csv  (isolate-level, sidebar > Optional files > Isolate-level CSV)
ATLAS has YEAR only, so alerts compare the last N YEARS with earlier years (the app detects annual data automatically).
ATLAS has no patient ID: each isolate is its own patient, so first-isolate de-duplication cannot be applied."""
import argparse, pathlib
import pandas as pd

SYN = {"isolate id": "Isolate_ID", "species": "Organism", "country": "Region", "state": "State", "gender": "Sex",
       "age group": "Age_Group", "speciality": "Ward", "source": "Specimen", "year": "Year", "in / out patient": "Setting"}


def convert(path, country=None, top=12, min_tested=30, sep=None):
    raw = pd.read_csv(path, sep=sep, engine="python", encoding="utf-8-sig")
    raw.columns = [str(c).strip() for c in raw.columns]
    df = raw.rename(columns={c: SYN[c.lower()] for c in raw.columns if c.lower() in SYN})
    for need in ("Organism", "Year", "Region"):
        if need not in df:
            raise SystemExit(f"Column for '{need}' not found. Columns: {list(raw.columns)[:25]}")
    if country:
        df = df[df.Region.astype(str).str.lower() == country.lower()]
        if df.empty:
            raise SystemExit(f"No rows for country '{country}'.")
    if country and "State" in df and df.State.notna().any():
        df["Region"] = df.State.fillna("Unknown")
    drugs = [c[:-2] for c in df.columns if c.endswith("_I") and c[:-2] in df.columns]
    if not drugs:
        raise SystemExit("No '<drug>_I' interpretation columns found (expected ATLAS format).")
    long = []
    for d in drugs:
        s = df[d + "_I"].astype(str).str.strip().str.upper().str.replace("INTERMEDIATE", "I").str[:1]
        s = s.where(s.isin(["S", "I", "R"]))
        t = df[["Organism", "Region", "Year"] + [c for c in ("Specimen", "Ward", "Age_Group", "Sex") if c in df]].copy()
        t["Antibiotic"], t["Res"] = d, s
        long.append(t.dropna(subset=["Res"]))
    long = pd.concat(long)
    keep = long.Antibiotic.value_counts().head(top).index
    long = long[long.Antibiotic.isin(keep)]
    long["Month"] = pd.to_datetime(long.Year.astype(int).astype(str) + "-01-01")
    long["Resistant"] = (long.Res == "R").astype(int)          # EUCAST/CLSI 'R' only; I is not counted
    cols = ["Month", "Region", "Organism", "Antibiotic"] + [c for c in ("Specimen", "Ward", "Age_Group", "Sex") if c in long]
    agg = long.groupby(cols, as_index=False).agg(Resistant=("Resistant", "sum"), Tested=("Resistant", "size"))
    agg = agg[agg.Tested >= min_tested]
    # drop context splits for the main file (keeps series long enough); context kept in a second file
    main = agg.groupby(["Month", "Region", "Organism", "Antibiotic"], as_index=False)[["Resistant", "Tested"]].sum()
    wide = df[["Organism", "Region", "Year"] + [c for c in ("Isolate_ID", "Specimen", "Ward") if c in df]].copy()
    wide["Date"] = pd.to_datetime(wide.Year.astype(int).astype(str) + "-01-01").dt.date
    wide["Patient_Key"] = wide["Isolate_ID"].astype(str) if "Isolate_ID" in wide else wide.index.astype(str)
    for d in keep:
        wide[d] = df[d + "_I"].astype(str).str.strip().str.upper().str[:1].where(lambda x: x.isin(["S", "I", "R"]))
    return main, agg, wide.drop(columns=["Year"])


if __name__ == "__main__":
    a = argparse.ArgumentParser(); a.add_argument("file"); a.add_argument("--country"); a.add_argument("--top-drugs", type=int, default=12)
    a.add_argument("--min-tested", type=int, default=30); a.add_argument("--out", default="data")
    x = a.parse_args(); out = pathlib.Path(x.out); out.mkdir(exist_ok=True)
    main, ctx, wide = convert(x.file, x.country, x.top_drugs, x.min_tested)
    main.to_csv(out / "atlas_aggregate.csv", index=False); ctx.to_csv(out / "atlas_aggregate_with_context.csv", index=False)
    wide.to_csv(out / "atlas_isolates.csv", index=False)
    print(f"aggregate rows {len(main)}, with-context rows {len(ctx)}, isolates {len(wide)} -> {out}/")
