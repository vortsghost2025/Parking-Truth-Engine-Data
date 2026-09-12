# Real Parking Telemetry Sources — arrival/departure events at volume

**Record ID:** PTE-TEL-001
**Snapshot date:** 2026-09-12
**Lane:** AVAILABILITY
**Legality claim made:** none. Every artifact described here carries
`legalityClaimed: false`.
**Companion tooling:** `tools/telemetry/telemetry_harvester.py`
**Companion schema:** `schemas/parking-telemetry-event-schema.json`

---

## 0. The answer, up front

The question was *"how can I generate enough real data to create telemetry I can
use to monitor when a parking space gets used and left?"*

**You do not need to generate it. It already exists, at a scale you cannot
exhaust, and it is openly licensed.**

The City of Melbourne publishes **historical parking-event archives** where each
row is one real parking event, with arrival time, departure time, duration, the
restriction that applied, and whether the vehicle overstayed. Confirmed volumes:

| Year | Rows | Compressed CSV |
|---|---:|---|
| 2014 | 51,500,000 | 1.56 GB |
| 2015 | 37,500,000 | 1.17 GB |
| 2016 | 34,100,000 | 1.07 GB |
| 2017 | 35,900,000 | 1.13 GB |
| 2018 | 30,200,000 | 504 MB |
| 2019 | 42,700,000 | 717.1 MB |
| 2020 (Jan–May) | 14,200,000 | 258.5 MB |
| **Quantified total** | **≈ 246,100,000** | **≈ 6.2 GB** |

A **2012** archive also exists (row count not captured in this preflight), and a
**2013** year is likely. So the real figure is *"a quarter of a billion real
parking arrival/departure events, spanning roughly eight years."*

Publisher's own description of what a row is:

> "These sensors record when a vehicle arrives and when it departs. Each record
> also includes the parking restriction for the bay and whether the vehicle has
> overstayed that restriction. An event will include if a vehicle was present or
> not which can determine stay time and vacancy time."

Licence: **CC-BY-4.0** on the current portal (earlier years list
**CC-BY-3.0-AU**). Both permit commercial reuse with attribution. Confirm per
dataset before shipping.

**This is not a proxy and not a simulation.** It is ground-truth occupancy
transition telemetry from in-ground sensors, which is precisely the thing you
were looking for and could not find in Hobart.

---

## 1. Why Melbourne and not Hobart

`docs/HOBART-AVAILABILITY-SOURCE-PREFLIGHT.md` (PTE-HBT-001) established that
Hobart's live data is real but **gated**: behind a WAF, no documented API, and
*"may not reuse or republish ... without written consent from the City."*

Melbourne is the opposite on every axis that matters here:

| | Hobart | Melbourne |
|---|---|---|
| Live per-bay status | WAF-blocked | Open, CC-BY-4.0 |
| Historical per-event archive | not published | **8 years, ~246M rows** |
| Documented API | none found | Opendatasoft, several shapes |
| Reuse terms | written consent required | CC-BY attribution |
| Geometry join | not confirmed | `marker_id` / `bay_id` documented |

This project already uses Melbourne as its software/data laboratory
(`PROJECT_STATUS.md`: *"live occupancy source verified … exact `kerbsideid`
occupancy/geometry join proven"*). PTE-TEL-001 extends that from *state* to
*events*, which is the thing that was missing.

**Hobart is still the right production target.** Melbourne is where you build and
prove the telemetry pipeline, because you can legally do it today and at a volume
that will surface bugs a small feed would hide.

---

## 2. Two ways to obtain telemetry, and the honest difference between them

### 2.1 Historical archive — OBSERVED events

One row = one real parking event with real arrival and departure timestamps.
`timeConfidence: OBSERVED`. This is the gold standard and there are ~246M of
them.

Limitations, all documented by the publisher:

- **Year-boundary truncation.** Events crossing into the following year are
  *excluded* (2014: 3,377; 2015: 4,138; 2016: 4,346; 2017: 3,858). Your stay
  distribution is right-censored at 31 December midnight.
- **Archive ends at May 2020.** There is no 2021+ historical event archive that
  this preflight found. For anything recent you must harvest live.

### 2.2 Live feed diffing — DERIVED events

The live dataset publishes **state**, not events: each bay has a `status`
(`Free` / `Occupied` / `Restricted` / `Unofficial`) and a `lastupdated`. To get
transitions you poll and diff:

- `Free → Occupied` = **ARRIVAL**
- `Occupied → Free` = **DEPARTURE**
- anything involving `Restricted` / `Unofficial` / a faulted sensor =
  **STATUS_UNKNOWN_TRANSITION**, recorded rather than guessed

`timeConfidence: DERIVED`. The true transition happened *somewhere* inside the
poll interval, and the event records that bound as `observationWindowSeconds`.

**The censoring bias you must not ignore.** A bay that is occupied *and* vacated
entirely between two polls is invisible. Short stays are therefore
**systematically undercounted**, and the bias is worse the longer your poll
interval. This is a property of the method, not a bug in the harvester, and it is
why the two modes are labelled differently in the schema. Any stay-duration model
built on live-diff data will be biased long; any model built on archive data will
be right-censored at year end. **Stratify on `timeConfidence` or your analysis
will silently mix the two.**

Practical consequence: poll as fast as the portal tolerates. Melbourne's live
dataset is near-real-time, so a 15–30 s interval is reasonable and matches
Hobart's published 15 s sensor cadence — meaning a pipeline tuned on Melbourne
transfers.

---

## 3. The publisher's own documented data defects

These are stated by the City of Melbourne in the dataset descriptions. They are
the most valuable part of this record, because they tell you exactly where real
sensor telemetry lies. The harvester **counts every one of them and flags it on
the event**; none are silently dropped or coerced.

| Defect | What the publisher says | Flag |
|---|---|---|
| **Stale restriction** | Rows where `Sign` ends in `OLD`: *"the restriction that has been captured is correct but when the data was extracted from the server the restriction had since changed"*, **or** *"the particular sensor has since been replaced."* 2014: 1,126,441 rows. 2015: 453,178. 2016: 342,475. 2017: 860. | `sign_old_suffix` |
| **Negative duration** | *"records that have a negative value in the duration in field `seconds`. This occurs due to a sensor detecting an arrival time being after the departure time."* | `negative_duration` |
| **Imputed times** | *"records where the arrival and departure times have not been recorded. If the time has not been recorded the time is calculated from midnight of the arrival day to either midnight of the departure day or to the departure time."* | `missing_times_imputed` |
| **Year-boundary exclusion** | *"there are N records where the parking event goes into [next year] and ends at midnight"* — excluded by the publisher. | `cross_year_excluded` |

Three consequences worth stating plainly:

1. **A negative duration is real evidence of a sensor fault**, not a parsing
   error on your side. Do not `abs()` it. Do not clamp it to zero. Flag it, count
   it, and exclude it from duration statistics *with the exclusion recorded*.
2. **Imputed times are not observations.** A row whose times were reconstructed
   from midnight will produce a stay duration that is an artifact of the
   calendar. Including those in a median stay time corrupts it. This is why the
   schema has `timeConfidence: IMPUTED` as a distinct value from `OBSERVED`.
3. **`Sign ... OLD` rows must not be used to validate legality.** The restriction
   attached to the event may no longer have applied. This is exactly the kind of
   source-drift problem PTE's provenance model exists to keep visible.

Additionally, for the **live** dataset, the publisher warns:

> "This dataset is updated through network relays and can be disrupted causing
> delays in data updates. Users of this data are encouraged to monitor the
> dataset's last updated timestamp (`Lastupdated` column) to check for delays."

The harvester does exactly that: it computes lag between poll time and the newest
`lastupdated`, and maps it onto the PTE source-health vocabulary
(`FRESH` / `STALE` / `DEGRADED`). This is not over-engineering — the publisher is
telling you the feed breaks.

---

## 4. Bonus finding: Melbourne documents the sign-to-curb chain

`README.md` records the central unresolved Montréal question:

> "how a geolocated sign post and its arrow code attach to the exact curb span
> governed by that sign without guessing. Until that relationship is proven from
> authoritative documentation or keys, affected curb legality remains UNKNOWN."

and the rule that would resolve it:

> "Sign-to-curb and source-to-segment attachment must be supported by
> authoritative keys, **documented municipal methodology**, or another
> reproducible rule."

**Melbourne publishes that methodology explicitly.** Four datasets, all on the
same portal, all CC-BY:

| Dataset | What it gives you |
|---|---|
| `sign-plates-located-in-each-parking-zone` | *"A sign plate is where the parking restrictions are displayed. This data set displays parking sign plates that are within a parking zone. There can be multiple restrictions per…"* |
| `parking-zones-linked-to-street-segments` | *"each parking zone and the street segment that it is linked to. The parking zone can go across multiple street segments and also one street segment can have…"* |
| `on-street-parking-bays` | Bay **polygons** — the actual curb spans |
| `on-street-car-park-bay-restrictions` | The restriction applying to each bay |

That is a documented, key-based chain:

```
sign plate  →  parking zone  →  street segment
                                      ↕
sensor  →  marker_id  →  bay polygon  →  bay_id  →  restriction
```

Documented join keys (from the portal's own schema notes):

- sensors ↔ bays join on **`marker_id`**
- sensors ↔ car-park-bay-restrictions join on **`bay_id`**
- **bays ↔ car-park-bay-restrictions do NOT currently join** — recorded so nobody
  assumes a transitive path that the publisher says does not exist

Why this matters beyond Melbourne: it is a **worked example of a municipality
solving sign-to-curb attachment with authoritative keys**. That is a template for
what to ask Montréal for, and evidence that the Montréal `UNKNOWN` is a gap in
*published documentation* rather than an inherently unsolvable problem. It also
means Melbourne can become a **legality-lane** city, not just an availability
laboratory — which `PROJECT_STATUS.md` currently lists as
*"restriction-to-current-sensor attachment remains unresolved."*

**Class: CITED** — dataset existence and descriptions verified first-hand from
portal metadata this session; the datasets themselves were not downloaded (no
outbound network in this sandbox). **Next step:** fetch each, record URL +
retrievedAt + SHA-256 + row count in `manifests/`, and confirm the joins
empirically.

---

## 5. Other real telemetry routes, ranked

| Route | Per-bay events? | Volume | Legality of reuse | Verdict |
|---|---|---|---|---|
| **Melbourne historical archives** | **Yes** | ~246M rows | CC-BY | **Use first. Best source found anywhere.** |
| **Melbourne live diffing** | Yes (derived) | ~4,600 bays, continuous | CC-BY | **Use for the live pipeline.** Censoring bias applies. |
| **Los Angeles occupancy** | Yes | large | open | Already `PROVEN` in this repo; second control case |
| **TfNSW Car Park API** | No — aggregate counts per facility | real-time + historical | open, key required | Good for a *supported* API integration test; not per-bay |
| **Geelong LoRa sensors** | Yes | small | other-open | Simplest open smoke test |
| **Your own users (crowdsourced)** | Yes | grows with users | **you own it** | The only route that scales to Hobart without consent. See §6. |
| **OpenStreetMap GPS traces** | Derivable | large | ODbL | **Weak — see §5.1** |
| Hobart `parkmyride.au` | Yes | ~2,000 bays @15 s | **written consent required**, WAF-blocked | Blocked. Partnership conversation, not a data task. |

### 5.1 Why OSM GPS traces are weaker than they look

`GET https://api.openstreetmap.org/api/0.6/trackpoints?bbox=left,bottom,right,top&page=N`
returns 5,000 public trackpoints per page as GPX, with no authentication, and you
can point it at Hobart directly. That sounds ideal for deriving parking dwell
events from real movement.

It isn't, for this purpose. The OSM API documentation states:

> "In violation of the GPX standard when downloading public GPX traces through
> the API, all waypoints of **non-trackable** traces are **randomized (or rather
> sorted by lat/lon)** and delivered as one trackSegment **for privacy reasons**."

Dwell detection depends entirely on **temporal ordering** — speed below a
threshold for a sustained period. If the waypoints have been sorted by
coordinate, the ordering is destroyed and every derived "parking event" is
fiction. Only `trackable` / `identifiable` traces preserve order, and you cannot
tell which is which from the bulk endpoint. The API also deliberately omits user
IDs, so you cannot even group points into trips reliably.

**Verdict: UNKNOWN, leaning do-not-use for dwell detection.** Fine for coarse
density-of-movement heatmaps. Not fine for arrival/departure telemetry. If you
want real GPS-derived parking events, use a research corpus with intact ordering
(e.g. GeoLife or T-Drive) and accept that it is not Hobart.

---

## 6. The crowdsourced route, and how to bootstrap it honestly

A "Waze for parking" does not get its telemetry from a city. Waze gets it from
every client being a probe. Applied to parking, the event you want is a **dwell**:

```
speed < ~1.5 m/s   AND   displacement < ~15 m   AND   duration > ~3 min
   → ARRIVAL at the start of the dwell
   → DEPARTURE at the end of the dwell
   → duration = departure − arrival
```

That is the same shape as everything else in this document, and
`schemas/parking-telemetry-event-schema.json` already carries `sourceMode:
"crowdsourced"` plus `deviceId` for it.

The honest problem is **cold start**: at zero users the crowdsourced layer is
empty, and it is the only layer that works in Hobart without consent. Three
things make the gap survivable:

1. **Calibrate the simulator on real statistics.** This is the actual answer to
   *"how do I generate enough data."* Run `telemetry_harvester.py archive` over a
   Melbourne year, take the resulting stay-duration percentiles, hour-of-day
   arrival curves, overstay rates and defect rates, and drive
   `tools/realtime-sim/sim_feed.py` from those numbers instead of its current
   hand-written curve. You then have **unlimited synthetic volume whose
   statistics are real**, and you can say exactly which archive they came from.
   Synthetic data with a cited real distribution is defensible; synthetic data
   with an invented one is not.
2. **Label the phases in the GPS rig.** `tools/realtime-sim/gps_replay.py`
   already emits `driving` / `searching` / `junction` / `manoeuvre` / `parked`
   with `trueLat`/`trueLon` ground truth, so a dwell detector can be built and
   **scored against known truth** before any real user data exists.
3. **Be explicit in the UI about which layer is which.** A Melbourne-calibrated
   synthetic estimate and a live sensor observation must not render identically.
   That is the same refusal of false certainty as `UNKNOWN`.

Privacy note: dwell events are derived from an individual's movements. Persist a
pseudonymous rotating device ID, not a stable one; aggregate at kerb-span level;
and do not retain raw traces longer than needed. The schema flags `deviceId` for
exactly this reason.

---

## 7. What the harvester does

`tools/telemetry/telemetry_harvester.py` — stdlib only, Python 3.8+.

```bash
# which API shape actually works on this portal? (report before you harvest)
python3 telemetry_harvester.py probe --base https://data.melbourne.vic.gov.au \
    --dataset on-street-parking-bay-sensors

# real near-live transitions: poll + diff
python3 telemetry_harvester.py live --interval 20 --minutes 60 --limit 5000 \
    --out out/live

# ~14.2M real 2020 parking events, streamed; nothing large retained
python3 telemetry_harvester.py archive --year 2020-jan-may \
    --max-emit 250000 --out out/archive
```

Design decisions that matter:

- **Storage policy honoured.** Archives download to a temp dir **outside the
  repo**, are SHA-256 hashed while streaming, and are **deleted** unless
  `--keep-download`. Only bounded derived artifacts are written. This is the
  `README.md` rule "URL + retrievedAt + bytes + SHA-256" enforced in code rather
  than in prose — which matters because a 1.56 GB 2014 archive would otherwise
  wreck a storage-constrained machine.
- **Statistics over the whole stream, sample in the file.** Aggregates
  (percentiles, hour-of-day, weekday, restriction, street, defect counts) are
  computed across **every** row; only `--max-emit` rows are written to JSONL, and
  the retained sample is **reservoir-sampled** so it is representative of the
  whole stream rather than being the first N rows.
- **Tolerant column resolution.** Municipal schemas drift between years and
  portals. Columns are matched through an alias table, and the tool **prints what
  it mapped and what it could not** instead of failing. First run on a new year
  reveals that year's real schema.
- **Endpoint auto-discovery.** `probe` tries five API shapes (Opendatasoft
  explore v2.1, v2 records, records v1.0, v2 exports, Socrata SODA v2.0) and
  reports which work. Necessary because this preflight found Melbourne had
  **migrated off Socrata** — the old `/resource/vh2v-4nfs.json` endpoint returns
  404 today, so any code hardcoding it is already broken.
- **Delays and delimiters handled.** Auto-falls back to `;` or tab when the
  header indicates it (a known issue with Montréal snapshots in this repo).
- **Never guesses.** Unparseable timestamps become `timeConfidence:
  UNPARSEABLE`; a status that is neither free nor occupied becomes
  `STATUS_UNKNOWN_TRANSITION`; rows with no time information at all are skipped
  and the skip is counted.

### Verified in this session

Ran against a purpose-built fixture reproducing Melbourne's documented column
names and defect rates (24,000 rows):

- all 16 columns mapped correctly; only genuinely-absent ones reported unmapped
- injected defects recovered exactly: `negative_duration` 649 (expected
  ⌊24000/37⌋ = 648), `missing_times_imputed` 453 (expected ⌊24000/53⌋ = 453)
- stay distribution recovered the generator's lognormal: median 9.08 min vs
  e^6.3 s = 9.07 min expected; time range 140.68 days
- `.zip` streamed and hashed without extraction to disk; `.gz` supported
- semicolon-delimited variant auto-detected and parsed
- SHA-256 and byte count recorded in a manifest entry

Ran `probe` and `live` against a mock Opendatasoft portal:

- `probe` identified 3 of 5 endpoint shapes as live, printed field lists and the
  resolved column map, and wrote a recommendation
- `live` ran 9 polls over 120 bays and derived **66 real transition events**
  (ARRIVAL / DEPARTURE), with `observationWindowSeconds: 2.0` and
  `timeConfidence: DERIVED` on each
- two bays forced to `Restricted` / `Unofficial` correctly counted as `unk=2`
  and never coerced to FREE or OCCUPIED
- source-health computed `FRESH` from zero lag; error counter empty

**Not verified:** the real Melbourne endpoints. This sandbox's bash has no
outbound network and the page fetcher became unreliable for
`data.melbourne.vic.gov.au` mid-session. Run `probe` from a normal machine
first — that is what it is for.

---

## 8. Recommended sequence

1. **`probe` from a normal network.** Confirm which live endpoint works today and
   record the field list. 5 minutes. Removes all guessing.
2. **`archive --year 2020-jan-may`.** Smallest real archive (258 MB, 14.2M rows).
   Stream it, keep the stats, delete the download. You now have real stay-duration
   percentiles, real hour-of-day arrival curves, real overstay rates and real
   defect rates.
3. **Calibrate `tools/realtime-sim/sim_feed.py` from step 2's statistics.**
   Replace the hand-written demand curve with measured ones. Cite the archive
   SHA-256 in the simulator config. This is the honest version of "generate
   enough data."
4. **`live --interval 20 --minutes 1440`.** A full day of real derived
   transitions, to compare against step 2's observed distribution and *measure
   the censoring bias* rather than assuming it.
5. **Fetch the four §4 datasets** and test the `marker_id` / `bay_id` joins. This
   is the highest-value legality-lane work available and it directly informs what
   to request from Montréal.
6. **Then, and only then, approach Hobart** — with a working pipeline, measured
   statistics, and a concrete ask.

---

## 9. Provenance

- Verified first-hand this session: City of Melbourne portal dataset metadata for
  `on-street-parking-bay-sensors`, `on-street-parking-bays`,
  `on-street-car-parking-sensor-data-{2014,2015,2016,2017}`, publisher defect
  notes and archive sizes/row counts; `data.gov.au` listings for the 2015, 2018,
  2019 and 2020 (Jan–May) archives including two direct `opendatasoft-s3`
  download URLs; the OSM API v0.6 `trackpoints` specification including the
  non-trackable randomisation caveat.
- Verified first-hand as **broken**: `data.melbourne.vic.gov.au/resource/vh2v-4nfs.json`
  → HTTP 404 (Socrata decommissioned; portal migrated to Opendatasoft).
- Not fetched (no outbound network): all archive bodies, all live record
  payloads.
- Machine-readable references: `manifests/real-parking-telemetry-manifest.json`.
- Everything here is **CITED** unless marked as verified by direct fetch.
