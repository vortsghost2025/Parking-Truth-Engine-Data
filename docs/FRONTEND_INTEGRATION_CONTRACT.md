# Frontend Integration Contract — Owner Summary

**Status:** Contract-hardened frontend using mock data only.  
**Live Montréal integration:** intentionally paused pending PTE-007 review.

## Purpose

The Parking Truth Engine frontend is designed so the user interface does **not** make its own parking-law decisions.

The frontend asks a client layer for structured parking results and displays them. Today that client is a mock implementation. Later it can be replaced by the live PTE core API without copying the rule engine into the UI.

This separation is important because there should be one authoritative legality engine, not one set of rules in the backend and another hidden set in the app.

## Current frontend boundary

The contract is represented in the app through dedicated API/domain modules:

- `lib/api/types.ts`
- `lib/api/client.ts`
- `lib/api/mockClient.ts`
- `lib/api/presentation.ts`

The primary boundary is a `ParkingTruthClient` interface.

The current mock client implements that interface for demo and testing purposes.

## Core rule: legality and availability are different

The contract keeps these two questions separate:

### Legality

> **Can I legally park here for the requested interval?**

Possible normalized legality results include:

- `ALLOWED`
- `ALLOWED_PAID`
- `TIME_LIMITED`
- `PERMIT_REQUIRED`
- `PROHIBITED`
- `SPECIAL_USE_ONLY`
- `CONFLICT`
- `UNKNOWN`

### Availability

> **Is an open space likely to be available?**

Current availability categories are deliberately non-numeric:

- `HIGH`
- `LIMITED`
- `UNKNOWN`

Availability can help rank already-legal candidates. It cannot change the legality result.

For example:

- `PROHIBITED + HIGH availability` still means **do not park there**.
- `UNKNOWN legality + HIGH availability` still means the legality is **UNKNOWN**.

## What a legality result must be able to explain

The frontend contract requires enough structure to display why a result exists rather than showing only a colored curb.

A live core result must be able to provide, where applicable:

- stable curb-segment identity
- requested/evaluated parking interval
- legality verdict
- explanation
- applicable rules
- restrictions
- payment requirement
- maximum stay
- move-by time
- evidence records
- source identities
- observed/retrieved timestamps
- freshness
- reliability classification
- conflicts
- provenance / source lineage

## UNKNOWN is a real result

`UNKNOWN` is not treated as a UI error.

It means the system does not currently have enough trustworthy evidence to make a supported legality determination for the requested interval.

The frontend must preserve that uncertainty instead of converting it into a friendlier-looking answer.

## CONFLICT retains evidence lineage

When the core returns `CONFLICT`, the frontend contract preserves the IDs of the disagreeing sources/evidence records.

The UI can therefore explain **what disagrees** instead of displaying a generic warning.

`CONFLICT` applies to disagreement about the same claim. It is not used merely because legality and availability differ.

## Park My Car snapshots

When the user saves a parked vehicle, the app captures the legality/evidence state that existed at parking time.

That historical snapshot should not silently mutate later if source data changes.

The exact long-term persistence mechanism is still an open integration decision, but the frontend contract already models the snapshot as immutable evidence from the parking event.

## Find Parking behavior

Find Parking is legality-gated.

The frontend should not rank an apparently vacant location as a valid destination unless the legality layer permits it under the agreed product rules.

One remaining product question is how `TIME_LIMITED` candidates should be treated when the requested stay approaches or exceeds the allowed duration. That decision remains open rather than being guessed in the UI.

## Source health

The frontend can display source-health records independently from the parking verdict.

Example states include:

- current/fresh
- stale
- degraded
- unavailable

A source-health failure must not cause the frontend to invent a legality result.

## Minimum live core API capability

Before mock data can be replaced safely, the live core needs to expose at least:

1. Stable curb-segment IDs and renderable geometry.
2. Interval-evaluated legality verdicts, including `UNKNOWN` and `CONFLICT`.
3. Structured rules/restrictions and payment/max-stay/move-by data where known.
4. Evidence records with stable IDs and provenance.
5. Source IDs plus observed/retrieved timestamps and freshness.
6. Conflict records with disagreeing source/evidence IDs.
7. Reliability classification.
8. Availability as a separate field/feed, or an explicit `UNKNOWN` fallback.
9. Source-health records.

## Open integration questions

These remain deliberately unresolved until the core/data work can answer them cleanly:

- exact eligibility rules for `TIME_LIMITED` Find Parking candidates
- canonical source identity model
- whether geometry is returned by the legality endpoint or a segment endpoint
- ownership/lifecycle of availability data
- exact `CONFLICT` vs `UNKNOWN` boundary for incomplete/contradictory evidence
- persistence location and retention policy for parked snapshots

## Current verification

After contract hardening, the frontend reported:

- `npm run typecheck` — passed
- `npm run test` — passed (**1 test file / 6 tests**)
- `npm run build` — passed
- Playwright smoke verification — passed
- no mobile horizontal overflow
- no browser console errors

The six contract-focused tests cover the key separation/integrity rules, including availability independence, conflict lineage, source-health failure behavior, legality-gated Find Parking, and parked snapshot immutability.

## Integration gate

**Do not connect live Montréal legality data yet.**

The next gate is completion and review of the PTE-007 Montréal translation/coverage work, including source-to-rule mapping, sign-to-curb attachment, coverage accounting, conflict/UNKNOWN causes, and bounded human-reviewed real-curb evidence.

Once that evidence is stable, the mock client can be replaced by a live client against the same contract.
