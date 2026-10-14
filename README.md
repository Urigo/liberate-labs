# liberate-labs

Get your blood test results **out** of locked health portals and **into** places you control — a SQLite database, a trends dashboard, and (on iOS 27) Apple Health — with help from an AI agent.

Built around two real portals — **Maccabi Healthcare Services (מכבי שירותי בריאות, Israel)** and **Blueprint Biomarkers (Bryan Johnson)** — but the techniques generalise to any React/Next.js patient portal that has no export button.

> **Hebrew / עברית:** ייצוא תוצאות בדיקות דם ממכבי (מכבי אונליין) לקובץ SQLite / CSV, מעקב מגמות לאורך זמן, והזנה ל-Apple Health. למכבי יש תוסף כרום ייעודי לייצוא כל התיק הרפואי (ראו למטה); הסקריפטים כאן הופכים את הייצוא שלו, או נתונים שנשלפו ישירות מהדפדפן, למסד נתונים אחד.

**Read the story first:** [docs/writeup.md](docs/writeup.md) — why the obvious approaches failed and what worked, for both the portal side and the Apple Health side.

## Maccabi members: start with the extension

If your portal is Maccabi Online, don't scrape it — use **[Health Records Export for Maccabi](https://github.com/RoniRachmani/health-records-export-for-maccabi)** by Roni Rachmani ([Chrome Web Store](https://chromewebstore.google.com/detail/lmjcbhajlnbpldofejcglcdclceampjp), MIT, unofficial). One click on the logged-in tab and a few minutes later you have a ZIP with every lab panel as JSON, a per-measurement history that reaches back further than the results lobby shows, and everything else on the account (visits, prescriptions, referrals, letters, your full medical file as PDF). It talks only to `online.maccabi4u.co.il`, never sees your password, and the one side effect — it orders a fresh copy of your medical file, which makes Maccabi send you an SMS — is documented up front.

Then:

```sh
python scripts/build_db.py --maccabi-export ~/Downloads/maccabi-export-2026-10-11.zip \
                           --blueprint blueprint_tests.json --out blood_tests.db
```

That's the whole Maccabi side. To refresh later, run the extension again and rebuild, keeping the other sources from the previous database:

```sh
python scripts/build_db.py --carry blood_tests.db:blueprint --maccabi-export ~/Downloads/maccabi-export-2026-11-01.zip --out blood_tests_new.db
```

**No extension, no clicks, no browser:** the same collector runs from the terminal. `npm run export` in that repo (merged upstream in [PR #15](https://github.com/RoniRachmani/health-records-export-for-maccabi/pull/15), shipped from v0.8.8) opens Chrome, signs in with credentials from 1Password or `.env`, pulls test results and every measurement's history in about 90 seconds, orders nothing (so no SMS), and writes the same folder the ZIP holds. `npm run export -- --no-browser` (proposed upstream as a second PR) does the same with no Chrome at all: Maccabi's SAML sign-in replayed over `fetch` — the chain [Oren Yomtov's maccabi-health](https://github.com/orenyomtov/maccabi-health) first worked out — with the site's password road in place of the SMS, so it runs from `cron` with no one present. `build_db.py --maccabi-export <folder>` reads either folder directly. That's the version to put on a schedule.

The browser-console route below (`scripts/maccabi_extract.js`) still works and is kept as the generic technique for portals that *don't* have a tool like this — which is most of them.

## What's here

| Path | What it does |
|---|---|
| `scripts/build_db.py` | Normalises everything into one SQLite schema (`lab_test`, `result`, `v_results`). Reads the Maccabi extension's ZIP/folder (`--maccabi-export`), the console-route TSV (`--maccabi`), and Blueprint JSON (`--blueprint`); `--carry old.db:source` keeps a source from an earlier build. Handles qualitative results (short answer in `value_text`, the lab's note in `interpretation`), "no range" sentinels, and de-duplicates the export's three copies of each value. |
| `scripts/blueprint_extract.js` | Pulls the full biomarker list for a Blueprint test straight from its API using the page's own session token. |
| `scripts/maccabi_extract.js` | Fallback / generic technique: browser-console snippets that pull every lab panel out of a React portal's rendered state and move it out of the page (two escape hatches for when downloads are blocked). |
| `scripts/assemble_from_network_log.py` | Reassembles data smuggled out through URL-encoded `fetch` requests (the "network-log channel"). |
| `scripts/entry_sheet.py` | Produces the "latest value per marker" sheet you need for Apple Health's lab-entry forms, in the units those forms expect. |
| `dashboard/` | Self-contained HTML trends dashboard (small multiples, reference bands, light/dark, table view). |
| `skills/lab-portal-export/` | A Claude skill: get labs out of a portal — via the extension when there is one, by driving the browser when there isn't — and into the database. |
| `skills/apple-health-lab-entry/` | A Claude skill: enter lab results into Apple Health via iPhone Mirroring + computer control. |
| `examples/` | Synthetic data in each input format, including a miniature extension export (`maccabi_export_example/`). |
| `docs/writeup.md` | The narrative: how it was done and what we learned. |
| `docs/gotchas.md` | Everything that bit us, as a checklist. |

## The short version

**Getting data out.** Check for a purpose-built exporter first; for Maccabi there is one, and a deterministic tool beats an agent clicking through pages every time. Where there isn't one: modern patient portals render results from an authenticated API into React state, and the *rendered state is right there in the DOM*. Walk React's fiber tree, find the prop holding the results array, and you have clean structured data without reverse-engineering the API. Then you need to get it out of the browser tab, which is where it gets fun: browsers block repeated programmatic downloads, so we use two escape hatches — `window.name` (survives navigation, even cross-origin) to accumulate data across pages, and URL-encoded `fetch` requests whose URLs get captured by the agent's network log.

**Getting data in.** Apple Health's HealthKit has no data types for lab markers and its clinical-records store is read-only for apps. iOS 27 adds a manual lab-entry UI inside the Longevity tab. Drive it from a Mac via iPhone Mirroring: taps and typing reach the phone, scrolling does not, paste long text instead of typing it, and the platelet field is per-µL (enter `224000`, not `224`).

## Quick start

1. **Maccabi:** run the extension, note where the ZIP landed. **Blueprint / other portals:** open the portal in Chrome, logged in, DevTools → Console, paste the relevant snippet from `scripts/` (see comments inside each file for the exact flow).
2. `python scripts/build_db.py --maccabi-export <zip> --blueprint <json> --out blood_tests.db`
3. `python dashboard/build_dashboard.py blood_tests.db` for the trends page.
4. `python scripts/entry_sheet.py blood_tests.db` for the Apple Health sheet.

With Claude (Cowork / Claude Code + Claude in Chrome), install the two skills and ask it to do the above for you.

## Prior art and credits

- **[Health Records Export for Maccabi](https://github.com/RoniRachmani/health-records-export-for-maccabi)** (Roni Rachmani) — the right tool for Maccabi. Its README also documents the lab-value quirks (`result: 0` with the answer in `message`, `min_lim`/`max_lim` of 0/0 meaning no range, units and ranges changing over time) more thoroughly than we do, and its code showed that Maccabi's `getresultsbyid` endpoint *does* answer a plain replay once you send `doc_id` and the gender fields with the `request_id` — our "it needs a per-request hash" conclusion in the write-up was wrong; see the correction there.
- **[maccabi-health](https://github.com/orenyomtov/maccabi-health)** (Oren Yomtov) — an npm library, CLI and MCP server that queries Maccabi live with no browser. Its `docs/AUTH.md` is where the SAML sign-in chain over plain `fetch` was first worked out, and its `docs/research/SESSION-LIFETIME.md` measured the one-hour absolute session cap and the idle timeout; the browserless exporter above is built on both, with the password road added.
- The React-fiber-walk, `window.name` accumulator and network-log channel are general browser-agent techniques; nothing here is specific to health data.

## Privacy

Nothing in this repo contains real patient data. Example files use synthetic values. Your exported data stays on your machine; the scripts make no network calls except to the portal you're already logged into.

## License

MIT — do whatever you want with it.
