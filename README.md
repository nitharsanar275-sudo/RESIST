# RESIST-X v3 - AMR Early-Warning (screening prototype)
Run: `pip install -r requirements.txt && streamlit run app.py` (Windows: `run.bat`). Tests: `python -m pytest tests`.
Optional inputs: aggregate CSV (+Hospital, Ward, Specimen, Age_Group, Sex, Outcome), isolate-level wide CSV (S/I/R per drug),
antibiotic-use CSV, labelled events CSV. Demo data is SYNTHETIC. Outputs are for human review only, not validated for clinical/operational use.

## Real data (ATLAS)
1. Register + download ATLAS (Vivli https://amr.vivli.org/ or Synapse syn17009517).
2. `python convert_atlas.py atlas.csv --country India --out data`
3. App: Data source = Upload CSV -> `data/atlas_aggregate.csv` (or `..._with_context.csv`), mark "Real surveillance data".
   Sidebar > Optional files > Isolate-level CSV -> `data/atlas_isolates.csv`.
ATLAS is annual: windows then count YEARS (use Recent window 2-3, lower min samples if needed).

## Quick real data (no registration): Zenodo 14224680 (ECDC EARS-Net 1998-2019)
Download summary_AMR_filtered.csv from https://zenodo.org/records/14224680 then `python convert_eu.py summary_AMR_filtered.csv --out data` and upload data/eu_aggregate.csv. Annual; I+R counted together.
