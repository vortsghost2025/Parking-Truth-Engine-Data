# Project Status

**Snapshot date:** 2026-09-12  
**Status:** Active development

## Core

- Deterministic legality kernel: implemented
- Whole requested interval evaluation: implemented
- Fail-closed UNKNOWN: implemented
- Same-precedence conflict preservation: implemented
- Occupancy independence: implemented and regression tested
- IANA timezone support: implemented
- `America/Toronto` DST tests: implemented
- Latest ordinary test result: **126/126 passing**

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

Reported implementation:

- Next.js
- TypeScript
- MapLibre
- map/find-parking/my-car views
- all normalized curb states
- evidence/provenance inspector
- source-health UI
- legality/availability separation
- responsive desktop/mobile layout
- mock-data labeling

Reported verification:

- typecheck passed
- production build passed
- desktop/mobile rendered
- no browser console errors

Live Montréal integration remains intentionally paused until the real legality translation/coverage work is reviewed.

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
