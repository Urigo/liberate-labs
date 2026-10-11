#!/usr/bin/env python3
"""
Build one SQLite database from Blueprint JSON + Maccabi lab results.

Maccabi results can come from either of two sources:

  --maccabi-export PATH   The ZIP (or unzipped folder) written by Roni Rachmani's
                          "Health Records Export for Maccabi" Chrome extension —
                          https://github.com/RoniRachmani/health-records-export-for-maccabi
                          This is the recommended path: one click, every lab panel,
                          plus a per-measurement history that reaches further back
                          than the results lobby shows.
  --maccabi TSV           The TSV produced by scripts/maccabi_extract.js (the
                          browser-console / React-state route, for when you can't
                          or don't want to install an extension).

Usage:
    python build_db.py --blueprint blueprint_tests.json --maccabi-export maccabi-export-2026-10-11.zip --out blood_tests.db
    python build_db.py --blueprint blueprint_tests.json --maccabi maccabi_all.tsv --out blood_tests.db
    # refresh Maccabi from a new export, keep Blueprint from the previous database:
    python build_db.py --carry old.db:blueprint --maccabi-export maccabi-export-2026-11-01.zip --out blood_tests.db

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
* Maccabi qualitative results live in `message` (or message_list); when
  `result` is 0 and a message exists, the message wins. `is_messages == "2"`
  means "answer only in text" and is honoured when present.
* Blueprint's isAbnormal is taken as-is; Maccabi's is computed from the range.
* Biomarker names are NOT harmonised across labs ("Glucose" vs "Glucose (B)").
  Match with LIKE when trending across sources; harmonising is a judgement
  call best left to the reader.
* From the extension's export, each (test_id, lab_date) is loaded once even
  though the ZIP holds it up to three times (details/, history/, latest).
  Values that only exist in history/ (older than any panel in details/) are
  attached to a synthetic per-date lab_test with source_test_id "history:<date>".
"""
import argparse
import csv
import io
import json
import os
import sqlite3
import zipfile

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

MACCABI_COLS = ("requestId", "lab_date", "group", "test_id", "test_desc", "result", "message", "min", "max", "units")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def iso(d):
    return str(d)[:10] if d else None


def clean(s):
    return " ".join(str(s).split()) if s not in (None, "") else ""


# ----------------------------------------------------------------------------
# Blueprint
# ----------------------------------------------------------------------------

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


# ----------------------------------------------------------------------------
# Maccabi — shared row insertion
# ----------------------------------------------------------------------------

def insert_maccabi_rows(c, rows, tests=None):
    """rows: dicts with MACCABI_COLS keys (+ optional 'is_messages', 'interpretation').
    tests: optional {requestId: {"date":..., "referrer":..., "name":...}} from the export's list.json."""
    tests = tests or {}
    ids = {}
    for rid in dict.fromkeys(r["requestId"] for r in rows):
        meta = tests.get(rid, {})
        dates = [r["lab_date"] for r in rows if r["requestId"] == rid and r["lab_date"]]
        test_date = meta.get("date") or (min(dates) if dates else None)
        c.execute("INSERT INTO lab_test(source,source_test_id,test_name,lab_name,test_date,referrer) VALUES(?,?,?,?,?,?)",
                  ("maccabi", rid, meta.get("name") or "Lab panel", "Maccabi", test_date, meta.get("referrer")))
        ids[rid] = c.lastrowid
    n = 0
    for r in rows:
        mn, mx = num(r["min"]), num(r["max"])
        if mn == 0 and mx == 0:
            mn = mx = None
        raw, msg = r["result"], clean(r.get("message"))
        rn = num(raw)
        text_only = str(r.get("is_messages") or "") == "2"
        if msg and (text_only or rn is None or (rn == 0 and mn is None and mx is None)):
            vnum, vtext = None, msg
        elif raw not in ("", None):
            vnum, vtext = rn, (raw if rn is None else (msg or str(raw)))
        else:
            vnum, vtext = None, (msg or None)
        abn = 1 if (vnum is not None and ((mn is not None and vnum < mn) or (mx is not None and vnum > mx))) else 0
        c.execute("""INSERT INTO result(lab_test_id,source,test_date,panel,biomarker,value_num,value_text,unit,
                     ref_min,ref_max,interpretation,status,is_abnormal,tags,source_ref) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (ids[r["requestId"]], "maccabi", r["lab_date"] or None, r["group"] or None, r["test_desc"],
                   vnum, vtext, r["units"] or None, mn, mx, r.get("interpretation") or None, None, abn, None, r["test_id"] or None))
        n += 1
    return n


def load_maccabi(c, path):
    """TSV from scripts/maccabi_extract.js."""
    rows = list(csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"))
    return insert_maccabi_rows(c, rows)


# ----------------------------------------------------------------------------
# Maccabi — the extension's export (ZIP or folder)
# ----------------------------------------------------------------------------

def _export_files(path):
    """Yield (relative_path_inside_test-results, text) for every JSON under test-results/."""
    if os.path.isdir(path):
        for root, _dirs, files in os.walk(path):
            for f in files:
                full = os.path.join(root, f)
                rel = full.replace(os.sep, "/")
                if "test-results/" in rel and f.endswith(".json"):
                    yield rel.split("test-results/", 1)[1], open(full, encoding="utf-8").read()
    else:
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if "test-results/" in name and name.endswith(".json"):
                    yield name.split("test-results/", 1)[1], z.read(name).decode("utf-8")


def _unwrap(text):
    """The export wraps each response as {endpoint, fetched_at, status, data, ...extra}."""
    obj = json.loads(text)
    if isinstance(obj, dict) and "data" in obj and "endpoint" in obj:
        return obj, obj["data"]
    return {}, obj


def _value_row(v, rid, group):
    """One group_values[] entry as a TSV-shaped row. `message` carries the short answer (the site's
    `message`, else the first line of `message_list` when there is no number); the whole note
    (`message_list` joined — a reference range, a method change, an interpretation) goes to
    `interpretation` so the value column stays short and the note is not lost."""
    msg = clean(v.get("message"))
    ml = [clean(x) for x in (v.get("message_list") or []) if clean(x)] if isinstance(v.get("message_list"), list) else []
    if not msg and ml and num(v.get("result")) in (None, 0.0):
        msg = ml[0]
    note = " ".join(ml)
    return {
        "requestId": rid, "lab_date": iso(v.get("lab_date")), "group": clean(group),
        "test_id": clean(v.get("test_id")), "test_desc": clean(v.get("test_desc")),
        "result": v.get("result", ""), "message": msg,
        "min": v.get("min_lim", ""), "max": v.get("max_lim", ""), "units": clean(v.get("units")),
        "is_messages": v.get("is_messages", ""), "interpretation": note if note and note != msg else None,
    }


def _walk_values(obj):
    """Yield every dict that looks like a lab value, wherever it sits (history files vary in shape)."""
    if isinstance(obj, dict):
        if "test_id" in obj and "lab_date" in obj and ("result" in obj or "message" in obj):
            yield obj
        for val in obj.values():
            yield from _walk_values(val)
    elif isinstance(obj, list):
        for val in obj:
            yield from _walk_values(val)


def load_maccabi_export(c, path):
    tests, rows, seen = {}, [], set()
    details, histories = [], []
    for rel, text in _export_files(path):
        if rel == "list.json":
            _w, data = _unwrap(text)
            for t in (data or {}).get("tests", []) or []:
                if t.get("type") not in (None, "lab_result"):
                    continue  # imaging / cardiology / external: findings are PDFs only
                tests[str(t.get("request_id"))] = {
                    "date": iso(t.get("execute_date")),
                    "referrer": clean(t.get("referrer_name") or t.get("doctor_name")) or None,
                    "name": "Lab panel",
                }
        elif rel.startswith("details/"):
            details.append(text)
        elif rel.startswith("history/") or rel == "latest-lab-results.json":
            histories.append(text)  # latest-lab-results may name measurements no panel in the lobby has

    # 1. Panels: one lab_test per request_id, values grouped as the site groups them.
    for text in details:
        wrap, data = _unwrap(text)
        if wrap.get("type") not in (None, "lab_result"):
            continue
        rid = str(wrap.get("request_id") or "")
        groups = (data or {}).get("results") if isinstance(data, dict) else None
        if not groups:
            continue
        if not rid:
            rid = "panel:" + (groups[0].get("group_values") or [{}])[0].get("lab_date", "?")[:10]
        for g in groups:
            group = g.get("group_name") or g.get("group_desc") or g.get("name") or ""
            for v in g.get("group_values") or []:
                row = _value_row(v, rid, group)
                key = (row["test_id"] or row["test_desc"], row["lab_date"])
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
    n_panels = len(rows)

    # 2. Histories: anything older than the panels, once per (test_id, lab_date).
    for text in histories:
        _w, data = _unwrap(text)
        for v in _walk_values(data):
            row = _value_row(v, None, "")
            key = (row["test_id"] or row["test_desc"], row["lab_date"])
            if key in seen or not row["lab_date"]:
                continue
            seen.add(key)
            row["requestId"] = "history:" + row["lab_date"]
            rows.append(row)
    for rid in {r["requestId"] for r in rows if r["requestId"].startswith("history:")}:
        tests[rid] = {"date": rid.split(":", 1)[1], "referrer": None, "name": "Lab panel (from history)"}

    n = insert_maccabi_rows(c, rows, tests)
    print(f"  maccabi export: {len(details)} panel files, {len(histories)} history files -> "
          f"{n_panels} panel values + {n - n_panels} history-only values")
    return n


# ----------------------------------------------------------------------------
# Carry a source over from an earlier database (e.g. keep Blueprint while
# rebuilding Maccabi from a fresh export when the raw Blueprint JSON is gone)
# ----------------------------------------------------------------------------

def carry_source(c, old_db, source):
    old = sqlite3.connect(old_db)
    n = 0
    for lt in old.execute("SELECT id, source_test_id, test_name, lab_name, test_date, referrer FROM lab_test WHERE source=?", (source,)):
        c.execute("INSERT INTO lab_test(source,source_test_id,test_name,lab_name,test_date,referrer) VALUES(?,?,?,?,?,?)",
                  (source,) + tuple(lt[1:]))
        new_id = c.lastrowid
        for r in old.execute("""SELECT test_date,panel,biomarker,value_num,value_text,unit,ref_min,ref_max,interpretation,
                                       status,is_abnormal,tags,source_ref FROM result WHERE lab_test_id=?""", (lt[0],)):
            c.execute("""INSERT INTO result(lab_test_id,source,test_date,panel,biomarker,value_num,value_text,unit,
                         ref_min,ref_max,interpretation,status,is_abnormal,tags,source_ref) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (new_id, source) + tuple(r))
            n += 1
    old.close()
    return n


# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--blueprint", help="Blueprint JSON from scripts/blueprint_extract.js")
    ap.add_argument("--maccabi", help="TSV from scripts/maccabi_extract.js (console route)")
    ap.add_argument("--maccabi-export", help="ZIP or folder from the Health Records Export for Maccabi extension")
    ap.add_argument("--carry", action="append", default=[], metavar="OLD.db:SOURCE",
                    help="copy one source's rows from an earlier database, e.g. old.db:blueprint (repeatable)")
    ap.add_argument("--out", default="blood_tests.db")
    a = ap.parse_args()
    if os.path.exists(a.out):
        os.remove(a.out)
    con = sqlite3.connect(a.out)
    c = con.cursor()
    c.executescript(SCHEMA)
    if a.blueprint:
        print("blueprint results:", load_blueprint(c, a.blueprint))
    for spec in a.carry:
        old_db, source = spec.rsplit(":", 1)
        print(f"{source} results carried from {old_db}:", carry_source(c, old_db, source))
    if a.maccabi_export:
        print("maccabi results (extension export):", load_maccabi_export(c, a.maccabi_export))
    if a.maccabi:
        print("maccabi results (console TSV):", load_maccabi(c, a.maccabi))
    con.commit()
    print("total:", c.execute("SELECT count(*) FROM result").fetchone()[0], "->", a.out)


if __name__ == "__main__":
    main()
