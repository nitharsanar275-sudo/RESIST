import sys, pathlib, sqlite3
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pandas as pd
import engine as E, extras as X

base = E.make_demo(); ctx = X.make_demo_context(base)


def test_context_split_preserves_totals():
    assert ctx.Tested.sum() == base.Tested.sum() and (ctx.Resistant <= ctx.Tested).all()


def test_scenarios():
    t = E.analyze_all(ctx).set_index(["Organism", "Antibiotic", "Region"])
    assert t.loc[("K. pneumoniae", "Meropenem", "East Zone"), "Status"] == E.RED
    assert t.loc[("S. aureus", "Oxacillin", "West Zone"), "Status"] == E.AMBER
    assert t.loc[("E. coli", "Ciprofloxacin", "North Zone"), "Status"] == E.GREEN


def test_pii_blocked_and_dropped():
    raw = pd.DataFrame({"Month": ["2025-01-01"], "Region": ["a"], "Organism": ["o"], "Antibiotic": ["x"],
                        "Resistant": [1], "Tested": [5], "Patient_Name": ["Raj"], "Note": ["call 9876543210"]})
    clean, errs, warns = E.validate_upload(raw)
    assert clean is None and errs and any("Patient_Name" in w for w in warns)


def test_suppression():
    s = X.suppress(pd.DataFrame({"Resistant": [1, 9], "Tested": [3, 20]}), 5)
    assert s.Resistant.isna().tolist() == [True, False]


def test_coresistance_detects_driver():
    d, drugs, e, w = X.validate_isolates(X.make_demo_isolates())
    co = X.coresistance(X.to_binary(X.first_isolates(d), drugs), drugs)
    top = co.iloc[0]
    assert top.Phi > 0.3 and top.FDR_q < 0.001


def test_backtest_detects_event_and_abstains():
    det, _ = X.backtest(ctx, X.demo_events(base))
    assert det["RESISTX"]["Detected"] == 1 and det["RESISTX"]["False_alerts_per_100_series_months"] <= det["Naive"]["False_alerts_per_100_series_months"]


def test_audit_chain(tmp_path):
    E.DB = tmp_path / "r.db"
    X.add_audit("s", "Escalated", "Ann", "Analyst", "n"); X.add_audit("s", "Escalated", "Bob", "Surveillance expert", "n")
    assert X.review_state(X.load_audit(), "s").startswith("FINAL") and X.verify_audit()[0]
    c = sqlite3.connect(E.DB); c.execute("update audit set note='x' where id=1"); c.commit()
    assert not X.verify_audit()[0]
