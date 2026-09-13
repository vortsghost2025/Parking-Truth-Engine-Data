# Real Camden Run — PTE-TEL-004 (pre-registration)

**Record ID:** PTE-TEL-004
**Snapshot date:** 2026-09-13
**Type:** Pre-registration. Written **before** any Camden row was read.
**Freezes:** [`CAMDEN-SIGNAL-HARNESS.md`](CAMDEN-SIGNAL-HARNESS.md) (PTE-TEL-003) at commit `a602244`
**Freeze record:** [`manifests/camden-harness-freeze.json`](../manifests/camden-harness-freeze.json)
**Upstream:** PTE-TEL-002 §5 action 2 → PTE-TEL-003 (harness) → this record (the run)
**Lane:** AVAILABILITY (research). `legalityClaimed: false`.

---

## 0. Status

**Not run.** This sandbox has no outbound network except the `fetch_page` and
`web_search` tools, so the two OGL downloads must happen on a machine that has
one. What *was* done this turn is retrieve Camden's own **dataset metadata** for
both inputs — which turned out to change the run materially.

Four defects were found in the plan, all from publisher metadata, all before a
single data row was read. They are pre-registered in §4 with their evidence.

**The harness is frozen at `a602244`**, verified with `sha256sum -c`, and
`DEFAULT_THRESHOLDS` is snapshotted in the freeze manifest. Nothing about the
verdict logic may change after a result is seen.

---

## 1. Why "run it unchanged" needs one qualification

The instruction was to run PTE-TEL-003 unchanged and not to tune thresholds after
seeing the result. That instruction is right, and the freeze enforces it. But
metadata retrieval showed the harness **cannot ingest the real files as-is**, and
that one of the five fail criteria would be **silently inoperative**.

So there is a distinction that has to be drawn explicitly, because the whole
value of the experiment depends on it:

> **A correction derived from publisher metadata before any data is read is
> pre-registration. A correction derived from a result already seen is tuning.
> Only the first is permitted.**

Everything in §4 is the first kind: it is dated today, it cites Camden's own
metadata, and it is committed **before** the download. If any of those four items
were changed *after* a verdict came back, it would be tuning and the run would be
worthless.

Thresholds are not among the four. **No threshold changes, before or after.**

---

## 2. Verified inputs

### PCN series — `4k7m-4gkk`

*"Parking Services Penalty Charge Notices Current Financial Year"*, London Borough
of Camden, `licenseId: UK_OGLV3.0`, `provenance: official`, updated daily
(`rowsUpdatedAt` = 2026-09-13 01:49 UTC).

**495,814 rows**, spanning **2025-04-01T01:09:00 → 2026-09-10T20:51:54** — 527
days, ~17.3 months, ~941 rows/day. **Timestamps carry a time component**, so the
unknown-hour path should not be exercised by this dataset.

Columns verified from publisher metadata (position · name · `fieldName` · notable
values):

| # | Name | fieldName | Verified content |
|---|---|---|---|
| 1 | Contravention Date | `contravention_date` | calendar_date, 495,814 non-null, **0 null** |
| 2 | Contravention In Last 7 Days | `contravention_in_last_7_days` | No 491,517 · Yes 4,297 |
| 3 | Ticket Type | `ticket_type` | **O/S TMA 312,203 · MTC 170,747 · BUS 7,032 · CCTV TMA 5,194 · VDA 491 · PFS 147** |
| 4 | Ticket Description | `ticket_description` | On Street / Moving Traffic / Bus Lane / CCTV Parking Contravention · Vehicle Driven Away · Prevented From Serving |
| 5 | Contravention Code | `contravention_code` | **33H 76,882 · 52M 73,148 · 12R 72,219 · 11 68,427** · … |
| 9 | *(name not retrieved)* | — | CPZ-style values: CA-F 56,191 · CA-B 39,572 · CA-H 29,140 · CA-G 25,591 · CA-Q 25,390 · +12 more |
| 10 | Street | `street` | **UPPERCASE, junction-qualified, postcode-suffixed** — see §3 |
| 11 | Vehicle Category | `vehicle_category` | 1n/A 182,622 · (Private) Car 127,283 · 5 Door Hatchback 46,081 · Van 46,079 · … |
| 12 | Vehicle Removed | `vehicle_removed` | No 494,604 · Yes 1,210 |
| 13 | Status Of Case | `status_of_case` | Paid/Closed 360,282 · Outstanding 92,183 · Cancelled 39,930 · WrittenOff 3,419 |
| 14 | Charging Band Description | `charging_band_description` | Band A (Higher) 385,789 · Band A (Lower) 109,841 · Band B (Higher) 152 · "d" 19 · Band B (Lower) 10 · "F" 3 |
| 15 | Civil Enforcement Officer Error | `civil_enforcement_officer_error` | No 494,272 · Yes 1,542 |
| 16 | Penalty Charge Notice Cancelled | `penalty_charge_notice_cancelled` | No 455,884 · Yes 39,930 |
| 17 | Penalty Charge Notice Written Off | `penalty_charge_notice_written_off` | No 492,395 · Yes 3,419 |
| 18 | Cancellation Reason | `cancellation_reason` | 43,340 non-null, **452,474 null** · Liability Waived 28,539 · Mitigation 5,565 · … |
| 19 | Cancellation Reason Description | `cancellation_reason_description` | 43,340 non-null |
| 20 | Foreign Vehicle | `foreign_vehicle` | No 491,994 · Yes 3,820 |
| 21 | Country Vehicle Registered To | `country_vehicle_registered_to` | United Kingdom 491,994 · (Other) 3,798 |
| 22 | Has Appeal | `has_appeal` | No 493,806 · Yes 2,008 |
| 23 | Formal Representation | `formal_representation` | No 464,094 · Yes 31,720 |
| 24 | Ward Code | `ward_code` | **300,618 non-null, 195,196 null (39.4%)** · ONS codes E050136xx |
| 25 | Ward Name | `ward_name` | 300,618 non-null · Holborn and Covent Garden 53,164 · Bloomsbury 51,900 · Camden Town 27,600 · +17 more |
| 26–27 | Easting / Northing | `easting` / `northing` | EPSG:27700, **304,079 non-null, 191,735 null (38.7%)** |
| 28–29 | Longitude / Latitude | `longitude` / `latitude` | EPSG:4326, same null pattern |
| 30 | Location | `location` | point type, concatenation of lon/lat |

**Not retrieved:** positions 6, 7, 8 and 31+. The `fetch_page` proxy returned
`SignatureDoesNotMatch` on the remaining chunks, so **`Spatial Accuracy` itself was
not directly confirmed** — though the dataset description documents it explicitly
and the ward/coordinate descriptions reference *"the Civil Enforcement Officer
location, fixed CCTV location or **mobile CCTV** location"*.

### Bay inventory — `7hiv-3r9k` (see correction C1)

*"Parking Bays"*, `assetType: dataset`, `displayType: table`, `UK_OGLV3.0`,
`provenance: official`, 15,107 downloads, updated daily, `EPSG:27700`.

| # | Name | fieldName | Publisher description |
|---|---|---|---|
| 1 | Restriction Type | `restriction_type` | type of vehicle or permit accepted in this bay |
| 2 | **Parking Spaces** | `parking_spaces` | number of spaces in this bay — **"Known issues with echelon shaped parking bays"** |
| 3 | Times Of Operation | `times_of_operation` | days and hours the restriction operates |
| 4 | Maximum Stay | `maximum_stay` | length of time allowed |
| 5 | Tariff | `tariff` | cost of parking in this bay |
| 6 | **Cashless Identifier** | `cashless_identifier` | **"Location ID for cashless payment"** — see §6 |
| 7 | Nearest Machine | `nearest_machine` | — |
| 8 | Road Name | `road_name` | road this bay is on |
| 9 | Postcode | `postcode` | nearest OS Code-Point Open postcode |
| 10 | Controlled Parking Zone | `controlled_parking_zone` | defined areas of restricted parking |
| 11 | Valid Parking Permits | `valid_parking_permits` | — |
| 12 | **Parking Bay Length Metres** | `parking_bay_length_metres` | length with a nominal 4 m removed for end markings — **"Known issues with echelon shaped parking bays"** |
| 13 | Disclaimer | `disclaimer` | — |
| 14–15 | Easting / Northing | `easting` / `northing` | **"X coordinate along the line of a parking bay — not the centre of a parking bay"** |

Both capacity fields carry the same publisher-documented quality warning about
**echelon-shaped bays**. That must travel with every capacity figure into the
report: the denominator is approximate in a way the publisher has flagged, not
merely approximate in principle.

### `t4s2-xa5a` is a map, not a dataset

`assetType: "map"`, `displayType: "visualization_canvas_map"`, and its
`columns` array is **empty**. Its `modifyingViewUid` and its map series'
`dataSource.datasetUid` both point at `7hiv-3r9k`. It is a visualisation *over*
the bay dataset.

---

## 3. Three things in the real data that the fixture did not model

**Street strings are not clean.** The PCN `Street` column is uppercase, carries
postcode suffixes and frequently carries a junction qualifier:

```
TOTTENHAM COURT ROAD W1 BY JUNCTION WITH CHENIES STREET       27,940
TOTTENHAM COURT ROAD W1 BY JUNCTION WITH GREAT RUSSELL STREET 21,819
TOTTENHAM COURT ROAD W1 BY JUNCTION WITH HOWLAND STREET       19,079
HOLMES ROAD NW5                                               11,256
FROGNAL (CA-B) NW3                                             4,593
MAPLE STREET W1                                                9,141
```

`street_key()` lowercases and strips punctuation but does **not** strip `BY
JUNCTION WITH …`, postcode suffixes, or embedded CPZ codes. Against a bay
`road_name` like `Tottenham Court Road`, most of these will not match. The five
Tottenham Court Road junction variants alone are **75,584 rows — 15.2% of the
entire dataset** — and they would fragment across five unmatched keys.

Consequence: **the CPZ join is the reliable level, not the street join.** Both
datasets carry a CPZ-style field and, if the coding agrees, CPZ-level aggregation
avoids the string problem entirely. A street-level run should still be produced,
but its capacity-coverage figure must be read as a *matching* result rather than a
data-availability result. This is exactly what F3 measures, and the run report
must say which of the two it is.

**Coordinate duplication is a camera signature.** Easting `530066` appears on
**4,958** rows; longitude `-0.126582` on **4,913**. Thousands of PCNs sharing one
exact coordinate is a fixed installation, not a patrolled kerb. That is a
deployment diagnostic available *without* contravention-code semantics — but it
requires code, so it is **not** part of the frozen run. It is recorded here as the
first candidate for a pre-registered revision *after* the frozen result exists.

**38.7% of rows have no coordinates and 39.4% have no ward.** That is not
missingness to fill; it is a stratum. It almost certainly corresponds to the
location types the description mentions, and it means any diagnostic that needs a
coordinate covers at most 61.3% of the series.

---

## 4. Pre-registered corrections

Four items, each with its evidence, all committed before any download. Full
machine-readable form in the freeze manifest.

### C1 — the bay dataset is `7hiv-3r9k`, not `t4s2-xa5a`

`t4s2-xa5a` is a map view with an empty `columns` array. Download it expecting
tabular bay data and there is nothing to read. **Use `7hiv-3r9k`.** No code change.

### C2 — two real bay column names do not match the adapter candidates

`Parking Spaces` (`parking_spaces`) and `Parking Bay Length Metres`
(`parking_bay_length_metres`) are not in `BAY_FIELD_CANDIDATES`. Candidate matching
is exact after cleaning, and `"parking spaces"` is not equal to `"spaces"`.

**This one is severe and silent.** Both fields are *optional*, so the adapter
would not raise. Every bay would load with `spaceCount = None`, capacity would be
unknown everywhere, `streetCountWithIndex` would be **0**, and F3 would fire as
"insufficient capacity coverage". The run would report a coverage FAIL **caused by
our own adapter**, and the natural reading — "Camden doesn't publish usable
capacity" — would be exactly wrong.

**Fix without touching code:** supply `--field-map`. That is preferred, because it
is recorded in the report at `inputs.fieldMapOverrides` and leaves the frozen
binaries bit-identical.

```json
{ "bay-map": { "spaceCount": "Parking Spaces",
               "bayLengthM": "Parking Bay Length Metres",
               "cpz":        "Controlled Parking Zone" } }
```

### C3 — 35.9% of the PCN dataset is not parking

| `ticket_type` | `ticket_description` | Rows | Share |
|---|---|---|---|
| O/S TMA | On Street Contravention | 312,203 | 63.0% |
| CCTV TMA | CCTV Parking Contravention | 5,194 | 1.0% |
| **MTC** | **Moving Traffic Contravention** | **170,747** | **34.4%** |
| **BUS** | **Bus Lane Contravention** | **7,032** | **1.4%** |
| VDA | Vehicle Driven Away | 491 | 0.1% |
| PFS | Prevented From Serving | 147 | 0.03% |

Moving-traffic and bus-lane contraventions are **not parking events**. Including
them attributes a bus-lane camera's throughput to parking pressure on that street —
and the street table in §3 shows the top locations are junction-qualified camera
sites, which is consistent with moving-traffic enforcement.

**Pre-declared inclusion filter:** `ticket_type IN ('O/S TMA', 'CCTV TMA')` →
**317,397 rows (64.0%)**. VDA and PFS (638 rows) are **excluded and reported as
excluded**, not silently dropped. Declared here, before any data was read.

### C4 — F1 would be silently inoperative, and that is the dangerous one

`contravention_code` values are London numeric codes with suffixes: `33H`, `52M`,
`12R`, `11`. `classify_contravention()` matches **keywords** in the code plus its
description. Numeric codes contain no keywords, and no contravention-description
column was confirmed anywhere in the retrieved metadata.

So on real data every row classifies `UNCLASSIFIED` → `prohibitionShareOverall` is
`None` → indicator I2 can never trigger → **F1 can never fire**. And
`decide_verdict()` treats a non-firing criterion as not-triggered.

**The harness could therefore return PASS or PARTIAL while the single most
important confound — enforcement deployment versus parking demand — was never
tested.** That is a false negative on the criterion that matters most, and it is
worse than a FAIL, because a FAIL would at least be honest.

**Pre-registered handling, in order of preference:**

1. Source an **authoritative London Councils contravention-code → class mapping**
   and supply it as *data*, not as keywords. Then F1 is evaluable.
2. If no authoritative mapping can be sourced, declare **F1 UNEVALUABLE** on this
   dataset, **cap the verdict at PARTIAL**, and record the reason in the report.

What must not happen is a PASS that quietly skipped F1.

---

## 5. Unverified at freeze time

Recorded so nobody mistakes an assumption for a finding:

- **`Spatial Accuracy` was not directly confirmed.** The dataset description
  documents it, but metadata chunks covering positions 31+ could not be retrieved
  (`SignatureDoesNotMatch` from the fetch proxy). Its exact column name and value
  set are unknown.
- **A `MOBILE CCTV` stratum may exist.** The ward and coordinate descriptions say
  location is *"based on the Civil Enforcement Officer location, fixed CCTV
  location or **mobile CCTV** location"* — three types. The harness models two
  plus unknown. If a mobile-CCTV value appears it will land in `UNKNOWN_OTHER` and
  be surfaced as `UNRECOGNISED`, which is the designed behaviour, but it means the
  stratification is incomplete rather than wrong.
- PCN columns at positions 6, 7, 8.
- The exact PCN column **name** for CPZ (position 9 carries the `CA-*` values).
- **Whether bay `Controlled Parking Zone` uses the same `CA-*` coding as the PCN
  dataset.** If yes, CPZ is the reliable join level. If no, both joins degrade.
  This is the first thing to check after download.
- Bay columns at positions 16+ (likely `Longitude`, `Latitude`, `WKT`).
- Whether a `Parking Restriction` column exists in the PCN dataset.

---

## 6. A strategic find that was not being looked for

`7hiv-3r9k` position 6 is **`Cashless Identifier`** (`cashless_identifier`),
described by Camden as *"**Location ID for cashless payment**"*.

That is the join key to RingGo / MiPermit session data — PTE-TEL-002 class A — and
it joins **on an identifier, not on a street string**. Every street-matching
problem in §3 disappears if sessions can be attached to bays by cashless location
ID, which then carries capacity, restriction type, maximum stay, tariff and CPZ
with it.

This is the strongest concrete bridge found so far between the enforcement-exhaust
path and the payment-session path, and it came from Camden's own bay inventory
rather than from any negotiation with a payment provider. **It does not change the
frozen run.** It changes what is worth asking for next.

---

## 7. Run protocol

Execute in this order. Do not skip step 2, and do not proceed past a step that
fails.

```bash
# 0. Confirm the harness is still frozen
cd tools/camden && sha256sum -c FREEZE.sha256        # all 9 must say OK

# 1. Download both OGL inputs from opendata.camden.gov.uk
#      7hiv-3r9k  "Parking Bays"                                   <- NOT t4s2-xa5a
#      4k7m-4gkk  "Parking Services PCNs Current Financial Year"
#    Record the sha256 of each downloaded file before doing anything else.

# 2. FIELD RESOLVER FIRST. Inspect everything before running the test.
python3 camden_sources.py --bays bays.csv --pcn pcn.csv --report resolve.json
#    Read: fieldMap, ambiguousFieldMatches, unresolvedOptionalFields,
#          unconsumedSourceFields, spatialAccuracyValuesObserved
#    Confirm C1/C2 are resolved and check the §5 unknowns against reality.

# 3. Apply the C3 filter, recording the row counts before and after.
# 4. Apply the C2 field map.
# 5. Run CPZ level first (the reliable join), then street level as a diagnostic.
python3 camden_signal_test.py --bays bays.csv --pcn pcn.csv \
        --field-map fields.camden.json --level CPZ    --out report-cpz.json
python3 camden_signal_test.py --bays bays.csv --pcn pcn.csv \
        --field-map fields.camden.json --level STREET --out report-street.json

# 6. Report the verdict. No threshold changes. No re-running with different
#    flags until a preferred answer appears.
```

**No independent proxy has been sourced.** Expect the verdict to be capped at
**PARTIAL** for that reason alone, before C4 is even considered. That is the
correct outcome and should be reported as such, not as a disappointment.

---

## 8. What each verdict would mean

| Verdict | Reading | Consequence |
|---|---|---|
| **FAIL** | PCN exhaust is too enforcement-biased, too poorly matched, or too thin to build on | Cheap, useful. **Drop PTE-TEL-002 class B** and stop treating enforcement byproducts as a demand signal |
| **PARTIAL** | Signal is stable and reproducible but unvalidated | Enough to justify pursuing payment-session access — and `cashless_identifier` (§6) says that path has a clean join key waiting |
| **PASS** | Administrative exhaust carries a pressure signal agreeing with something independent | Strongest available evidence for historical inference from administrative exhaust instead of waiting for cities to install sensors |

Given C4 and the absence of a proxy, **PASS is not reachable in this run**, and
saying so in advance is the point of pre-registering. The realistic outcomes are
FAIL or PARTIAL, and both are informative.

---

## 9. The line to hold

Availability-adjacent research lane. `legalityClaimed: false` throughout. The
legality kernel is not modified, imported or consulted; PTE-007 and PTE-008
evidence is untouched; the camera lane stays frozen — this consumes other people's
published enforcement records and operates no lens. No individual-space occupancy
is inferred. Nothing is deployed, nothing is merged to main, no existing data is
overwritten.

**A PCN says a car was there. It does not say a car may be there.**
