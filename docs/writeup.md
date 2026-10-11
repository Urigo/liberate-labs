# Liberating my blood tests: from locked health portals to Apple Health, with an AI agent doing the clicking

*Six years of lab results, two portals with no export button, one read-only Health app — and the handful of tricks that got the data where I wanted it.*

I had blood work in two places I didn't control. My Israeli HMO, Maccabi, holds every panel since 2020 behind a web portal with no export. Blueprint — Bryan Johnson's biomarker service, which I used on a trip to the US — holds a 120-marker panel behind another. I wanted all of it in one SQLite file, charted over time, and ideally in Apple Health. I did it with Claude driving my browser and, eventually, my iPhone. This is what worked, what didn't, and what I'd want anyone — human or AI agent — to know before trying.

The code and two reusable Claude skills are in [liberate-labs](https://github.com/Urigo/liberate-labs). None of my values are in there; the techniques are the point.

## Part 1 — Getting the data out

### Don't replay the API. Read the React state.

Both portals are React single-page apps that fetch results from an authenticated API and render them. My first instinct was to replay the API: find the request in the network tab, copy the auth header, loop over IDs. Maccabi's results endpoint (`getresultsbyid`) took a bearer token happily and then returned an empty `results: []` for every ID — it wanted a per-request hash I'd have had to reverse out of minified JavaScript.

So I stopped fighting the API and read what it had already rendered. Every React component keeps its props on the DOM node under a `__reactFiber$…` key. Walk upward from any element through `memoizedProps` and `.return`, and somewhere you'll find the prop holding the array you want. On Maccabi it's called `labResultData`: an array of groups, each with `group_values` of `{test_desc, result, min_lim, max_lim, units, lab_date}`. Clean, structured, and no auth required beyond already being logged in.

```js
// find the results prop on any page that has rendered it
for (const el of document.querySelectorAll('*')) {
  const key = Object.keys(el).find(k => k.startsWith('__reactFiber$'));
  if (!key) continue;
  for (let f = el[key]; f; f = f.return) {
    const m = f.memoizedProps;
    for (const k in m) if (Array.isArray(m[k]) && m[k][0]?.group_values) return m[k];
  }
}
```

Blueprint was the opposite case: its Next.js page hands the client an access token in `pageProps`, and the API is a clean REST surface. One fetch for the token, two for the data, done.

### The page reloads between results. Your variables don't survive. `window.name` does.

Maccabi has 21 lab panels. Each one is its own full page load, which wipes every `window.*` variable you set — I lost my accumulator three times before I noticed. The one thing a browser carries across navigation is `window.name`, a plain string that persists for the life of the tab, *even across origins*. So: on each page, parse `window.name`, push the panel's data, stringify it back. It held 156 KB without complaint.

### The browser will stop letting you download.

Here's the one that cost me an hour. I'd planned to download a JSON file per panel. The first download worked. The second was silently blocked — Chrome's "this site is trying to download multiple files" protection — and once engaged, the block stuck for the whole origin. Then I navigated the tab to a different origin (remember, `window.name` came along for the ride) and tried once more. Blocked there too.

So I needed a channel out of the page that wasn't a download and wasn't a tool return value — the agent's JavaScript tool truncates results around 1,400 characters and redacts anything that looks like base64. The answer was the **network log**: URL-encode the data, fire it in 2 KB chunks as `fetch('/__E__/00-18?d=…')`, and read the full request URLs back out of the agent's network-requests tool. That tool's output overflows to a file when large, which is exactly what you want — it bypasses the display truncation entirely. Eighteen requests, one read, 461 rows reassembled byte-for-byte.

That's a general-purpose trick for any agent that can observe a tab's network traffic but can't receive files: **the request URL is a write channel.**

### Qualitative results hide in a different field

Thirty-six Maccabi rows came back as `result: 0`. They weren't zeros; they were "NEGATIVE," "HIV negative," and "Folic Acid >10 ng/ml," living in a `message` field or, for a few, in `message_list[0]`. And `min_lim: 0, max_lim: 0` means "no reference range," not a range of zero. Every portal has a shape like this; budget time to find it.

The result: one SQLite database, 581 results across 22 draws, 2020–2026, with a `v_results` view that lets you trend a marker across both labs. The dashboard script turns that into small multiples with reference bands.

## Part 2 — Getting the data in

### Apple Health can't take it. By design.

I assumed importing into Apple Health would be the easy half. It isn't possible — not in iOS 26, and not in iOS 27.0 either. HealthKit's open-write catalog has no data types for lab markers; cholesterol, ferritin, testosterone simply don't exist as quantity types (blood glucose is the lone exception). Lab results *do* appear in Health's "Health Records" section — but that store is read-only for apps and only fills via a FHIR connection to a participating hospital. Apple's developer docs are explicit: apps can query clinical records, never write them. The CSV-importer apps say the same in their FAQs. It's a provenance decision — a lab value carries medical weight, so Apple wants it to come from the institution that produced it — and it's unlikely to change.

iOS 27's redesigned Health app changes the picture: a new Longevity tab with manual lab entry. But it did **not** ship with iOS 27.0; Apple says "later this year, starting in U.S. English." It's in the betas. If you're looking for a Labs or Longevity section and can't find it, you don't have it yet.

### Driving the phone from the Mac

Once I had the beta, the entry forms were real: five panels (Cardiac, Blood Count, Liver & Kidney, Glucose, Cholesterol), each a paged form with value, unit, date, and optional reference range. Nineteen fields. I didn't want to type them, and I wanted to see whether an agent could.

iPhone Mirroring on macOS puts the phone's screen in a Mac window, and Claude's computer control can click in that window. It mostly works, with two findings worth writing down. First: **taps and typing reach the phone; scroll and drag do not.** Neither background actions nor full-screen synthetic scroll-wheel or click-drag moved the mirrored screen, while taps and keyboard worked in both modes. So the workflow became: I scroll to the form, the agent fills it. Second: the mirrored window has no accessibility tree, so everything is coordinate clicks off screenshots — fine, but keep the Mirroring window frontmost or the clicks land elsewhere.

### The platelet trap

The forms look consistent and aren't. WBC's field is in 10³/mcL, so "6" is correct. Platelets' field is in **1/mcL**, so "224" — the value every lab prints — is read as 224 cells per microlitre, and Health raised a **"Platelets Critical"** alert with a "discuss with your doctor" card. The correct entry is 224000. Same panel, adjacent fields, different magnitude. The agent caught it because the alert appeared mid-session; a person typing from a lab printout wouldn't. I've filed it with Apple. Read the unit row on every field.

Also: results must be dated within the last 12 months, so the 2020–2025 history can't go in. Apple Health is a current-snapshot layer. The history lives in the database.

## What I'd take away

- For locked portals: rendered state beats the API; `window.name` beats every other variable; the network log is a write channel when downloads fail.
- For agents: tool return values are not a data path. Design for the channels that overflow to files.
- For Apple Health: it's a trust model, not a missing feature — and when the door finally opens, read the units.

Everything's in the repo, including two Claude skills — `lab-portal-export` and `apple-health-lab-entry` — that encode all of the above so you can hand the job to an agent and go make coffee. MIT, do what you like.
