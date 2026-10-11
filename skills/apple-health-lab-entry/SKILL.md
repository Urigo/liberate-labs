---
name: apple-health-lab-entry
description: Enter blood test / lab results into Apple Health's lab-entry panels (iOS 27 Longevity → Labs) by driving the user's iPhone through iPhone Mirroring on their Mac with computer control. Use when the user asks to put, import, or sync their lab results into Apple Health, or asks why Apple Health can't import them.
---

# Apple Health lab entry (via iPhone Mirroring)

## First, check the door exists

- Before iOS 27 there is **no way** to enter lab results: HealthKit has no lab quantity types (blood glucose aside) and clinical records are read-only, provider-synced via FHIR. Say so plainly; don't suggest CSV-importer apps for labs — they can't.
- iOS 27.0 shipped **without** the new Health app; the Longevity tab and lab entry arrive in a later update, US English first. If the user can't find a Longevity tab, they don't have it yet.
- When it exists, lab entry is at **Longevity → Labs card → "Enter Your Lab Results"** (panels: Cardiac, Blood Health/CBC, Liver & Kidney, Glucose, Cholesterol). It is *not* a searchable data type — don't bother with the Browse search.
- Results must be dated **within the last 12 months**. Older history can't go in; keep it in the database/dashboard.

## Setup

1. Load the computer-use skill, then `computer_resolve_access(["iPhone Mirroring"])` → `computer_request_access`.
2. Ask the user to open iPhone Mirroring and navigate the phone to the lab-entry panel they want filled. **You cannot scroll the mirrored phone** — scroll-wheel and drag gestures are not delivered; taps and typing are. Division of labour: the human scrolls/navigates, you fill forms.
3. Background `app_*` taps work, but you'll need **full-screen control** for a reliable keyboard; request it once (`computer_request_full_control`), and keep iPhone Mirroring frontmost (`computer_open_application` if focus drifts). The mirrored window has no accessibility tree — click by coordinates from screenshots.
4. Prepare the values first with `scripts/entry_sheet.py blood_tests.db --source <lab>` so a whole panel shares one draw date.

## Filling a panel

Each panel is a paged form: `Result/value`, `Unit` (read-only), `Date Collected`, optional `Reference Range`, then **Next** / **Done** / **Skip**. For every page:

1. Screenshot. **Read the Unit row before typing** — units differ within a panel.
2. Tap the value field, type the number. Tap the keyboard's ✓ to dismiss it (otherwise Next is covered).
3. Optionally fill the reference range (low field, high field) from the lab's reported range.
4. Tap Next; on the last page tap Done. Back on the panel list, confirm it shows "Completed."
5. After all panels, tap **Evaluate** and screenshot the summary.

## Unit traps (these caused real false alarms)

| Field | Health's unit | Enter |
|---|---|---|
| WBC | 10³/mcL | `6` for 6.0 K/µL |
| **Platelets** | **1/mcL** | **`224000`** for 224 K/µL — `224` triggers a "Platelets Critical" alert |
| Hemoglobin | g/dL | as reported |
| hsCRP | mg/L | convert if the lab reported mg/dL (×10) |
| Insulin | mcIU/mL | as reported |

Dates follow the device locale (dd/mm in Israel/UK). Lab reference ranges go in the optional fields; Health keeps its own "Health Range" separately.

## Verify

Open each panel's **Edit** and step through pages comparing to the sheet; fix anything off and re-Evaluate. Expected evaluation after a clean entry: panels "In Range"/"Normal"/"Good"; a "Fair"/"Out of Range" should correspond to a genuinely flagged marker (e.g. ApoB over its cutoff), not a unit error.

## Hand-off

Report which panels are complete, each value entered with its unit, anything skipped and why, and the 12-month limitation. Release the computer-use lock when done. Persist the entered-state summary somewhere durable (a project doc) so the next draw can be diffed against it.
