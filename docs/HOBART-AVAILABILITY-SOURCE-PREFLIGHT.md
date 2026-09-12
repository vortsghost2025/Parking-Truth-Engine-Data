# Hobart Availability & GPS Source Preflight

**Record ID:** PTE-HBT-001
**Snapshot date:** 2026-09-12
**Lane:** AVAILABILITY (plus one LEGALITY geometry lead)
**Status:** Research preflight. No Hobart source is wired into PTE core.
**Legality claim made:** none. Nothing in this document asserts that any Hobart
curb is legal or illegal to park on.

---

## 0. Headline finding

The working assumption that triggered this preflight was:

> "there's no reliable real-time data on any parking spot in Hobart"

**That assumption is incorrect.** Hobart has one of the better live parking
situations in Australia. What is actually true is narrower and more useful:

- Live on-street and off-street occupancy for Hobart **exists and is public-facing**.
- It is **not published as a documented, supported API**.
- The on-street map sits **behind bot protection**.
- The City of Hobart **explicitly prohibits reuse/republishing without written consent**.
- Sensor coverage is **partial by design** — the map only shows bays that have sensors.

So the blocker is not *absence of data*. It is **access terms and API shape**.
That is a partnership/legal problem, not a data-existence problem, and it changes
what to do next.

Evidence classification used below follows the repository convention:
**PROVEN** (verified first-hand from this session) / **CITED** (authoritative
secondary source, not first-hand verified) / **UNKNOWN** / **BLOCKED**.

---

## 1. Source inventory

| # | Source | Lane | Cadence | Access | Class |
|---|---|---|---|---|---|
| H1 | `parking-occupancy.hobartcity.com.au` — Car Park Dashboard | Availability, off-street | 60 s (published) | Plain HTTP, no bot protection observed | **PROVEN** |
| H2 | `parkmyride.au` — Park My Ride live map | Availability, on-street + off-street | 15 s sensors (published) | **BLOCKED** — WAF | **PROVEN blocked** |
| H3 | EasyPark "FIND" in-app availability for Hobart | Availability, on-street | unknown | Third-party app, no public API | **CITED** |
| H4 | `hobartcc.maps.arcgis.com` — "Street Parking" / "Other Kerb Use" layers | **Legality geometry** | static/slow | ArcGIS Online org exists; specific item now inaccessible | **PARTIAL** |
| H5 | City of Hobart parking rules & signs pages | Legality semantics | static | Plain HTML | **CITED** |
| H6 | City of Hobart Parking FAQs — non-sensored bays | Coverage accounting | static | Plain HTML | **CITED** |

---

## 2. H1 — Off-street occupancy dashboard: PROVEN LIVE

### What was verified first-hand

Fetched `https://parking-occupancy.hobartcity.com.au/` at **2026-09-12T18:50:00Z**.

| Car park | Occupied | Capacity | Available (gauge) | `avail + occ == total` |
|---|---:|---:|---:|:--:|
| ARGYLE | 37 | 1133 | 1096 | PASS |
| CENTREPOINT | 0 | 780 | 780 | PASS |
| CENTRAL | 46 | 460 | 414 | PASS |

Dashboard self-reported `Last Updated: 13-09-2026 04:49:59`.

**Liveness proof.** That timestamp is Hobart local (AEST, UTC+10). Converting:
`2026-09-13T04:49:59+10:00` == `2026-09-12T18:49:59Z` — roughly **one second**
before the retrieval. This is a genuinely live page, not a cached or static
artifact. Full observation preserved at
`sources/hobart/occupancy-snapshot/2026-09-12T184959Z-dashboard-observation.json`
(raw text + SHA-256 alongside).

**Independent corroboration (lower provenance).** A search-index cache of the same
URL dated `01-09-2026 12:08:35` reported ARGYLE **958**/1133, CENTREPOINT
**551**/780, CENTRAL **326**/460. That is 84.6% / 70.6% / 70.9% occupancy at
midday versus 3.3% / 0.0% / 10.0% at 04:49 on a Sunday. A diurnal swing of that
size across two independent observations is strong evidence the numbers move with
real demand. Classified **CITED** because it came from a search cache, not from a
direct fetch.

### Findings that matter for PTE

**H1-F1 — Capacity disagreement between two same-authority sources.**

| Car park | Dashboard | Media release 2025-09-01 | Delta |
|---|---:|---:|---:|
| ARGYLE | 1133 | 1133 | 0 |
| CENTREPOINT | 780 | 782 | **-2** |
| CENTRAL | 460 | 462 | **-2** |

Both are City of Hobart publications. Under PTE conflict semantics this is a
same-claim disagreement and should surface as a capacity **CONFLICT** or be
resolved from an authoritative facility record — **not silently averaged**.
Plausible explanation (out-of-service bays excluded from the live counter feed)
is **NOT VERIFIED**.

**H1-F2 — The zero-occupancy false-certainty trap.**

CENTREPOINT reported **exactly 0 occupied**, hence "780 available", at 04:49 on a
Sunday. The feed cannot distinguish:

1. the facility is genuinely empty, from
2. the facility is **closed overnight** and its counters are reporting zero.

A naive consumer renders "780 spaces available" at 4:50am. If (2) is true that is
exactly the **false certainty** this project exists to refuse. Correct handling:
an all-zero counter outside plausible operating hours should degrade to
`availability: UNKNOWN` with a reason, not `HIGH`. **Status: UNRESOLVED —
Centrepoint operating hours must be verified before any consumer shows a count.**

The simulator at `tools/realtime-sim/sim_feed.py` reproduces this class of failure
on purpose (see §7) so the frontend contract's `UNKNOWN` path gets exercised.

**H1-F3 — No structured API discovered.**

The values are present in the delivered document, so they are scrapeable. But the
underlying feed URL, request contract and true poll interval are **UNKNOWN** from
this sandbox: bash has no outbound network, and the page fetcher returns rendered
markdown with scripts stripped. **Action:** from a normal network, open devtools →
Network on that URL and record the XHR/fetch contract. Do not assume the HTML is
the intended interface.

**H1-F4 — Reuse is prohibited without written consent.** (see §6)

---

## 3. H2 — Park My Ride: PROVEN BLOCKED

`https://parkmyride.au/` returned, to this session's fetcher:

```
Service unavailable
## The request is blocked.
20260912T185059Z-16d6867c979c8stvhC1BN1b4tg0000001sa0000000006dcr
```

That is an **Azure Front Door / WAF** rejection with a tracking ID — i.e. bot
management, not an outage. `robots.txt` and a plain `HEAD /` were also refused.
**Class: BLOCKED for programmatic access.**

What it publishes (all **CITED**, from the City of Hobart media release of
2025-09-01 and the council's Live parking availability map page):

- Launched **1 September 2025**; first Tasmanian council to do so.
- In-ground sensors in the **city centre, Midtown, North Hobart and Salamanca**.
- Sensor refresh **every 15 seconds**.
- **~2,000 on-street bays** sensored, plus six facilities:
  Argyle Street (1,133), Centrepoint (782), Hobart Central (462),
  Condell Place (83), Dunn Place (82), Lefroy Street (47) — **4,000+ spaces** total.
- **40+ accessible bays** highlighted.
- Includes permitted stay times, street view and navigation.
- Built in-house by the City's **Transport and Business Intelligence** teams.
- Originates from the Council-endorsed **Parking and Kerbside Management 10 Year Plan**.

**H2-F1 — Coverage is partial by design, and the council says so.**

> "our live parking map **only shows available parking spaces where in-ground
> sensors are installed.**"

and, from the Parking FAQs, non-sensored bays:

> "Areas without sensors will continue to have the timed restrictions enforced"

So sensored ≈ 2,000 bays; total Hobart on-street bays is materially larger.
**Any availability figure must carry a coverage denominator**, otherwise a driver
is shown "nothing available" on a street that simply has no sensors. This is the
same failure mode as H1-F2. Coverage accounting is **UNKNOWN** — the count of
non-sensored bays is not published as far as this preflight found.

**H2-F2 — History: the sensor estate is older than the map.**

**CITED**: in August 2017 Smart Parking (ASX:SPZ), in partnership with APARC, won
a ~$800k contract to install **2,100 in-ground vehicle detection sensors** and 251
meters for Hobart City Council. The ~2,000 figure in the 2025 launch is consistent
with that estate, i.e. the map is a new presentation layer over years-old sensing.
Useful context when negotiating: the city already owns the hard part.

**H2-F3 — EasyPark is the sanctioned distribution channel.**

**CITED**: the council confirmed Hobart on-street availability would be made
available in the **EasyPark** app via its **FIND** feature (already live in
Melbourne, Canberra, Newcastle, Parramatta, Gold Coast and several European
cities). FIND is explicitly **probability-based**, colouring streets
green/yellow/orange-red rather than asserting per-bay truth — a design choice
worth noting because it is philosophically aligned with PTE's refusal of false
certainty. EasyPark is a commercial partner; there is no public developer API for
this that this preflight found. **Class: UNKNOWN.**

---

## 4. H4 — Legality geometry lead (separate lane)

A 2024 community report describes a council-published detailed on-street
restrictions map at `hobartcc.maps.arcgis.com`, with layers named **"Street
Parking"** and **"Other Kerb Use"**.

Verified first-hand this session:

- `hobartcc.maps.arcgis.com` **does** exist as an ArcGIS Online organisation and
  answers `/sharing/rest/search`.
- The specific web-map item ID circulated in that 2024 report
  (`ba937e74524740ba81655d907d7a4465`) now returns
  `{"error":{"code":400,"messageCode":"CONT_0001","message":"Item does not exist or is inaccessible."}}`
  — so it was **retired, moved, or made private**.

**Class: PARTIAL.** The organisation is real and this is the most promising route
to authoritative Hobart *restriction* geometry — which is exactly the Melbourne /
Montréal legality-lane problem in a new city. But no live layer URL is confirmed.

**Caution — do not confuse two Hobarts.** Searching for Hobart open data returns
`data-1-hobartcc.opendata.arcgis.com` and `hub-cityofhobart.hub.arcgis.com`, which
are **Hobart, Indiana, USA**, not Hobart, Tasmania. Their "Parking Meters"
dataset is irrelevant here and was rejected. Recorded so nobody re-walks that
trap.

**Next step:** from a normal network, browse
`https://hobartcc.maps.arcgis.com/home/search.html?q=parking` and
`https://www.hobartcity.com.au/City-services/Parking/Car-parks` (which embeds a
"Street Parking Map" element requiring JavaScript) and capture the live service
URLs. Record each as URL + retrievedAt + SHA-256 + licence per the repository
storage policy.

---

## 5. Legally open real-time feeds usable for testing today

These are the feeds that can be pointed at the pipeline **without** a consent
conversation, because they are published for third-party integration.

| Feed | What | Why it's useful here | Class |
|---|---|---|---|
| **TfNSW Car Park API** (`opendata.transport.nsw.gov.au`) | Real-time **and historical** occupancy for Transport Park&Ride car parks, incl. Sydney Metro NW stations | A genuine, documented, supported real-time occupancy API with an API key — the correct thing to build and test an adapter against. Newer variant returns **all car parks in one call**. Docs updated Aug 2026, so actively maintained. | **CITED** (dataset page verified first-hand; API not called — needs a key) |
| **City of Melbourne on-street parking bay sensors** | Live on-street bay status | Already **PROVEN** in this project — `PROJECT_STATUS.md` records live occupancy verified and an exact `kerbsideid` occupancy↔geometry join. Real-time on-street exists *today* in the repo's own laboratory city. | **PROVEN (prior)** |
| **Geelong real-time parking availability** (`geelongdataexchange.com.au`) | LoRa sensor status, CSV/JSON/GeoJSON/SHP/KML export | Small, simple, openly licensed real-time feed — good for a first end-to-end smoke test | **CITED** |
| **Los Angeles** | Occupancy + inventory with exact `spaceid` join | Already **PROVEN**; second-city control case | **PROVEN (prior)** |

**Important consequence.** The premise "I can't find reliable real-time data on
*any* parking spot" does not hold even before Hobart is considered: this project
has already verified live occupancy joins in Melbourne and Los Angeles. Melbourne
in particular is *on-street*, which is the hard case.

Two notes on the TfNSW feed, both **CITED** from its own forum:

- The maintainers explicitly warn **not to hard-code capacities** — spot counts
  change and are supplied in the feed itself.
- Counter feeds **do** go out of sync during trackworks (a documented Kiama
  incident), i.e. real feeds need the same `STALE`/`DEGRADED` handling PTE's
  source-health layer already implements. Good validation that the design is not
  over-engineered.

---

## 6. BLOCKED: reuse terms

The City of Hobart Live parking availability map page states:

> "The content displayed on the dashboard is the property of the City of Hobart.
> You may not reuse or republish the content without written consent from the
> City. The real-time car park occupancy data is provided by the off-street car
> parking system. The occupancy data is updated every 60 seconds."

**Classification: `NO_REUSE_WITHOUT_WRITTEN_CONSENT`.**

What that does and does not permit:

- **Permitted** — reading the page to verify live data exists; internal research;
  recording hashes and observations as evidence, as done here.
- **Not permitted** — shipping these occupancy numbers inside a product,
  republishing them, or presenting them to end users as your own availability
  layer, without written consent.

This applies to H1 and, by reasonable extension, to H2 (Park My Ride), which is
the same council's publication. It does **not** apply to the openly licensed
feeds in §5.

**Owner decision required.** Any commercial Hobart product needs one of:

1. written consent / a data agreement with the City of Hobart;
2. a commercial relationship via EasyPark or the sensor vendor;
3. a **crowdsourced** availability layer built from your own users' data, which
   you own outright — see §8.

**Do not scrape and ship.** Beyond the terms, `parkmyride.au` is behind a WAF, so
scraping would be both a legal and a technical fight, and would be brittle.

---

## 7. What was built in response: the real-time test rig

The immediate question — *"can I test whether the GPS part works in real time?"* —
does **not** require any of the above to be resolved. It requires a live position
stream and a live availability stream. Both are now synthesised under
`tools/realtime-sim/`:

| File | Role |
|---|---|
| `sim_feed.py` | Synthetic Hobart-CBD availability feed. 15 s tick by default (matching Park My Ride's published cadence), 6 car parks at **real cited capacities** with synthetic counts, ~850–950 synthetic bays, SSE event stream, PTE-shaped source-health. |
| `gps_replay.py` | GPS trace generator + replayer. Synthesises a "cruising for a park" CBD drive, or replays a real GPX, and POSTs fixes to your ingest endpoint at wall-clock speed. |
| `README.md` | How to run them and what each failure mode is for. |

Failure modes deliberately reproduced, because they are the ones that break real
integrations and the ones PTE's contract must survive:

- **sensor gaps** → bays report `UNKNOWN`, never an inferred `FREE`
- **sensor faults** → `sensorOk: false`, `UNKNOWN`, and `source-health` degrades
- **counter feed going stale** → off-street `availability: UNKNOWN` (models H1-F2)
- **GPS dropouts, accuracy spikes, backwards drift** → models urban-canyon Hobart
- **overstay** → `overstayed: true` without the availability lane making any
  legality claim
- **restrictions carried as inventory metadata only** → so a test can assert that
  `PROHIBITED + HIGH availability` stays prohibited (an existing frontend
  contract invariant)

Every payload carries `"synthetic": true` and a `disclaimer` string. **Nothing in
this tool is real parking data and none of it may be shown to end users as real
availability.**

Verified working in this session: all endpoints respond, all four bay statuses
(`FREE` / `OCCUPIED` / `UNKNOWN` / `RESTRICTED`) occur, the stale-feed path
produced `availability: UNKNOWN` for one car park, sensor faults drove
`faultedSensors: 2`, a 2.7-simulated-hour run produced 76 overstayed bays, and
the GPS replayer streamed 387 fixes with `sent=387 failed=0`.

---

## 8. Strategic note: "Waze for parking" answers its own data question

Waze does not obtain live traffic from cities. It obtains it from **its own users'
phones** — every client is a probe. That is why Waze works in places with zero
municipal instrumentation, and it is why the Ottawa street-camera assumption was a
dead end: cameras are an *authority* data source, and authorities rarely open
them. Waze never needed permission.

Applied here, the durable architecture is:

1. **Legality** — municipal sources (H4/H5). Slow-moving, authoritative, must be
   licensed or openly published. This is where written consent matters.
2. **Availability** — **your own users**. Arrival/departure events, dwell time,
   and passive "did this device stop here and then leave" signals. You own this
   data outright; no consent conversation, no WAF, no 60-second feed you can't
   legally use.
3. **Municipal sensors** — an *enhancement* to (2) when a city agrees, not the
   foundation. Hobart is unusually well placed to become that enhancement later,
   because the sensor estate already exists (§3, H2-F2).

This is already anticipated in `docs/ARCHITECTURE.md`, which lists
"privacy-preserving phone/mesh events" as an availability input. Cold-start is the
real cost: a crowdsourced layer is useless at zero users, which is precisely what
the simulator in §7 stands in for until there is traffic.

**Note on cruising detection.** Since users' phones are the probe, the highest
value signal is *search behaviour* — a device moving slowly (2–6 m/s) along a
street, then stopping. `gps_replay.py` labels exactly these phases
(`driving` / `searching` / `junction` / `manoeuvre` / `parked`), so a
cruising-detection heuristic can be developed and measured against labelled
ground truth before any real user data exists.

---

## 9. Recommended next actions

Ordered by value per unit of effort.

1. **[Owner decision]** Choose the Hobart availability strategy: consent path
   (§6.1), EasyPark/vendor path (§6.2), or crowdsourced (§8). Everything
   downstream depends on this.
2. **[30 min, normal network]** Open devtools on
   `https://parking-occupancy.hobartcity.com.au/`, capture the real XHR contract
   for H1, and record it in `manifests/`. Resolves H1-F3.
3. **[30 min]** Resolve H1-F2: find Centrepoint operating hours. If it closes
   overnight, codify the "all-zero outside operating hours ⇒ `UNKNOWN`" rule as a
   test.
4. **[1 hr, normal network]** Browse `hobartcc.maps.arcgis.com/home/search.html?q=parking`
   and the council's Street Parking Map; capture live service URLs for H4. This is
   the legality-geometry unlock and the only route to a real Hobart legality lane.
5. **[1 hr]** Apply for a TfNSW Open Data key and build the Car Park API adapter
   against `sim_feed.py`'s contract. Proves the adapter architecture on a *real,
   legal, documented* real-time feed before Hobart is negotiable.
6. **[Already available]** Wire the Hostinger app's GPS ingest to
   `gps_replay.py --post-url` and confirm real-time position handling today. No
   parking data required.
7. **[Then]** Re-run `PROJECT_STATUS.md` coverage accounting for Hobart:
   sensored vs total on-street bays (H2-F1). Without a denominator, availability
   percentages are not meaningful.

---

## 10. Provenance of this record

- First-hand fetches this session: `parking-occupancy.hobartcity.com.au`,
  `parkmyride.au` (blocked), `hobartcc.maps.arcgis.com/sharing/rest/*`,
  `opendata.transport.nsw.gov.au/data/dataset/car-park-api`,
  `hobartstreets.au` project page.
- Preserved observation: `sources/hobart/occupancy-snapshot/` (raw text, SHA-256,
  structured JSON).
- Machine-readable source references: `manifests/hobart-availability-sources-manifest.json`.
- Sandbox limitation, stated plainly: **bash in this environment has no outbound
  network** (all `curl` attempts returned `SSL_ERROR_SYSCALL`, including to
  `example.com`). Only the browser-side page fetcher and web search reached the
  internet. Any step requiring raw HTTP inspection, devtools, or an API key must
  be performed on a normal machine.
