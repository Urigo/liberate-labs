#!/usr/bin/env python3
"""
Build one SQLite database from Blueprint JSON + Maccabi TSV.

Usage:
    python build_db.py --blueprint blueprint_tests.json --maccabi maccabi_all.tsv --out blood_tests.db

Schema
------
lab_test : one row per draw/session (source, source_test_id, lab_name, test_date, referrer)
result   : one row per measurement (biomarker, value_num, value_text, unit, ref_min, ref_max,
           status, is_abnormal, tags, panel, source_ref)
v_results: convenience view joining both

Design notes
------------
* value_num is NULL for qualitative results; value_text always holds the
  original ("NEGATIVE", "<2", "HIV negative").
* Maccabi reports 0/0 for "no reference range" -> stored as NULL/NULL.
* Maccabi qualitative results live in `message` (or message_list[0]); when
  `result` is 0 and a message exists, the message wins.
* Blueprint's isAbnormal is taken as-is; Maccabi's is computed from the range.
* Biomarker names are NOT harmonised across labs ("Glucose" vs "Glucose (B)").
  Match with LIKE when trending across sources; harmonising is a judgement
  call best left to the reader.
"""
import argparse
import csv
import json
import os
import sqlite3

SCHEMA = """
CREATE TABLE lab_test (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL, source_test_id TEXT, test_name TEXT, lab_name TEXT,
  test_date TEXT, referrer TEXT, UNIQUE(source, source_test_id));
CREATE TABLE result (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lab_test_id INTEGER NOT NULL REFERENCES lab_test(id),
  source TEXT NOT NULL, test_date TEXT, panel TEXT, biomarker TEXT NOT NULL,
  value_num REAL, value_text TEXT, unit TEXT, ref_min REAL, ref_max REAL,
  interpretation TEXT, status TEXT, is_abnormal INTEGER, tags TEXT, source_ref TEXT);
CREATE INDEX idx_result_bio ON result(biomarker);
CREATE INDEX idx_result_date ON result(test_date);
CREATE VIEW v_results AS
  SELECT r.id, r.source, lt.test_date AS draw_date, r.test_date AS result_date, r.panel,
         r.biomarker, r.value_num, r.value_text, r.unit, r.ref_min, r.ref_max, r.status,
         r.is_abnormal, lt.lab_name, lt.referrer
  FROM result r JOIN lab_test lt ON r.lab_test_id = lt.id;
"""


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def iso(d):
    return str(d)[:10] if d else None


def load_blueprint(c, path):
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict):  # single-test export
        data = [data]
    n = 0
    for entry in data:
        t, bms = entry["test"], entry["biomarkers"]
        c.execute("INSERT INTO lab_test(source,source_test_id,test_name,lab_name,test_date,referrer) VALUES(?,?,?,?,?,?)",
                  ("blueprint", t["id"], t.get("testName"), t.get("labName"), iso(t.get("testDate")), None))
        tid = c.lastrowid
        for b in bms:
            tags = b.get("tags") or []
            vs = b.get("valueString")
            vt = vs if vs is not None else (str(b["value"]) if b.get("value") is not None else None)
            c.execute("""INSERT INTO result(lab_test_id,source,test_date,panel,biomarker,value_num,value_text,unit,
                         ref_min,ref_max,interpretation,status,is_abnormal,tags,source_ref) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (tid, "blueprint", iso(b.get("dateMeasured")), tags[0] if tags else None, b.get("biomarkerName"),
                       num(b.get("value")), vt, b.get("measurementUnit"), num(b.get("providedRangeMin")),
                       num(b.get("providedRangeMax")), b.get("interpretation"), b.get("status"),
                       1 if b.get("isAbnormal") else 0, "|".join(tags) or None, b.get("biomarkerId")))
            n += 1
    return n


def load_maccabi(c, path):
    rows = list(csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"))
    ids = {}
    for rid in dict.fromkeys(r["requestId"] for r in rows):
        dates = [r["lab_date"] for r in rows if r["requestId"] == rid and r["lab_date"]]
        c.execute("INSERT INTO lab_test(source,source_test_id,test_name,lab_name,test_date,referrer) VALUES(?,?,?,?,?,?)",
                  ("maccabi", rid, "Lab panel", "Maccabi", dates[0] if dates else None, None))
        ids[rid] = c.lastrowid
    n = 0
    for r in rows:
        mn, mx = num(r["min"]), num(r["max"])
        if mn == 0 and mx == 0:
            mn = mx = None
        raw, msg = r["result"], (r.get("message") or "").strip()
        rn = num(raw)
        if msg and (rn is None or (rn == 0 and mn is None and mx is None)):
            vnum, vtext = None, msg
        elif raw not in ("", None):
            vnum, vtext = rn, (raw if rn is None else (msg or str(raw)))
        else:
            vnum, vtext = None, (msg or None)
        abn = 1 if (vnum is not None and ((mn is not None and vnum < mn) or (mx is not None and vnum > mx))) else 0
        c.execute("""INSERT INTO result(lab_test_id,source,test_date,panel,biomarker,value_num,value_text,unit,
                     ref_min,ref_max,interpretation,status,is_abnormal,tags,source_ref) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (ids[r["requestId"]], "maccabi", r["lab_date"] or None, r["group"] or None, r["test_desc"],
                   vnum, vtext, r["units"] or None, mn, mx, None, None, abn, None, r["test_id"] or None))
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blueprint")
    ap.add_argument("--maccabi")
    ap.add_argument("--out", default="blood_tests.db")
    a = ap.parse_args()
    if os.path.exists(a.out):
        os.remove(a.out)
    con = sqlite3.connect(a.out)
    c = con.cursor()
    c.executescript(SCHEMA)
    if a.blueprint:
        print("blueprint results:", load_blueprint(c, a.blueprint))
    if a.maccabi:
        print("maccabi results:", load_maccabi(c, a.maccabi))
    con.commit()
    print("total:", c.execute("SELECT count(*) FROM result").fetchone()[0], "->", a.out)


if __name__ == "__main__":
    main()
