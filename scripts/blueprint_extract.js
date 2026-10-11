/**
 * Blueprint Biomarkers (biomarkers.bryanjohnson.com) — full biomarker export.
 *
 * Next.js app. The lab-test page's getServerSideProps returns an accessToken
 * (a JWT) that the client uses as a Bearer token against
 *   https://api.blueprintbiomarkers.com
 * Replaying is easy: fetch the page's own _next/data JSON to get the token,
 * then call the API.
 *
 * Run on any page of the site while logged in. Replace the BUILD id with the
 * one in your page's /_next/data/<BUILD>/... requests (DevTools → Network),
 * and the TEST_ID with the UUID from the lab-test page URL.
 */
await (async () => {
  const BUILD   = 'build-XXXXXXXXXXXX';           // from any /_next/data/<BUILD>/*.json request
  const TEST_ID = '00000000-0000-0000-0000-000000000000';  // /lab-tests/<TEST_ID>

  const props = await fetch(`/_next/data/${BUILD}/lab-tests/${TEST_ID}.json`, { credentials: 'include' }).then(r => r.json());
  const tok = props.pageProps.accessToken;
  const api = p => fetch('https://api.blueprintbiomarkers.com' + p, { headers: { Authorization: 'Bearer ' + tok } }).then(r => r.json());

  const tests = await api('/account-health/lab-test');            // every test on the account
  // Only tests actually run by Blueprint have labName "Blueprint Biomarkers" and status
  // "Results Ready"; uploaded third-party PDFs show status "Uploaded" — filter those out
  // if you only want Blueprint's own draws.
  const own = tests.filter(t => t.status === 'Results Ready' && t.labName === 'Blueprint Biomarkers');

  const out = [];
  for (const t of own) {
    const biomarkers = await api(`/account-health/lab-test/${t.id}/biomarkers`);
    out.push({ test: t, biomarkers });
  }
  // Each biomarker row: biomarkerName, value, valueString (e.g. "<2", "NEGATIVE"),
  // measurementUnit, providedRangeMin/Max, dateMeasured, interpretation, isAbnormal,
  // status ("In Range" | "High" | "Low" | "Normal"), tags (organ systems).

  const blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'blueprint_tests.json';
  document.body.appendChild(a); a.click(); a.remove();
  return { tests: own.length, biomarkers: out.reduce((s, x) => s + x.biomarkers.length, 0) };
})();
