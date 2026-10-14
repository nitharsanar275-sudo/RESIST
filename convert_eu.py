"""Convert Zenodo 14224680 (real ECDC EARS-Net 1998-2019) to RESIST-X format.
Usage: python convert_eu.py summary_AMR_filtered.csv --out data"""
import argparse, pathlib, pandas as pd
a = argparse.ArgumentParser(); a.add_argument("file"); a.add_argument("--out", default="data"); a.add_argument("--min-tested", type=int, default=30)
x = a.parse_args()
d = pd.read_csv(x.file, encoding="utf-8-sig")
o = pd.DataFrame({"Month": pd.to_datetime(d["Year"].astype(int).astype(str) + "-01-01"), "Region": d["Country"],
                  "Organism": d.get("Pathogen_long", d["Pathogen"]), "Antibiotic": d.get("Antibiotic_long", d["Antibiotic"]),
                  "Setting": d["patientType"], "Resistant": pd.to_numeric(d["N_I_R"], errors="coerce"),
                  "Tested": pd.to_numeric(d["N"], errors="coerce").fillna(pd.to_numeric(d["N_tested"], errors="coerce"))})
o = o.dropna(); o = o[(o.Tested >= 1) & (o.Resistant <= o.Tested)]
k = ["Month", "Region", "Organism", "Antibiotic"]
main = o.groupby(k, as_index=False)[["Resistant", "Tested"]].sum(); main = main[main.Tested >= x.min_tested]
ctx = o.rename(columns={"Setting": "Ward"}).groupby(k + ["Ward"], as_index=False)[["Resistant", "Tested"]].sum()
p = pathlib.Path(x.out); p.mkdir(exist_ok=True)
main.astype({"Resistant": int, "Tested": int}).to_csv(p / "eu_aggregate.csv", index=False)
ctx.astype({"Resistant": int, "Tested": int}).to_csv(p / "eu_aggregate_with_context.csv", index=False)
print(len(main), "rows ->", p / "eu_aggregate.csv", "| also eu_aggregate_with_context.csv (Ward = INPAT/OUTPAT)")
