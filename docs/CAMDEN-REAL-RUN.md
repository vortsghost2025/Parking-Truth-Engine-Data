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

## 4A. C4 executed — and it falsified the C4 plan

C4 was approved first because it is cheap and authoritative. It was executed
before any Camden row was read, and it produced a result that changes the plan.
Everything below is pre-registration: no Camden data has been downloaded.

### The authoritative source

`sources/camden/london-councils-contravention-codes-v7.0.json`
(sha256 `539c5413ff430eb4ec9756fa27ea020d02ca0bca648ef14f20d03c3c1a892a80`)

London Councils, *Penalty Charge Notices: Contravention Code List*, document
footer **PCN Codes v7.0, effective 31 May 2022**, retrieved 2026-09-13 from the
2025-03 webpage-version PDF. 91 codes transcribed verbatim with their general
suffixes, `Diff. level` and section (on-street / off-street).

Two things the source gives us that we were not expecting:

1. **Corroborating evidence for C3 — not a classifier.** All 18 moving-traffic
   and bus-lane codes carry `Diff. level = n/a`, so the implication
   *moving-traffic ⟹ `n/a`* holds without exception (recall 1.00). The converse
   does **not**: 25 codes carry `n/a`, and 7 of them are not moving traffic —
   codes **64, 65, 66 are parking** contraventions (verge, public-land and
   footway parking; Essex and Exeter only) and **13, 17, 39, 77 are reserved** for
   TfL LEZ/ULEZ, road-user charging and DVLA use. Precision is therefore 18/25 =
   0.72, and `n/a` is necessary but **not sufficient** for non-parking.

   An earlier draft of this record said `n/a` marked "*exactly* the
   moving-traffic and bus-lane codes". That was too strong and is corrected here:
   `Diff. level` corroborates C3 from a source with no connection to Camden's own
   `ticket_type` field, and it is genuinely useful for that, but it must not be
   used as the discriminator. Class is declared from description content and only
   cross-checked against `Diff. level`.
2. **Suffix `j` means camera enforcement.** "Suffix 'j' identifies a
   contravention that can be used on highways other than red routes using CCTV."
   A suffix is therefore an authoritative *deployment* marker carried in the code
   itself. The frozen harness does not read it and under the freeze protocol must
   not be changed to. It is recorded as the highest-value candidate for a future
   amendment, because it would let F1 test deployment directly instead of
   inferring it from code mix.

### The declaration is ours, not the publisher's

London Councils says what a contravention *means*. It publishes no
"parking-pressure class" taxonomy and none is implied by the list. Which codes
count as turnover/payment-related versus prohibition/entitlement-related for F1
is our judgement, declared per code with a rationale and frozen in the artifact:

| declared class | codes | maps to harness label |
| --- | --- | --- |
| `TURNOVER_PAYMENT` | 18 | `TURNOVER_TYPE` |
| `PROHIBITION_ENTITLEMENT` | 46 | `PROHIBITION_TYPE` |
| `MIXED` | 2 (codes 12, 19) | `AMBIGUOUS` |
| `NOT_PARKING` | 18 | excluded before classification (C3) |
| `RESERVED` | 7 | excluded before classification |

Codes 12 and 19 are declared `MIXED` because the official text of each combines
an entitlement violation with a payment or expiry violation in a single code.
Forcing them to one side would invent a distinction the source does not make.

### Suffix resolution had to be code-aware

The same letter means different things on different codes. Resolving from the
general legend alone reports **`33H` as "hospital bay"** when the source's
code-specific list says **"local buses and cycles only"**, and **`52M` as
"parking meter"** when it means **"motor vehicles"**. `CODE_SPECIFIC_SUFFIXES`
overrides the general legend. With that fixed, Camden's two highest-volume codes
are authoritatively a bus/cycle route restriction and a vehicle-type prohibition
— both moving traffic, consistent with `ticket_type = MTC` on 170,747 rows.
33H + 52M account for 150,030 of the 177,779 moving-traffic and bus-lane rows.
Two independent sources agree.

### The audit result: the C4 input-data route does not work

`sources/camden/code-classification-audit.json` runs the **frozen, unmodified**
`classify_contravention()` on every authoritative description and compares it
against the declaration. The frozen harness is bit-identical to `a602244`
(`sha256sum -c FREEZE.sha256` → 9/9 OK, self-test still 14/14).

**Agreement: 42 of 66 classified codes = 0.636.** 24 codes disagree.

| declared class | recognised | rate |
| --- | --- | --- |
| `TURNOVER_TYPE` | 9 of 18 | **0.500** |
| `PROHIBITION_TYPE` | 31 of 46 | 0.674 |
| `AMBIGUOUS` | 2 of 2 | 1.000 |

Every failure collapses into `AMBIGUOUS` or `UNCLASSIFIED`. **No code is ever
inverted** from one substantive class into the other — the classifier destroys
information rather than swapping it. But it destroys it *asymmetrically*, and
that is what makes it consequential.

Four mechanisms, all evidenced per code in the audit:

- **Substring matching.** `classify_contravention()` tests `hint in text` with no
  word boundary. `"permit"` is a substring of `"permitted"`, so code 30 *"Parked
  for longer than permitted"* — the cleanest maximum-stay code in the list —
  fires the prohibition hint alongside `"longer than"` and returns `AMBIGUOUS`.
  Codes 09 and 80 identically.
- **Overbroad hint `"bay"`.** Nearly every parking contravention concerns a bay
  or parking place, so it contaminates turnover codes such as 04 into
  `AMBIGUOUS` for no semantic reason.
- **Vocabulary gap.** The hints were written from paraphrase, not authoritative
  wording. The hint is `"expired"`; code 05 says *"expiry"*. Code 05 *"Parked
  after the expiry of paid for time"* — the purest overstay contravention in the
  list — returns `UNCLASSIFIED`. So do codes 22, 35, 41, 42, 43, 45, 49, 56, 57,
  62, 64, 65, 82, 90, 91, 93, 95.
- **Circular validation — the root cause.** The 14/14 green self-test validated
  the classifier against fixture text generated by `make_camden_fixture.py`,
  which used the classifier's own vocabulary. The fixture could not have exposed
  these failures because it was written in the language the classifier already
  understood. This is a methodological defect in PTE-TEL-003, found by C4, and
  it is recorded here rather than buried.

### Direction of the bias, computed not assumed

F1 indicator I2 fires when `prohibitionShareOverall > 0.50`. That share is
`PROHIBITION_TYPE / total over ALL classes`, so reclassifying rows into
`AMBIGUOUS`/`UNCLASSIFIED` leaves the denominator unchanged while shrinking both
numerators — and it shrinks turnover harder (0.500) than prohibition (0.674).
The net effect is an **upward** bias on `prohibitionShareOverall`:

| true prohibition share | as reported | bias | false F1 trigger? |
| --- | --- | --- | --- |
| 0.10 | 0.130 | +0.030 | no |
| 0.25 | 0.310 | +0.060 | no |
| 0.35 | 0.421 | +0.071 | no |
| 0.40 | 0.473 | +0.073 | no |
| **0.45** | **0.524** | **+0.074** | **YES** |
| 0.50 | 0.574 | +0.074 | already above |
| 0.60 | 0.669 | +0.069 | — |

The bias is large enough to cross the frozen threshold unaided. A false F1
trigger produces a FAIL verdict whose stated meaning is *"the signal is
dominated by enforcement deployment, not parking demand"* — and the
pre-registered reading of a Camden FAIL is to drop the PCN-exhaust source class
as too enforcement-biased. So this defect can manufacture the specific evidence
that would cause the project to abandon the approach, for a reason that is an
artefact of a keyword list. That is a strategic-grade false negative.

An earlier draft of this finding claimed the bias ran the other way. It does not;
the arithmetic in `_contravention_mix()` was checked before the claim was
written, and the claim was corrected.

### Why this cannot be fixed through input data alone

Protocol rule 3 permits changes only through `--field-map` and input data. The
only input-data lever is the description column. Making a weak keyword classifier
reproduce a correct table-driven answer would require writing text engineered to
trip specific keywords — description text that is *not* the authoritative
description. That fabricates exactly the provenance the harness exists to
preserve and makes the result uninterpretable. It is worse than amending the
classifier.

**C4 is therefore recorded as executed and its planned remedy as falsified.** The
run is blocked pending a decision on amendment C4A, which must be committed
before any Camden row is read in order to remain pre-registration.

## 4B. Amendment C4A — authoritative classification, committed before any row was read

C4A executes C4's own pre-registered option (a): *"supply an authoritative London
Councils contravention-code to class mapping **as data, not as keywords**."* It
was justified by a defect measured against an external authoritative codebook
**before any Camden row was read**, so it is pre-registration, not post-hoc
tuning. The pressure-class declaration itself was **not** revised: the artifact
sha256 `539c5413ff430eb4ec9756fa27ea020d02ca0bca648ef14f20d03c3c1a892a80` is
identical before and after C4A. **The code changed to match the declaration, not
the declaration to match the code.**

### What changed

Classification is now a lookup of the base code against the frozen artifact:

| declared class | harness label |
| --- | --- |
| `TURNOVER_PAYMENT` | `TURNOVER_TYPE` |
| `PROHIBITION_ENTITLEMENT` | `PROHIBITION_TYPE` |
| `MIXED` | `AMBIGUOUS` |
| `NOT_PARKING` / `RESERVED` | excluded per the already-declared C3 policy |

`TURNOVER_CODE_HINTS` and `PROHIBITION_CODE_HINTS` are retained **byte-for-byte**
and remain reachable only as an explicit fallback for codes genuinely absent from
the artifact. Every fallback is counted and the offending raw codes are named in
the report — nothing degrades silently. A missing artifact **raises**; an explicit
`--code-map` path that does not exist raises rather than falling through to the
repo default, because a typo must not silently load a different artifact.

### What did not change

| file | status |
| --- | --- |
| `camden_pressure.py` | **bit-identical to `a602244`** — index math, `SEMANTIC_CONTRACT`, forbidden-key guard |
| `camden_aggregate.py` | **bit-identical to `a602244`** |
| `camden_sources.py` | **bit-identical to `a602244`** |
| `README.md`, `.gitignore` | bit-identical |
| `camden_normalize.py` | amended — classification section only |
| `camden_signal_test.py` | amended — `--code-map` threading + `classification` report block |
| `make_camden_fixture.py` | amended — codes derived from the artifact |
| `run_selftest.py` | amended — 9 new C4A guards |
| `build_code_map.py` | added |

No F1–F5 numerical threshold moved, no criterion was added, removed or redefined,
`decide_verdict()` is untouched, and `street_key()` / `join_key()` and the Spatial
Accuracy stratum mapping are untouched. Threshold immutability is asserted by
`c4a:no-f1-f5-threshold-changed`, which compares live `DEFAULT_THRESHOLDS`
against the `frozenThresholds` block committed in
`manifests/camden-harness-freeze.json` — not against a value retyped in the test,
so the check cannot be satisfied by editing both sides.

### The second defect C4A uncovered

The fixture did not merely use the classifier's own vocabulary. **It invented
codes that contradict the authoritative codebook.** Five of its nine codes carried
the wrong authoritative class and one did not exist:

| fixture said | authoritative source says |
| --- | --- |
| `("01", "Parked without payment")` | 01 = *"Parked in a restricted street during prescribed hours"* → **PROHIBITION** |
| `("02", "Parked longer than maximum stay")` | 02 = restricted-street waiting/loading offence → **PROHIBITION** |
| `("03", "Parked exceeding paid time")` | **code 03 does not exist** |
| `("12", "Parked in restricted zone")` | 12 = residents'/shared-use permit code → **MIXED** |
| `("30", "Parked without a permit in a CPZ")` | 30 = *"Parked for longer than permitted"* → **TURNOVER** — the cleanest duration-demand code in the entire list, sitting in the fixture's prohibition bucket |
| `("31", "Parked in a permit bay without a permit")` | 31 = *"Entering and stopping in a box junction"* → **NOT_PARKING**, a moving-traffic offence used as if it were a parking prohibition |

So the deployment-dominated scenario's "prohibition-heavy" series was built on a
fabricated codebook, and the 14/14 green self-test was validating the classifier
against invented ground truth. The fixture now derives every code and description
from the frozen artifact, and `c4a:fixture-codes-come-from-authoritative-artifact`
fails the suite if it ever drifts back.

### Result

| | keyword heuristic | C4A table lookup |
| --- | --- | --- |
| classified codes reproducing the declaration | 42 / 66 | **66 / 66** |
| upward bias on `prohibitionShareOverall` | +0.030 to +0.074 | **removed** |
| self-test | 14/14 (circular) | **23/23** |

All seven original scenario verdicts still hold on an authoritative codebook:
demand-dominated PASS, deployment-dominated FAIL(F1), gps-biased FAIL(F2),
sparse-coverage FAIL(F3), no-validation-route FAIL(F4), drifting FAIL(F5),
noproxy PARTIAL. F1 still fires when deployment genuinely dominates — it now fires
for the right reason.

The nine new guards are: every mapped code produces its declared class; the
keyword heuristic is retained as fallback only and still exhibits its documented
defective behaviour; a missing code map raises rather than degrades; unmapped
codes increment the reported fallback count with the codes named; non-parking rows
are surfaced as `c3PolicyRowsStillPresent` rather than absorbed into the F1
denominator; invalid code suffixes are surfaced; fixture codes come from the
artifact; suffix `j` is recorded but not used in any verdict; and no threshold
changed.

A new scenario `code-map-contaminated` mixes in moving-traffic, `MIXED` and
unmapped codes. It deliberately asserts **no verdict** — its purpose is to prove
contamination is surfaced and counted, since a harness that quietly folded those
rows into the F1 denominator would pass every other check and still be lying about
what it measured.

### Suffix `j` is recorded and deliberately not used

The source states suffix `j` identifies a contravention enforceable by CCTV. That
is an authoritative *deployment* marker carried in the code itself — exactly what
F1 is trying to detect. It is recorded in the artifact and counted in the report
(`cameraEnforcementSuffixRows`), but it does **not** influence any verdict, and
`cameraEnforcementSuffixUsedInVerdict` is asserted `False` by a self-test check.
Expanding F1 to read deployment from it would be a separate amendment with its own
pre-registration, not a side effect of this one.

### Re-freeze

`tools/camden/FREEZE.sha256` regenerated over 10 files; `sha256sum -c` passes.
`manifests/camden-harness-freeze.json` records the amendment, the per-file status
(`AMENDED_BY_C4A` / `UNCHANGED_SINCE_a602244` / `NEW_IN_C4A`) and the boundaries
respected. **The run protocol in §7 is unchanged and still must be executed
before any Camden row is read.**

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
