/**
 * Maccabi Online (online.maccabi4u.co.il) — lab results extraction.
 *
 * The portal is a React SPA. Results are fetched from
 *   POST /sonline/TestResultsAPI/webapi/mac/v1/members/0/<MEMBER_ID>/getresultsbyid
 * but replaying that call needs a per-request hash, so we don't bother.
 * Instead we read the rendered React state on each result page.
 *
 * FLOW
 *  1. On the results lobby (/sonline/testsResults/TestsResults/lobby/) run STEP 1
 *     to list every lab panel's requestId + docId.
 *  2. For each panel, navigate to
 *       /sonline/testsResults/TestsResults/LabResult/?requestId=<RID>&docId=2::lab_result::<RID>::<MEMBER_ID>::0
 *     and run STEP 2. It appends that panel's results to window.name, which
 *     survives full-page navigations (that's the whole trick — the SPA does a
 *     full reload per result page, wiping every other variable).
 *  3. Run STEP 3 once to get the data out of the browser.
 */

// ---------- STEP 1: list all lab panels (run on the lobby page) ----------
(() => {
  // Walk React fiber trees looking for a prop holding an array of tests.
  function findTests() {
    for (const el of document.querySelectorAll('*')) {
      const key = Object.keys(el).find(k => k.startsWith('__reactFiber$'));
      if (!key) continue;
      let f = el[key], hops = 0;
      while (f && hops < 80) {
        const m = f.memoizedProps;
        if (m && typeof m === 'object') {
          for (const pk of Object.keys(m)) {
            const v = m[pk];
            if (Array.isArray(v) && v.length && v[0] && typeof v[0] === 'object' &&
                Object.keys(v[0]).some(x => /request.?id/i.test(x))) return v;
          }
        }
        f = f.return; hops++;
      }
    }
    return null;
  }
  const tests = findTests() || [];
  const labs = tests
    .filter(t => (t.doc_id || '').includes('lab_result'))
    .map(t => ({ rid: t.request_id, doc: t.doc_id, date: t.execute_date, referrer: t.referrer_name }));
  console.table(labs);
  window.name = '[]';            // reset the accumulator
  return labs;
})();

// ---------- STEP 2: capture one panel (run on each LabResult page) ----------
await (async () => {
  function scan() {
    let best = null;
    for (const el of document.querySelectorAll('*')) {
      const key = Object.keys(el).find(k => k.startsWith('__reactFiber$'));
      if (!key) continue;
      let f = el[key], hops = 0;
      while (f && hops < 100) {
        const m = f.memoizedProps;
        if (m && typeof m === 'object') {
          for (const pk of Object.keys(m)) {
            const v = m[pk];
            if (Array.isArray(v) && v.length && v[0] && typeof v[0] === 'object' &&
                /group_values|group_name/.test(Object.keys(v[0]).join(','))) {
              if (!best || v.length > best.length) best = v;   // prop is `labResultData`
            }
          }
        }
        f = f.return; hops++;
      }
    }
    return best;
  }
  let data = null;
  for (let i = 0; i < 30 && !(data && data.length); i++) {   // poll until React has rendered
    data = scan(); if (!data) await new Promise(r => setTimeout(r, 300));
  }
  let acc = []; try { acc = JSON.parse(window.name || '[]'); } catch {}
  const rid = new URL(location.href).searchParams.get('requestId');
  acc = acc.filter(x => x.requestId !== rid);
  acc.push({ requestId: rid, groups: data });
  window.name = JSON.stringify(acc);
  return { rid, groups: (data || []).length, accumulated: acc.length };
})();

// ---------- STEP 3: get it out of the browser ----------
// Option A — single download. Works ONCE per site; Chrome blocks repeated
// programmatic downloads, and the block persists. If it's already blocked,
// navigate to any other origin (window.name travels with the tab!) and run this there.
(() => {
  const blob = new Blob([window.name], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'maccabi_all_labs.json';
  document.body.appendChild(a); a.click(); a.remove();
})();

// Option B — the network-log channel (for AI agents that can read the tab's
// network requests but can't receive files). Flatten to TSV, URL-encode in
// ~2 KB chunks, and fire them as fetches to a dummy path. The agent reads the
// full URLs back from its network log and reassembles (see assemble_from_network_log.py).
await (async () => {
  const acc = JSON.parse(window.name), rows = [];
  const clean = x => (x == null ? '' : String(x)).replace(/[\t\n|]/g, ' ');
  for (const t of acc) for (const g of (t.groups || [])) for (const v of (g.group_values || [])) {
    rows.push([t.requestId, (v.lab_date || '').slice(0, 10), clean(g.group_name), v.test_id || '',
      clean(v.test_desc), v.result ?? '', clean(v.message), v.min_lim ?? '', v.max_lim ?? '', clean(v.units)].join('\t'));
  }
  const tsv = 'requestId\tlab_date\tgroup\ttest_id\ttest_desc\tresult\tmessage\tmin\tmax\tunits\n' + rows.join('\n');
  const CH = 2000, parts = Math.ceil(tsv.length / CH);
  for (let i = 0; i < parts; i++) {
    const enc = encodeURIComponent(tsv.slice(i * CH, (i + 1) * CH));
    try { await fetch(`${location.origin}/__E__/${String(i).padStart(2, '0')}-${parts}?d=${enc}`, { mode: 'no-cors' }); } catch {}
  }
  return { rows: rows.length, parts };
})();

/*
 * Field notes on the Maccabi data shape (group_values[]):
 *   test_desc   — English marker name, e.g. "Glucose (B)", "HbA1C"
 *   result      — numeric value. For qualitative tests this is 0 and meaningless.
 *   message     — qualitative result ("NEGATIVE", "POSITIVE") when present
 *   message_list— free text; for some tests (HIV Ab, Folic Acid) the real result
 *                 is message_list[0] ("HIV negative", "10 ng/ml-גדול מ")
 *   min_lim/max_lim — reference range; 0/0 means "no range provided"
 *   units       — as reported ("mg/dl", "10*3/micl", "% Total Hb.")
 */
