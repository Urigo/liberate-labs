---
name: lab-portal-export
description: Extract a user's blood test / lab results from a locked patient portal (Maccabi Online, Blueprint Biomarkers, or any React/Next.js portal with no export) and load them into a SQLite database. Uses a purpose-built exporter when one exists (Maccabi has one) and drives the user's browser only when there isn't. Use when the user asks to export, download, back up, or consolidate their lab results from a health provider website.
---

# Lab portal export

The goal is *their* lab results, out of a portal that offers no export, into `blood_tests.db` on their machine. Everything stays local; you never send health data to any third party.

## Step 0 — look for a deterministic exporter before you drive anything

An agent clicking through result pages is slow, costs tokens on every run, and can mis-click. A purpose-built extension or script runs in seconds, needs no AI in the loop, gives a stable file format to diff month to month, and is what you should hand the user for repeat use. Before scraping, search for `<portal name> export extension` / `<portal name> github`.

**Maccabi Online has one.** [Health Records Export for Maccabi](https://github.com/RoniRachmani/health-records-export-for-maccabi) (Roni Rachmani, MIT, unofficial; [Chrome Web Store](https://chromewebstore.google.com/detail/lmjcbhajlnbpldofejcglcdclceampjp)). Procedure:

1. Tell the user to install it from the Web Store (you don't install extensions for them), log in to Maccabi Online, click the extension icon on that tab and press **Start export**. Warn them up front of its one side effect: it orders a fresh copy of their full medical file, so **Maccabi will text them an SMS** at the start, and the tab must stay in front for a few minutes (up to ~20 if the medical file is slow).
2. The result is `~/Downloads/maccabi-export-YYYY-MM-DD.zip`. Do not unzip it with macOS's `unzip` (garbles Hebrew names); the loader reads the ZIP directly, or use `ditto -x -k`.
3. `python scripts/build_db.py --maccabi-export <zip> [--blueprint <json>] --out blood_tests.db`. The loader reads `test-results/list.json`, `details/*.json` (one per panel) and `history/*.json` (one per measurement; reaches further back than the lobby), loading each `(test_id, lab_date)` once.
4. Report counts and the date range; spot-check 3–4 values against the portal UI. Skip to **Hand-off**.

The ZIP also contains a `README.md` written for AI assistants that documents every folder and the lab-value quirks — read it if anything in the data looks odd.

## Principles for portals with no exporter

1. **Read rendered state, not the API.** Portals fetch results into React props. Replaying the API needs the right token *and* the right body (Maccabi's `getresultsbyid` wants `doc_id` and gender fields alongside `request_id`, which is why a naive replay returns `results: []`); the rendered props need nothing. Walk the React fiber tree from any DOM node (`el.__reactFiber$…` → `memoizedProps` → `.return`) and find the array holding the results.
2. **Expect full-page reloads.** Many portals navigate per result page, wiping `window.*`. Accumulate across pages in **`window.name`** — a string that survives navigation, even cross-origin.
3. **Downloads are unreliable.** Browsers block repeated programmatic downloads and the block sticks. Prefer the **network-log channel**: URL-encode the data in ~2 KB chunks, fire them as `fetch(origin + '/__E__/<i>-<n>?d=…', {mode:'no-cors'})`, then read the full request URLs back with the network-requests tool (its output overflows to a file you can read in full). Reassemble with `scripts/assemble_from_network_log.py`.
4. **Tool return values are not a data channel.** They truncate at ~1,400 chars and redact base64/JWT-looking text. Use them only for small status objects.
5. **Never print tokens.** If you need a session token, use it inside page JS; don't return it.

## Procedure (browser route)

1. `tabs_context_mcp`, then open the portal in a **new tab**. Confirm the user is logged in from a screenshot; if not, ask them to log in — never enter credentials yourself.
2. Find the results list page. Capture the list via the fiber walk (look for objects with a `request_id`/`id` and a date). Record the IDs and dates; show the user the count and date range.
3. For each result page: navigate, run the capture snippet (poll up to ~10 s for the data prop to appear), append to `window.name`. Report progress every few pages.
4. Once all pages are captured, flatten to TSV in the page and push it out via the network-log channel. Read the network log, save it, run `assemble_from_network_log.py`.
5. Build the database with `scripts/build_db.py --maccabi <tsv>` (or `--blueprint`). Report row counts per source and spot-check 3–4 values against the portal UI.
6. Deliver `blood_tests.db` (and a CSV export) to the user. If a project is attached, save the CSV there — projects can't store binary files.

## Portal notes

**Maccabi Online** (`online.maccabi4u.co.il`) — browser route only if the extension is not an option: results lobby at `/sonline/testsResults/TestsResults/lobby/`; the list is in a `tests` prop (fields `request_id`, `doc_id`, `execute_date`, `referrer_name`, `type` — only `lab_result` has values; imaging/cardiology/external types are PDFs). Each panel: `/sonline/testsResults/TestsResults/LabResult/?requestId=<RID>&docId=<doc_id>`, data in the `labResultData` prop as `[{group_name, group_values:[{test_id, test_desc, result, message, message_list, is_messages, min_lim, max_lim, units, lab_date}]}]`. `result` is `0` for qualitative tests (`is_messages == "2"`) — use `message`, else `message_list`. `min_lim`/`max_lim` of `0`/`0` means no range. Units and ranges can change between dates for the same `test_id`; judge each value against its own range. Scroll gestures from automation are unreliable here; prefer direct URL navigation.

**Blueprint Biomarkers** (`biomarkers.bryanjohnson.com`): fetch `/_next/data/<BUILD>/lab-tests/<TEST_ID>.json` to get `pageProps.accessToken`, then call `https://api.blueprintbiomarkers.com/account-health/lab-test` (list) and `/account-health/lab-test/<id>/biomarkers` with `Authorization: Bearer <token>`. Filter `status === "Results Ready"` to exclude user-uploaded PDFs. A single JSON download usually works here.

## Hand-off

Tell the user: what was extracted (sources, draws, result count, date range), anything that couldn't be captured, and where the files are. If they used the extension, tell them the refresh routine is now "run the extension, re-run `build_db.py`". Offer the trends dashboard (`dashboard/build_dashboard.py`) and the Apple Health entry sheet (`scripts/entry_sheet.py`).
