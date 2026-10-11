#!/usr/bin/env python3
"""
Generate a self-contained HTML trends dashboard from blood_tests.db.

Usage:
    python build_dashboard.py blood_tests.db --out dashboard.html [--min-points 2]

Charts every numeric biomarker with >= --min-points timepoints (default 2),
grouped by panel, as small multiples: reference band, source-coloured points,
latest value label, hover tooltip, light/dark, and a table view.
Biomarker names are used as-is; add entries to ALIASES to merge names across labs.
"""
import argparse
import json
import sqlite3

# Merge differently-named markers across labs. Left: canonical; right: aliases.
ALIASES = {
    "Glucose": ["Glucose (B)"],
    "HbA1c": ["HbA1C"],
    "LDL-C": ["LDL-Cholesterol"],
    "HDL-C": ["HDL-Cholesterol"],
    "Cholesterol, Total": ["Cholesterol"],
    "Creatinine": ["Creatinine, Serum", "Creatinine (B)"],
    "ALT": ["ALT (GPT)"], "AST": ["AST (GOT)"],
    "Sodium": ["Na- Sodium (B)"], "Potassium": ["K+ Potassium (B)"],
    "WBC": ["WBC Count", "WBC-Leucocytes"], "Platelets": ["Platelet Count"],
}
CANON = {a: k for k, v in ALIASES.items() for a in v}

TEMPLATE = r"""<!DOCTYPE html><html lang="en" data-theme="light"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Blood Test Trends</title>
<style>
:root{--plane:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--base:#c3c2b7;--border:rgba(11,11,11,.1);
--s1:#2a78d6;--s2:#eb6834;--good:#0ca30c;--warn:#fab219;--bad:#ec835a;--band:rgba(12,163,12,.09)}
:root[data-theme=dark]{--plane:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;--base:#383835;--border:rgba(255,255,255,.1);--s1:#3987e5;--s2:#d95926;--band:rgba(12,163,12,.13)}
*{box-sizing:border-box}body{margin:0;background:var(--plane);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 80px}h1{font-size:26px;margin:0}.sub{color:var(--ink2);font-size:14px;margin:4px 0 0}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
button{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:7px 12px;cursor:pointer}button.active{background:var(--s1);color:#fff;border-color:transparent}
.legend{display:flex;gap:16px;margin:18px 0 6px;font-size:13px;color:var(--ink2);flex-wrap:wrap}.dot{width:11px;height:11px;border-radius:50%;display:inline-block;margin-right:6px}
h2.section{font-size:15px;text-transform:uppercase;letter-spacing:.02em;color:var(--ink2);margin:30px 0 2px;padding-bottom:6px;border-bottom:1px solid var(--grid)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px;margin-top:14px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:13px 14px 8px}.ttl{font-size:13.5px;font-weight:620;display:flex;justify-content:space-between;gap:8px}.u{font-size:11px;color:var(--muted);font-weight:400}
.latest{font-size:12.5px;color:var(--ink2);margin:2px 0 6px;display:flex;align-items:center;gap:7px}.chip{height:17px;padding:0 7px;border-radius:20px;font-size:10.5px;font-weight:650;color:#fff;display:inline-flex;align-items:center}
svg{display:block;width:100%;height:auto;overflow:visible}.gl{stroke:var(--grid)}.axis{stroke:var(--base)}.tick{fill:var(--muted);font-size:9.5px}.ref{stroke:var(--good);stroke-dasharray:3 3;opacity:.65}.pt{stroke:var(--surface);stroke-width:2}.lbl{fill:var(--ink);font-size:10.5px;font-weight:650}
.tt{position:fixed;pointer-events:none;z-index:50;background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:7px 10px;font-size:12px;box-shadow:0 6px 20px rgba(0,0,0,.14);opacity:0}
table{border-collapse:collapse;width:100%;font-size:12.5px}th,td{text-align:left;padding:6px 9px;border-bottom:1px solid var(--grid)}th{color:var(--muted)}td.n{text-align:right;font-variant-numeric:tabular-nums}.hide{display:none}
.disc{font-size:12px;color:var(--muted);margin-top:26px;border-top:1px solid var(--grid);padding-top:14px}
</style></head><body><div class="wrap">
<header><div><h1>Blood Test Trends</h1><p class="sub" id="sub"></p></div>
<div><button id="bC" class="active" onclick="view('c')">Charts</button> <button id="bT" onclick="view('t')">Table</button> <button onclick="document.documentElement.dataset.theme=document.documentElement.dataset.theme==='dark'?'light':'dark'">◐ Theme</button></div></header>
<div class="legend" id="legend"></div><div id="charts"></div><div id="table" class="hide"></div>
<p class="disc">Your own lab data, charted for reference — not medical advice. Reference ranges differ between labs; compare trends and discuss anything flagged with a clinician.</p></div>
<div class="tt" id="tt"></div>
<script>
const DATA=__DATA__;const SRC=__SOURCES__;const COL=['var(--s1)','var(--s2)','#1baf7a','#eda100'];
const fmt=v=>Math.abs(v)>=100?Math.round(v):Math.round(v*100)/100,P=d=>new Date(d+'T00:00:00').getTime();
const st=(c,v)=>{if(c.refMin!=null&&v<c.refMin)return v<c.refMin*.85?'bad':'warn';if(c.refMax!=null&&v>c.refMax)return v>c.refMax*1.25?'bad':'warn';return 'good'};
const SC={good:'var(--good)',warn:'var(--warn)',bad:'var(--bad)'},SL={good:'in range',warn:'borderline',bad:'out of range'};
document.getElementById('sub').textContent=`${DATA.length} markers · ${DATA.reduce((s,c)=>s+c.points.length,0)} results`;
document.getElementById('legend').innerHTML=SRC.map((s,i)=>`<span><span class="dot" style="background:${COL[i]}"></span>${s}</span>`).join('')+'<span><span class="dot" style="background:var(--band);border:1px solid var(--border)"></span>in-range zone</span>';
const W=290,H=150,m={t:16,r:16,b:22,l:34},iw=W-m.l-m.r,ih=H-m.t-m.b;
function card(c,i){const L=c.points.at(-1),s=st(c,L.value);return `<div class="card"><div class="ttl"><span>${c.title}</span><span class="u">${c.unit||''}</span></div><div class="latest">latest <b>&nbsp;${fmt(L.value)}</b><span class="chip" style="background:${SC[s]}">${SL[s]}</span></div><div id="s${i}"></div></div>`}
function draw(c,i){const xs=c.points.map(p=>P(p.date));let x0=Math.min(...xs),x1=Math.max(...xs);if(x0===x1){x0-=2.6e10;x1+=2.6e10}
let vals=c.points.map(p=>p.value),lo=Math.min(...vals),hi=Math.max(...vals);if(c.refMin!=null){lo=Math.min(lo,c.refMin);hi=Math.max(hi,c.refMin)}if(c.refMax!=null){lo=Math.min(lo,c.refMax);hi=Math.max(hi,c.refMax)}
const pad=(hi-lo)*.14||Math.abs(hi)*.1||1;lo-=pad;hi+=pad;const X=t=>m.l+(t-x0)/(x1-x0)*iw,Y=v=>m.t+ih-(v-lo)/(hi-lo)*ih;
let s=`<svg viewBox="0 0 ${W} ${H}">`;const bt=c.refMax!=null?Y(c.refMax):m.t,bb=c.refMin!=null?Y(c.refMin):m.t+ih;s+=`<rect x="${m.l}" y="${bt}" width="${iw}" height="${Math.max(0,bb-bt)}" fill="var(--band)"/>`;
for(let k=0;k<=2;k++){const yv=lo+(hi-lo)*k/2,y=Y(yv);s+=`<line class="gl" x1="${m.l}" y1="${y}" x2="${m.l+iw}" y2="${y}"/><text class="tick" x="${m.l-5}" y="${y+3}" text-anchor="end">${fmt(yv)}</text>`}
if(c.refMax!=null)s+=`<line class="ref" x1="${m.l}" y1="${Y(c.refMax)}" x2="${m.l+iw}" y2="${Y(c.refMax)}"/>`;if(c.refMin!=null)s+=`<line class="ref" x1="${m.l}" y1="${Y(c.refMin)}" x2="${m.l+iw}" y2="${Y(c.refMin)}"/>`;
[x0,x1].forEach((t,k)=>s+=`<text class="tick" x="${X(t)}" y="${H-6}" text-anchor="${k?'end':'start'}">${new Date(t).getFullYear()}</text>`);
if(c.points.length>1)s+=`<path fill="none" stroke="var(--base)" stroke-width="2" opacity=".5" d="${c.points.map((p,k)=>(k?'L':'M')+X(P(p.date)).toFixed(1)+','+Y(p.value).toFixed(1)).join(' ')}"/>`;
c.points.forEach((p,k)=>s+=`<circle class="pt" cx="${X(P(p.date)).toFixed(1)}" cy="${Y(p.value).toFixed(1)}" r="4.5" fill="${COL[SRC.indexOf(p.source)]}" data-c="${i}" data-k="${k}"/>`);
const L=c.points.at(-1);s+=`<text class="lbl" x="${Math.min(X(P(L.date)),m.l+iw-2)}" y="${Y(L.value)-8}" text-anchor="end">${fmt(L.value)}</text></svg>`;
const h=document.getElementById('s'+i);h.innerHTML=s;h.querySelectorAll('circle').forEach(el=>{el.onmousemove=e=>{const p=DATA[+el.dataset.c].points[+el.dataset.k],t=document.getElementById('tt');t.innerHTML=`<b>${fmt(p.value)} ${c.unit||''}</b> · ${p.source}<br>${p.date}`;t.style.left=e.clientX+12+'px';t.style.top=e.clientY+12+'px';t.style.opacity=1};el.onmouseleave=()=>document.getElementById('tt').style.opacity=0})}
const groups=[...new Set(DATA.map(c=>c.group))];document.getElementById('charts').innerHTML=groups.map(g=>`<h2 class="section">${g}</h2><div class="grid">${DATA.map((c,i)=>c.group===g?card(c,i):'').join('')}</div>`).join('');DATA.forEach(draw);
let rows=[];DATA.forEach(c=>c.points.forEach(p=>rows.push({t:c.title,...p,u:c.unit,s:st(c,p.value)})));rows.sort((a,b)=>a.t.localeCompare(b.t)||a.date.localeCompare(b.date));
document.getElementById('table').innerHTML=`<table><tr><th>Marker</th><th>Date</th><th>Source</th><th class="n">Value</th><th>Unit</th><th>Status</th></tr>${rows.map(r=>`<tr><td>${r.t}</td><td>${r.date}</td><td>${r.source}</td><td class="n">${fmt(r.value)}</td><td>${r.u||''}</td><td><span class="chip" style="background:${SC[r.s]}">${SL[r.s]}</span></td></tr>`).join('')}</table>`;
function view(v){document.getElementById('bC').classList.toggle('active',v==='c');document.getElementById('bT').classList.toggle('active',v==='t');document.getElementById('charts').classList.toggle('hide',v!=='c');document.getElementById('table').classList.toggle('hide',v!=='t')}
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db"); ap.add_argument("--out", default="dashboard.html"); ap.add_argument("--min-points", type=int, default=2)
    a = ap.parse_args()
    c = sqlite3.connect(a.db).cursor()
    rows = c.execute("SELECT biomarker,source,test_date,value_num,unit,ref_min,ref_max,panel FROM result WHERE value_num IS NOT NULL AND test_date IS NOT NULL ORDER BY test_date").fetchall()
    series = {}
    for bio, src, d, v, u, lo, hi, panel in rows:
        k = CANON.get(bio, bio)
        s = series.setdefault(k, {"title": k, "group": panel or "Other", "unit": u, "refMin": None, "refMax": None, "points": []})
        s["points"].append({"date": d, "source": src, "value": v})
        if lo is not None: s["refMin"] = lo
        if hi is not None: s["refMax"] = hi
        s["unit"] = s["unit"] or u
    data = [s for s in series.values() if len({p["date"] for p in s["points"]}) >= a.min_points]
    data.sort(key=lambda s: (s["group"], -len(s["points"]), s["title"]))
    sources = sorted({p["source"] for s in data for p in s["points"]})
    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False)).replace("__SOURCES__", json.dumps(sources))
    open(a.out, "w", encoding="utf-8").write(html)
    print(f"{len(data)} charts -> {a.out}")


if __name__ == "__main__":
    main()
