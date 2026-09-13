# Camden Signal Harness — can administrative exhaust carry a parking-pressure signal?

**Record ID:** PTE-TEL-003
**Snapshot date:** 2026-09-13
**Extends:** [`PARKING-DATA-SOURCE-REALITY-CHECK.md`](PARKING-DATA-SOURCE-REALITY-CHECK.md) (PTE-TEL-002), which proposed this experiment as action 2
**Lane:** AVAILABILITY (research). No legality claim made; `legalityClaimed: false` throughout.
**Code:** [`tools/camden/`](../tools/camden/) — 5,348 lines, stdlib only
**Schema:** [`schemas/camden-pressure-signal-schema.json`](../schemas/camden-pressure-signal-schema.json)
**Manifest:** [`manifests/camden-signal-harness-manifest.json`](../manifests/camden-signal-harness-manifest.json)
**Frozen by:** [`CAMDEN-REAL-RUN.md`](CAMDEN-REAL-RUN.md) (PTE-TEL-004) at commit `a602244`, **re-frozen after amendment C4A** — see [`manifests/camden-harness-freeze.json`](../manifests/camden-harness-freeze.json) and §4B of that record
**Authoritative code map:** [`sources/camden/london-councils-contravention-codes-v7.0.json`](../sources/camden/london-councils-contravention-codes-v7.0.json) (London Councils, PCN Codes v7.0) with its [classification audit](../sources/camden/code-classification-audit.json)
**Companion:** [`AVAILABILITY-INFERENCE-HANDOFF.md`](AVAILABILITY-INFERENCE-HANDOFF.md) (PTE-INF-001)

---

## 0. Status, stated first

**Built, amended by C4A, self-tested 23/23, and NOT yet run against real Camden
data.**

What is proven: the pipeline's arithmetic, and that the harness detects each of
the five failure modes it claims to detect, graded against fixtures built from
latent processes it did not create — and, since C4A, that contravention
classification reproduces a pre-declared taxonomy derived from an authoritative
external codebook.

What is **not** proven: that the column-name candidates match a live Camden
export, and therefore nothing at all about Camden. That gap is closed by
downloading two OGL files and running one command; it cannot be closed from
inside this sandbox, which has no outbound network except the fetch and search
tools.

**The harness is now FROZEN at commit `a602244`** for the real run, with
`DEFAULT_THRESHOLDS` snapshotted and every file hashed in
[`manifests/camden-harness-freeze.json`](../manifests/camden-harness-freeze.json).
Verify with `cd tools/camden && sha256sum -c FREEZE.sha256`. Retrieving Camden's
own dataset metadata before the run found four defects that mean the harness
cannot ingest the real files as-is; they are pre-registered in
[`CAMDEN-REAL-RUN.md`](CAMDEN-REAL-RUN.md) §4, dated and evidenced **before any
data row was read**. The most serious is that F1 — the deployment-dominance
criterion — would be **silently inoperative** on real Camden data, because
contravention codes are numeric (`33H`, `52M`, `12R`, `11`) and the classifier
matches keywords. That would permit a PASS which never tested the central
confound. See §11 below.

**Correction to that framing, found by executing C4.** Supplying authoritative
descriptions does *not* rescue the keyword classifier. Run against the London
Councils wording it agrees with the pre-declared taxonomy on only **42 of 66**
classified codes, recognising 9 of 18 turnover codes against 31 of 46 prohibition
codes. Because `prohibitionShareOverall` is `PROHIBITION_TYPE` over *all* classes,
that asymmetric attenuation biases it **upward by +0.030 to +0.074** — enough to
carry a true prohibition share of 0.45 to a reported **0.524** and cross the
frozen F1 threshold of 0.50 unaided. So F1 was not merely at risk of being
inoperative; it was at risk of **firing falsely**, which would produce a FAIL
whose pre-registered reading is to drop the PCN-exhaust source class as
enforcement-biased. The defect could manufacture the evidence for abandoning the
approach. Full analysis in [`CAMDEN-REAL-RUN.md`](CAMDEN-REAL-RUN.md) §4A.

**Amendment C4A** therefore replaced keyword classification with a lookup against
the frozen authoritative artifact, executing C4's own pre-registered option (a) —
*"as data, not as keywords"*. Agreement is now **66/66** and the bias is removed.
The keyword heuristic is retained byte-for-byte as a counted fallback; no F1–F5
threshold moved; `camden_pressure.py`, `camden_aggregate.py` and
`camden_sources.py` remain **bit-identical to `a602244`**. C4A also found that the
original fixture invented codes contradicting the authoritative codebook — five of
nine had the wrong class and code `03` does not exist — so the 14/14 green
self-test had been validating the classifier against fabricated ground truth. The
fixture is now derived from the artifact and the suite is **23/23**. Both changes
were committed **before any Camden row was read**. See
[`CAMDEN-REAL-RUN.md`](CAMDEN-REAL-RUN.md) §4B.

### Reporting correction

The commit message for `a602244` and the summary written alongside it both stated
that the only existing files changed were `README.md` and `docs/PROJECT_STATUS.md`,
"both link additions". **That is wrong for the second file.** `git show --stat
a602244` gives `README.md | 1 +` and `docs/PROJECT_STATUS.md | 74 ++++`. The
README change is one link line; the PROJECT_STATUS change is a substantial new
PTE-TEL-003 status section. It is not destructive and it does not breach the
experiment boundary — but describing a 74-line section as a link addition
understates what was touched, and an evidence record should not do that. The
commit message is now immutable, so the correction is recorded here instead.

---

## 1. The question and the scope

One question: **do Camden PCN event patterns contain a reproducible street/time
parking-pressure signal?**

The approved scope was explicit that the output is a **relative parking-pressure
signal**, not occupancy, and not to be called occupancy until calibrated against
independent ground truth. It also required joining at **street/CPZ level**, never
at individual bay level, because Camden states that individual parking spaces
cannot be identified and that bay coordinates derive from an *arbitrary node*
along the polyline geometry.

Why Camden: it publishes **both** sides under one OGL licence with an API —
transactional PCN events, and a Parking Bay Map (`t4s2-xa5a`) carrying
approximate bay length, approximate space count, restriction type, operating
times, maximum stay, tariff, road name, CPZ and WKT geometry. No procurement, no
FOI, no partnership. It is the cheapest available test of whether enforcement
exhaust carries real signal, which is the question that decides whether PTE-TEL-002's
class B is worth pursuing at all.

---

## 2. What was built

Seven deliverables, mapped to modules:

| # | Deliverable | Module |
|---|---|---|
| 1 | Camden source adapters | `camden_sources.py` |
| 2 | Deterministic normalisation schema | `camden_normalize.py` + the JSON schema |
| 3 | Street/CPZ aggregation | `camden_aggregate.py` |
| 4 | Spatial Accuracy stratification | `camden_aggregate.py` |
| 5 | Pressure-index calculation | `camden_pressure.py` |
| 6 | Synthetic fixture and self-test | `make_camden_fixture.py`, `run_selftest.py` |
| 7 | Report with PASS / PARTIAL / FAIL | `camden_signal_test.py` |

The report carries all seven required contents: coverage, missingness,
repeatability by time and street, whether GPS-quality events behave differently,
strongest and weakest signals, confounders, and the explicit verdict.

---

## 3. Constraints enforced by code, not by convention

The scope listed constraints that are easy to violate by accident and invisible
once violated. Each is enforced structurally.

| Constraint | Enforcement |
|---|---|
| Join at street/CPZ, never bay | No bay identifier or coordinate exists in a cell key. `assert_no_bay_level_join()` raises if one appears. The `joinLevel` enum has no `BAY` member |
| Strata preserved separately | `CEO_GPS` / `FIXED_CCTV` / `UNKNOWN_OTHER` is a dimension of every cell; they never share one |
| Never pool unless the report shows the effect | `pool_strata()` is the only route and stamps `pooledFrom`. Nothing pools by default |
| Unrecognised publisher values must not hide | `map_spatial_accuracy()` returns an `UNRECOGNISED` disposition and the raw value is reported verbatim with its count |
| Capacity only where supplied | `spaceCount` is `None`, never `0.0`. Zero spaces and unknown spaces mean different things to a rate |
| Approximate-capacity flags preserved | `capacityIsApproximate` propagates bay → street → index entry → report |
| Hours never imputed | A date-only PCN yields `hourKnown: false` and never lands in bucket 0. `hourImputationPerformed` is asserted false |
| Relative index only | `assert_no_forbidden_semantics()` walks the emitted report and raises on any key containing `occupanc`, `probabilit`, `vacanc`, `availability`, `confidence`, `pFree` and kin |
| No fake confidence percentages | Same guard |
| Determinism | Sorted iteration, fixed rounding, no wall clock (`asOf` defaults to the max date in the data), seeded RNG |

**The guard caught its own author.** During development it rejected
`isOccupancy: false` and `outputIsRelativeIndexNotOccupancy: true` — both
negations, both containing the forbidden substring. That is not a false positive.
A namespace in which denials are spelled with the forbidden vocabulary is a
namespace one careless edit away from asserting them. The contract now states its
negations as a value list (`doesNotClaim: [...]`) instead.

**Sparse grid, complete semantics.** Cells are materialised only where at least
one PCN exists. An absent `(street, stratum, dayType, hour)` combination means
**zero**, and because exposure is computed analytically as
`capacity × dates-of-that-dayType`, the zero is still counted in every rate. This
matters: without it, "no PCNs" is invisible, and no PCNs could mean low pressure
*or* no enforcement — which is the exact confound this harness exists to examine.
It also keeps memory bounded on a real download, where a fully materialised grid
would be hundreds of thousands of dicts.

---

## 4. Self-test results — 14/14

```
python3 tools/camden/run_selftest.py
```

Seven scenario assertions and seven structural ones, all passing. The scenario
figures below are the harness's own diagnostics on each fixture.

| Scenario | Verdict | Criteria triggered | Key diagnostic |
|---|---|---|---|
| `demand-dominated` | **PASS** | none | proxy rho **0.564** (n=47), threshold 0.40 |
| `deployment-dominated` | **FAIL** | F1 | prohibition share **0.964**; index-vs-prohibition rho **0.807** |
| `gps-biased` | **FAIL** | F1, F2 | CEO-GPS isolation rho **−0.304** — the ranking *inverts* |
| `sparse-coverage` | **FAIL** | F3 | 7 streets (min 10), 12 dates (min 28) |
| `no-validation-route` | **FAIL** | F4 | state `NONE_KNOWN` |
| `drifting` | **FAIL** | F5 | split-half rho **0.187**, threshold 0.50 |
| `demand-dominated-noproxy` | **PARTIAL** | none | verdict capped; PASS unreachable without a proxy |

Structural checks: fixture bytes deterministic across runs; report sha256
deterministic; forbidden-semantics guard fires on an occupancy-shaped key and
accepts a clean index; no-bay-level-join guard fires on a coordinate-bearing cell;
date-only PCNs yield `hourKnown: false` with nothing in hour bucket 0; an
unrecognised `Spatial Accuracy` value surfaces verbatim **and** lands in
`UNKNOWN_OTHER`; a real report conforms to the JSON schema.

For reference, the `demand-dominated` index distribution is
median **0.9988**, mean 1.0799, p25 0.7361, p75 1.2599, range 0.2394–2.8514 over
47 indexed streets with 7 suppressed — median ≈ 1.0 as constructed, and the mean
above 1.0 because the index is exposure-weighted rather than street-weighted.
Global rate 0.013988 PCNs per space per date. Report sha256
`529492a9c677bdd2cbcacd9a6c5778646dbf46e6a7abd15741004959b90ba496`.

### One fixture bug worth recording

`gps-biased` initially failed to trigger F2 — it failed on F1 instead. The reason
is instructive: with demand and deployment multipliers drawn **independently**,
the same streets topped both the all-strata and the CEO-GPS-only rankings, so
Spearman stayed high even though the magnitudes diverged sharply.

**F2 tests order collapse. Rescaling is not collapse.**

The scenario now anti-correlates the two latent multipliers
(`anticorrelate_multipliers()`) and attributes 97% of camera-street events to
CCTV, so isolating CEO GPS genuinely reorders the streets — and the observed rho
goes to −0.304. A test that passed for the wrong reason is worse than a test that
fails; this one was silently not testing what it claimed.

---

## 5. Verdict semantics

| ID | Criterion | Test |
|---|---|---|
| F1 | Signal dominated by enforcement deployment rather than parking demand | Prohibition-share dominance **and** the index rising with prohibition mix across streets |
| F2 | Results collapse when CEO GPS events are isolated | Spearman(all-strata, CEO-GPS-only) below 0.50 |
| F3 | Insufficient geographic / time coverage | Streets ≥ 10, dates ≥ 28, capacity coverage ≥ 0.50, CEO-GPS share ≥ 0.05 |
| F4 | No independent validation route | `SUPPLIED` / `AVAILABLE_NOT_SUPPLIED` / `NONE_KNOWN` |
| F5 | Unstable rankings across comparable periods | Spearman across chronological date halves, below 0.50 |

- **FAIL** — any criterion triggered
- **PASS** — none triggered **and** an independent proxy supplied **and**
  Spearman(index, proxy) ≥ 0.40
- **PARTIAL** — none triggered, PASS bar not met. In practice: no proxy supplied,
  so the output is descriptive signal characterisation only

All thresholds live in `DEFAULT_THRESHOLDS`, are overridable with
`--threshold NAME=VALUE`, and are printed into every report. A verdict whose
cut-offs are buried in code cannot be argued with.

F1 is deliberately a **conjunction**. Prohibition dominance alone would fail any
city with many yellow lines; a rising index-vs-mix correlation alone would fail
on noise. Requiring both is still not proof — see §6.

F1 also separates a **size confound** from a deployment confound and reports them
as different indicators. In the demand-dominated fixture, raw PCN counts are far
more concentrated than capacity-normalised rates (Gini gap 0.306, above the 0.25
threshold) — because street capacity is lognormal, so big streets naturally
accumulate more tickets. That is a normalisation artefact, not enforcement
targeting, and labelling it as deployment would have produced a spurious FAIL on
a clean signal.

---

## 6. The central limitation, which no amount of engineering removes

**PCN data alone cannot separate parking demand from enforcement deployment.**

```
PCN rate ≈ occupancy × violation rate × enforcement intensity
```

Dividing by publisher-supplied capacity removes the street-size term and only
that term. Violation rate and enforcement intensity remain entangled, and both
vary by street and hour — the same dimensions the index is trying to resolve.

The F1 indicators narrow this. Nothing computed from PCN data alone resolves it.
Only an **independent proxy** does, which is why F4 is a fail criterion rather
than a footnote and why a proxy-less run is capped at PARTIAL.

Two further limits the harness reports rather than hides:

- **Proxy independence is unverifiable from inside the harness.** It is an
  operator assertion, stamped into the report as such. A proxy derived from the
  PCN series makes the test circular and the verdict meaningless.
- **Contravention classification is a heuristic over free text.** It assigns
  `TURNOVER_TYPE` / `PROHIBITION_TYPE` / `AMBIGUOUS` / `UNCLASSIFIED` by keyword
  match and reports the reason for every call. `AMBIGUOUS` is a real outcome and
  is not forced into a bucket.

---

## 7. Limitations of this build

- **Never run on real Camden data.** The single largest caveat.
- **Column names are candidates, not verified spellings.** Resolution is
  case-insensitive and tolerant of Socrata suffixes, and `--field-map` pins a real
  download without a code edit. Verified behaviour: with `Road Name` and
  `Number of Spaces` renamed to strings no candidate matches, the harness exits
  non-zero with `could not resolve required field(s)` rather than substituting a
  plausible column; supplying the field map restores PASS.
- **Street matching between the two datasets is token-based.** Camden's PCN
  street strings and bay `Road Name` strings may not agree in form. Unmatched
  streets are reported on both sides rather than silently dropped, and a low
  match rate will show up as F3 capacity-coverage failure — which is the honest
  outcome.
- **The proxy mechanism is proven only against a synthetic proxy** derived from
  the fixture's latent demand process. That demonstrates the machinery; it says
  nothing about any real proxy.
- **Appealed and cancelled PCNs are included as issued.** `caseStatus` is reported
  but not used to filter, because filtering on outcome would condition the signal
  on what happened after the event.
- **No seasonality modelling.** `month` and `season` are carried as features and
  reported; nothing corrects for them, and a series spanning a holiday period
  will show it as drift.

---

## 8. What a real run requires

1. Download from `opendata.camden.gov.uk`: **Parking Bay Map** (`t4s2-xa5a`) and
   the **PCN series** (current plus historical financial years). Both OGL.
2. `python3 camden_sources.py --bays bays.csv --pcn pcn.csv --report resolve.json`
   and read `fieldMap`, `ambiguousFieldMatches`, `unresolvedOptionalFields`,
   `unconsumedSourceFields`, `spatialAccuracyValuesObserved`.
3. Pin mismatches with `--field-map fields.json`.
4. `python3 camden_signal_test.py --bays … --pcn … --out report.json`.
   Without a proxy expect **PARTIAL at best** — and that is the correct result,
   not a weak one.
5. Only if a genuinely independent proxy can be sourced, re-run with `--proxy`.
   Otherwise declare `--validation-route none_known` and accept the FAIL rather
   than manufacturing a route.

Expected reading of outcomes: a **FAIL** is a cheap, useful result — it means PCN
exhaust is too enforcement-biased to build on and the class-B line in PTE-TEL-002
should be dropped. A **PARTIAL** means the signal is stable and reproducible but
unvalidated, which is enough to justify pursuing payment-session access. A
**PASS** would mean administrative exhaust carries a pressure signal that agrees
with something independent, which is the strongest available evidence for the
historical-inference route around sensor-poor cities.

---

## 9. The next research question

Camden answers whether a pressure signal exists in administrative exhaust. It
does **not** answer the question that decides whether PTE scales:

> **Can a pressure model trained or calibrated in a ground-truth city preserve
> useful ranking in a city where only administrative exhaust exists?**

That is the transfer problem from PTE-TEL-002 §3, and it is the fork between a
generally transferable engine and a city-by-city data-acquisition project. The
published precedent (Assemi, Paz & Baker 2021, IEEE TITS) achieved R² > 94% from
payment data alone — but only after calibrating against camera-captured
occupancy, so the dependency on a ground-truth city is documented, not
hypothetical.

Sequencing matters: **run Camden before pursuing Hull procurement or MiPermit
access.** Camden is free, already published, and carries both the enforcement and
the capacity side. It can answer the scientific question before anyone spends
money or emails a council.

---

## 10. The line to hold

Availability-adjacent research lane. Nothing here makes an illegal, conflicted or
unknown curb legal. The legality kernel is not modified, imported or consulted.
PTE-007 and PTE-008 evidence is untouched. The camera lane stays frozen — this
harness consumes other people's published enforcement records and operates no
lens. No individual-space occupancy is inferred. Nothing is deployed, nothing is
merged to main, and no existing data is overwritten: outputs go to new paths and
`tools/camden/.gitignore` keeps fixtures, downloads and reports out of git.

**A PCN says a car was there. It does not say a car may be there.**

---

## 11. Post-freeze findings from Camden's own metadata

Retrieved 2026-09-13 from `opendata.camden.gov.uk/api/views/<id>.json` — the
publisher's own dataset metadata, **before any data row was read**. These correct
assumptions baked into this record and into the fixture. Full detail and evidence
in [`CAMDEN-REAL-RUN.md`](CAMDEN-REAL-RUN.md).

1. **The bay dataset is `7hiv-3r9k` ("Parking Bays"), not `t4s2-xa5a`.** The
   latter is `assetType: "map"` with an **empty `columns` array**, pointing at
   `7hiv-3r9k` as its data source. §1 of this record names `t4s2-xa5a`; that is
   the map view, not the table.
2. **Two real bay column names are not in the adapter's candidates:**
   `Parking Spaces` and `Parking Bay Length Metres`. Because both are *optional*
   fields the adapter would **not raise** — it would load every bay with
   `spaceCount = None`, produce zero indexed streets, and fail F3 for a reason
   that has nothing to do with Camden. A silent wrong conclusion, and the exact
   scenario the "run the field resolver first" protocol exists to catch.
3. **35.9% of the PCN dataset is not parking.** `ticket_type` over 495,814 rows:
   O/S TMA 312,203 (63.0%) and CCTV TMA 5,194 (1.0%) are parking; **MTC 170,747
   (34.4%) is moving traffic** and **BUS 7,032 (1.4%) is bus lanes**. The fixture
   modelled a parking-only series, so it never exercised this. Pre-declared
   filter: `ticket_type IN ('O/S TMA', 'CCTV TMA')` → 317,397 rows.
4. **F1 is inoperative on real data** — see §0. Numeric contravention codes carry
   no keywords, so every row classifies `UNCLASSIFIED`, I2 can never trigger, and
   F1 can never fire. Since `decide_verdict()` reads a non-firing criterion as
   not-triggered, the harness could return PASS having never tested deployment
   dominance. **Pre-registered handling: source an authoritative London Councils
   code→class mapping, or declare F1 unevaluable and cap the verdict at PARTIAL.**
5. **Street strings will not match.** PCN `Street` is uppercase with postcode
   suffixes and junction qualifiers — `TOTTENHAM COURT ROAD W1 BY JUNCTION WITH
   CHENIES STREET` (27,940 rows). Five such Tottenham Court Road variants are
   **15.2% of the whole dataset**. `street_key()` strips neither. **CPZ is the
   reliable join level**; a street-level run must be read as a *matching* result,
   not a data-availability result.
6. **A `MOBILE CCTV` location type may exist.** The publisher's ward and
   coordinate descriptions reference *"the Civil Enforcement Officer location,
   fixed CCTV location or mobile CCTV location"* — three types, where §3 of this
   record and the strata model assume two plus unknown. A mobile-CCTV value would
   surface as `UNRECOGNISED`, which is the designed behaviour.
7. **`Spatial Accuracy` itself was not retrieved.** Metadata chunks covering
   positions 31+ failed with `SignatureDoesNotMatch`. The column is documented in
   the dataset description but its exact name and value set are unverified.
8. **Capacity carries a publisher-documented defect:** both `Parking Spaces` and
   `Parking Bay Length Metres` warn of *"Known issues with echelon shaped parking
   bays"*. That must travel with every capacity figure, and it is stronger than
   the generic "approximate" flag this record described.
9. **38.7% of PCN rows have no coordinates and 39.4% no ward** — a stratum, not
   missingness to fill. Any coordinate-based diagnostic covers at most 61.3%.

**A find that was not being looked for:** `7hiv-3r9k` position 6 is
**`Cashless Identifier`** — *"Location ID for cashless payment"*. That is the join
key to RingGo / MiPermit session data (PTE-TEL-002 class A), and it joins on an
**identifier rather than a street string**, which dissolves finding 5 entirely for
the payment-session path. It does not change the frozen run; it changes what is
worth asking for next.

None of this is a threshold change and none of it is post-hoc tuning: all nine
items come from publisher metadata dated before the download. The distinction is
the whole reason the harness was frozen first.
