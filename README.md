# liberate-labs

Get your blood test results **out** of locked health portals and **into** places you control — a SQLite database, a trends dashboard, and (on iOS 27) Apple Health — with help from an AI agent.

Built around two real portals — **Maccabi Healthcare Services (מכבי שירותי בריאות, Israel)** and **Blueprint Biomarkers (Bryan Johnson)** — but the techniques generalise to any React/Next.js patient portal that has no export button.

> **Hebrew / עברית:** ייצוא תוצאות בדיקות דם ממכבי (מכבי אונליין) לקובץ SQLite / CSV, מעקב מגמות לאורך זמן, והזנה ל-Apple Health. אין במכבי אונליין כפתור ייצוא — הסקריפטים כאן מוציאים את הנתונים ישירות מהדפדפן.

## What's here

| Path | What it does |
|---|---|
| `scripts/maccabi_extract.js` | Browser-console snippets that pull every lab panel out of Maccabi Online's React state and move it out of the page (two escape hatches for when downloads are blocked). |
| `scripts/blueprint_extract.js` | Pulls the full biomarker list for a Blueprint test straight from its API using the page's own session token. |
| `scripts/assemble_from_network_log.py` | Reassembles data smuggled out through URL-encoded `fetch` requests (the "network-log channel"). |
| `scripts/build_db.py` | Normalises both sources into one SQLite schema (`lab_test`, `result`, `v_results`) with sane handling of qualitative results and "no range" sentinels. |
| `scripts/entry_sheet.py` | Produces the "latest value per marker" sheet you need for Apple Health's lab-entry forms, in the units those forms expect. |
| `dashboard/` | Self-contained HTML trends dashboard (small multiples, reference bands, light/dark, table view). |
| `skills/lab-portal-export/` | A Claude skill: drive the browser to extract labs from a locked portal. |
| `skills/apple-health-lab-entry/` | A Claude skill: enter lab results into Apple Health via iPhone Mirroring + computer control. |
| `docs/gotchas.md` | Everything that bit us. Read this first. |

## The short version

**Getting data out.** Modern patient portals render results from an authenticated API into React state. The API is often locked behind tokens and per-request hashes that are painful to replay — but the *rendered state is right there in the DOM*. Walk React's fiber tree, find the prop holding the results array, and you have clean structured data without touching the API. Then you need to get it out of the browser tab, which is where it gets fun: browsers block repeated programmatic downloads, so we use two escape hatches — `window.name` (survives navigation, even cross-origin) to accumulate data across pages, and URL-encoded `fetch` requests whose URLs get captured by the agent's network log.

**Getting data in.** Apple Health's HealthKit has no data types for lab markers and its clinical-records store is read-only for apps. iOS 27 adds a manual lab-entry UI inside the Longevity tab. Drive it from a Mac via iPhone Mirroring: taps and typing reach the phone, scrolling does not, and the platelet field is per-µL (enter `224000`, not `224`).

## Quick start

1. Open the portal in Chrome, logged in. Open DevTools → Console.
2. Paste the relevant snippet from `scripts/` (see comments inside each file for the exact flow).
3. Pull the captured data into `scripts/build_db.py` to get `blood_tests.db`.
4. `python scripts/entry_sheet.py blood_tests.db` for the Apple Health sheet.

With Claude (Cowork / Claude Code + Claude in Chrome), install the two skills and ask it to do the above for you.

## Privacy

Nothing in this repo contains real patient data. Example files use synthetic values. Your exported data stays on your machine; the scripts make no network calls except to the portal you're already logged into.

## License

MIT — do whatever you want with it.
