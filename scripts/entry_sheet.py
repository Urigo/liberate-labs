#!/usr/bin/env python3
"""
Print the "latest value per marker" sheet for Apple Health's lab-entry panels
(iOS 27, Longevity → Labs), in the units those forms expect.

Usage:
    python entry_sheet.py blood_tests.db [--source blueprint]

Apple Health panels (as of the iOS 27 beta) and their fields:
  Cardiac Labs      : ApoB (mg/dL), Lp(a) (nmol/L), hsCRP (mg/L)
  Blood Health (CBC): WBC (10^3/mcL), Hemoglobin (g/dL), Hematocrit (%), Platelets (**1/mcL**)
  Liver & Kidney    : Sodium, Potassium (mmol/L), Creatinine (mg/dL), eGFR, AST, ALT (U/L)
  Glucose Labs      : Fasting glucose (mg/dL), Fasting insulin (mcIU/mL), HbA1c (%)
  Cholesterol Labs  : HDL, LDL, Triglycerides (mg/dL)

Health only accepts results dated within the last 12 months.
"""
import argparse
import sqlite3

# (panel, field label, Health unit, candidate biomarker names in the DB, multiplier to Health unit)
FIELDS = [
    ("Cardiac Labs", "ApoB", "mg/dL", ["Apolipoprotein B", "ApoB"], 1),
    ("Cardiac Labs", "Lp(a)", "nmol/L", ["Lipoprotein (a)", "Lp(a)"], 1),
    ("Cardiac Labs", "hsCRP", "mg/L", ["hs-CRP", "hsCRP"], 1),
    ("Blood Health Labs", "WBC", "10^3/mcL", ["WBC Count", "WBC-Leucocytes", "WBC"], 1),
    ("Blood Health Labs", "Hemoglobin", "g/dL", ["Hemoglobin"], 1),
    ("Blood Health Labs", "Hematocrit", "%", ["Hematocrit"], 1),
    ("Blood Health Labs", "Platelets", "1/mcL  <-- per microlitre!", ["Platelet Count", "Platelets"], 1000),
    ("Liver & Kidney", "Sodium", "mmol/L", ["Sodium", "Na- Sodium (B)"], 1),
    ("Liver & Kidney", "Potassium", "mmol/L", ["Potassium", "K+ Potassium (B)"], 1),
    ("Liver & Kidney", "Creatinine", "mg/dL", ["Creatinine, Serum", "Creatinine (B)"], 1),
    ("Liver & Kidney", "eGFR", "mL/min/1.73m2", ["eGFR"], 1),
    ("Liver & Kidney", "AST", "U/L", ["AST", "AST (GOT)"], 1),
    ("Liver & Kidney", "ALT", "U/L", ["ALT", "ALT (GPT)"], 1),
    ("Glucose Labs", "Fasting glucose", "mg/dL", ["Glucose", "Glucose (B)"], 1),
    ("Glucose Labs", "Fasting insulin", "mcIU/mL", ["Insulin"], 1),
    ("Glucose Labs", "HbA1c", "%", ["HbA1c", "HbA1C"], 1),
    ("Cholesterol Labs", "HDL", "mg/dL", ["HDL-C", "HDL-Cholesterol"], 1),
    ("Cholesterol Labs", "LDL", "mg/dL", ["LDL-C", "LDL-Cholesterol"], 1),
    ("Cholesterol Labs", "Triglycerides", "mg/dL", ["Triglycerides"], 1),
]


def fmt(v):
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--source", help="prefer this source (e.g. blueprint) so a panel shares one draw date")
    a = ap.parse_args()
    c = sqlite3.connect(a.db).cursor()
    cur = None
    for panel, label, unit, names, mult in FIELDS:
        q = f"SELECT value_num, unit, test_date, ref_min, ref_max FROM result WHERE biomarker IN ({','.join('?'*len(names))}) AND value_num IS NOT NULL"
        params = list(names)
        if a.source:
            q += " AND source=?"; params.append(a.source)
        row = c.execute(q + " ORDER BY test_date DESC LIMIT 1", params).fetchone()
        if panel != cur:
            print(f"\n## {panel}"); cur = panel
        if not row:
            print(f"  {label:16} — not found"); continue
        v, u, d, lo, hi = row
        rng = f"  ref {fmt(lo*mult) if lo is not None else '–'}–{fmt(hi*mult) if hi is not None else '–'}" if (lo is not None or hi is not None) else ""
        print(f"  {label:16} {fmt(v*mult):>8}  {unit:<28} ({d}){rng}")


if __name__ == "__main__":
    main()
