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
