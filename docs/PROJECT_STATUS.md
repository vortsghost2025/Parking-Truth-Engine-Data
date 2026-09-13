# Project Status

**Snapshot date:** 2026-09-13  
**Status:** Active development

## Core

- Deterministic legality kernel: implemented
- Whole requested interval evaluation: implemented
- Fail-closed UNKNOWN: implemented
- Same-precedence conflict preservation: implemented
- Occupancy independence: implemented and regression tested
- IANA timezone support: implemented
- `America/Toronto` DST tests: implemented
- Latest ordinary core test result: **126/126 passing**

## Reliability / evidence service

Implemented work includes:

- immutable raw snapshots
- SHA-256 evidence hashing
- source health
- warm restart from disk
- degraded restored state
- corrupt snapshot fallback
- retry/backoff
- manifest records
- bounded collection pagination

## City adapters / research

### Melbourne

- live occupancy source verified
- parking-bay geometry source verified
- exact `kerbsideid` occupancy/geometry join proven
- historical archive route verified
- restriction-to-current-sensor attachment remains unresolved

### Los Angeles

- occupancy verified
- inventory verified
- exact `spaceid` join proven
- second-city shared architecture proven

### Montréal

PTE-007 is in progress.

Current focus:

- structured AMD rules/periods
- RPA/RTP codification
- sign-to-curb attachment
- roadwork overlays
- snow-operation overlays
- bounded coverage accounting
- human-review packet before production claims

The project expects a meaningful percentage of `UNKNOWN` results where municipal evidence cannot yet support a deterministic curb verdict.

## Availability inference lane (PTE-INF-001)

Implemented and validated offline. See
[`AVAILABILITY-INFERENCE-HANDOFF.md`](AVAILABILITY-INFERENCE-HANDOFF.md) for the
full record, reproduction commands and the invariants that must not be broken.

Two layers, stdlib Python only:

- **climatology** (`tools/inference/availability_engine.py`) — calibrated P(free)
  per street/day-type/hour from historical archives. Needs no sensors.
- **live fusion** (`tools/inference/live_fusion.py`) — Bayesian update of that
  prior with partial live sensing, to infer the bays that have **no** sensor.

Status:

- four-state contract implemented: `HIGH` / `LIMITED` / `CONFLICT` / `UNKNOWN`
- fail-closed on thin evidence: unmeasurable dispersion floors rather than
  collapsing to zero, and a 2-date cell publishes `UNKNOWN`, not `HIGH`
- layer 1 validated on held-out dates: Brier skill **+0.883**, MAE **0.048**,
  95% coverage **0.975**; the `HIGH` label is 3× more accurate than `LIMITED`
- layer 2 validated against **unsensed** bays only: fusion beats climatology
  *and* raw sensor proportion at every coverage level, **+19%** at 5% sensed
  rising to **+85%** at 70%, and **+91%** on atypical days
- deterministic offline test fixture committed
  (`tools/telemetry/make_test_fixture.py`, SHA-256 recorded) so all of the above
  reproduces without a 258 MB download
- simulator calibration chain verified end to end (convergence 0.91–0.97 of
  target)

Not done:

- **never run against real data.** The authoring sandbox has no outbound network,
  so every number comes from the synthetic fixture. Running the chain on the real
  2020 Jan–May Melbourne archive is the highest-value next step.
- systematic residual bias remains on some street/hour cells; a time-of-day-only
  model cannot know about things that changed
- **frontend contract decision outstanding.** The contract types availability as
  three states and "deliberately non-numeric"; this lane emits four states and a
  calibrated number. See §6a of the handoff record. Needs an owner decision
  before wiring into `S:\Parking-Truth-Engine-App`.

Availability only. Nothing in this lane may upgrade a legality verdict.

## Data source strategy (PTE-TEL-002)

Field research in Hull (no on-street data) and Hong Kong (full data, six
competitors) confirmed that live on-street occupancy does not exist for most
cities and is not free where it does. Recorded in
[`PARKING-DATA-SOURCE-REALITY-CHECK.md`](PARKING-DATA-SOURCE-REALITY-CHECK.md).

Findings that change the plan (rev 2, after external review — see §7 of the
record for what was overclaimed and withdrawn):

- **Cashless parking sessions are the missed source, and they are a byproduct,
  not a sensor.** A pay-by-phone session records location, start and **expiry**
  (determined by the amount paid), fee and vehicle category. It reuses the
  harvester's ingest path, but it observes **paid sessions, not physical
  occupancy**: permits, free bays, paper tickets, Blue Badge, overstayers and
  unpaid cars all create **systematic missingness** that varies by street and
  restriction type. Modellable, but it **needs calibration** — rev 1's
  "structurally identical to a ground sensor" is withdrawn.
- **It is not one integration.** Only RingGo is evidenced. MiPermit and
  PayByPhone schemas, access models, retention, granularity and licensing are
  **unverified**. Treat class A as a promising **adapter family**, not a
  universal adapter. RingGo's own *"clients can access data from their parking
  locations only"* means coverage is assembled council by council regardless.
- **It is not real-time.** RingGo's "real-time" refers to Insight dashboards. The
  documented feed into a council platform is a **daily batch**: Hackney's
  published playbook describes a previous-day CSV dropped to SFTP each afternoon
  (`data_warehouse_-YYYY-MM-DD.csv`). Right shape for the climatological layer;
  not a live occupancy sensor.
- **The approach is published and measured.** Assemi, Paz & Baker (2021), *IEEE
  Transactions on Intelligent Transportation Systems*, DOI 10.1109/TITS.2021.3095277:
  occupancy estimated from **payment data only** at **R² > 94%, RMSE 1.2 bays** —
  but calibrated against **camera-captured** bay-level occupancy. Precedent for
  class A, and independent confirmation that cold start is the central risk.
- **Hull confirms MiPermit on-street**, not only in car parks
  (`hull.gov.uk/parking/mipermitcashless-parking`). Upgraded from a
  privacy-notice inference to an official statement.
- **Enforcement byproducts are real occupancy evidence.** Camden publishes
  transactional PCN data under OGL with street, restriction, contravention code
  and a `Spatial Accuracy` column separating CEO GPS from fixed-CCTV locations.
  Positive-only and biased, so usable for *relative* pressure; needs an absolute
  anchor to invert.
- **Camden also publishes the bay inventory** (`t4s2-xa5a`): bay length,
  approximate space count, restriction type, operating times, maximum stay,
  tariff, road name, CPZ, WKT geometry. So PCN events *and* capacity come from
  one OGL publisher with **no procurement step** — which is why the Camden
  experiment is first. Join at street/CPZ level only: bay coordinates derive from
  an *arbitrary node* on the polyline and individual spaces are not identifiable.
- **Hull holds an on-street inventory, but Traffweb is not a lawful source for
  it.** `hull.traffweb.app` publishes CPZs, resident/business bays and
  restrictions, and is marked *"IN BETA MODE AND ALL DATA IS FOR TESTING PURPOSES
  ONLY"*, may omit temporary/experimental orders, and defers legal authority to
  the **Traffic Order documents**. **Probed this turn: no machine-readable
  endpoint advertised** (negative result). Hull's denominator must come from the
  Traffic Orders register or FOI. No scraping workaround.
- **Hong Kong's feed is coarser than assumed, and the staleness claim was
  misattributed.** Verified against the official specification: `vacancy_type` B
  is binary only, `-1` means the operator provided nothing, `lastupdate` exposes
  per-record age. The *"hours to even months"* lag is a **motorist complaint
  relayed in a 2017 legislator's question**, not a government finding — do not
  cite it. The verified admission is that TD-managed car parks were **updated
  manually hourly** in 2017, with replacement from 2018. Current staleness must
  be **measured** from `lastupdate`, which needs no authentication.
- **Hong Kong and Melbourne are calibration laboratories, not markets.**
  Sensor-poor cities are the actual inference problem, because there is nothing
  there to relay.
- **Cameras you operate remain a dead end**, consistent with the frozen camera
  lane. The usable inversion is other people's enforcement records, never the
  lens.

**Approved next experiments, deliberately bounded:**

1. ~~Hull Traffweb probe~~ — ✅ **run, negative**. Redirect to Traffic Orders.
2. **Camden signal test** — PCN events plus Camden bay inventory; test whether
   street/time patterns correlate with an **independent parking-pressure proxy**.
   **Do not call it occupancy until calibrated.** Output stays a relative index.
3. Measure HK staleness from `lastupdate` directly, replacing the 2017 citation.
4. Test the adapter-family hypothesis: find MiPermit and PayByPhone export
   schemas and access models.

Open risk: **cold start.** A city with inventory but no event history has nothing
to train on locally — and the published precedent needed camera-captured ground
truth to calibrate, so this is a documented dependency, not a hypothetical. The
intended answer is transferring demand *shape* from ground-truth cities with wide
intervals that narrow as local evidence accumulates; the empirical-Bayes
prior/shrinkage structure in layer 1 is already the right mechanism, but **it is
not built.** The consequence is commercial: **if transfer fails, this is a
city-by-city data-procurement business rather than a transferable Parking Truth
Engine.** That fork should be decided before anything is promised.

## Camden signal harness (PTE-TEL-003)

Approved and built this turn: a bounded test of whether Camden's PCN exhaust
carries a reproducible street/time parking-pressure signal.
[`CAMDEN-SIGNAL-HARNESS.md`](CAMDEN-SIGNAL-HARNESS.md), code in
[`tools/camden/`](../tools/camden/), schema
[`camden-pressure-signal-schema.json`](../schemas/camden-pressure-signal-schema.json).

**Status: built and self-tested 14/14. NOT run against real Camden data** — the
sandbox has no outbound network, so the two OGL downloads have to happen on a
machine that has one. Column names are therefore candidates, and `--field-map`
exists so a real download can be pinned without editing code. Unresolved
*required* fields raise rather than guess; verified by renaming columns until the
harness refused.

Output is a **relative parking-pressure index** — PCNs per space per date,
rescaled to an exposure-weighted mean of 1.0. It is not occupancy, not a
probability of finding a space, and not a confidence figure, and that is
machine-enforced rather than conventional: `assert_no_forbidden_semantics()`
walks every emitted report and raises on any key implying one of those claims. It
caught two of its author's own keys (`isOccupancy`,
`outputIsRelativeIndexNotOccupancy`), both negations, which is the guard working
— a namespace that spells denials with the forbidden vocabulary is one careless
edit away from asserting them.

Scope constraints enforced structurally: street/CPZ join with no bay identifier
or coordinate permitted in a cell key; `CEO_GPS` / `FIXED_CCTV` / `UNKNOWN_OTHER`
strata never pooled by default; capacity used only where the publisher supplies
it (`None`, never `0.0`); approximate-capacity flags propagated end to end;
hours never imputed, so a date-only PCN is excluded from hourly diagnostics
rather than placed at midnight; unrecognised publisher values surfaced verbatim
instead of absorbed into `UNKNOWN_OTHER`; no wall clock anywhere.

Five fail criteria from the approved scope, each demonstrated on a fixture built
from latent demand and enforcement-deployment processes the harness did not
create:

| Scenario | Verdict | Diagnostic |
|---|---|---|
| demand-dominated | PASS | proxy rho 0.564 (n=47) |
| deployment-dominated | FAIL F1 | prohibition share 0.964; index-vs-mix rho 0.807 |
| gps-biased | FAIL F1+F2 | CEO-GPS isolation rho **−0.304** — ranking inverts |
| sparse-coverage | FAIL F3 | 7 streets (min 10), 12 dates (min 28) |
| no-validation-route | FAIL F4 | state `NONE_KNOWN` |
| drifting | FAIL F5 | split-half rho 0.187 |
| demand-dominated, no proxy | PARTIAL | verdict correctly capped |

One fixture bug worth keeping: `gps-biased` originally failed on F1 rather than
F2, because with demand and deployment multipliers drawn independently the same
streets topped both rankings, so Spearman stayed high even though magnitudes
diverged. **F2 tests order collapse; rescaling is not collapse.** Fixed by
anti-correlating the multipliers. A test that passes for the wrong reason is
worse than one that fails.

**Central limitation, which no engineering removes:** `PCN rate ≈ occupancy ×
violation rate × enforcement intensity`. Dividing by capacity removes the
street-size term and only that term. **PCN data alone cannot separate parking
demand from enforcement deployment.** The F1 indicators narrow it; only an
independent proxy resolves it — which is why F4 is a fail criterion and why a
proxy-less run is capped at PARTIAL. A signal that correlates only with itself is
not evidence.

Reading of outcomes: **FAIL** is cheap and useful (drop PTE-TEL-002 class B);
**PARTIAL** justifies pursuing payment-session access; **PASS** is the strongest
available evidence for historical inference from administrative exhaust.

Sequencing holds: **Camden before Hull procurement or MiPermit access.** It is
free, already published, and carries both the enforcement and capacity sides.

Boundaries respected: legality kernel not modified, imported or consulted;
PTE-007/PTE-008 evidence untouched; camera lane still frozen (this consumes other
people's published records, operates no lens); no individual-space occupancy
inferred; nothing deployed; nothing merged to main; no existing data overwritten.

## Camera lane

**FROZEN — `CAMERA_FIXED_VIEW_PARTIAL`**

Restart only when external evidence justifies it, with:

- independent labeling
- balanced ground truth
- frozen pipeline
- measure-don't-tune evaluation

Camera occupancy is not required by the core product.

## Frontend

Separate workspace:

`S:\Parking-Truth-Engine-App`

### Application shell

Implemented and verified locally:

- Next.js
- TypeScript
- MapLibre
- map / Find Parking / My Car views
- normalized curb-state legend
- evidence / provenance inspector
- source-health UI
- legality / availability separation
- responsive desktop/mobile layout
- clear mock-data labeling

### Contract hardening

The frontend integration boundary has now been explicitly typed and separated from mock implementation details.

Added frontend API/domain modules:

- `lib/api/types.ts`
- `lib/api/client.ts`
- `lib/api/mockClient.ts`
- `lib/api/presentation.ts`
- `lib/api/mockClient.test.ts`

The contract now explicitly represents:

- legality and availability as separate fields
- availability states `HIGH`, `LIMITED`, `UNKNOWN`
- legitimate legality `UNKNOWN`
- conflict source/evidence lineage
- requested/evaluated intervals
- explanation and restrictions
- provenance
- source timestamps and freshness
- payment / maximum-stay / move-by information where available
- reliability classification
- immutable parked verdict/evidence snapshots
- source-health records

The frontend uses a `ParkingTruthClient` boundary so the mock implementation can later be replaced by the live core API without reproducing the legality kernel in the UI.

### Frontend verification

Reported verification after contract hardening:

- `npm run typecheck` — passed
- `npm run test` — passed, **1 file / 6 tests**
- `npm run build` — passed
- Playwright smoke verification — passed
- Find Parking returned 3 legal candidates
- Park My Car snapshot persisted in the mock flow
- source-health view opened successfully
- no mobile horizontal overflow
- no browser console errors

Contract regression tests include the architectural invariants that:

- `PROHIBITED + HIGH availability` remains prohibited
- `UNKNOWN + HIGH availability` does not become allowed
- conflict lineage retains disagreeing source/evidence references
- source-health failure does not fabricate legality
- Find Parking remains legality-gated
- parked snapshots preserve the verdict/evidence state captured at parking time

### Minimum core API capabilities required for live integration

1. Stable curb-segment IDs and renderable geometry.
2. Interval-evaluated legality verdicts including `UNKNOWN` and `CONFLICT`.
3. Structured rules, restrictions, payment, maximum-stay, and move-by data where known.
4. Evidence records with stable IDs, source IDs, observed/retrieved timestamps, freshness, and provenance.
5. Conflict records retaining disagreeing source/evidence IDs.
6. Reliability classification.
7. Separate availability data, or an explicit `UNKNOWN` availability fallback.
8. Source-health records for the evidence sources.

Open contract questions remain documented, including time-limited Find Parking eligibility, source identity, geometry ownership, availability ownership, conflict-vs-unknown semantics, and parked-snapshot persistence.

See `docs/FRONTEND_INTEGRATION_CONTRACT.md` for the owner-readable integration summary.

**Live Montréal integration remains intentionally paused until PTE-007's Montréal translation and coverage work is reviewed.**

## Storage

The development machine is storage constrained.

Current policy:

- private GitHub evidence repository = canonical off-PC evidence store
- large public/reproducible data = URL/hash/metadata rather than repeated Git blobs
- local workspace = active files only
- delete local evidence only after remote/reproducibility verification

## Production readiness

**Not production-ready for real-city legality claims yet.**

Current blockers/gates include:

- Montréal sign-to-curb semantics
- measured source coverage
- source precedence verification
- bounded real-curb study
- human review of machine-derived results
- frontend/core live contract integration
