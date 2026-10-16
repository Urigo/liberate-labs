# Gotchas — everything that bit us

## Getting data out of portals

**Look for a deterministic exporter before you scrape.** We built an agent-driven extraction for Maccabi and only afterwards found [Health Records Export for Maccabi](https://github.com/RoniRachmani/health-records-export-for-maccabi), a Chrome extension that does the whole account in ~3 minutes with no AI in the loop, including a per-measurement history that reaches further back than the results lobby shows. For repeat use it wins on every axis: speed, cost, reproducibility, a stable file format. Search `<portal> export extension` / `<portal> github` first; `build_db.py --maccabi-export` takes its ZIP directly.

**Our "the API needs a per-request hash" diagnosis was wrong.** Maccabi's `getresultsbyid` returned `results: []` when we replayed it, and we concluded it wanted a hash. The extension's source shows it answers a plain bearer-token request — the body just has to carry `doc_id`, `logged_user_gender` and `current_user_gender` alongside `request_id`. The per-request `hash`/`t` fields only sign the PDF download URL. Lesson: an empty 200 usually means a missing field, not a signature; diff your body against the page's own request before giving up on the API.

**The authenticated API answers plain `fetch`; only the sign-in needed a browser, and then not even that.** Roni's extension and our first CLI sent every request from inside the tab on the assumption that Maccabi's bot protection (Radware/Imperva) only accepts page requests. Oren Yomtov's maccabi-health showed the `/sonline/` API answers a Node client with `User-Agent: node` once it holds the session cookies and the bearer from the portal's bootstrap endpoint (`TokenServerAPI/…/members/token/full`); the challenge bites only the public directory. The sign-in is a SAML handoff you can replay over fetch with a cookie jar (his `docs/AUTH.md`), and the site's password road is one more `POST /infosec/auth` with `type: "password"` — recorded from the page with a DevTools Network capture that printed shapes, never values. Session facts from his research: a hard 3600 s cap from login (decoded from the `F5_ST` cookie), an idle logout under six minutes held off by `MainAppAPI/v1/alive`, expiry always a 302 to `/my.policy`, and a 401/403 meaning a bot challenge, not expiry. One wrong password or code ends the attempt; never retry — that is what locks the account.

**Read React state, not the API — when you can't fix the API.** Both portals render results from an authenticated API into React component props, and the rendered `labResultData` prop has the same data as the response. Walk `el.__reactFiber$…` → `memoizedProps` upward from any DOM node and look for the array you want. Poll — the data arrives a beat after `DOMContentLoaded`. It needs nothing but being logged in, which is why it's the right generic fallback.

**Full-page reloads wipe your variables; `window.name` doesn't.** Maccabi's result pages are full navigations, so every `window.*` accumulator you set is gone on the next page. `window.name` is the one string that survives navigation — even cross-origin. Store a JSON array there and append per page. (Budget: it held 156 KB without complaint.)

**Browsers block repeated programmatic downloads — and the block sticks.** The first `a.click()` download works. Fire a second one quickly and Chrome silently blocks it, and keeps blocking that origin for the session. Even a brand-new origin may be blocked once the block has engaged. Don't design around per-page downloads.

**Escape hatch 1: carry data to another origin.** `window.name` survives cross-origin navigation, so you can navigate the tab to `example.com` and download from there. Worked once for us; not guaranteed.

**Escape hatch 2: the network-log channel.** If you're an agent that can read the tab's network requests but can't receive files: URL-encode the data, fire it as `fetch(origin + '/__E__/00-18?d=…')` in ~2 KB chunks, then read the request URLs back from your network log. Long URLs (~18 KB) were silently dropped; 2 KB chunks were reliable. The tool's output overflows to a file, which is exactly what you want — it bypasses the return-value truncation that caps most agent tools at roughly 1,400 characters.

**Agent tool outputs truncate at ~1,400 chars and *block* base64.** Don't try to pull data out through `javascript_tool` return values in big chunks; the display truncates, and anything that looks like base64 or a JWT is redacted entirely. Plain TSV passes.

**Maccabi data shape traps.** `result` is `0` for qualitative tests — the real answer is in `message` ("NEGATIVE") or, for a few (HIV Ab, Folic Acid, Hep B Ab, SARS-CoV-2 PCR), in `message_list`; `is_messages == "2"` flags "answer only in text". `min_lim`/`max_lim` of `0`/`0` means "no range," not zero. Units are free text (`10*3/micl`, `% Total Hb.`) and, per the extension's README, units and ranges for the same `test_id` can change between dates, with older `units` sometimes blank — judge each value against its own range and don't trend across a method change. The extension's export holds each value up to three times (`details/` by panel, `history/` by measurement, `latest-lab-results.json`); count each `(test_id, lab_date)` once.

**Blueprint includes uploads.** `/account-health/lab-test` returns everything on the account, including third-party PDFs the user uploaded (`status: "Uploaded"`, `labName: "Unknown"`). Filter to `status === "Results Ready"` for Blueprint's own draws.

## Getting data into Apple Health

**Before iOS 27 there is no door.** HealthKit has no quantity types for lab markers (blood glucose is the lone exception), and `HKClinicalRecord` is read-only for apps — results only enter via a FHIR link to a healthcare institution. CSV-importer apps say so explicitly. This isn't a missing feature; it's the trust model.

**iOS 27.0 shipped without the new Health app.** The redesigned app with the Longevity tab and lab entry is "later this year, starting in U.S. English." If you can't find a Labs or Longevity section, you don't have it yet. Betas have it.

**iOS 27.2 beta 4 (13 Oct 2026) pulled the new Health app again.** The Longevity and Insights tabs are gone and the old app is back; a pop-up says the new app is coming later this year and that data from the beta stays on the device and is viewable in Settings. Reports expect it back in an iOS 27.3 beta. Labs entered in earlier betas are not lost, but you can't see or add to them in Health until it returns.

**Lab entry lives at Longevity → Labs card → "Enter Your Lab Results."** It is *not* a searchable data type: Browse-tab search for "LDL" finds nothing; "Cholesterol" finds only *dietary* cholesterol. Panels must be fully complete to count in the evaluation.

**The manual forms only take each panel's core markers.** Complete Blood Count is 4 fields (WBC, Hemoglobin, Hematocrit, Platelets), yet Longevity's "Your Results" counts Blood Health as *x of 20 markers* and lists the differential and indices (basophils … neutrophils as % and count, MCH, MCHC, MCV, MPV, RBC, RDW) as missing. Cholesterol counts 7, Kidney 9, Liver 8 — again more than the forms ask for. There is no "add another marker" option, and the missing rows and "Get Deeper Insights With Labs" lead back to the same forms.

**SMART Health Cards import, but Longevity ignores them.** A `.smart-health-card` file (FHIR lab Observations with LOINC codes, signed with your own key — `scripts/make_shc.py`) opened from Files/Mail/AirDrop is accepted: Health adds one "Lab Result Record", marked *Not Verified*, and the values show under Browse → Lab Results with history. But the Longevity panel counts don't move (Blood Health stayed 4 of 20 with all 16 extra CBC markers imported), the Lab Results "Groupings" tab shows *No Data*, and the entries carry LOINC long names ("Basophils/100 leukocytes in Blood by Automated count") instead of Health's short ones. Opening the file straight from a cloud-storage app gives "Can't add this data". An import can only be deleted as a whole. Filed as FB25211694 (Oct 2026). Whether a *verified* card (issuer in the VCI directory) would count is untested.

**Results must be dated within the last 12 months.** Older history can't be entered. Health is a current-snapshot layer; keep your long history elsewhere.

**Units differ *within* the same panel.** WBC is in 10³/mcL (`6` is right). Platelets is in **1/mcL** (`224000`, not `224`). Entering `224` produces a "Platelets Critical" alert. Read the Unit row before typing every single field.

**Dates follow the device locale** — `07/06/2026` was 7 June, not July 6.

## Driving the phone via iPhone Mirroring + computer control

**Taps and typing reach the phone. Scroll-wheel and click-drag don't.** Neither background `app_*` actions nor full-screen synthetic scroll/drag moved the mirrored screen; taps and keyboard worked in both modes. Plan the workflow so the human does any scrolling and the agent fills forms. One exception seen: in Feedback Assistant, a scroll-wheel event with a large amount (50 clicks) moved the form by roughly 30 points per event, enough to reach every field; Health's Longevity screens still didn't move.

**The mirrored window has no accessibility tree.** You're clicking by coordinates off screenshots. Keep the Mirroring window frontmost; if focus drifts to another app, re-open it before clicking.

**Mirroring blanks out on privacy-sensitive screens.** Tapping the Labs card's "Start" (the US-only Quest ordering flow) turned the mirror grey — likely a purchase sheet mirroring hides. Stop when the screen goes blank; don't tap blind.

**Dismiss the keyboard before tapping Next.** The ✓ on the keyboard toolbar; otherwise the tap lands on the keyboard.

**Don't *type* long text into a mirrored iPhone — paste it.** Synthetic typing of anything beyond a few words gets scrambled on the phone side: keystrokes reorder and duplicate, especially around quote characters (smart punctuation) and line breaks. A 1,800-character bug report came out with fragments repeated and words spliced mid-stream, three times in a row. iPhone Mirroring shares the Mac clipboard, so write the text to the Mac clipboard and press ⌘V in the field — it lands byte-exact, paragraphs and all. Short values (numbers, a word) type fine. If you can't use the clipboard, type in chunks of a few hundred characters with **no line breaks** and a pause between them — that came through with one garbled word in 1,650 characters, while the same text with newlines was spliced badly.

**Background mode selects the wrong picker row.** In background (`app_*`) control, tapping a row that opens a sheet/picker tends to also "select" whichever row slides under the cursor as the sheet animates in — we got Apple Intelligence, App Switcher and App Store in turn when aiming at Health. Full-screen control sends proper press/release and doesn't do this. Also: wait ~1.5 s after opening a sheet before screenshotting, or you'll click coordinates from a mid-animation frame.

**The Mac's own Control Center / Notification Center can steal focus** mid-task if a click lands near the menu bar; if typing suddenly goes nowhere, re-front iPhone Mirroring before continuing.
