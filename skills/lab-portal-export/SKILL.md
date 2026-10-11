---
name: lab-portal-export
description: Extract a user's blood test / lab results from a locked patient portal (Maccabi Online, Blueprint Biomarkers, or any React/Next.js portal with no export) via their browser, and load them into a SQLite database. Use when the user asks to export, download, back up, or consolidate their lab results from a health provider website.
---

# Lab portal export

You are driving the user's own logged-in browser (Claude in Chrome) to get *their* lab results out of a portal that offers no export. Everything stays on their machine; you never send health data to any third party.

## Principles

1. **Read rendered state, not the API.** Portals fetch results into React props. Replaying the API usually needs tokens or per-request hashes; the rendered props don't. Walk the React fiber tree from any DOM node (`el.__reactFiber$…` → `memoizedProps` → `.return`) and find the array holding the results.
2. **Expect full-page reloads.** Many portals navigate per result page, wiping `window.*`. Accumulate across pages in **`window.name`** — a string that survives navigation, even cross-origin.
3. **Downloads are unreliable.** Browsers block repeated programmatic downloads and the block sticks. Prefer the **network-log channel**: URL-encode the data in ~2 KB chunks, fire them as `fetch(origin + '/__E__/<i>-<n>?d=…', {mode:'no-cors'})`, then read the full request URLs back with the network-requests tool (its output overflows to a file you can read in full). Reassemble with `scripts/assemble_from_network_log.py`.
4. **Tool return values are not a data channel.** They truncate at ~1,400 chars and redact base64/JWT-looking text. Use them only for small status objects.
5. **Never print tokens.** If you need a session token, use it inside page JS; don't return it.

## Procedure

1. `tabs_context_mcp`, then open the portal in a **new tab**. Confirm the user is logged in from a screenshot; if not, ask them to log in — never enter credentials yourself.
2. Find the results list page. Capture the list via the fiber walk (look for objects with a `request_id`/`id` and a date). Record the IDs and dates; show the user the count and date range.
3. For each result page: navigate, run the capture snippet (poll up to ~10 s for the data prop to appear), append to `window.name`. Report progress every few pages.
4. Once all pages are captured, flatten to TSV in the page and push it out via the network-log channel. Read the network log, save it, run `assemble_from_network_log.py`.
5. Build the database with `scripts/build_db.py`. Report row counts per source and spot-check 3–4 values against the portal UI.
6. Deliver `blood_tests.db` (and a CSV export) to the user. If a project is attached, save the CSV there — projects can't store binary files.

## Portal notes

**Maccabi Online** (`online.maccabi4u.co.il`): results lobby at `/sonline/testsResults/TestsResults/lobby/`; the list is in a `tests` prop (fields `request_id`, `doc_id`, `execute_date`, `referrer_name`). Each panel: `/sonline/testsResults/TestsResults/LabResult/?requestId=<RID>&docId=<doc_id>`, data in the `labResultData` prop as `[{group_name, group_values:[{test_desc, result, message, message_list, min_lim, max_lim, units, lab_date}]}]`. `result` is `0` for qualitative tests — use `message`, else `message_list[0]`. `min_lim`/`max_lim` of `0`/`0` means no range. Scroll gestures from automation are unreliable here; prefer direct URL navigation.

**Blueprint Biomarkers** (`biomarkers.bryanjohnson.com`): fetch `/_next/data/<BUILD>/lab-tests/<TEST_ID>.json` to get `pageProps.accessToken`, then call `https://api.blueprintbiomarkers.com/account-health/lab-test` (list) and `/account-health/lab-test/<id>/biomarkers` with `Authorization: Bearer <token>`. Filter `status === "Results Ready"` to exclude user-uploaded PDFs. A single JSON download usually works here.

## Hand-off

Tell the user: what was extracted (sources, draws, result count, date range), anything that couldn't be captured, and where the files are. Offer the trends dashboard (`dashboard/build_dashboard.py`) and the Apple Health entry sheet (`scripts/entry_sheet.py`).
